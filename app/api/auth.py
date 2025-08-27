from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.security import (
    create_access_token,
    get_password_hash,
    verify_password,
    verify_token,
)
from app.core.repository_factory import repository_factory
from app.core.validators import SecureUserCreate, SecurityValidators
from app.database.connection import get_db
from app.models.database import User
from app.models.schemas import Token, UserLogin, UserResponse
from config.settings import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    summary="Register new user",
    description="""
    Creates a new user in the system with secure input validation.

    **Validation includes:**
    - Username and email uniqueness check
    - Password strength validation
    - Input sanitization

    **Security:**
    - Passwords are hashed using bcrypt
    - Input data is validated against XSS and injection
    """,
    response_description="Created user data without password",
)
async def register_user(user: SecureUserCreate, db: Session = Depends(get_db)):
    """User registration with secure validation"""
    # Additional check for user existence
    db_user = repository_factory.get_user_repository().get_by_username(
        db, user.username
    )
    if not db_user:
        db_user = repository_factory.get_user_repository().get_by_email(db, user.email)

    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already registered",
        )

    # Create a new user with a hashed password
    hashed_password = get_password_hash(user.password)
    db_user = User(
        username=user.username, email=user.email, hashed_password=hashed_password
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    # Create default user settings automatically
    from app.core.user_utils import create_default_user_settings

    create_default_user_settings(db_user.id, db)

    return db_user


@router.post("/login", response_model=Token)
async def login_user(user: UserLogin, db: Session = Depends(get_db)):
    """User login with brute-force protection"""
    # Validate input data
    if not SecurityValidators.validate_username(user.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid username format"
        )

    db_user = repository_factory.get_user_repository().get_by_username(
        db, user.username
    )

    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    # Check user activity
    if not db_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is deactivated"
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    return {"access_token": access_token, "token_type": "bearer"}


async def get_current_user(
    authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Get the current user with enhanced security"""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
        )

    try:
        # Check token format
        if not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format"
            )

        token = authorization.split(" ")[1]
        username = verify_token(token)

        if not username:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        user = repository_factory.get_user_repository().get_by_username(db, username)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is deactivated",
            )

        return user

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication failed"
        )
