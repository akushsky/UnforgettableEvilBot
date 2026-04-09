import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.repository_factory import repository_factory
from app.database.connection import get_db
from app.dependencies import get_whatsapp_service
from app.models.database import MonitoredChat
from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["web-admin"])
templates = Jinja2Templates(directory="web/templates")


# --- Chat management routes ---


@router.get("/users/{user_id}/chats")
async def get_available_chats(user_id: int, db: Session = Depends(get_db)):
    """Get the user's available chats"""
    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    if not user.whatsapp_connected:
        return JSONResponse({"status": "error", "message": "WhatsApp not connected"})

    try:
        whatsapp_service = get_whatsapp_service()
        chats = await whatsapp_service.get_chats(user_id)
        return JSONResponse({"status": "success", "chats": chats})
    except Exception as e:
        logger.error(f"Error getting chats for user {user_id}: {e}")
        return JSONResponse(
            {"status": "error", "message": f"Error getting chats: {e!s}"}
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

    chat.custom_name = custom_name.strip() if custom_name.strip() else None
    db.commit()
    return RedirectResponse(url=f"/admin/users/{user_id}", status_code=303)


# --- QR code and WhatsApp connection routes ---


@router.get("/users/{user_id}/qr")
async def get_user_qr_code(user_id: int, db: Session = Depends(get_db)):
    """Get a QR code for the user"""
    repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    try:
        bridge_url = settings.WHATSAPP_BRIDGE_URL

        async with httpx.AsyncClient(timeout=30.0) as client:
            logger.debug(f"Getting QR code for user {user_id}")

            qr_response = await client.get(f"{bridge_url}/qr/{user_id}")
            logger.debug(f"QR response status: {qr_response.status_code}")

            if qr_response.status_code == 200:
                qr_data = qr_response.json()
                logger.debug("QR code successfully retrieved")
                return {
                    "status": "success",
                    "qr_code": qr_data.get("qrCode"),
                    "timestamp": qr_data.get("timestamp"),
                    "message": "QR-код готов для сканирования",
                }
            elif qr_response.status_code == 404:
                logger.debug("QR code not ready yet")
                return {
                    "status": "pending",
                    "message": "QR-код пока не готов, попробуйте через несколько секунд",
                }
            else:
                error_text = qr_response.text
                logger.debug(f"QR request failed: {error_text}")
                return JSONResponse(
                    status_code=500,
                    content={
                        "status": "error",
                        "message": f"Failed to get QR code: {error_text}",
                    },
                )

    except httpx.ConnectError as e:
        logger.debug(f"Connection error: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "message": f"Не удается подключиться к WhatsApp bridge: {e!s}",
            },
        )
    except httpx.TimeoutException as e:
        logger.debug(f"Timeout error: {e}")
        return JSONResponse(
            status_code=504,
            content={
                "status": "error",
                "message": f"Таймаут подключения к WhatsApp bridge: {e!s}",
            },
        )
    except Exception as e:
        logger.error(f"General QR code error: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Ошибка генерации QR-кода: {e!s}",
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


@router.get("/users/{user_id}/whatsapp/status")
async def get_user_whatsapp_status(user_id: int, db: Session = Depends(get_db)):
    """Get WhatsApp connection status for a specific user"""
    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    try:
        db_status = user.whatsapp_connected
        bridge_connected = False

        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                bridge_response = await client.get(
                    f"{settings.WHATSAPP_BRIDGE_URL}/status/{user_id}"
                )
                if bridge_response.status_code == 200:
                    bridge_data = bridge_response.json()
                    bridge_connected = bridge_data.get("connected", False)
            except Exception as e:
                logger.warning(f"Bridge status check failed: {e}")

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
                "message": f"Ошибка проверки статуса: {e!s}",
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
        user.whatsapp_session_id = f"user_{user_id}" if connected else None
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
                "message": f"Failed to update status: {e!s}",
            },
        )


# --- Digest routes ---


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
        from app.scheduler.digest_scheduler import DigestScheduler

        scheduler = DigestScheduler()
        await scheduler.create_and_send_digest(user, db)

        return JSONResponse(
            {"status": "success", "message": "Дайджест успешно создан и отправлен"}
        )
    except Exception as e:
        logger.error(f"Failed to generate digest for user {user_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Ошибка генерации дайджеста: {e!s}",
            },
        )


