from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def audit(
    db: Session,
    action: str,
    entity: str,
    entity_id: Any = None,
    *,
    user_id: int | None = None,
    api_key_id: int | None = None,
    before: dict | None = None,
    after: dict | None = None,
    ip: str | None = None,
) -> None:
    """Record an auditable change. Committed together with the caller's transaction."""
    db.add(
        AuditLog(
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            actor_user_id=user_id,
            actor_api_key_id=api_key_id,
            before=before,
            after=after,
            ip=ip,
        )
    )
