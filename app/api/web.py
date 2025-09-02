import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth.admin_auth import (
    create_admin_session,
    get_admin_login_page,
    get_admin_login_page_with_error,
    logout_admin,
    require_admin_auth,
    verify_admin_password,
)
from app.auth.security import get_password_hash
from app.core.repository_factory import repository_factory
from app.database.connection import get_db
from app.models.database import MonitoredChat, User, UserSettings
from app.whatsapp.service import WhatsAppService
from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["web-admin"])
templates = Jinja2Templates(directory="web/templates")

# Create WhatsApp service for working with QR codes
whatsapp_service = WhatsAppService(
    settings.WHATSAPP_SESSION_PATH, settings.WHATSAPP_BRIDGE_URL
)


# Admin authentication routes
@router.get("/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    """Admin login page"""
    return get_admin_login_page(request)


@router.post("/login")
async def admin_login(request: Request, password: str = Form(...)):
    """Admin login handler"""
    if verify_admin_password(password):
        session_id = create_admin_session(request)
        response = RedirectResponse(url="/admin/users", status_code=303)
        response.set_cookie(
            "admin_session", session_id, httponly=True, secure=not settings.DEBUG
        )
        return response
    else:
        return get_admin_login_page_with_error(request, "Invalid admin password")


@router.get("/logout")
async def admin_logout(request: Request):
    """Admin logout handler"""
    return logout_admin(request)


# Dashboard route removed - using main.py root route (/) instead
# This eliminates duplicate functionality and simplifies the routing structure


@router.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, db: Session = Depends(get_db)):
    """User management page"""
    require_admin_auth(request)
    users = repository_factory.get_user_repository().get_all(db)
    return templates.TemplateResponse(
        "users.html", {"request": request, "users": users}
    )


@router.post("/users/create")
async def create_user(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    """Create a new user"""
    require_admin_auth(request)

    # Check whether the user already exists
    existing_user = repository_factory.get_user_repository().get_by_username(
        db, username
    )
    if not existing_user:
        existing_user = repository_factory.get_user_repository().get_by_email(db, email)

    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")

    # Create a new user
    hashed_password = get_password_hash(password)
    new_user = User(username=username, email=email, hashed_password=hashed_password)

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Create default user settings automatically
    from app.core.user_utils import create_default_user_settings

    create_default_user_settings(int(new_user.id), db)

    return RedirectResponse(url="/admin/users", status_code=303)


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail(user_id: int, request: Request, db: Session = Depends(get_db)):
    """User detail page"""
    require_admin_auth(request)

    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    # Get monitored chats
    monitored_chats = (
        repository_factory.get_monitored_chat_repository().get_active_chats_for_user(
            db, user_id
        )
    )

    # Get last digest information
    last_digest = (
        repository_factory.get_digest_log_repository().get_last_digest_for_user(
            db, user_id
        )
    )

    # Get digest statistics
    digests = repository_factory.get_digest_log_repository().get_digests_for_period(
        db, user_id, 365
    )  # Last year
    total_digests = len(digests)
    successful_digests = len([d for d in digests if d.telegram_sent])

    return templates.TemplateResponse(
        "user_detail.html",
        {
            "request": request,
            "user": user,
            "monitored_chats": monitored_chats,
            "last_digest": last_digest,
            "total_digests": total_digests,
            "successful_digests": successful_digests,
        },
    )


@router.get("/users/{user_id}/qr")
async def get_user_qr_code(user_id: int, db: Session = Depends(get_db)):
    """Get a QR code for the user"""
    repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    try:
        bridge_url = settings.WHATSAPP_BRIDGE_URL

        # Get QR code directly without initialization
        async with httpx.AsyncClient(timeout=30.0) as client:
            print(f"[DEBUG] Getting QR code for user {user_id}")

            # Retrieve the QR code
            print(f"[DEBUG] Getting QR code for user {user_id}")
            qr_response = await client.get(f"{bridge_url}/qr/{user_id}")
            print(f"[DEBUG] QR response status: {qr_response.status_code}")

            if qr_response.status_code == 200:
                qr_data = qr_response.json()
                print("[DEBUG] QR code successfully retrieved")
                return {
                    "status": "success",
                    "qr_code": qr_data.get("qrCode"),
                    "timestamp": qr_data.get("timestamp"),
                    "message": "QR-код готов для сканирования",
                }
            elif qr_response.status_code == 404:
                print("[DEBUG] QR code not ready yet")
                return {
                    "status": "pending",
                    "message": "QR-код пока не готов, попробуйте через несколько секунд",
                }
            else:
                error_text = qr_response.text
                print(f"[DEBUG] QR request failed: {error_text}")
                return JSONResponse(
                    status_code=500,
                    content={
                        "status": "error",
                        "message": f"Failed to get QR code: {error_text}",
                    },
                )

    except httpx.ConnectError as e:
        print(f"[DEBUG] Connection error: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "message": f"Не удается подключиться к WhatsApp bridge: {str(e)}",
            },
        )
    except httpx.TimeoutException as e:
        print(f"[DEBUG] Timeout error: {e}")
        return JSONResponse(
            status_code=504,
            content={
                "status": "error",
                "message": f"Таймаут подключения к WhatsApp bridge: {str(e)}",
            },
        )
    except httpx.RequestError as e:
        print(f"[DEBUG] Request error: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "message": f"Ошибка запроса к WhatsApp bridge: {str(e)}",
            },
        )
    except Exception as e:
        print(f"[DEBUG] General error: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Ошибка генерации QR-кода: {str(e)}",
            },
        )


@router.get("/users/{user_id}/qr/check")
async def check_qr_code(user_id: int):
    """Check QR code availability"""
    try:
        async with httpx.AsyncClient() as client:
            qr_response = await client.get(
                f"{settings.WHATSAPP_BRIDGE_URL}/qr/{user_id}"
            )

            if qr_response.status_code == 200:
                qr_data = qr_response.json()
                return JSONResponse(
                    {
                        "status": "ready",
                        "qr_code": qr_data["qrCode"],
                        "timestamp": qr_data["timestamp"],
                    }
                )
            else:
                return JSONResponse(
                    {"status": "not_ready", "message": "QR code not available yet"}
                )
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})


@router.post("/users/{user_id}/qr/send")
async def send_qr_code(
    user_id: int, email: str = Form(...), db: Session = Depends(get_db)
):
    """Send the QR code to the user by email"""
    repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    try:
        # Retrieve the QR code
        async with httpx.AsyncClient() as client:
            qr_response = await client.get(
                f"{settings.WHATSAPP_BRIDGE_URL}/qr/{user_id}"
            )

            if qr_response.status_code == 200:
                qr_data = qr_response.json()

                # Email sending with the QR code can be added here
                # For demonstration, just return success

                return JSONResponse(
                    {
                        "status": "success",
                        "message": f"QR code sent to {email}",
                        "qr_code": qr_data["qrCode"],
                    }
                )
            else:
                return JSONResponse(
                    {"status": "error", "message": "QR code not available"}
                )

    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})


@router.get("/users/{user_id}/chats")
async def get_available_chats(user_id: int, db: Session = Depends(get_db)):
    """Get the user's available chats"""
    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    if not user.whatsapp_connected:
        return JSONResponse({"status": "error", "message": "WhatsApp not connected"})

    try:
        chats = await whatsapp_service.get_chats(user_id)
        return JSONResponse({"status": "success", "chats": chats})
    except Exception as e:
        return JSONResponse(
            {"status": "error", "message": f"Error getting chats: {str(e)}"}
        )


@router.post("/users/{user_id}/chats/add")
async def add_monitored_chat(
    user_id: int,
    chat_id: str = Form(...),
    chat_name: str = Form(...),
    chat_type: str = Form(...),
    db: Session = Depends(get_db),
):
    """Add a chat for monitoring"""
    repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    # Check whether this chat is already being monitored
    existing_chat = (
        repository_factory.get_monitored_chat_repository().get_by_user_and_chat_id(
            db, user_id, chat_id
        )
    )

    if existing_chat:
        if not existing_chat.is_active:
            existing_chat.is_active = True
            db.commit()
    else:
        new_chat = MonitoredChat(
            user_id=user_id, chat_id=chat_id, chat_name=chat_name, chat_type=chat_type
        )
        db.add(new_chat)
        db.commit()

    return RedirectResponse(url=f"/admin/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/chats/{chat_id}/remove")
async def remove_monitored_chat(
    user_id: int, chat_id: int, db: Session = Depends(get_db)
):
    """Remove a chat from monitoring"""
    chat = repository_factory.get_monitored_chat_repository().get_by_id(db, chat_id)
    if not chat or chat.user_id != user_id:
        raise HTTPException(status_code=404, detail="Chat not found")

    if chat:
        chat.is_active = False
        db.commit()

    return RedirectResponse(url=f"/admin/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/chats/{chat_id}/rename")
async def rename_monitored_chat(
    user_id: int,
    chat_id: int,
    custom_name: str = Form(...),
    db: Session = Depends(get_db),
):
    """Rename a monitored chat with a custom alternative name"""
    chat = repository_factory.get_monitored_chat_repository().get_by_id(db, chat_id)
    if not chat or chat.user_id != user_id:
        raise HTTPException(status_code=404, detail="Chat not found")

    if chat:
        chat.custom_name = custom_name.strip() if custom_name.strip() else None
        db.commit()

    return RedirectResponse(url=f"/admin/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/settings")
async def update_user_settings(
    user_id: int,
    telegram_channel_id: str = Form(...),
    digest_interval_hours: int = Form(...),
    db: Session = Depends(get_db),
):
    """Update user settings"""
    logger.info(
        f"Updating user settings for user {user_id}: telegram_channel_id={telegram_channel_id}, digest_interval_hours={digest_interval_hours}"
    )

    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    user.telegram_channel_id = telegram_channel_id
    user.digest_interval_hours = digest_interval_hours
    db.commit()

    logger.info(f"Successfully updated user settings for user {user_id}")

    return RedirectResponse(url=f"/admin/users/{user_id}", status_code=303)


@router.get("/system/status")
async def system_status():
    """API for getting system status"""
    try:
        # Check the status of the Node.js bridge

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{settings.WHATSAPP_BRIDGE_URL}/health", timeout=5.0
                )
                bridge_status = (
                    response.json()
                    if response.status_code == 200
                    else {"status": "error"}
                )
            except Exception:
                bridge_status = {"status": "offline"}

        return JSONResponse({"fastapi": "online", "bridge": bridge_status})
    except Exception as e:
        return JSONResponse(
            {"fastapi": "online", "bridge": {"status": "error", "message": str(e)}}
        )


