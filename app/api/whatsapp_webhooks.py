from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.webhook_auth import verify_bridge_secret
from app.core.repository_factory import repository_factory
from app.core.user_utils import get_user_settings
from app.core.validators import SecurityValidators
from app.database.connection import get_db
from app.dependencies import get_openai_service, get_telegram_service
from app.models.database import MonitoredChat, User, WhatsAppMessage
from app.models.schemas import WhatsAppConnectionWebhook, WhatsAppMessageWebhook
from config.logging_config import get_logger

logger = get_logger(__name__)

# Stored in place of the body when a message carries no analysable text, so the
# message is still persisted and counted in digests instead of being dropped.
EMPTY_CONTENT_PLACEHOLDER = "[media]"
MAX_CONTENT_LENGTH = 5000
# Fallback digest threshold when the user's own min_importance_level cannot be
# read. Matches the UserSettings.min_importance_level column default.
DEFAULT_DIGEST_IMPORTANCE_FLOOR = 3
router = APIRouter(
    prefix="/webhook/whatsapp",
    tags=["whatsapp-webhooks"],
    dependencies=[Depends(verify_bridge_secret)],
)


class WhatsAppReconnectionService:
    """Service for WhatsApp connection restoration"""

    async def handle_connection_restored(self, user_id: str):
        """Processing connection restoration.

        Runs after the response is sent, so it opens its own session instead of
        reusing the request-scoped one, which is already closed by then.
        """
        from app.database.connection import get_db_session

        try:
            with get_db_session() as db:
                user = repository_factory.get_user_repository().get_by_id(
                    db, int(user_id)
                )
                if not (user and user.telegram_channel_id):
                    return
                telegram_channel_id = user.telegram_channel_id
                username = user.username

            telegram_service = get_telegram_service()
            notification = (
                f"✅ WhatsApp подключение восстановлено для пользователя {username}"
            )
            await telegram_service.send_notification(telegram_channel_id, notification)
            logger.info(f"Connection restored notification sent for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to send reconnection notification: {e}")


reconnection_service = WhatsAppReconnectionService()


def _validate_and_sanitize_message(
    message: WhatsAppMessageWebhook,
) -> tuple[str, str, str | None]:
    """Validate and sanitize message input data"""
    sanitized_content = (
        SecurityValidators.sanitize_input(
            message.content, max_length=MAX_CONTENT_LENGTH
        )
        if message.content
        else ""
    )
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
        raise HTTPException(status_code=400, detail="Invalid user ID format") from None


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


def _get_existing_message(message_id: str, db: Session) -> WhatsAppMessage | None:
    """The already-stored row for this message id, if any."""
    return repository_factory.get_whatsapp_message_repository().get_by_message_id(
        db, message_id
    )


def _urgent_notifications_enabled(user_id: int, db: Session) -> bool:
    """Whether the user opted to receive urgent alerts.

    Urgent alerts are opt-out, so an unreadable or missing setting keeps them on.
    """
    try:
        user_settings = get_user_settings(user_id, db)
    except Exception as e:
        logger.warning(
            f"Could not read urgent_notifications for user {user_id}: {e}. "
            "Assuming enabled."
        )
        return True

    enabled = user_settings.urgent_notifications
    return True if enabled is None else bool(enabled)


def _digest_importance_floor(user_id: int, db: Session) -> int:
    """Lowest importance the user still wants to see in a digest."""
    try:
        user_settings = get_user_settings(user_id, db)
        return int(user_settings.min_importance_level)
    except Exception as e:
        logger.warning(
            f"Could not read min_importance_level for user {user_id}: {e}. "
            f"Using default {DEFAULT_DIGEST_IMPORTANCE_FLOOR}."
        )
        return DEFAULT_DIGEST_IMPORTANCE_FLOOR


def _parse_timestamp(timestamp: str) -> datetime:
    """Parse timestamp safely"""
    try:
        if timestamp.endswith("Z"):
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        else:
            return datetime.fromisoformat(timestamp)
    except Exception as e:
        logger.warning(f"Failed to parse timestamp '{timestamp}': {e}")
        return datetime.now(UTC)


