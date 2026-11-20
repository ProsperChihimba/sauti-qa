from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, utcnow
from app.models import ApiKey, User
from app.models.enums import Role
from app.security import api_key_matches, decode_access_token, parse_api_key_prefix

DB = Depends(get_db)


def _token_from_request(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(get_settings().cookie_name)


def current_user(request: Request, db: Session = DB) -> User:
    token = _token_from_request(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_access_token(token)
        user = db.get(User, int(payload["sub"]))
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session") from exc
    if not user or not user.is_active or payload.get("tv") != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user


@dataclass
class ApiClient:
    key: ApiKey


def api_key_client(x_api_key: str | None = Header(default=None), db: Session = DB) -> ApiClient:
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-API-Key header")
    prefix = parse_api_key_prefix(x_api_key)
    key = db.scalar(select(ApiKey).where(ApiKey.prefix == prefix)) if prefix else None
    if not key or key.revoked_at is not None or not api_key_matches(x_api_key, key.key_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    key.last_used_at = utcnow()
    db.commit()
    return ApiClient(key=key)


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None
