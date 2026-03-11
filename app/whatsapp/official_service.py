from datetime import UTC, datetime
from typing import Any

import httpx

from config.logging_config import get_logger

logger = get_logger(__name__)


class WhatsAppOfficialService:
    """Service for sending messages via official WhatsApp Business API"""

    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        base_url: str = "https://graph.facebook.com/v18.0",
    ):
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.base_url = base_url
        self.http_client = httpx.AsyncClient()

    async def send_digest(
        self,
        phone_number: str,
        digest_content: str,
        user_display_name: str | None = None,
    ) -> dict[str, Any]:
        """Send digest via official WhatsApp API"""
        try:
            # Format digest content for WhatsApp
            formatted_digest = self._format_digest_for_whatsapp(
                digest_content, user_display_name
            )

            # Send message
            response = await self.http_client.post(
                f"{self.base_url}/{self.phone_number_id}/messages",
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "messaging_product": "whatsapp",
                    "to": phone_number,
                    "type": "text",
                    "text": {"body": formatted_digest},
                },
                timeout=30.0,
            )

            if response.status_code == 200:
                response_data = response.json()
                logger.info(f"Digest sent successfully to {phone_number}")
                return {
                    "success": True,
                    "message_id": response_data.get("messages", [{}])[0].get("id"),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            else:
                error_msg = f"Failed to send digest: {response.text}"
                logger.error(error_msg)
                return {
                    "success": False,
                    "error": error_msg,
                    "status_code": response.status_code,
                }

        except Exception as e:
            error_msg = f"Error sending WhatsApp digest: {e}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

    async def send_digest_to_multiple_phones(
        self,
        phone_numbers: list[str],
        digest_content: str,
        user_display_name: str | None = None,
    ) -> dict[str, Any]:
        """Send digest to multiple phone numbers"""
        results = []
        success_count = 0
        error_count = 0

        for phone in phone_numbers:
            result = await self.send_digest(phone, digest_content, user_display_name)
            results.append({"phone_number": phone, "result": result})

            if result["success"]:
                success_count += 1
            else:
                error_count += 1

        return {
            "total_phones": len(phone_numbers),
            "success_count": success_count,
            "error_count": error_count,
            "results": results,
        }

    def _format_digest_for_whatsapp(
        self, digest_content: str, user_display_name: str | None = None
    ) -> str:
        """Format digest content for WhatsApp (remove Markdown, add emojis)"""
        # Remove Markdown formatting
        formatted = digest_content.replace("*", "").replace("_", "")

        # Add WhatsApp-friendly formatting
        header = "📋 WhatsApp Digest"
        if user_display_name:
            header += f" для {user_display_name}"

        return f"{header}\n\n{formatted}"

    async def test_connection(self) -> bool:
        """Test the connection to WhatsApp Business API"""
        try:
            response = await self.http_client.get(
                f"{self.base_url}/{self.phone_number_id}",
                headers={"Authorization": f"Bearer {self.access_token}"},
                timeout=10.0,
            )

            if response.status_code == 200:
                logger.info("WhatsApp Business API connection test successful")
                return True
            else:
                logger.error(
                    f"WhatsApp Business API connection test failed: {response.text}"
                )
                return False

        except Exception as e:
            logger.error(f"Error testing WhatsApp Business API connection: {e}")
            return False

    async def close(self):
        """Close the HTTP client. Call during app shutdown."""
        await self.http_client.aclose()