def _save_message(
    message: WhatsAppMessageWebhook,
    chat_db_id: int,
    sanitized_content: str,
    sanitized_sender: str | None,
    timestamp: datetime,
    db: Session,
) -> bool:
    """Persist the message with its provisional importance before AI analysis.

    Returns False only when the row is genuinely already there (unique
    message_id), so the caller can report a skip instead of failing the bridge
    webhook. Any other IntegrityError is re-raised: the webhook must answer 500
    so the bridge retries instead of silently dropping the message.
    """
    whatsapp_message = WhatsAppMessage(
        chat_id=chat_db_id,
        message_id=message.messageId,
        sender=sanitized_sender or "",
        content=sanitized_content or EMPTY_CONTENT_PLACEHOLDER,
        timestamp=timestamp,
        importance_score=message.importance,
        has_media=message.hasMedia,
        is_processed=False,
        ai_analyzed=False,
    )

    db.add(whatsapp_message)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if _get_existing_message(message.messageId, db) is not None:
            logger.info(f"Message {message.messageId} already stored - skipping insert")
            return False

        logger.error(
            f"IntegrityError storing message {message.messageId} but no existing row "
            "found - failing the webhook so the bridge retries"
        )
        raise

    return True


def _duplicate_response(
    message: WhatsAppMessageWebhook,
    chat_db_id: int,
    user_id: int,
    background_tasks: BackgroundTasks,
    existing: WhatsAppMessage | None,
) -> dict[str, str]:
    """Answer a duplicate delivery, re-queueing analysis if it never happened.

    A row that exists but was never scored means the previous attempt died
    between the insert and the AI call. Hard-skipping it would leave the
    message stuck at its provisional importance forever.
    """
    if existing is not None and not existing.ai_analyzed:
        logger.info(
            f"Message {message.messageId} already stored but not analyzed - "
            "re-queueing analysis"
        )
        background_tasks.add_task(
            analyze_and_save_message,
            message,
            chat_db_id,
            str(user_id),
        )
        return {
            "status": "requeued",
            "message": "Message already stored but not analyzed - queued for analysis",
        }

    logger.info(f"Message {message.messageId} already processed")
    return {"status": "skipped", "message": "Message already processed"}


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

        chat_db_id = int(monitored_chat.id)

        # Check for duplicate message
        existing = _get_existing_message(message.messageId, db)
        if existing is not None:
            return _duplicate_response(
                message, chat_db_id, user_id, background_tasks, existing
            )

        # Parse timestamp
        timestamp = _parse_timestamp(message.timestamp)

        # Persist before analysis so a failing/slow AI call cannot lose the message
        stored = _save_message(
            message,
            chat_db_id,
            sanitized_content,
            sanitized_sender,
            timestamp,
            db,
        )
        if not stored:
            return _duplicate_response(
                message,
                chat_db_id,
                user_id,
                background_tasks,
                _get_existing_message(message.messageId, db),
            )

        # Enrich the stored row with AI importance after the response is sent
        background_tasks.add_task(
            analyze_and_save_message,
            message,
            chat_db_id,
            str(user_id),
        )

        return {
            "status": "success",
            "message": "Message stored and queued for analysis",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error processing message: {e!s}"
        ) from e


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

        user = repository_factory.get_user_repository().get_by_id(
            db, int(connection.userId)
        )
        if user:
            user.whatsapp_connected = True
            user.whatsapp_last_seen = datetime.now(UTC)
            user.whatsapp_session_id = f"session_{connection.userId}"
            db.commit()

            # Start connection restoration in the background
            background_tasks.add_task(
                reconnection_service.handle_connection_restored, connection.userId
            )

        return {"status": "success", "message": "Connection status updated"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating connection status: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


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
        raise HTTPException(status_code=500, detail=str(e)) from e


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

        user = repository_factory.get_user_repository().get_by_id(
            db, int(connection.userId)
        )
        if user:
            user.whatsapp_connected = False
            user.whatsapp_last_seen = datetime.now(UTC)
            db.commit()

            if user.telegram_channel_id:
                telegram_service = get_telegram_service()
                notification = f"❌ WhatsApp отключен для пользователя {user.username}"
                await telegram_service.send_notification(
                    user.telegram_channel_id, notification
                )

        return {"status": "success", "message": "Disconnection status updated"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating disconnection status: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


async def analyze_and_save_message(
    message: WhatsAppMessageWebhook, chat_db_id: int, user_id: str
):
    """Background task: score the already-persisted message and update it."""
    from app.database.connection import get_db_session

    try:
        sanitized_content = SecurityValidators.sanitize_input(
            message.content, max_length=MAX_CONTENT_LENGTH
        )
        if not sanitized_content:
            logger.info(
                f"Message {message.messageId} has no analysable text - "
                "keeping provisional importance"
            )
            return

        openai_service = get_openai_service()
        chat_name = message.chatName or ""
        ai_importance = await openai_service.analyze_message_importance(
            sanitized_content,
            f"Чат: {SecurityValidators.sanitize_input(chat_name, max_length=100)}, Тип: {message.chatType}",
        )

        final_importance = max(message.importance, ai_importance)

        with get_db_session() as db:
            stored_message = (
                repository_factory.get_whatsapp_message_repository().get_by_message_id(
                    db, message.messageId
                )
            )

            if stored_message is None:
                # Should not happen: the webhook persists before queueing this
                # task. Recover rather than lose the message.
                logger.warning(
                    f"Message {message.messageId} missing at analysis time - inserting"
                )
                stored_message = WhatsAppMessage(
                    chat_id=chat_db_id,
                    message_id=message.messageId,
                    sender=SecurityValidators.sanitize_input(
                        message.sender or "", max_length=100
                    ),
                    content=sanitized_content,
                    timestamp=_parse_timestamp(message.timestamp),
                    has_media=message.hasMedia,
                    is_processed=False,
                )
                db.add(stored_message)

            stored_message.importance_score = final_importance
            stored_message.ai_analyzed = True

            # Scored below the user's digest threshold: it will never be picked
            # up by a digest, so close it out instead of leaving it unprocessed
            # forever, where cleanup also refuses to touch it.
            importance_floor = _digest_importance_floor(int(user_id), db)
            if final_importance < importance_floor:
                logger.info(
                    f"Message {message.messageId} scored {final_importance} < "
                    f"{importance_floor} - marking processed (not digest-eligible)"
                )
                stored_message.is_processed = True

        logger.info(
            f"Analyzed message {message.messageId} with importance {final_importance}"
        )

        if final_importance >= 5:
            await send_urgent_notification(message, user_id)

    except Exception as e:
        logger.error(f"Error analyzing and saving message: {e}")


async def send_urgent_notification(message: WhatsAppMessageWebhook, user_id: str):
    """Send an urgent notification with safe handling"""
    from app.database.connection import get_db_session

    try:
        if not message.content:
            logger.warning("Message content is empty for urgent notification")
            return

        with get_db_session() as db:
            user = repository_factory.get_user_repository().get_by_id(db, int(user_id))
            if not (user and user.is_active and user.telegram_channel_id):
                return

            if not _urgent_notifications_enabled(int(user_id), db):
                logger.info(
                    f"Urgent notifications disabled for user {user_id} - "
                    f"skipping alert for message {message.messageId}"
                )
                return

            monitored_chat = repository_factory.get_monitored_chat_repository().get_by_user_and_chat_id(
                db, int(user_id), message.chatId
            )

            if monitored_chat and monitored_chat.custom_name:
                sanitized_chat_name = SecurityValidators.sanitize_input(
                    monitored_chat.custom_name, max_length=100
                )
            else:
                sanitized_chat_name = SecurityValidators.sanitize_input(
                    message.chatName or "", max_length=100
                )

            telegram_channel_id = user.telegram_channel_id

        sanitized_content = SecurityValidators.sanitize_input(
            message.content, max_length=2000
        )
        sanitized_sender = SecurityValidators.sanitize_input(
            message.sender or "", max_length=100
        )

        openai_service = get_openai_service()
        translated_message = await openai_service.translate_to_russian(
            sanitized_content
        )

        urgent_text = "🚨 *СРОЧНОЕ СООБЩЕНИЕ*\n\n"
        urgent_text += f"📱 Чат: *{sanitized_chat_name}*\n"
        urgent_text += f"👤 От: *{sanitized_sender}*\n"
        urgent_text += f"💬 Сообщение: {translated_message}\n"
        urgent_text += f"🕐 Время: {datetime.now().strftime('%H:%M %d.%m.%Y')}"

        telegram_service = get_telegram_service()
        await telegram_service.send_notification(telegram_channel_id, urgent_text)

        logger.info(f"Sent urgent notification for message {message.messageId}")

    except Exception as e:
        logger.error(f"Error sending urgent notification: {e}")
