"""WATI webhook handlers - INTERACTIVE SALES AGENT WITH LOCATION AND NAME"""

from fastapi import APIRouter, Request
import logging
import time
import asyncio
from app.config import settings
from app.services.wati_service import WATIService
from app.services.erpnext_service import ERPNextService
from app.services.claude_service import ClaudeService
from app.prompts.bioman_knowledge import BIOMAN_KNOWLEDGE
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["webhooks"])

wati_service = WATIService(settings.WATI_TOKEN, settings.WATI_ENDPOINT)
erpnext_service = ERPNextService(
    settings.ERPNEXT_URL,
    settings.ERPNEXT_API_KEY,
    settings.ERPNEXT_API_SECRET
)

claude_service = None
conversation_history = {}
customer_context = {}

# ─────────────────────────────────────────────────────────────────────
# ANTI-SPAM GUARDS
# ─────────────────────────────────────────────────────────────────────

# 1. Dedup: remember every whatsappMessageId we already processed
#    Keeps last 1000 entries to avoid unbounded growth
processed_message_ids: set = set()
processed_message_ids_order: list = []   # to evict oldest when > 1000

# 2. Per-customer cooldown: track when we last sent a reply
#    { mobile_number → unix_timestamp_of_last_reply }
last_reply_time: dict = {}
REPLY_COOLDOWN_SECONDS = 4   # min gap between two AI replies to same customer

# 3. Stale message threshold: ignore customer messages older than this
MAX_MESSAGE_AGE_SECONDS = 60  # messages older than 60s won't trigger AI

# ─────────────────────────────────────────────────────────────────────
# EVENT CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────

SKIP_EVENTS = {
    "sessionMessageSent_v2",
    "templateMessageSent_v2",
    "sentMessageDELIVERED_v2",
    "sentMessageREAD_v2",
}

OUTGOING_SENT_EVENTS = {
    "sessionMessageSent",
    "templateMessageSent",
}

STATUS_UPDATE_EVENTS = {
    "sentMessageDELIVERED": "Delivered",
    "sentMessageREAD":      "Read",
}

# whatsappMessageId → mobile_number (for status updates that lack waId)
message_id_to_mobile: dict = {}


# ─────────────────────────────────────────────────────────────────────
# HELPER: GET OR CREATE CONVERSATION
# ─────────────────────────────────────────────────────────────────────

def get_or_create_conversation(mobile_number: str, headers: dict):
    mobile_number = str(mobile_number).replace("+", "").replace(" ", "")

    resp = requests.get(
        f"{settings.ERPNEXT_URL}/api/resource/WhatsApp Conversation",
        headers=headers,
        params={
            "filters": f'[["mobile_number","=","{mobile_number}"]]',
            "fields":  '["name","incoming_count","outgoing_count"]'
        }
    )
    data = resp.json().get("data", [])

    if not data:
        cr = requests.post(
            f"{settings.ERPNEXT_URL}/api/resource/WhatsApp Conversation",
            headers=headers,
            json={
                "doctype":        "WhatsApp Conversation",
                "mobile_number":  mobile_number,
                "chat_status":    "Open",
                "incoming_count": 0,
                "outgoing_count": 0
            }
        )
        conversation_name = cr.json().get("data", {}).get("name")
        incoming_count    = 0
        outgoing_count    = 0
    else:
        conversation_name = data[0]["name"]
        incoming_count    = data[0].get("incoming_count") or 0
        outgoing_count    = data[0].get("outgoing_count") or 0

    doc_resp = requests.get(
        f"{settings.ERPNEXT_URL}/api/resource/WhatsApp Conversation/{conversation_name}",
        headers=headers
    )
    doc = doc_resp.json().get("data", {})
    return conversation_name, doc, incoming_count, outgoing_count


# ─────────────────────────────────────────────────────────────────────
# SAVE NEW MESSAGE ROW
# ─────────────────────────────────────────────────────────────────────

