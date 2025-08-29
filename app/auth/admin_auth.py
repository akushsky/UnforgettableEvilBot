from fastapi import HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)

# Templates for admin login
templates = Jinja2Templates(directory="web/templates")

# Session storage (in-memory only)
admin_sessions = set()


def create_admin_session(request: Request) -> str:
    """Create a new admin session"""
    client_host = request.client.host if request.client else "unknown"
    session_id = f"admin_{client_host}_{id(request)}"
    admin_sessions.add(session_id)
    logger.info(f"Admin session created: {session_id}")
    return session_id


def is_admin_authenticated(request: Request) -> bool:
    """Check if admin is authenticated"""
    session_id = request.cookies.get("admin_session")
    if session_id and session_id in admin_sessions:
        return True
    return False


def require_admin_auth(request: Request) -> bool:
    """Require admin authentication - returns True if authenticated, raises exception otherwise"""
    if not is_admin_authenticated(request):
        # Check if this is a login attempt
        if request.url.path == "/admin/login" and request.method == "POST":
            return True  # Allow login attempts

        # Redirect to login page
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Admin authentication required",
            headers={"Location": "/admin/login"},
        )
    return True


def get_admin_auth_dependency(request: Request) -> bool:
    """FastAPI dependency for admin authentication"""
    return require_admin_auth(request)


def verify_admin_password(password: str) -> bool:
    """Verify admin password against environment variable"""
    try:
        admin_password = getattr(settings, "ADMIN_PASSWORD", "admin123")
        return password == admin_password
    except Exception as e:
        logger.error(f"Error verifying admin password: {e}")
        # Fallback to default password in case of settings error
        return password == "admin123"


def get_admin_login_page(request: Request) -> HTMLResponse:
    """Get admin login page"""
    return templates.TemplateResponse(
        "admin_login.html", {"request": request, "error": None}
    )


def get_admin_login_page_with_error(request: Request, error: str) -> HTMLResponse:
    """Get admin login page with error message"""
    return templates.TemplateResponse(
        "admin_login.html", {"request": request, "error": error}
    )


def logout_admin(request: Request) -> Response:
    """Logout admin by removing session"""
    session_id = request.cookies.get("admin_session")
    if session_id and session_id in admin_sessions:
        admin_sessions.remove(session_id)
        logger.info(f"Admin session removed: {session_id}")

    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie("admin_session")
    return response
