from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth.admin_auth import require_admin_auth
from app.auth.security import get_password_hash
from app.core.repository_factory import repository_factory
from app.database.connection import get_db
from app.dependencies import get_telegram_service
from app.models.database import User, UserSettings
from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["web-admin"])
templates = Jinja2Templates(directory="web/templates")


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

    existing_user = repository_factory.get_user_repository().get_by_username(
        db, username
    )
    if not existing_user:
        existing_user = repository_factory.get_user_repository().get_by_email(db, email)

    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")

    hashed_password = get_password_hash(password)
    new_user = User(username=username, email=email, hashed_password=hashed_password)

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    from app.core.user_utils import create_default_user_settings

    create_default_user_settings(int(new_user.id), db)

    return RedirectResponse(url="/admin/users", status_code=303)


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail(user_id: int, request: Request, db: Session = Depends(get_db)):
    """User detail page"""
    require_admin_auth(request)

    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)
    monitored_chats = (
        repository_factory.get_monitored_chat_repository().get_active_chats_for_user(
            db, user_id
        )
    )
    last_digest = (
        repository_factory.get_digest_log_repository().get_last_digest_for_user(
            db, user_id
        )
    )
    digests = repository_factory.get_digest_log_repository().get_digests_for_period(
        db, user_id, 365
    )
    total_digests = len(digests)
    successful_digests = len([d for d in digests if d.telegram_sent or d.whatsapp_sent])
    digest_preferences = (
        repository_factory.get_digest_preference_repository().get_active_preferences(db)
    )
    whatsapp_phones = (
        repository_factory.get_whatsapp_phone_repository().get_active_phones_for_user(
            db, user_id
        )
    )

    return templates.TemplateResponse(
        "user_detail.html",
        {
            "request": request,
            "user": user,
            "monitored_chats": monitored_chats,
            "last_digest": last_digest,
            "total_digests": total_digests,
            "successful_digests": successful_digests,
            "digest_preferences": digest_preferences,
            "whatsapp_phones": whatsapp_phones,
        },
    )


@router.post("/users/{user_id}/settings")
async def update_user_settings(
    user_id: int,
    digest_preference_id: int = Form(...),
    telegram_channel_id: str = Form(None),
    digest_interval_hours: int = Form(...),
    phone_numbers: list[str] = Form([]),
    phone_display_names: list[str] = Form([]),
    db: Session = Depends(get_db),
):
    """Update user settings with multi-channel support"""
    logger.info(
        f"Updating user settings for user {user_id}: digest_preference_id={digest_preference_id}, "
        f"telegram_channel_id={telegram_channel_id}, digest_interval_hours={digest_interval_hours}, "
        f"phone_numbers={phone_numbers}"
    )

    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)
    user.digest_preference_id = digest_preference_id
    user.telegram_channel_id = telegram_channel_id
    user.digest_interval_hours = digest_interval_hours

    digest_preference = repository_factory.get_digest_preference_repository().get_by_id(
        db, digest_preference_id
    )

    if digest_preference and digest_preference.name == "whatsapp":
        whatsapp_phone_repo = repository_factory.get_whatsapp_phone_repository()
        existing_phones = whatsapp_phone_repo.get_active_phones_for_user(db, user_id)
        for phone in existing_phones:
            whatsapp_phone_repo.deactivate_phone(db, phone.id)
        for i, phone_number in enumerate(phone_numbers):
            if phone_number.strip():
                display_name = (
                    phone_display_names[i] if i < len(phone_display_names) else None
                )
                whatsapp_phone_repo.create_phone(
                    db, user_id, phone_number.strip(), display_name
                )

    db.commit()
    logger.info(f"Successfully updated user settings for user {user_id}")
    return RedirectResponse(url=f"/admin/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/settings/create")
async def create_user_settings(user_id: int, db: Session = Depends(get_db)):
    """Create default settings for user if they don't exist"""
    try:
        user = repository_factory.get_user_repository().get_by_id(db, user_id)
        if not user:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": "User not found"},
            )

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

        default_settings = UserSettings(
            user_id=user_id,
            max_message_age_hours=24,
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
                "message": f"Error creating user settings: {e!s}",
            },
        )


@router.post("/users/{user_id}/suspend")
async def suspend_user_web(user_id: int, db: Session = Depends(get_db)):
    """Suspend a user via web interface"""
    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    if not user.is_active:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "User is already suspended"},
        )

    user.is_active = False
    user.whatsapp_connected = False
    user.updated_at = datetime.now(UTC)
    db.commit()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            disconnect_response = await client.post(
                f"{settings.WHATSAPP_BRIDGE_URL}/disconnect/{user_id}",
                json={"reason": "user_suspended"},
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

    try:
        from app.core.resource_savings import resource_savings_service

        savings_result = resource_savings_service.record_suspension_savings(
            db, user_id, user.updated_at
        )
        if "error" not in savings_result:
            logger.info(
                f"Resource savings recorded for suspended user {user_id}: {savings_result}"
            )
    except Exception as e:
        logger.error(
            f"Error recording resource savings for suspended user {user_id}: {e}"
        )

    return JSONResponse(
        content={
            "status": "success",
            "message": f"User {user.username} has been suspended successfully",
        }
    )


@router.post("/users/{user_id}/resume")
async def resume_user_web(user_id: int, db: Session = Depends(get_db)):
    """Resume a suspended user via web interface"""
    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    if user.is_active:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "User is already active"},
        )

    user.is_active = True
    user.whatsapp_connected = False
    user.updated_at = datetime.now(UTC)
    db.commit()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            reconnect_response = await client.post(
                f"{settings.WHATSAPP_BRIDGE_URL}/reconnect/{user_id}",
                json={"reason": "user_resumed"},
            )
            if reconnect_response.status_code == 200:
                logger.info(
                    f"WhatsApp bridge reconnection initiated for resumed user {user_id}"
                )
    except Exception as e:
        logger.error(
            f"Error reconnecting WhatsApp bridge for resumed user {user_id}: {e}"
        )

    return JSONResponse(
        content={
            "status": "success",
            "message": f"User {user.username} has been resumed successfully",
        }
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
        telegram_service = get_telegram_service()
        verification = await telegram_service.verify_channel_access(
            user.telegram_channel_id
        )

        if verification["success"]:
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
            content={"status": "error", "message": f"Ошибка тестирования: {e!s}"},
        )


@router.get("/users/{user_id}/telegram/setup-guide")
async def get_telegram_setup_guide(user_id: int, db: Session = Depends(get_db)):
    """Get instructions for setting up a Telegram channel"""
    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)
    try:
        telegram_service = get_telegram_service()
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
                "message": f"Ошибка получения инструкций: {e!s}",
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
        telegram_service = get_telegram_service()
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
                "message": f"Ошибка получения статистики: {e!s}",
            },
        )
