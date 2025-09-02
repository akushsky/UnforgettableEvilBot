from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.repository_factory import repository_factory
from app.core.validators import SecurityValidators
from app.database.connection import get_db
from app.models.database import MonitoredChat, User, WhatsAppMessage
from app.models.schemas import WhatsAppConnectionWebhook, WhatsAppMessageWebhook
from app.openai_service.service import OpenAIService
from config.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/webhook/whatsapp", tags=["whatsapp-webhooks"])


class WhatsAppReconnectionService:
    """Service for WhatsApp connection restoration"""

    async def handle_connection_restored(self, user_id: str, db: Session):
        """Processing connection restoration"""
        try:
            user = repository_factory.get_user_repository().get_by_id(db, user_id)
            if user and user.telegram_channel_id:
                from app.telegram.service import TelegramService

                telegram_service = TelegramService()

                notification = f"✅ WhatsApp подключение восстановлено для пользователя {user.username}"
                await telegram_service.send_notification(
                    user.telegram_channel_id, notification
                )

                logger.info(f"Connection restored notification sent for user {user_id}")

        except Exception as e:
            logger.error(f"Failed to send reconnection notification: {e}")


reconnection_service = WhatsAppReconnectionService()


def _validate_and_sanitize_message(
    message: WhatsAppMessageWebhook,
) -> tuple[str, str, str | None]:
    """Validate and sanitize message input data"""
    sanitized_content = message.content or ""
    sanitized_chat_name = (
        SecurityValidators.sanitize_input(message.chatName, max_length=100)
        if message.chatName
        else ""
    )
    sanitized_sender = (
        SecurityValidators.sanitize_input(message.sender, max_length=100)
        if message.sender
        else None
    )
    return sanitized_content, sanitized_chat_name, sanitized_sender


def _get_user_id(message: WhatsAppMessageWebhook) -> int:
    """Extract and validate user ID from message"""
    try:
        return int(message.userId)
    except ValueError:
        logger.warning(f"Invalid user ID format: {message.userId}")
        raise HTTPException(status_code=400, detail="Invalid user ID format")


def _validate_user(user_id: int, db: Session) -> User:
    """Validate that user exists and is active"""
    user = repository_factory.get_user_repository().get_by_id(db, user_id)
    if not user:
        logger.warning(f"User {user_id} not found")
        raise HTTPException(status_code=404, detail="User not found")

    if not user.is_active:
        logger.info(
            f"User {user_id} ({user.username}) is suspended - skipping message processing"
        )
        raise HTTPException(status_code=200, detail="User is suspended")

    return user


def _validate_monitored_chat(
    user_id: int, chat_id: str, chat_name: str, db: Session
) -> MonitoredChat | None:
    """Validate that chat is being monitored"""
    monitored_chat = (
        repository_factory.get_monitored_chat_repository().get_by_user_and_chat_id(
            db, user_id, chat_id
        )
    )

    if not monitored_chat:
        logger.info(
            f"Chat {chat_id} ({chat_name}) is not monitored by user {user_id} - skipping message"
        )
        return None

    return monitored_chat


def _check_duplicate_message(message_id: str, db: Session) -> bool:
    """Check if message has already been processed"""
    existing_message = (
        repository_factory.get_whatsapp_message_repository().get_by_message_id(
            db, message_id
        )
    )

    if existing_message:
        logger.info(f"Message {message_id} already processed")
        return True

    return False


def _parse_timestamp(timestamp: str) -> datetime:
    """Parse timestamp safely"""
    try:
        if timestamp.endswith("Z"):
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        else:
            return datetime.fromisoformat(timestamp)
    except Exception:
        return datetime.utcnow()


def _save_message(
    message: WhatsAppMessageWebhook,
    monitored_chat: MonitoredChat,
    sanitized_content: str,
    sanitized_sender: str | None,
    timestamp: datetime,
    db: Session,
) -> None:
    """Save the message to the database"""
    whatsapp_message = WhatsAppMessage(
        chat_id=monitored_chat.id,
        message_id=message.messageId,
        sender=sanitized_sender or "",
        content=sanitized_content,
        timestamp=timestamp,
        importance_score=message.importance,
        has_media=message.hasMedia,
        is_processed=False,
    )

    db.add(whatsapp_message)
    db.commit()