@router.get("/users/{user_id}/whatsapp/status")
async def get_user_whatsapp_status(user_id: int, db: Session = Depends(get_db)):
    """Get WhatsApp connection status for a specific user"""
    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    try:
        # Check the status in the database
        db_status = user.whatsapp_connected

        # Additionally check via the bridge for a more accurate status
        bridge_url = settings.WHATSAPP_BRIDGE_URL
        bridge_connected = False

        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                bridge_response = await client.get(f"{bridge_url}/status/{user_id}")
                if bridge_response.status_code == 200:
                    bridge_data = bridge_response.json()
                    bridge_connected = bridge_data.get("connected", False)
            except Exception as e:
                logger.warning(
                    f"Bridge status check failed: {e}"
                )  # Log the error instead of silently passing

        return JSONResponse(
            {
                "user_id": user_id,
                "whatsapp_connected": db_status,
                "bridge_connected": bridge_connected,
                "status": (
                    "connected" if (db_status or bridge_connected) else "disconnected"
                ),
            }
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Ошибка проверки статуса: {str(e)}",
            },
        )


@router.post("/users/{user_id}/whatsapp/update-status")
async def update_user_whatsapp_status(
    user_id: int, request: Request, db: Session = Depends(get_db)
):
    """Update the user's WhatsApp connection status"""
    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    try:
        body = await request.json()
        connected = body.get("connected", False)

        user.whatsapp_connected = connected
        if connected:
            user.whatsapp_session_id = f"user_{user_id}"
        else:
            user.whatsapp_session_id = None

        db.commit()

        return JSONResponse(
            {
                "status": "success",
                "message": f"User status updated to {'connected' if connected else 'disconnected'}",
            }
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Failed to update status: {str(e)}",
            },
        )


