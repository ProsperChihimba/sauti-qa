from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import get_settings

_ph = PasswordHasher()
JWT_ALG = "HS256"
API_KEY_PREFIX = "sqa_"


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters")


def create_access_token(user_id: int, token_version: int) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "tv": token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, s.secret_key, algorithm=JWT_ALG)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, get_settings().secret_key, algorithms=[JWT_ALG])


def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, prefix, hash). Only the hash is stored."""
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    full = f"{API_KEY_PREFIX}{prefix}_{secret}"
    return full, prefix, hash_api_key(full)


def hash_api_key(full_key: str) -> str:
    # Keys are high-entropy, so a keyed SHA-256 is sufficient and fast to verify.
    return hmac.new(get_settings().secret_key.encode(), full_key.encode(), hashlib.sha256).hexdigest()


def parse_api_key_prefix(full_key: str) -> str | None:
    if not full_key.startswith(API_KEY_PREFIX):
        return None
    rest = full_key[len(API_KEY_PREFIX):]
    prefix, _, secret = rest.partition("_")
    return prefix if prefix and secret else None


def api_key_matches(full_key: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(full_key), stored_hash)
