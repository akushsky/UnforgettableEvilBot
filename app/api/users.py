from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.decorators import safe_endpoint
from app.core.repository_factory import repository_factory
from app.core.validators import SecurityValidators
from app.database.connection import get_db
from app.models.database import User
from app.models.schemas import UserResponse, UserUpdate
from config.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/", response_model=List[UserResponse])
@safe_endpoint("get_users")
async def get_users(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(10, ge=1, le=100, description="Number of records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get list of users with pagination"""
    users = repository_factory.get_user_repository().get_all(db, skip=skip, limit=limit)
    return users


@router.get("/me", response_model=UserResponse)
@safe_endpoint("get_current_user_info")
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get information about the current user"""
    return current_user


@router.get("/{user_id}", response_model=UserResponse)
@safe_endpoint("get_user_by_id")
async def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a user by ID"""
    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)
    return user


@router.put("/me", response_model=UserResponse)
@safe_endpoint("update_current_user")
async def update_current_user(
    user_update: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update information about the current user"""
    # Validate input data
    if user_update.email and not SecurityValidators.validate_email(user_update.email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    # Check whether the email is taken by another user
    if user_update.email:
        existing_user = repository_factory.get_user_repository().get_by_email(
            db, user_update.email
        )
        if existing_user and existing_user.id != current_user.id:
            raise HTTPException(status_code=400, detail="Email already registered")

    # Update the user
    update_data = user_update.dict(exclude_unset=True)
    updated_user = repository_factory.get_user_repository().update(
        db, current_user, update_data
    )

    return updated_user


@router.get("/me/chats")
@safe_endpoint("get_user_chats")
async def get_user_chats(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """Get the current user's chats"""
    chats = (
        repository_factory.get_monitored_chat_repository().get_active_chats_for_user(
            db, current_user.id
        )
    )
    return {"user_id": current_user.id, "chats": chats, "total": len(chats)}


@router.post("/me/chats")
@safe_endpoint("add_user_chat")
async def add_user_chat(
    chat_data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a chat for monitoring"""
    # Validate chat data
    if not chat_data.get("chat_id") or not chat_data.get("chat_name"):
        raise HTTPException(status_code=400, detail="Chat ID and name are required")

    # Check whether this chat is already being monitored
    existing_chat = (
        repository_factory.get_monitored_chat_repository().get_by_user_and_chat_id(
            db, current_user.id, chat_data["chat_id"]
        )
    )
    if existing_chat:
        raise HTTPException(status_code=400, detail="Chat is already being monitored")

    # Create a new chat for monitoring
    chat_data["user_id"] = current_user.id
    chat_data["is_active"] = True

    new_chat = repository_factory.get_monitored_chat_repository().create(db, chat_data)

    return {"message": "Chat added for monitoring", "chat": new_chat}


@router.delete("/me/chats/{chat_id}")
@safe_endpoint("remove_user_chat")
async def remove_user_chat(
    chat_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a chat from monitoring"""
    # Find the user's chat
    chat = repository_factory.get_monitored_chat_repository().get_by_user_and_chat_id(
        db, current_user.id, chat_id
    )
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Delete the chat
    repository_factory.get_monitored_chat_repository().delete(db, chat.id)

    return {"message": "Chat removed from monitoring"}


@router.get("/me/digests")
@safe_endpoint("get_user_digests")
async def get_user_digests(
    days_back: int = Query(7, ge=1, le=30, description="Number of days to look back"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the user's digest history"""
    digests = repository_factory.get_digest_log_repository().get_digests_for_period(
        db, current_user.id, days_back
    )

    return {
        "user_id": current_user.id,
        "digests": digests,
        "total": len(digests),
        "period_days": days_back,
    }


@router.get("/stats")
@safe_endpoint("get_user_stats")
async def get_user_stats(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """Get user statistics"""
    # Get complete user data
    user_with_data = repository_factory.get_user_repository().get_user_with_full_data(
        db, current_user.id
    )

    if not user_with_data:
        raise HTTPException(status_code=404, detail="User not found")

    # Calculate statistics
    total_chats = len(user_with_data.monitored_chats)
    active_chats = len(
        [chat for chat in user_with_data.monitored_chats if chat.is_active]
    )
    total_digests = len(user_with_data.digest_logs)

    return {
        "user_id": current_user.id,
        "stats": {
            "total_chats": total_chats,
            "active_chats": active_chats,
            "total_digests": total_digests,
            "whatsapp_connected": current_user.whatsapp_connected,
            "telegram_configured": bool(current_user.telegram_channel_id),
        },
    }


@router.post("/{user_id}/suspend")
@safe_endpoint("suspend_user")
async def suspend_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Suspend a user (admin only)"""
    # Check if current user is admin (you might want to add admin role check)
    if current_user.id != 1:  # Assuming user ID 1 is admin
        raise HTTPException(status_code=403, detail="Admin access required")

    # Get the user to suspend
    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    # Check if user is already suspended
    if not user.is_active:
        raise HTTPException(status_code=400, detail="User is already suspended")

    # Suspend the user
    user.is_active = False
    user.updated_at = datetime.utcnow()
    db.commit()

    # Immediately disconnect WhatsApp bridge for suspended user
    try:
        import httpx

        bridge_url = "http://localhost:3000"
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

    return {"message": f"User {user.username} has been suspended successfully"}


@router.post("/{user_id}/resume")
@safe_endpoint("resume_user")
async def resume_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resume a suspended user (admin only)"""
    # Check if current user is admin (you might want to add admin role check)
    if current_user.id != 1:  # Assuming user ID 1 is admin
        raise HTTPException(status_code=403, detail="Admin access required")

    # Get the user to resume
    user = repository_factory.get_user_repository().get_by_id_or_404(db, user_id)

    # Check if user is already active
    if user.is_active:
        raise HTTPException(status_code=400, detail="User is already active")

    # Resume the user
    user.is_active = True
    user.updated_at = datetime.utcnow()
    db.commit()

    # Optionally reconnect WhatsApp bridge for resumed user (if they had it
    # connected before)
    if user.whatsapp_connected:
        try:
            import httpx

            bridge_url = "http://localhost:3000"
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

    return {"message": f"User {user.username} has been resumed successfully"}