@router.post("/users/{user_id}/digest/generate")
async def generate_immediate_digest(user_id: int, db: Session = Depends(get_db)):
    """Immediate generation and sending of a digest for the user"""
    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    if not user.is_active:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Пользователь приостановлен"},
        )

    if not user.whatsapp_connected:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "WhatsApp не подключен"},
        )

    if not user.telegram_channel_id:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Telegram канал не настроен"},
        )

    try:
        # Import the digest creation service
        from app.scheduler.digest_scheduler import DigestScheduler

        # Create a scheduler instance
        scheduler = DigestScheduler()

        # Perform creation and sending of the digest
        await scheduler.create_and_send_digest(user, db)

        return JSONResponse(
            {"status": "success", "message": "Дайджест успешно создан и отправлен"}
        )

    except Exception as e:
        print(f"[ERROR] Failed to generate digest for user {user_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Ошибка генерации дайджеста: {str(e)}",
            },
        )


@router.post("/users/{user_id}/telegram/test")
async def test_telegram_connection(user_id: int, db: Session = Depends(get_db)):
    """Test connection to the user's Telegram channel"""
    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    if not user.is_active:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Пользователь приостановлен"},
        )

    if not user.telegram_channel_id:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Telegram канал не настроен"},
        )

    try:
        from app.telegram.service import TelegramService

        telegram_service = TelegramService()

        # Check access to the channel
        verification = await telegram_service.verify_channel_access(
            user.telegram_channel_id
        )

        if verification["success"]:
            # Send a test message
            test_success = await telegram_service.test_connection(
                user.telegram_channel_id
            )

            return JSONResponse(
                {
                    "status": "success" if test_success else "warning",
                    "message": (
                        "Тестовое сообщение отправлено"
                        if test_success
                        else "Доступ есть, но отправка не удалась"
                    ),
                    "channel_info": verification["chat_info"],
                    "permissions": verification["bot_permissions"],
                }
            )
        else:
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "message": f"Нет доступа к каналу: {verification['error']}",
                    "suggestions": verification.get("suggestions", []),
                },
            )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Ошибка тестирования: {str(e)}"},
        )


