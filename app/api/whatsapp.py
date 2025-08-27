import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.repository_factory import repository_factory
from app.database.connection import get_db
from app.models.database import User
from app.telegram.service import TelegramService
from app.whatsapp.service import WhatsAppService
from config.settings import settings

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


# Create services without initialization on import
def get_whatsapp_service():
    """Get Whatsapp Service."""
    return WhatsAppService(settings.WHATSAPP_SESSION_PATH)


def get_telegram_service():
    """Get Telegram Service."""
    return TelegramService()


@router.post("/connect")
async def connect_whatsapp(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Connect to WhatsApp"""
    try:
        whatsapp_service = get_whatsapp_service()
        success = await whatsapp_service.initialize_client(current_user.id)

        if success:
            current_user.whatsapp_connected = True
            current_user.whatsapp_session_id = f"user_{current_user.id}"
            db.commit()

            return {
                "message": "WhatsApp connection started. Check QR code in console or wait for ready status."
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to start WhatsApp connection",
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"WhatsApp connection error: {str(e)}",
        )


@router.get("/active-users")
async def get_active_users(db: Session = Depends(get_db)):
    """Get list of active users for WhatsApp bridge"""
    try:
        active_users = (
            repository_factory.get_user_repository().get_active_users_with_whatsapp(db)
        )

        return {
            "active_users": [
                {
                    "id": user.id,
                    "username": user.username,
                    "whatsapp_session_id": user.whatsapp_session_id,
                }
                for user in active_users
            ]
        }
    except Exception as e:
        logger.error(f"Error getting active users: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting active users: {str(e)}",
        )


@router.post("/disconnect-suspended")
async def disconnect_suspended_users(db: Session = Depends(get_db)):
    """Disconnect suspended users from WhatsApp bridge"""
    try:
        # Get suspended users with active WhatsApp connections
        suspended_users = (
            repository_factory.get_user_repository().get_suspended_users_with_whatsapp(
                db
            )
        )

        if not suspended_users:
            return {"message": "No suspended users with active WhatsApp connections"}

        # Disconnect each suspended user
        get_whatsapp_service()
        results = []

        for user in suspended_users:
            try:
                # Update user status
                user.whatsapp_connected = False
                user.whatsapp_session_id = None
                db.commit()

                # Notify bridge to disconnect
                import httpx

                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"http://localhost:3000/cleanup/{user.id}", timeout=10.0
                    )

                results.append(
                    {
                        "user_id": user.id,
                        "username": user.username,
                        "status": "disconnected",
                    }
                )

            except Exception as e:
                logger.error(f"Failed to disconnect user {user.id}: {e}")
                results.append(
                    {
                        "user_id": user.id,
                        "username": user.username,
                        "status": "error",
                        "error": str(e),
                    }
                )

        return {
            "message": f"Processed {len(suspended_users)} suspended users",
            "results": results,
        }

    except Exception as e:
        logger.error(f"Error disconnecting suspended users: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error disconnecting suspended users: {str(e)}",
        )


@router.get("/qr-code")
async def get_qr_code(current_user: User = Depends(get_current_user)):
    """Get WhatsApp QR code for the current user"""
    try:
        bridge_url = "http://localhost:3000"

        # Initialize the client first
        async with httpx.AsyncClient() as client:
            init_response = await client.post(
                f"{bridge_url}/initialize/{current_user.id}"
            )
            if init_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to initialize WhatsApp client",
                )

            # Wait a little for QR code generation
            await asyncio.sleep(2)

            # Retrieve the QR code
            qr_response = await client.get(f"{bridge_url}/qr/{current_user.id}")

            if qr_response.status_code == 200:
                qr_data = qr_response.json()
                return {
                    "success": True,
                    "qr_code": qr_data.get("qrCode"),
                    "timestamp": qr_data.get("timestamp"),
                    "message": "QR-код готов для сканирования",
                }
            elif qr_response.status_code == 404:
                return {
                    "success": False,
                    "message": "QR-код пока не готов, попробуйте через несколько секунд",
                }
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to get QR code from bridge",
                )

    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"WhatsApp bridge is not available: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"QR code generation error: {str(e)}",
        )


@router.get("/status")
async def get_whatsapp_status(current_user: User = Depends(get_current_user)):
    """Get WhatsApp connection status"""
    try:
        whatsapp_service = get_whatsapp_service()
        status_info = await whatsapp_service.get_client_status(current_user.id)

        return {
            "user_id": current_user.id,
            "whatsapp_connected": current_user.whatsapp_connected,
            "bridge_status": status_info,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get status: {str(e)}",
        )


@router.get("/chats/available")
async def get_available_chats(current_user: User = Depends(get_current_user)):
    """Get a list of available chats from WhatsApp"""
    if not current_user.whatsapp_connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="WhatsApp is not connected"
        )

    try:
        whatsapp_service = get_whatsapp_service()
        chats = await whatsapp_service.get_chats(current_user.id)
        return {"chats": chats}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get chats: {str(e)}",
        )


@router.post("/disconnect")
async def disconnect_whatsapp(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Disconnect from WhatsApp"""
    try:
        whatsapp_service = get_whatsapp_service()
        await whatsapp_service.disconnect(current_user.id)

        current_user.whatsapp_connected = False
        current_user.whatsapp_session_id = None
        db.commit()

        return {"message": "WhatsApp disconnected successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Disconnection error: {str(e)}",
        )


@router.post("/telegram/test")
async def test_telegram_connection(current_user: User = Depends(get_current_user)):
    """Test connection to the Telegram channel"""
    if not current_user.telegram_channel_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram channel not configured",
        )

    try:
        telegram_service = get_telegram_service()
        success = await telegram_service.test_connection(
            current_user.telegram_channel_id
        )

        if success:
            return {"message": "Telegram connection successful"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to send test message to Telegram",
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Telegram connection error: {str(e)}",
        )
