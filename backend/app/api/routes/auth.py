from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DB, client_ip, current_user
from app.config import get_settings
from app.db import utcnow
from app.models import User
from app.schemas import LoginIn, PasswordChange, UserOut
from app.security import create_access_token, hash_password, validate_password_strength, verify_password
from app.services.audit import audit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = DB):
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        audit(db, "auth.login_failed", "user", user.id if user else None, ip=client_ip(request),
              after={"email": body.email})
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    user.last_login_at = utcnow()
    audit(db, "auth.login", "user", user.id, user_id=user.id, ip=client_ip(request))
    db.commit()
    s = get_settings()
    response.set_cookie(
        s.cookie_name,
        create_access_token(user.id, user.token_version),
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        max_age=s.jwt_expire_minutes * 60,
        path="/",
    )
    return user


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(get_settings().cookie_name, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.post("/password", status_code=204)
def change_password(body: PasswordChange, request: Request, response: Response,
                    user: User = Depends(current_user), db: Session = DB):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    try:
        validate_password_strength(body.new_password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    audit(db, "user.password_change", "user", user.id, user_id=user.id, ip=client_ip(request))
    db.commit()
    s = get_settings()
    response.set_cookie(s.cookie_name, create_access_token(user.id, user.token_version), httponly=True,
                        secure=s.cookie_secure, samesite="lax", max_age=s.jwt_expire_minutes * 60, path="/")
