from fastapi import APIRouter
from datetime import datetime, timedelta
import requests

from app.config import settings
from app.services.wati_service import WATIService
from app.services.erpnext_service import ERPNextService

router = APIRouter(
    prefix="/api/v1/drip",
    tags=["drip-followup"]
)

wati_service = WATIService(
    settings.WATI_TOKEN,
    settings.WATI_ENDPOINT
)

erpnext_service = ERPNextService(
    settings.ERPNEXT_URL,
    settings.ERPNEXT_API_KEY,
    settings.ERPNEXT_API_SECRET
)


@router.get("/run")
async def run_drip_followup():

    today = datetime.now().strftime("%Y-%m-%d")

    headers = {
        "Authorization": erpnext_service.auth_header
    }

    filters = [
        ["Opportunity", "custom_drip_next_followup_date", "=", today],
        ["Opportunity", "status", "=", "Follow-up"],
        ["Opportunity", "custom_agent_status", "!=", "Customer Replied"]
    ]

    url = f"{settings.ERPNEXT_URL}/api/resource/Opportunity"

    response = requests.get(
        url,
        headers=headers,
        params={
            "filters": str(filters).replace("'", '"'),
            # "fields": '["name","party_name","contact_mobile","custom_followup_stage"]'
            "fields": '["name","title","contact_mobile","custom_followup_stage","opportunity_owner"]'
        }
    )

    opportunities = response.json().get("data", [])

    for opp in opportunities:

        
        mobile = opp.get("contact_mobile")
        stage = opp.get("custom_followup_stage")

        owner_email = opp.get("opportunity_owner")

        owner_name = "Sales Executive"

        if owner_email:

            user_response = requests.get(
                f"{settings.ERPNEXT_URL}/api/resource/User/{owner_email}",
                headers={
                    "Authorization": erpnext_service.auth_header
                }
            )

            user_data = user_response.json().get("data", {})

            owner_name = (
                user_data.get("first_name")
                or user_data.get("full_name")
                or "Sales Executive"
            )

        print("===================================")
        print("OPPORTUNITY =", opp.get("name"))
        print("RAW MOBILE =", mobile)
        print("STAGE =", stage)

        if not mobile:
            print("MOBILE NUMBER MISSING")
            continue

        mobile = str(mobile).replace("+", "").replace(" ", "")

        print("FORMATTED MOBILE =", mobile)



        template_name = ""
        next_stage = ""
        next_days = 7

        # DAY 1
        if stage == "Day1":

            template_name = "bioman_day1_followup"
            next_stage = "Day2"
            next_days = 1

        # DAY 2
        elif stage == "Day2":

            template_name = "bioman_day2_followup"
            next_stage = "Day4"
            next_days = 2

        # DAY 4
        elif stage == "Day4":

            template_name = "bioman_day4_followup"
            next_stage = "Weekly"
            next_days = 7

        # WEEKLY
        elif stage == "Weekly":

            template_name = "bioman_weekly_followup"
            next_stage = "Weekly"
            next_days = 7

        else:
            continue

        
        print("TEMPLATE NAME =", template_name)

        

        # SEND TEMPLATE
        result = await wati_service.send_template_message(
            whatsapp_id=mobile,
            template_name=template_name,
            broadcast_name="Bioman Drip Followup",
            # parameters=[
            #     {
            #         "name": "1",
            #         "value": opp.get("party_name") or "Customer"
            #     },
            #     {
            #         "name": "2",
            #         "value": "Pravinraj"
            #     }
            # ]

            parameters=[
                {
                    "name": "1",
                    "value": opp.get("title") or "Customer"
                },
                {
                    "name": "2",
                    "value": owner_name
                }
            ]
        )

        print("===================================")
        print("WATI TEMPLATE RESULT =", result)
        print("===================================")

        if not result:
            print("WATI FAILED FOR =", mobile)


        # UPDATE NEXT FOLLOWUP DATE
        next_date = (
            datetime.now() + timedelta(days=next_days)
        ).strftime("%Y-%m-%d")

        update_payload = {
            "custom_followup_stage": next_stage,
            "custom_drip_next_followup_date": next_date
        }

        requests.put(
            f"{settings.ERPNEXT_URL}/api/resource/Opportunity/{opp['name']}",
            headers={
                "Authorization": erpnext_service.auth_header,
                "Content-Type": "application/json"
            },
            json=update_payload
        )

    return {
        "status": "success",
        "processed": len(opportunities)
    }