def save_message_to_conversation(
    mobile_number,
    direction,
    whatsapp_message_id="",
    message="",
    message_type="Text",
    template_name="",
    status="",
    event_type="",
):
    mobile_number = str(mobile_number).replace("+", "").replace(" ", "")
    headers = {
        "Authorization": erpnext_service.auth_header,
        "Content-Type": "application/json"
    }

    conversation_name, doc, incoming_count, outgoing_count = \
        get_or_create_conversation(mobile_number, headers)

    existing_messages = doc.get("messages", [])

    if direction == "Incoming":
        incoming_count += 1
    else:
        outgoing_count += 1

    existing_messages.append({
        "doctype":       "WhatsApp Messages",
        "message_time":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "direction":     direction,
        "message":       message,
        "message_type":  message_type,
        "template_name": template_name,
        "status":        status,
        "event_type":    event_type,
        "raw_payload":   whatsapp_message_id,
    })

    result = requests.put(
        f"{settings.ERPNEXT_URL}/api/resource/WhatsApp Conversation/{conversation_name}",
        headers=headers,
        json={
            "messages":          existing_messages,
            "last_message":      message,
            "last_message_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "incoming_count":    incoming_count,
            "outgoing_count":    outgoing_count,
        }
    )
    print(f"SAVE ({direction}) http={result.status_code} mobile={mobile_number}")
    if result.status_code not in (200, 201):
        print(f"SAVE ERROR: {result.text[:300]}")


# ─────────────────────────────────────────────────────────────────────
# UPDATE STATUS ON EXISTING ROW
# ─────────────────────────────────────────────────────────────────────

def update_message_status(mobile_number: str, whatsapp_message_id: str, new_status: str):
    if not whatsapp_message_id or not mobile_number:
        return

    mobile_number = str(mobile_number).replace("+", "").replace(" ", "")
    headers = {
        "Authorization": erpnext_service.auth_header,
        "Content-Type": "application/json"
    }

    resp = requests.get(
        f"{settings.ERPNEXT_URL}/api/resource/WhatsApp Conversation",
        headers=headers,
        params={
            "filters": f'[["mobile_number","=","{mobile_number}"]]',
            "fields":  '["name"]'
        }
    )
    data = resp.json().get("data", [])
    if not data:
        return

    conversation_name = data[0]["name"]
    doc_resp = requests.get(
        f"{settings.ERPNEXT_URL}/api/resource/WhatsApp Conversation/{conversation_name}",
        headers=headers
    )
    messages = doc_resp.json().get("data", {}).get("messages", [])

    updated = False
    for row in messages:
        if row.get("raw_payload") == whatsapp_message_id:
            row["status"] = new_status
            updated = True
            break

    if not updated:
        return

    result = requests.put(
        f"{settings.ERPNEXT_URL}/api/resource/WhatsApp Conversation/{conversation_name}",
        headers=headers,
        json={"messages": messages}
    )
    print(f"STATUS → {new_status} for {mobile_number} | http={result.status_code}")


# ─────────────────────────────────────────────────────────────────────
# WEBHOOK HANDLER
# ─────────────────────────────────────────────────────────────────────

