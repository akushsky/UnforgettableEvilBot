from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth.admin_auth import (
    create_admin_session,
    get_admin_login_page,
    get_admin_login_page_with_error,
    logout_admin,
    verify_admin_password,
)
from config.settings import settings

router = APIRouter(prefix="/admin", tags=["web-admin"])


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
