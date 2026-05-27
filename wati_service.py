
"""WATI WhatsApp API integration"""



import aiohttp

import logging

import urllib.parse

from datetime import datetime



logger = logging.getLogger(__name__)





class WATIService:

    """WATI API client"""

    

    def __init__(self, token: str, endpoint: str):

        self.token = token

        self.endpoint = endpoint

    

    async def send_message(self, whatsapp_id: str, message_text: str) -> dict:

        """Send WhatsApp message"""

        

        encoded_message = urllib.parse.quote(message_text)

        url = f"{self.endpoint}/api/v1/sendSessionMessage/{whatsapp_id}?messageText={encoded_message}"

        

        headers = {

            "Authorization": f"Bearer {self.token}",

            "accept": "application/json"

        }

        

        try:

            async with aiohttp.ClientSession() as session:

                async with session.post(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:

                    

                    if response.status == 200:

                        data = await response.json()

                        logger.info(f"Message sent to {whatsapp_id}")

                        return {

                            "status": "success",

                            "message_id": data.get("messageId"),

                            "timestamp": datetime.now().isoformat()

                        }

                    else:

                        logger.error(f"WATI error: {response.status}")

                        return {"status": "error", "error": f"HTTP {response.status}"}

        

        except Exception as e:

            logger.error(f"WATI error: {str(e)}")

            return {"status": "error", "error": str(e)}
        

    #new code added for followup
    async def send_template_message(
        self,
        whatsapp_id: str,
        template_name: str,
        broadcast_name: str,
        parameters=None
    ) -> dict:

        """Send WhatsApp template message"""

        whatsapp_id = ''.join(filter(str.isdigit, str(whatsapp_id)))

        if len(whatsapp_id) == 10:
            whatsapp_id = "91" + whatsapp_id

        url = f"{self.endpoint}/api/v1/sendTemplateMessage?whatsappNumber={whatsapp_id}"

    

        payload = {
            "template_name": template_name,
            "broadcast_name": broadcast_name,
            "parameters": parameters or []
        }



        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        try:

            async with aiohttp.ClientSession() as session:

                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:

                    

                    print("FINAL PAYLOAD =", payload)

                    data = await response.json()

                    print("STATUS CODE =", response.status)
                    print("WATI RESPONSE =", data)


                    if response.status == 200 and data.get("result") == True:

                        logger.info(f"Template sent to {whatsapp_id}")

                        return {
                            "status": "success",
                            "response": data
                        }

                    else:

                        logger.error(f"WATI Template Error: {data}")

                        return {
                            "status": "error",
                            "error": data
                        }

        except Exception as e:

            logger.error(f"Template Send Error: {str(e)}")

            return {
                "status": "error",
                "error": str(e)
            }
        

