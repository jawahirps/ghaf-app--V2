"""
Ghaf App — authentication & login tracking endpoints.
"""
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, LoginLog
from ..schemas import Token, UserOut, UserCreate, LoginLogOut
from ..security import (
    verify_password,
    hash_password,
    create_access_token,
    get_current_user,
    require_roles,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Authenticate a user and record the attempt in the login_logs audit trail."""
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    user = db.query(User).filter(User.email == form_data.username).first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        db.add(
            LoginLog(
                user_id=user.id if user else None,
                email_attempted=form_data.username,
                success=False,
                failure_reason="invalid_credentials",
                ip_address=ip,
                user_agent=user_agent,
            )
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    if not user.is_active:
        db.add(
            LoginLog(
                user_id=user.id,
                email_attempted=form_data.username,
                success=False,
                failure_reason="inactive_account",
                ip_address=ip,
                user_agent=user_agent,
            )
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")

    user.last_login_at = datetime.utcnow()
    db.add(
        LoginLog(
            user_id=user.id,
            email_attempted=form_data.username,
            success=True,
            ip_address=ip,
            user_agent=user_agent,
        )
    )
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id), "role": user.role})
    return Token(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/login-logs", response_model=List[LoginLogOut])
def login_logs(
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "billing_manager")),
):
    """Recent login activity (admin / billing manager only)."""
    return (
        db.query(LoginLog)
        .order_by(LoginLog.created_at.desc())
        .limit(min(limit, 500))
        .all()
    )


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    """Create a new application user (admin only)."""
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        facility_id=payload.facility_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/users", response_model=List[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    return db.query(User).order_by(User.full_name.asc()).all()