@router.get("/users/{user_id}/messages")
async def get_user_messages(user_id: int, db: Session = Depends(get_db)):
    """Get messages for a specific user"""
    repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    # Get all monitored chats for the user
    monitored_chats = (
        repository_factory.get_monitored_chat_repository().get_active_chats_for_user(
            db, user_id
        )
    )

    if not monitored_chats:
        return JSONResponse(
            content={
                "status": "success",
                "user_id": user_id,
                "messages": [],
                "total": 0,
                "monitored_chats": 0,
            }
        )

    # Get messages from all monitored chats
    chat_ids = [chat.id for chat in monitored_chats]
    messages = (
        repository_factory.get_whatsapp_message_repository().get_messages_by_chat_ids(
            db, chat_ids
        )
    )

    # Convert to dict format
    messages_data = []
    for msg in messages:
        messages_data.append(
            {
                "id": msg.id,
                "message_id": msg.message_id,
                "sender": msg.sender,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
                "importance_score": msg.importance_score,
                "has_media": msg.has_media,
                "is_processed": msg.is_processed,
                "ai_analyzed": msg.ai_analyzed,
                "processing_attempts": msg.processing_attempts,
                "chat_id": msg.chat_id,
            }
        )

    return JSONResponse(
        content={
            "status": "success",
            "user_id": user_id,
            "messages": messages_data,
            "total": len(messages_data),
            "monitored_chats": len(monitored_chats),
        }
    )


@router.get("/users/{user_id}/digests")
async def get_user_digests(user_id: int, db: Session = Depends(get_db)):
    """Get digest logs for a specific user"""
    repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    # Get digest logs for the user
    digest_logs = repository_factory.get_digest_log_repository().get_digests_for_period(
        db, user_id, 365
    )  # Last year

    # Convert to dict format
    digests_data = []
    for digest in digest_logs:
        digests_data.append(
            {
                "id": digest.id,
                "digest_content": digest.digest_content,
                "message_count": digest.message_count,
                "telegram_sent": digest.telegram_sent,
                "created_at": digest.created_at.isoformat(),
            }
        )

    return JSONResponse(
        content={
            "status": "success",
            "user_id": user_id,
            "digests": digests_data,
            "total": len(digests_data),
        }
    )


