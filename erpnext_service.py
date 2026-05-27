
"""ERPNext CRM integration"""



import aiohttp

import logging

import json

import base64

from typing import Optional, Dict, Any



logger = logging.getLogger(__name__)





class ERPNextService:

    """ERPNext API client"""

    

    def __init__(self, url: str, api_key: str, api_secret: str):

        self.url = url

        self.api_key = api_key

        self.api_secret = api_secret

        

        auth_string = f"{api_key}:{api_secret}"

        encoded = base64.b64encode(auth_string.encode()).decode()

        self.auth_header = f"Basic {encoded}"

    

    async def get_lead_by_phone(self, phone_number: str) -> Optional[Dict]:

        """Get lead by phone number"""

        

        cleaned_phone = phone_number.replace("+", "").replace("-", "").replace(" ", "")

        

        filters = json.dumps([["whatsapp_no", "=", cleaned_phone]])

        

        try:

            headers = {

                "Authorization": self.auth_header,

                "Accept": "application/json"

            }

            

            async with aiohttp.ClientSession() as session:

                async with session.get(

                    f"{self.url}/api/method/frappe.client.get_list",

                    params={

                        "doctype": "Lead",

                        "filters": filters,

                        "fields": '["name", "first_name", "email", "mobile_no"]',

                        "limit_page_length": 1

                    },

                    headers=headers,

                    timeout=aiohttp.ClientTimeout(total=30)

                ) as response:

                    

                    if response.status == 200:

                        data = await response.json()

                        leads = data.get("message", [])

                        

                        if leads:

                            return await self.get_lead(leads[0]["name"])

                    

                    return None

        

        except Exception as e:

            logger.error(f"Error fetching lead: {str(e)}")

            return None

    

    async def get_lead(self, lead_id: str) -> Optional[Dict]:

        """Get lead details"""

        

        try:

            headers = {

                "Authorization": self.auth_header,

                "Accept": "application/json"

            }

            

            async with aiohttp.ClientSession() as session:

                async with session.get(

                    f"{self.url}/api/resource/Lead/{lead_id}",

                    headers=headers,

                    timeout=aiohttp.ClientTimeout(total=30)

                ) as response:

                    

                    if response.status == 200:

                        data = await response.json()

                        return data.get("data")

                    

                    return None

        

        except Exception as e:

            logger.error(f"Error fetching lead: {str(e)}")

            return None

    

    async def create_lead(

        self,

        name: str,

        phone: str,

        email: Optional[str] = None,

        source: str = "WhatsApp AI Agent",

        product_enquired: str = "Bioman",

        customer_category: str = "B2C"

    ) -> Dict:

        """Create new lead"""

        

        payload = {

            "doctype": "Lead",

            "first_name": name,

            "mobile_no": phone,

            "whatsapp_no": phone,

            "whatsapp_number": phone,

            "email": email or f"contact@bioman.in",

            "source": source,

            "ai_lead_score": 20,

            "ai_stage": "Awareness",

            "custom_product_enquired": product_enquired,

            "custom_customer_category": customer_category

        }

        

        try:

            headers = {

                "Authorization": self.auth_header,

                "Accept": "application/json",

                "Content-Type": "application/json"

            }

            

            async with aiohttp.ClientSession() as session:

                async with session.post(

                    f"{self.url}/api/resource/Lead",

                    json=payload,

                    headers=headers,

                    timeout=aiohttp.ClientTimeout(total=30)

                ) as response:

                    

                    if response.status in [200, 201]:

                        data = await response.json()

                        logger.info(f"Created lead: {data['data']['name']}")

                        return data.get("data", {})

                    

                    return {}

        

        except Exception as e:

            logger.error(f"Error creating lead: {str(e)}")

            return {}

    

    async def update_lead_score(self, lead_id: str, new_score: int) -> bool:

        """Update lead score"""

        

        from datetime import datetime

        

        payload = {

            "ai_lead_score": new_score,

            "last_ai_interaction": datetime.now().isoformat()

        }

        

        try:

            headers = {

                "Authorization": self.auth_header,

                "Accept": "application/json",

                "Content-Type": "application/json"

            }

            

            async with aiohttp.ClientSession() as session:

                async with session.put(

                    f"{self.url}/api/resource/Lead/{lead_id}",

                    json=payload,

                    headers=headers,

                    timeout=aiohttp.ClientTimeout(total=30)

                ) as response:

                    

                    if response.status in [200, 201]:

                        logger.info(f"Updated lead score: {new_score}")

                        return True

                    

                    return False

        

        except Exception as e:

            logger.error(f"Error updating score: {str(e)}")

            return False 
        

    #new agent status update code starts below***

    async def update_customer_reply_status(self, phone: str):

        
        """Update Opportunity status when customer replies"""

        try:

            last_10 = phone[-10:]

            filters = json.dumps([
                ["Opportunity", "contact_mobile", "like", f"%{last_10}%"]
            ])

            headers = {
                "Authorization": self.auth_header,
                "Accept": "application/json",
                "Content-Type": "application/json"
            }

            async with aiohttp.ClientSession() as session:

                # FIND OPPORTUNITY
                async with session.get(
                    f"{self.url}/api/method/frappe.client.get_list",
                    params={
                        "doctype": "Opportunity",
                        "filters": filters,
                        "fields": '["name"]',
                        "limit_page_length": 1
                    },
                    headers=headers
                ) as response:

                    data = await response.json()

                    opportunities = data.get("message", [])

                    if opportunities:

                        opportunity_name = opportunities[0]["name"]

                        # UPDATE STATUS
                        payload = {
                            "custom_agent_status": "Customer Replied"
                        }

                        async with session.put(
                            f"{self.url}/api/resource/Opportunity/{opportunity_name}",
                            json=payload,
                            headers=headers
                        ) as update_response:

                            update_data = await update_response.json()

                            logger.info(
                                f"{opportunity_name} updated as Customer Replied"
                            )

                            return update_data

            return None

        except Exception as e:

            logger.error(f"Reply Status Update Error: {str(e)}")
            return None
        


