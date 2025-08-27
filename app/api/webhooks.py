from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.repository_factory import repository_factory
from app.database.connection import SessionLocal
from app.models.database import WhatsAppMessage
from app.openai_service.service import OpenAIService

router = APIRouter(prefix="/webhook", tags=["webhooks"])


class WhatsAppMessageWebhook(BaseModel):
    """WhatsAppMessageWebhook class."""

    userId: int
    id: str
    body: str
    timestamp: str
    from_: Optional[str] = None
    fromMe: bool
    author: Optional[str] = None
    type: str
    hasMedia: bool
    chatId: str

    class Config:
        """Config class."""

        fields = {"from_": "from"}

    """QRGeneratedWebhook class."""


class QRGeneratedWebhook(BaseModel):
    userId: int
    qr: str

    """ClientReadyWebhook class."""


class ClientReadyWebhook(BaseModel):
    userId: int


@router.post("/whatsapp/qr_generated")
async def receive_qr_generated(data: QRGeneratedWebhook):
    """Webhook for QR code generation notifications"""
    print(f"[WEBHOOK] QR code generated for user {data.userId}")
    # Notification logic for the user can be added here
    # For example, sending an email or push notification
    return {"status": "ok", "message": "QR generation notification received"}


@router.post("/whatsapp/client_ready")
async def receive_client_ready(data: ClientReadyWebhook):
    """Webhook for notifications about WhatsApp client readiness"""
    print(f"[WEBHOOK] WhatsApp client ready for user {data.userId}")

    # Update the user's status in the database
    db = SessionLocal()
    try:
        user = repository_factory.get_user_repository().get_by_id(db, data.userId)
        if user:
            user.whatsapp_connected = True
            user.whatsapp_session_id = f"user_{data.userId}"
            db.commit()
            print(f"[WEBHOOK] Updated user {data.userId} status to connected")
        else:
            print(f"[WEBHOOK] User {data.userId} not found")
    except Exception as e:
        print(f"[WEBHOOK] Error updating user status: {e}")
        db.rollback()
    finally:
        db.close()

    return {"status": "ok", "message": "Client ready notification received"}


@router.post("/whatsapp/message")
async def receive_whatsapp_message(message_data: WhatsAppMessageWebhook):
    """Webhook for receiving new messages from the WhatsApp Bridge"""
    db = SessionLocal()
    try:
        # Find the user
        user = repository_factory.get_user_repository().get_by_id_or_404(
            db, message_data.userId
        )

        # Check whether this chat is being monitored
        monitored_chat = (
            repository_factory.get_monitored_chat_repository().get_by_user_and_chat_id(
                db, user.id, message_data.chatId
            )
        )

        if not monitored_chat:
            # Chat is not monitored; ignore the message
            return {"message": "Chat not monitored, message ignored"}

        # Check whether we've already processed this message
        existing_message = (
            repository_factory.get_whatsapp_message_repository().get_by_message_id(
                db, message_data.messageId
            )
        )

        if existing_message:
            return {"message": "Message already processed"}

        # Analyze message importance via OpenAI
        content_text = message_data.content or ""
        openai_service = OpenAIService()
        importance_score = await openai_service.analyze_message_importance(
            content_text, monitored_chat.chat_name
        )

        # Save the message to the database
        db_message = WhatsAppMessage(
            chat_id=monitored_chat.id,
            message_id=message_data.messageId,
            sender=message_data.sender or "Unknown",
            content=content_text,
            timestamp=datetime.fromisoformat(
                message_data.timestamp.replace("Z", "+00:00")
            ),
            importance_score=importance_score,
            is_processed=False,
        )

        db.add(db_message)
        db.commit()

        return {
            "message": "Message received and processed",
            "importance_score": importance_score,
            "chat_name": monitored_chat.chat_name,
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing message: {str(e)}",
        )
    finally:
        db.close()