@router.post("/users/{user_id}/messages/reset-processed")
async def reset_processed_messages(user_id: int, db: Session = Depends(get_db)):
    """Reset is_processed flag for user's messages"""
    repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    # Get all monitored chats for the user
    monitored_chats = (
        repository_factory.get_monitored_chat_repository().get_active_chats_for_user(
            db, user_id
        )
    )

    if not monitored_chats:
        return JSONResponse(
            content={
                "status": "warning",
                "message": "No monitored chats found for user",
                "reset_count": 0,
            }
        )

    # Get messages from all monitored chats and reset is_processed flag
    chat_ids = [chat.id for chat in monitored_chats]
    messages = (
        repository_factory.get_whatsapp_message_repository().get_messages_by_chat_ids(
            db, chat_ids
        )
    )
    # Filter for processed messages only
    processed_messages = [msg for msg in messages if msg.is_processed]

    reset_count = 0
    for msg in processed_messages:
        msg.is_processed = False
        reset_count += 1

    db.commit()

    return JSONResponse(
        content={
            "status": "success",
            "message": f"Reset is_processed flag for {reset_count} messages",
            "reset_count": reset_count,
        }
    )


@router.get("/storage/stats")
async def get_storage_stats(db: Session = Depends(get_db)):
    """Get storage statistics"""
    try:
        from app.core.data_cleanup import cleanup_service

        stats = await cleanup_service.get_storage_stats(db)

        return JSONResponse(content={"status": "success", "storage_stats": stats})
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Error getting storage stats: {str(e)}",
            },
        )


@router.post("/storage/cleanup")
async def run_storage_cleanup(db: Session = Depends(get_db)):
    """Run manual storage cleanup"""
    try:
        from app.core.data_cleanup import cleanup_service

        cleanup_results = await cleanup_service.run_full_cleanup()

        return JSONResponse(
            content={
                "status": "success",
                "message": "Storage cleanup completed",
                "cleanup_results": cleanup_results,
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Error during cleanup: {str(e)}"},
        )


@router.get("/users/{user_id}/cleanup-settings")
async def get_user_cleanup_settings(user_id: int, db: Session = Depends(get_db)):
    """Get user cleanup settings"""
    try:
        repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

        from app.core.user_utils import get_user_settings

        settings = get_user_settings(user_id, db)

        return JSONResponse(
            content={
                "status": "success",
                "settings": {
                    "max_message_age_hours": settings.max_message_age_hours,
                    "min_importance_level": settings.min_importance_level,
                    "include_media_messages": settings.include_media_messages,
                    "urgent_notifications": settings.urgent_notifications,
                    "daily_summary": settings.daily_summary,
                    "auto_add_new_chats": settings.auto_add_new_chats,
                    "auto_add_group_chats_only": settings.auto_add_group_chats_only,
                },
            }
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Error getting cleanup settings: {str(e)}",
            },
        )


@router.post("/users/{user_id}/cleanup-settings")
async def update_user_cleanup_settings(
    user_id: int,
    max_message_age_hours: int = Form(24),
    min_importance_level: int = Form(3),
    include_media_messages: bool = Form(True),
    urgent_notifications: bool = Form(True),
    daily_summary: bool = Form(True),
    auto_add_new_chats: bool = Form(False),
    auto_add_group_chats_only: bool = Form(True),
    db: Session = Depends(get_db),
):
    """Update user cleanup settings"""
    try:
        repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

        from app.core.user_utils import get_user_settings

        settings = get_user_settings(user_id, db)

        # Update settings
        settings.max_message_age_hours = int(max_message_age_hours)
        settings.min_importance_level = int(min_importance_level)
        settings.include_media_messages = bool(include_media_messages)
        settings.urgent_notifications = bool(urgent_notifications)
        settings.daily_summary = bool(daily_summary)
        settings.auto_add_new_chats = bool(auto_add_new_chats)
        settings.auto_add_group_chats_only = bool(auto_add_group_chats_only)

        db.commit()

        return JSONResponse(
            content={
                "status": "success",
                "message": "Cleanup settings updated successfully",
                "settings": {
                    "max_message_age_hours": settings.max_message_age_hours,
                    "min_importance_level": settings.min_importance_level,
                    "include_media_messages": settings.include_media_messages,
                    "urgent_notifications": settings.urgent_notifications,
                    "daily_summary": settings.daily_summary,
                    "auto_add_new_chats": settings.auto_add_new_chats,
                    "auto_add_group_chats_only": settings.auto_add_group_chats_only,
                },
            }
        )

    except Exception as e:
        db.rollback()
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Error updating cleanup settings: {str(e)}",
            },
        )