@router.get("/users/{user_id}/messages")
async def get_user_messages(user_id: int, db: Session = Depends(get_db)):
    """Get messages for a specific user"""
    repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

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

    chat_ids = [chat.id for chat in monitored_chats]
    messages = (
        repository_factory.get_whatsapp_message_repository().get_messages_by_chat_ids(
            db, chat_ids
        )
    )

    messages_data = [
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
        for msg in messages
    ]

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

    digest_logs = repository_factory.get_digest_log_repository().get_digests_for_period(
        db, user_id, 365
    )

    digests_data = [
        {
            "id": digest.id,
            "digest_content": digest.digest_content,
            "message_count": digest.message_count,
            "telegram_sent": digest.telegram_sent,
            "created_at": digest.created_at.isoformat(),
        }
        for digest in digest_logs
    ]

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

    chat_ids = [chat.id for chat in monitored_chats]
    messages = (
        repository_factory.get_whatsapp_message_repository().get_messages_by_chat_ids(
            db, chat_ids
        )
    )
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


# --- Storage and cleanup routes ---


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
                "message": f"Error getting storage stats: {e!s}",
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
            content={"status": "error", "message": f"Error during cleanup: {e!s}"},
        )


@router.get("/users/{user_id}/cleanup-settings")
async def get_user_cleanup_settings(user_id: int, db: Session = Depends(get_db)):
    """Get user cleanup settings"""
    try:
        repository_factory.get_user_repository().get_by_id_or_404(db, user_id)
        from app.core.user_utils import get_user_settings

        user_settings = get_user_settings(user_id, db)
        return JSONResponse(
            content={
                "status": "success",
                "settings": {
                    "max_message_age_hours": user_settings.max_message_age_hours,
                    "min_importance_level": user_settings.min_importance_level,
                    "include_media_messages": user_settings.include_media_messages,
                    "urgent_notifications": user_settings.urgent_notifications,
                    "daily_summary": user_settings.daily_summary,
                    "auto_add_new_chats": user_settings.auto_add_new_chats,
                    "auto_add_group_chats_only": user_settings.auto_add_group_chats_only,
                },
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Error getting cleanup settings: {e!s}",
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

        user_settings = get_user_settings(user_id, db)
        user_settings.max_message_age_hours = int(max_message_age_hours)
        user_settings.min_importance_level = int(min_importance_level)
        user_settings.include_media_messages = bool(include_media_messages)
        user_settings.urgent_notifications = bool(urgent_notifications)
        user_settings.daily_summary = bool(daily_summary)
        user_settings.auto_add_new_chats = bool(auto_add_new_chats)
        user_settings.auto_add_group_chats_only = bool(auto_add_group_chats_only)
        db.commit()

        return JSONResponse(
            content={
                "status": "success",
                "message": "Cleanup settings updated successfully",
            }
        )
    except Exception as e:
        db.rollback()
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Error updating cleanup settings: {e!s}",
            },
        )


# --- Resource savings routes ---


@router.get("/resource-savings")
async def get_resource_savings(
    days_back: int = Query(30, ge=1, le=365),
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
                "message": f"Failed to get resource savings: {e!s}",
            },
        )


@router.get("/users/{user_id}/resource-savings")
async def get_user_resource_savings(
    user_id: int,
    days_back: int = Query(30, ge=1, le=365),
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
                "message": f"Failed to get user resource savings: {e!s}",
            },
        )


@router.get("/resource-savings-page", response_class=HTMLResponse)
async def resource_savings_page(request: Request):
    """Resource savings metrics page"""
    return templates.TemplateResponse(request, "resource_savings.html")


@router.get("/system/status")
async def system_status():
    """API for getting system status"""
    try:
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
            except Exception as e:
                logger.warning(f"WhatsApp bridge health check failed: {e}")
                bridge_status = {"status": "offline"}

        return JSONResponse({"fastapi": "online", "bridge": bridge_status})
    except Exception as e:
        return JSONResponse(
            {"fastapi": "online", "bridge": {"status": "error", "message": str(e)}}
        )