@router.post("/message")
async def receive_whatsapp_message(
    message: WhatsAppMessageWebhook,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Receive a new message from WhatsApp via the Node.js bridge with secure validation"""
    try:
        logger.info(f"Received WhatsApp message for user {message.userId}")

        # Validate and sanitize input data
        (
            sanitized_content,
            sanitized_chat_name,
            sanitized_sender,
        ) = _validate_and_sanitize_message(message)

        # Validate user
        user_id = _get_user_id(message)
        _validate_user(user_id, db)

        # Validate monitored chat
        monitored_chat = _validate_monitored_chat(
            user_id, message.chatId, sanitized_chat_name, db
        )

        # Skip if chat is not monitored
        if not monitored_chat:
            return {"status": "skipped", "message": "Chat is not being monitored"}

        # Check for duplicate message
        if _check_duplicate_message(message.messageId, db):
            return {"status": "skipped", "message": "Message already processed"}

        # Parse timestamp
        _parse_timestamp(message.timestamp)

        # Add background task for AI analysis and saving
        background_tasks.add_task(
            analyze_and_save_message,
            message,
            int(monitored_chat.id),
            str(user_id),
        )

        return {"status": "success", "message": "Message queued for analysis"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error processing message: {str(e)}"
        )


@router.post("/connected")
async def whatsapp_connected(
    connection: WhatsAppConnectionWebhook,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Notification about WhatsApp client connection with validation"""
    try:
        # Validate connection data
        if not connection.userId:
            raise HTTPException(status_code=400, detail="Invalid user ID")

        logger.info(f"WhatsApp client connected for user {connection.userId}")

        # Update the user's status
        user = repository_factory.get_user_repository().get_by_id(db, connection.userId)
        if user:
            user.whatsapp_connected = True
            user.whatsapp_last_seen = datetime.utcnow()
            user.whatsapp_session_id = f"session_{connection.userId}"
            db.commit()

            # Start connection restoration in the background
            background_tasks.add_task(
                reconnection_service.handle_connection_restored, connection.userId, db
            )

        return {"status": "success", "message": "Connection status updated"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating connection status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def whatsapp_webhook_health():
    """Health check endpoint for WhatsApp webhooks"""
    return {"status": "healthy", "service": "whatsapp-webhooks"}


@router.get("/active-users")
async def get_active_users(db: Session = Depends(get_db)):
    """Get active users for WhatsApp bridge restoration"""
    try:
        # Get active users with WhatsApp connected
        active_users = (
            repository_factory.get_user_repository().get_active_users_with_whatsapp(db)
        )

        return {
            "active_users": [
                {
                    "id": user.id,
                    "username": user.username,
                    "whatsapp_connected": user.whatsapp_connected,
                    "is_active": user.is_active,
                }
                for user in active_users
            ]
        }
    except Exception as e:
        logger.error(f"Error getting active users: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/disconnected")
async def whatsapp_disconnected(
    connection: WhatsAppConnectionWebhook, db: Session = Depends(get_db)
):
    """Notification about WhatsApp client disconnection"""
    try:
        # Validate connection data
        if not connection.userId:
            raise HTTPException(status_code=400, detail="Invalid user ID")

        logger.info(f"WhatsApp client disconnected for user {connection.userId}")

        # Update the user's status
        user = repository_factory.get_user_repository().get_by_id(db, connection.userId)
        if user:
            user.whatsapp_connected = False
            user.whatsapp_last_seen = datetime.utcnow()
            db.commit()

            # Send a Telegram notification if configured
            if user.telegram_channel_id:
                from app.telegram.service import TelegramService

                telegram_service = TelegramService()

                notification = f"❌ WhatsApp отключен для пользователя {user.username}"
                await telegram_service.send_notification(
                    user.telegram_channel_id, notification
                )

        return {"status": "success", "message": "Disconnection status updated"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating disconnection status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def analyze_and_save_message(
    message: WhatsAppMessageWebhook, chat_db_id: int, user_id: str
):
    """Background task: analyze importance and save the message with safe handling"""
    # Create a new DB session for the background task
    from app.database.connection import SessionLocal

    db = SessionLocal()

    try:
        # Additional validation in the background task
        if not message.content:
            logger.warning(f"Message content is empty for message {message.messageId}")
            return

        sanitized_content = SecurityValidators.sanitize_input(
            message.content, max_length=5000
        )
        if not sanitized_content:
            logger.warning(
                f"Message content sanitization failed for message {message.messageId}"
            )
            return

        # Use OpenAI for a more accurate importance analysis
        openai_service = OpenAIService()
        chat_name = message.chatName or ""
        ai_importance = await openai_service.analyze_message_importance(
            sanitized_content,
            f"Чат: {SecurityValidators.sanitize_input(chat_name, max_length=100)}, Тип: {message.chatType}",
        )

        # Take the maximum between the base score and AI
        final_importance = max(message.importance, ai_importance)

        # Safe parsing of the timestamp
        try:
            if message.timestamp.endswith("Z"):
                timestamp = datetime.fromisoformat(
                    message.timestamp.replace("Z", "+00:00")
                )
            elif "+" in message.timestamp or message.timestamp.endswith("UTC"):
                timestamp = datetime.fromisoformat(message.timestamp.replace("UTC", ""))
            else:
                # If the format is unknown, use the current time
                timestamp = datetime.utcnow()
                logger.warning(
                    f"Unknown timestamp format: {message.timestamp}, using current time"
                )
        except (ValueError, AttributeError) as e:
            logger.warning(
                f"Failed to parse timestamp {message.timestamp}: {e}, using current time"
            )
            timestamp = datetime.utcnow()

        # Save the message to the database
        whatsapp_message = WhatsAppMessage(
            chat_id=chat_db_id,
            message_id=message.messageId,
            sender=SecurityValidators.sanitize_input(
                message.sender or "", max_length=100
            ),
            content=sanitized_content,
            timestamp=timestamp,
            importance_score=final_importance,
            has_media=message.hasMedia,
            is_processed=False,
            ai_analyzed=True,  # Mark as analyzed by AI
        )

        db.add(whatsapp_message)
        db.commit()

        logger.info(
            f"Saved message {message.messageId} with importance {final_importance}"
        )

        # If the message is critically important, we can send an immediate notification
        if final_importance >= 5:
            await send_urgent_notification(message, user_id)

    except Exception as e:
        logger.error(f"Error analyzing and saving message: {e}")
        db.rollback()
    finally:
        db.close()


async def send_urgent_notification(message: WhatsAppMessageWebhook, user_id: str):
    """Send an urgent notification with safe handling"""
    # Create a new DB session for the background task
    from app.database.connection import SessionLocal

    db = SessionLocal()

    try:
        user = repository_factory.get_user_repository().get_by_id(db, user_id)
        if user and user.is_active and user.telegram_channel_id:
            from app.telegram.service import TelegramService

            telegram_service = TelegramService()

            # Safe message processing
            if not message.content:
                logger.warning("Message content is empty for urgent notification")
                return

            sanitized_content = SecurityValidators.sanitize_input(
                message.content, max_length=2000
            )
            # Get the monitored chat to check for custom name
            monitored_chat = repository_factory.get_monitored_chat_repository().get_by_user_and_chat_id(
                db, int(user_id), message.chatId
            )

            # Use custom name if available, otherwise use original chat name
            if monitored_chat and monitored_chat.custom_name:
                sanitized_chat_name = SecurityValidators.sanitize_input(
                    monitored_chat.custom_name, max_length=100
                )
            else:
                sanitized_chat_name = SecurityValidators.sanitize_input(
                    message.chatName or "", max_length=100
                )
            sanitized_sender = SecurityValidators.sanitize_input(
                message.sender or "", max_length=100
            )

            # Translate the message into Russian via OpenAI
            openai_service = OpenAIService()
            translated_message = await openai_service.translate_to_russian(
                sanitized_content
            )

            urgent_text = "🚨 *СРОЧНОЕ СООБЩЕНИЕ*\n\n"
            urgent_text += f"📱 Чат: *{sanitized_chat_name}*\n"
            urgent_text += f"👤 От: *{sanitized_sender}*\n"
            urgent_text += f"💬 Сообщение: {translated_message}\n"
            urgent_text += f"🕐 Время: {datetime.now().strftime('%H:%M %d.%m.%Y')}"

            await telegram_service.send_notification(
                user.telegram_channel_id, urgent_text
            )

            logger.info(f"Sent urgent notification for message {message.messageId}")

    except Exception as e:
        logger.error(f"Error sending urgent notification: {e}")
    finally:
        db.close()