@router.post("/users/{user_id}/settings/create")
async def create_user_settings(user_id: int, db: Session = Depends(get_db)):
    """Create default settings for user if they don't exist"""
    try:
        # Check if user exists
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": "User not found"},
            )

        # Check if settings already exist
        existing_settings = (
            repository_factory.get_user_settings_repository().get_by_user_id(
                db, user_id
            )
        )

        if existing_settings:
            return JSONResponse(
                content={
                    "status": "info",
                    "message": "User settings already exist",
                    "settings": {
                        "max_message_age_hours": existing_settings.max_message_age_hours,
                        "min_importance_level": existing_settings.min_importance_level,
                    },
                }
            )

        # Create default settings
        default_settings = UserSettings(
            user_id=user_id,
            max_message_age_hours=24,  # 24 hours default
            min_importance_level=3,
            include_media_messages=True,
            urgent_notifications=True,
            daily_summary=True,
            auto_add_new_chats=False,
            auto_add_group_chats_only=True,
        )

        db.add(default_settings)
        db.commit()

        return JSONResponse(
            content={
                "status": "success",
                "message": "Default user settings created",
                "settings": {
                    "max_message_age_hours": default_settings.max_message_age_hours,
                    "min_importance_level": default_settings.min_importance_level,
                },
            }
        )

    except Exception as e:
        db.rollback()
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Error creating user settings: {str(e)}",
            },
        )


@router.get("/users/{user_id}/telegram/setup-guide")
async def get_telegram_setup_guide(user_id: int, db: Session = Depends(get_db)):
    """Get instructions for setting up a Telegram channel"""
    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    try:
        from app.telegram.service import TelegramService

        telegram_service = TelegramService()

        guide = await telegram_service.create_channel_for_user(user.username)

        return JSONResponse(
            {
                "status": "success",
                "user": user.username,
                "setup_guide": guide["instructions"],
                "bot_username": guide["bot_username"],
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Ошибка получения инструкций: {str(e)}",
            },
        )


@router.get("/users/{user_id}/telegram/stats")
async def get_telegram_channel_stats(user_id: int, db: Session = Depends(get_db)):
    """Get statistics of the user's Telegram channel"""
    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    if not user.telegram_channel_id:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Telegram канал не настроен"},
        )

    try:
        from app.telegram.service import TelegramService

        telegram_service = TelegramService()

        stats = await telegram_service.get_channel_statistics(user.telegram_channel_id)

        return JSONResponse(
            {
                "status": "success" if stats["success"] else "error",
                "statistics": stats.get("statistics"),
                "error": stats.get("error"),
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Ошибка получения статистики: {str(e)}",
            },
        )