@router.post("/webhooks/wati")
async def handle_wati_webhook(request: Request):
    global claude_service

    try:
        data = await request.json()

        event_type          = data.get("eventType", "")
        whatsapp_message_id = data.get("whatsappMessageId", "")

        print(f"\n--- EVENT: {event_type} | msgId: {whatsapp_message_id[:40] if whatsapp_message_id else 'none'} ---")

        # ── STEP 1: Skip _v2 duplicates ──────────────────────────────
        if event_type in SKIP_EVENTS:
            return {"status": "ignored", "reason": "v2 duplicate"}

        # ── STEP 2: Status receipt events ────────────────────────────
        if event_type in STATUS_UPDATE_EVENTS:
            new_status    = STATUS_UPDATE_EVENTS[event_type]
            mobile_number = data.get("waId") or message_id_to_mobile.get(whatsapp_message_id)
            if mobile_number:
                update_message_status(mobile_number, whatsapp_message_id, new_status)
            return {"status": "status_updated"}

        # ── STEP 3: Outgoing sent ─────────────────────────────────────
        if event_type in OUTGOING_SENT_EVENTS:
            mobile_number = (
                data.get("waId")
                or data.get("whatsappNumber")
                or data.get("phone")
                or data.get("recipient")
            )
            if not mobile_number:
                return {"status": "ignored", "reason": "no mobile"}

            if whatsapp_message_id:
                message_id_to_mobile[whatsapp_message_id] = mobile_number
                if len(message_id_to_mobile) > 500:
                    del message_id_to_mobile[next(iter(message_id_to_mobile))]

            save_message_to_conversation(
                mobile_number=mobile_number,
                direction="Outgoing",
                whatsapp_message_id=whatsapp_message_id,
                message=data.get("text") or "",
                message_type=(data.get("type") or "Text").title(),
                template_name=data.get("templateName") or "",
                status="Sent",
                event_type=event_type,
            )
            return {"status": "saved", "direction": "outgoing"}

        # ── STEP 4: Incoming customer message ─────────────────────────
        whatsapp_id  = data.get("waId")
        message_text = data.get("text", "")

        if not whatsapp_id or data.get("owner"):
            return {"status": "ignored"}

        # ── GUARD 1: DEDUPLICATION ────────────────────────────────────
        # Same whatsappMessageId must never be processed twice
        if whatsapp_message_id and whatsapp_message_id in processed_message_ids:
            print(f"DEDUP SKIP — already processed msgId: {whatsapp_message_id[:40]}")
            return {"status": "ignored", "reason": "duplicate message"}

        # ── GUARD 2: STALE MESSAGE CHECK ──────────────────────────────
        # WATI sometimes delivers old messages 20-40 minutes late.
        # Save them to DB (for audit) but do NOT send an AI reply.
        msg_timestamp  = int(data.get("timestamp") or 0)
        current_time   = int(time.time())
        message_age_seconds = current_time - msg_timestamp if msg_timestamp else 0

        print(f"MESSAGE AGE: {message_age_seconds}s (max allowed: {MAX_MESSAGE_AGE_SECONDS}s)")

        # Always save to DB regardless of age
        save_message_to_conversation(
            mobile_number=whatsapp_id,
            direction="Incoming",
            whatsapp_message_id=whatsapp_message_id,
            message=message_text,
            message_type="Text",
            status="Received",
            event_type=event_type,
        )

        # Mark as processed (deduplicate future re-delivery)
        if whatsapp_message_id:
            processed_message_ids.add(whatsapp_message_id)
            processed_message_ids_order.append(whatsapp_message_id)
            if len(processed_message_ids_order) > 1000:
                oldest = processed_message_ids_order.pop(0)
                processed_message_ids.discard(oldest)

        if message_age_seconds > MAX_MESSAGE_AGE_SECONDS:
            print(f"STALE MESSAGE SKIP — {message_age_seconds}s old, saved to DB but no AI reply sent")
            return {"status": "stale_saved", "age_seconds": message_age_seconds}

        # ── GUARD 3: PER-CUSTOMER COOLDOWN ───────────────────────────
        # Prevent burst replies when customer sends multiple messages quickly
        last_sent = last_reply_time.get(whatsapp_id, 0)
        time_since_last = current_time - last_sent

        if time_since_last < REPLY_COOLDOWN_SECONDS:
            wait_time = REPLY_COOLDOWN_SECONDS - time_since_last
            print(f"COOLDOWN — waiting {wait_time:.1f}s before replying to {whatsapp_id}")
            await asyncio.sleep(wait_time)

        logger.info(f"Received message from {whatsapp_id}: {message_text}")

        # Update opportunity status
        await erpnext_service.update_customer_reply_status(whatsapp_id)

        customer = await erpnext_service.get_lead_by_phone(whatsapp_id)
        if not customer:
            customer = await erpnext_service.create_lead(
                name="New Customer",
                phone=whatsapp_id,
                source="WhatsApp AI Agent",
                product_enquired="Bioman",
                customer_category="B2C"
            )
            logger.info(f"Created new lead: {customer.get('name')}")

        if claude_service is None:
            claude_service = ClaudeService(settings.CLAUDE_API_KEY)

        history      = conversation_history.get(whatsapp_id, [])
        history.append(f"Customer: {message_text}")
        history      = history[-30:]
        history_text = "\n".join(history)
        context      = customer_context.get(whatsapp_id, {})

        system_prompt = f"""You are Bioman's INTERACTIVE SALES AGENT. Goal: QUALIFY LEADS AND DRIVE SALES!

KNOWLEDGE BASE:
{BIOMAN_KNOWLEDGE}

CONVERSATION HISTORY:
{history_text}

CUSTOMER INFO COLLECTED:
- Name: {context.get('name', 'NOT ASKED YET')}
- Location/City: {context.get('location', 'NOT ASKED YET')}
- Occupancy: {context.get('occupancy', 'NOT ASKED YET')}
- Water Type: {context.get('water_type', 'NOT ASKED YET')}
- Available Space: {context.get('space', 'NOT ASKED YET')}
- Crane Access: {context.get('crane', 'NOT ASKED YET')}
- Timeline: {context.get('timeline', 'NOT ASKED YET')}

SALES FUNNEL - ASK IN THIS ORDER:
1. NAME: "Hi! What is your name please?" (FIRST MESSAGE)
2. LOCATION: "Which city/area are you located in?" (SECOND MESSAGE)
3. OCCUPANCY: "How many people will be using the STP?"
4. WATER TYPE: "Is it for toilet only (blackwater), shower+kitchen (greywater), or all water (combined)?"
5. SPACE: "How much space do you have available?"
6. CRANE: "Can a 2-5 ton crane reach your property?"
7. TIMELINE: "When do you need this installed?"
8. RECOMMENDATION: Recommend ONLY tank size first
9. Share pricing ONLY if customer explicitly asks for price/quotation/cost/budget
10. BENEFITS: Highlight savings and features
11. CALL TO ACTION: Push for quote/site visit

CRITICAL RULES:
- ALWAYS ask Name first if not provided
- ALWAYS ask Location/City second
- Ask ONE question per message
- Don't ask for info already provided
- Build on their answers naturally
- Use their name in responses
- Move conversation forward
- NEVER show pricing unless customer explicitly asks
- NEVER show internal tank combinations like "10KL x 2" or "10KL + 5KL"
- ONLY mention final system capacity like "15KL System", "50KL System"

TONE:
- Warm, professional, friendly
- Like a real sales representative
- Enthusiastic about product benefits
- Problem-solving focused
- 4-6 sentences max per message

IF FIRST MESSAGE (history length < 4):
"Hi! Welcome to Bioman BioSTP! I am your sales assistant. Before we proceed, may I have your good name please?"

IF THEY GAVE NAME BUT NO LOCATION:
"Thank you [Name]! Which city or area are you located in? We serve across South India."

IF THEY GAVE BOTH NAME AND LOCATION:
"Great [Name]! So you are in [Location]. Perfect, we have several installations there! Now, how many people will be using the STP?"

AFTER COLLECTING DISCOVERY INFO:
"[Name], based on X people + Y water type, I recommend a [SIZE]KL System. This will save you Rs.X lakhs per year and comes with 25-year warranty!"

CLOSING TECHNIQUES:
- "Ready to get your personalized quote?"
- "Shall I arrange a free site visit?"
- "Can I book you for a consultation call with our technical team?"

NEXT STEP PUSH:
When ready: "Perfect [Name]! To move forward:
- Call: 800 655 4400
- Email: ask@biomanstp.com
- Or I can arrange a FREE site visit!"

REMEMBER: Always be moving towards the next question or closing action. Build momentum!"""

        ai_response = await claude_service.generate_reply(
            customer_message=message_text,
            system_prompt=system_prompt,
            max_tokens=250
        )

        logger.info(f"Generated response: {ai_response}")

        history.append(f"Bioman: {ai_response}")
        conversation_history[whatsapp_id] = history

        send_result = await wati_service.send_message(
            whatsapp_id=whatsapp_id,
            message_text=ai_response
        )

        # Record the time we sent this reply (for cooldown guard)
        last_reply_time[whatsapp_id] = int(time.time())

        await erpnext_service.update_lead_score(
            lead_id=customer.get("name"),
            new_score=min(100, 35 + len(history))
        )

        logger.info(f"Message processed successfully")

        return {
            "status":      "success",
            "customer_id": customer.get("name"),
            "message_id":  send_result.get("message_id")
        }

    except Exception as e:
        logger.error(f"Webhook error: {str(e)}", exc_info=True)
        return {"status": "error", "error": str(e)}
