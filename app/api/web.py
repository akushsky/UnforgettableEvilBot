"""
Admin web interface router.

Aggregates all admin sub-routers into a single module for backward compatibility.
New routes should be added to the appropriate sub-router:
  - auth_routes.py: login/logout
  - user_routes.py: user CRUD, settings, telegram integration
  - admin_routes.py: chats, QR, digests, cleanup, resource savings
"""

from fastapi import APIRouter

from app.api.admin_routes import router as admin_router
from app.api.auth_routes import router as auth_router
from app.api.user_routes import router as user_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(user_router)
router.include_router(admin_router)