@router.post("/users/{user_id}/suspend")
async def suspend_user_web(user_id: int, db: Session = Depends(get_db)):
    """Suspend a user via web interface"""
    from datetime import datetime

    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    # Check if user is already suspended
    if not user.is_active:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "User is already suspended"},
        )

    # Suspend the user
    user.is_active = False
    user.whatsapp_connected = False  # Disconnect WhatsApp when suspending
    user.updated_at = datetime.utcnow()
    db.commit()

    # Immediately disconnect WhatsApp bridge for suspended user
    try:
        bridge_url = settings.WHATSAPP_BRIDGE_URL
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Send disconnect command to WhatsApp bridge
            disconnect_response = await client.post(
                f"{bridge_url}/disconnect/{user_id}", json={"reason": "user_suspended"}
            )

            if disconnect_response.status_code == 200:
                logger.info(
                    f"WhatsApp bridge disconnected for suspended user {user_id}"
                )
            else:
                logger.warning(
                    f"Failed to disconnect WhatsApp bridge for user {user_id}: {disconnect_response.status_code}"
                )

    except Exception as e:
        logger.error(
            f"Error disconnecting WhatsApp bridge for suspended user {user_id}: {e}"
        )
        # Don't fail the suspend operation if bridge is unavailable

    # Record resource savings from suspension
    try:
        from app.core.resource_savings import resource_savings_service

        savings_result = resource_savings_service.record_suspension_savings(
            db, user_id, user.updated_at
        )
        if "error" not in savings_result:
            logger.info(
                f"Resource savings recorded for suspended user {user_id}: {savings_result}"
            )
        else:
            logger.warning(
                f"Failed to record resource savings for user {user_id}: {savings_result}"
            )
    except Exception as e:
        logger.error(
            f"Error recording resource savings for suspended user {user_id}: {e}"
        )
        # Don't fail the suspend operation if savings recording fails

    return JSONResponse(
        content={
            "status": "success",
            "message": f"User {user.username} has been suspended successfully",
        }
    )


@router.post("/users/{user_id}/resume")
async def resume_user_web(user_id: int, db: Session = Depends(get_db)):
    """Resume a suspended user via web interface"""
    from datetime import datetime

    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    # Check if user is already active
    if user.is_active:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "User is already active"},
        )

    # Resume the user
    user.is_active = True
    user.whatsapp_connected = False  # Reset WhatsApp status - user needs to reconnect
    user.updated_at = datetime.utcnow()
    db.commit()

    # Always try to reconnect WhatsApp bridge for resumed user
    # The bridge will handle the reconnection logic
    try:
        bridge_url = settings.WHATSAPP_BRIDGE_URL
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Send reconnect command to WhatsApp bridge
            reconnect_response = await client.post(
                f"{bridge_url}/reconnect/{user_id}", json={"reason": "user_resumed"}
            )

            if reconnect_response.status_code == 200:
                logger.info(
                    f"WhatsApp bridge reconnection initiated for resumed user {user_id}"
                )
            else:
                logger.warning(
                    f"Failed to reconnect WhatsApp bridge for user {user_id}: {reconnect_response.status_code}"
                )

    except Exception as e:
        logger.error(
            f"Error reconnecting WhatsApp bridge for resumed user {user_id}: {e}"
        )
        # Don't fail the resume operation if bridge is unavailable

    return JSONResponse(
        content={
            "status": "success",
            "message": f"User {user.username} has been resumed successfully",
        }
    )


@router.get("/resource-savings")
async def get_resource_savings(
    days_back: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    db: Session = Depends(get_db),
):
    """Get resource savings metrics from suspended users"""
    try:
        from app.core.resource_savings import resource_savings_service

        total_savings = resource_savings_service.get_total_savings(db, days_back)
        current_system = resource_savings_service.get_current_system_savings()

        return JSONResponse(
            {
                "status": "success",
                "total_savings": total_savings,
                "current_system": current_system,
                "period_days": days_back,
            }
        )

    except Exception as e:
        logger.error(f"Error getting resource savings: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Failed to get resource savings: {str(e)}",
            },
        )


@router.get("/users/{user_id}/resource-savings")
async def get_user_resource_savings(
    user_id: int,
    days_back: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    db: Session = Depends(get_db),
):
    """Get resource savings history for a specific user"""
    try:
        from app.core.resource_savings import resource_savings_service

        user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

        savings_history = resource_savings_service.get_savings_by_user(
            db, user_id, days_back
        )

        return JSONResponse(
            {
                "status": "success",
                "user_id": user_id,
                "username": user.username,
                "savings_history": savings_history,
                "period_days": days_back,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user resource savings: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Failed to get user resource savings: {str(e)}",
            },
        )


@router.get("/resource-savings-page", response_class=HTMLResponse)
async def resource_savings_page(request: Request):
    """Resource savings metrics page"""
    return templates.TemplateResponse("resource_savings.html", {"request": request})
