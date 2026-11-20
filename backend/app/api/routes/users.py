from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DB, client_ip, require_admin
from app.db import utcnow
from app.models import ApiKey, User
from app.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyOut, PasswordReset, UserCreate, UserOut, UserUpdate
from app.security import generate_api_key, hash_password, validate_password_strength
from app.services.audit import audit

router = APIRouter(tags=["users"])


@router.get("/users", response_model=list[UserOut])
def list_users(_: User = Depends(require_admin), db: Session = DB):
    return db.scalars(select(User).order_by(User.name)).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, request: Request, admin: User = Depends(require_admin), db: Session = DB):
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(409, "A user with this email already exists")
    try:
        validate_password_strength(body.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    user = User(email=body.email.lower(), name=body.name, role=body.role, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    audit(db, "user.create", "user", user.id, user_id=admin.id, ip=client_ip(request),
          after={"email": user.email, "role": user.role})
    db.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, request: Request, admin: User = Depends(require_admin),
                db: Session = DB):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    changes = body.model_dump(exclude_unset=True)
    if user.id == admin.id and (changes.get("role") == "analyst" or changes.get("is_active") is False):
        raise HTTPException(400, "You cannot demote or deactivate yourself")
    before = {k: getattr(user, k) for k in changes}
    for k, v in changes.items():
        setattr(user, k, v)
    if changes.get("is_active") is False or "role" in changes:
        user.token_version += 1  # end existing sessions
    audit(db, "user.update", "user", user.id, user_id=admin.id, ip=client_ip(request), before=before, after=changes)
    db.commit()
    return user


@router.post("/users/{user_id}/reset-password", status_code=204)
def reset_password(user_id: int, body: PasswordReset, request: Request, admin: User = Depends(require_admin),
                   db: Session = DB):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    try:
        validate_password_strength(body.new_password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    audit(db, "user.reset_password", "user", user.id, user_id=admin.id, ip=client_ip(request))
    db.commit()


@router.get("/api-keys", response_model=list[ApiKeyOut])
def list_keys(_: User = Depends(require_admin), db: Session = DB):
    return db.scalars(select(ApiKey).order_by(ApiKey.created_at.desc())).all()


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201)
def create_key(body: ApiKeyCreate, request: Request, admin: User = Depends(require_admin), db: Session = DB):
    full, prefix, digest = generate_api_key()
    key = ApiKey(name=body.name, prefix=prefix, key_hash=digest, created_by_id=admin.id)
    db.add(key)
    db.flush()
    audit(db, "api_key.create", "api_key", key.id, user_id=admin.id, ip=client_ip(request), after={"name": body.name})
    db.commit()
    return ApiKeyCreated(**ApiKeyOut.model_validate(key).model_dump(), key=full)


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_key(key_id: int, request: Request, admin: User = Depends(require_admin), db: Session = DB):
    key = db.get(ApiKey, key_id)
    if not key:
        raise HTTPException(404, "API key not found")
    if key.revoked_at is None:
        key.revoked_at = utcnow()
        audit(db, "api_key.revoke", "api_key", key.id, user_id=admin.id, ip=client_ip(request))
        db.commit()
