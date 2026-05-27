from fastapi import APIRouter
from pydantic import BaseModel

from app.services.wati_service import WATIService
from app.services.erpnext_service import ERPNextService

from app.config import settings

from datetime import datetime, timedelta

import requests

router = APIRouter(
    prefix="/api/v1/followup",
    tags=["followup"]
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


class TemplateRequest(BaseModel):
    mobile: str
    customer_name: str
    opportunity_name: str


@router.post("/send-template")
async def send_template(data: TemplateRequest):

    mobile = data.mobile
    customer_name = data.customer_name
    opportunity_name = data.opportunity_name

    # ============================================================
    # Prevent Sending Duplicate 0 Day Followup Template Starts
    # ============================================================

    # CHECK WHETHER DRIP FOLLOWUP ALREADY INITIALIZED

    response = requests.get(
        f"{settings.ERPNEXT_URL}/api/resource/Opportunity/{opportunity_name}",
        headers={
            "Authorization": erpnext_service.auth_header
        }
    )

    opp_data = response.json().get("data", {})

    existing_drip_date = opp_data.get(
        "custom_drip_next_followup_date"
    )

    # IF DRIP NEXT FOLLOWUP DATE ALREADY EXISTS,
    # IT MEANS 0 DAY TEMPLATE WAS ALREADY SENT EARLIER.
    # SO PREVENT SENDING DUPLICATE 0 DAY FOLLOWUP TEMPLATE.

    if existing_drip_date:

        print(
            f"{opportunity_name} already initialized for drip followup"
        )

        return {
            "status": "ignored",
            "message": "0 Day Followup already sent"
        }

    # ============================================================
    # END - Prevent Sending Duplicate 0 Day Followup Template
    # ============================================================


    # SEND 0 DAY FOLLOWUP TEMPLATE

    result = await wati_service.send_template_message(
        whatsapp_id=mobile,
        template_name="bioman_today_followup",
        broadcast_name="Today Followup",
        parameters=[
            {
                "name": "1",
                "value": customer_name
            }
        ]
    )

    # START DRIP FOLLOWUP AUTOMATION

    try:

        tomorrow = (
            datetime.now() + timedelta(days=1)
        ).strftime("%Y-%m-%d")

        update_payload = {
            "custom_followup_stage": "Day1",
            "custom_drip_next_followup_date": tomorrow,
            "custom_agent_status": "Customer Not Replied"
        }

        requests.put(
            f"{settings.ERPNEXT_URL}/api/resource/Opportunity/{opportunity_name}",
            headers={
                "Authorization": erpnext_service.auth_header,
                "Content-Type": "application/json"
            },
            json=update_payload
        )

        print(f"{opportunity_name} drip initialized")

    except Exception as e:

        print("DRIP INIT ERROR =", str(e))

    return {
        "status": "success",
        "result": result
    }
