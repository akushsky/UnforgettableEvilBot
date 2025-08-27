import asyncio
import logging
import os
import signal
import subprocess
from datetime import datetime
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class WhatsAppService:
    """WhatsAppService class."""

    def __init__(self, session_path: str):
        """Initialize the class.

        Args:
            session_path: Description of session_path.
        """
        self.session_path = session_path
        self.bridge_url = "http://localhost:3000"
        self.bridge_process: Optional[subprocess.Popen] = None
        self.is_connected = False
        self.http_client = httpx.AsyncClient()

    async def start_bridge_if_needed(self):
        """Start Node.js bridge if not already running"""
        try:
            # Check whether the bridge is running
            response = await self.http_client.get(
                f"{self.bridge_url}/health", timeout=2.0
            )
            if response.status_code == 200:
                logger.info("WhatsApp Bridge already running")
                return True
        except BaseException:
            # Bridge is not running; start it
            logger.info("Starting WhatsApp Bridge...")
            bridge_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "..", "whatsapp_bridge"
            )

            self.bridge_process = subprocess.Popen(
                ["node", "persistent_bridge.js"],
                cwd=bridge_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid if os.name != "nt" else None,
            )

            # Wait for the service to start
            for _ in range(30):  # 30 seconds for startup
                try:
                    response = await self.http_client.get(
                        f"{self.bridge_url}/health", timeout=1.0
                    )
                    if response.status_code == 200:
                        logger.info("WhatsApp Bridge started successfully")
                        return True
                except BaseException:
                    await asyncio.sleep(1)

            logger.error("Failed to start WhatsApp Bridge")
            return False

        return True

    async def initialize_client(self, user_id: int):
        """Initialize the WhatsApp client for the user"""
        try:
            # Start the bridge if needed
            if not await self.start_bridge_if_needed():
                return False

            logger.info(f"Initializing WhatsApp client for user {user_id}")

            response = await self.http_client.post(
                f"{self.bridge_url}/initialize/{user_id}", timeout=30.0
            )

            if response.status_code == 200:
                self.is_connected = True
                logger.info(
                    f"WhatsApp client initialization started for user {user_id}"
                )

                # Check connection status
                await asyncio.sleep(2)  # Give time for initialization
                await self.get_client_status(user_id)

                return True
            else:
                logger.error(f"Failed to initialize client: {response.text}")
                return False

        except Exception as e:
            logger.error(f"Failed to initialize WhatsApp client: {e}")
            return False

    async def get_client_status(self, user_id: int) -> Dict:
        """Get client status"""
        try:
            response = await self.http_client.get(
                f"{self.bridge_url}/status/{user_id}", timeout=10.0
            )

            if response.status_code == 200:
                return response.json()
            else:
                return {"connected": False, "error": response.text}

        except Exception as e:
            logger.error(f"Failed to get client status: {e}")
            return {"connected": False, "error": str(e)}

    async def get_chats(self, user_id: int) -> List[Dict]:
        """Get a list of all user's chats"""
        try:
            response = await self.http_client.get(
                f"{self.bridge_url}/chats/{user_id}", timeout=30.0
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("chats", [])
            else:
                logger.error(f"Failed to get chats: {response.text}")
                return []

        except Exception as e:
            logger.error(f"Failed to get chats: {e}")
            return []

    async def get_new_messages(
        self, user_id: int, chat_ids: List[str], since: datetime
    ) -> List[Dict]:
        """Get new messages from specified chats since a certain time"""
        try:
            all_messages = []

            for chat_id in chat_ids:
                response = await self.http_client.get(
                    f"{self.bridge_url}/messages/{user_id}/{chat_id}",
                    params={"limit": 100, "since": since.isoformat()},
                    timeout=30.0,
                )

                if response.status_code == 200:
                    data = response.json()
                    messages = data.get("messages", [])

                    # Filter messages by time
                    for msg in messages:
                        msg_time = datetime.fromisoformat(
                            msg["timestamp"].replace("Z", "+00:00")
                        )
                        if (
                            msg_time > since and not msg["fromMe"]
                        ):  # Don't take our own messages
                            msg["chat_id"] = chat_id
                            all_messages.append(msg)
                else:
                    logger.error(
                        f"Failed to get messages for chat {chat_id}: {response.text}"
                    )

            return all_messages

        except Exception as e:
            logger.error(f"Failed to get messages: {e}")
            return []

    async def disconnect(self, user_id: int):
        """Disconnect from WhatsApp"""
        try:
            response = await self.http_client.post(
                f"{self.bridge_url}/disconnect/{user_id}", timeout=10.0
            )

            if response.status_code == 200:
                logger.info(f"WhatsApp client disconnected for user {user_id}")
                self.is_connected = False
            else:
                logger.error(f"Failed to disconnect: {response.text}")

        except Exception as e:
            logger.error(f"Failed to disconnect: {e}")

    def __del__(self):
        """Cleanup resources when deleting the object"""
        if self.bridge_process:
            try:
                if os.name != "nt":
                    os.killpg(os.getpgid(self.bridge_process.pid), signal.SIGTERM)
                else:
                    self.bridge_process.terminate()
            except Exception as e:
                logger.warning(
                    f"Failed to terminate bridge process: {e}"
                )  # Log the error instead of silently passing
