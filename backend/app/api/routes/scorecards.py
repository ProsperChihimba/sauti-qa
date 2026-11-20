from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import DB, client_ip, current_user, require_admin
from app.models import Evaluation, Scorecard, User
from app.services.audit import audit
from app.services.scoring import ensure_default_scorecard
from app.services.scoring.scorecard import ScorecardDefinition, load_seed

router = APIRouter(prefix="/scorecards", tags=["scorecards"])


def out(sc: Scorecard, usage: int | None = None) -> dict[str, Any]:
    return {"id": sc.id, "key": sc.key, "name": sc.name, "version": sc.version, "is_active": sc.is_active,
            "pass_threshold": sc.pass_threshold, "created_at": sc.created_at, "created_by_id": sc.created_by_id,
            "definition": {"name": sc.name, "pass_threshold": sc.pass_threshold, **sc.definition},
            "evaluations": usage}


def _parse(definition: dict) -> ScorecardDefinition:
    try:
        return ScorecardDefinition(**definition)
    except ValidationError as exc:
        raise HTTPException(422, [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors(include_url=False)]) from exc
    except TypeError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("")
def list_scorecards(_: User = Depends(current_user), db: Session = DB):
    ensure_default_scorecard(db)
    db.commit()
    usage = dict(db.execute(select(Evaluation.scorecard_id, func.count()).group_by(Evaluation.scorecard_id)).all())
    rows = db.scalars(select(Scorecard).order_by(Scorecard.key, Scorecard.version.desc())).all()
    return [out(r, usage.get(r.id, 0)) for r in rows]


@router.get("/template")
def template(_: User = Depends(current_user)):
    return load_seed().model_dump()


class ValidateIn(BaseModel):
    definition: dict[str, Any]


@router.post("/validate")
def validate(body: ValidateIn, _: User = Depends(current_user)):
    sc = _parse(body.definition)
    return {"ok": True, "criteria": len(sc.criteria), "sections": sc.sections,
            "total_weight": sum(c.weight for c in sc.criteria),
            "critical": [c.id for c in sc.criteria if c.critical]}


@router.get("/{scorecard_id}")
def get_scorecard(scorecard_id: int, _: User = Depends(current_user), db: Session = DB):
    sc = db.get(Scorecard, scorecard_id)
    if not sc:
        raise HTTPException(404, "Scorecard not found")
    return out(sc)


class CreateIn(BaseModel):
    key: str | None = None
    definition: dict[str, Any]
    activate: bool = False


@router.post("", status_code=201)
def create(body: CreateIn, request: Request, admin: User = Depends(require_admin), db: Session = DB):
    d = _parse(body.definition)
    import re

    key = body.key or re.sub(r"[^a-z0-9]+", "-", d.name.lower()).strip("-")[:90] or "scorecard"
    if db.scalar(select(Scorecard.id).where(Scorecard.key == key)):
        raise HTTPException(409, "A scorecard with this key exists; save a new version instead")
    sc = Scorecard(key=key, name=d.name, version=1, definition=d.storage_dict(), pass_threshold=d.pass_threshold,
                   created_by_id=admin.id)
    db.add(sc)
    db.flush()
    if body.activate:
        _activate(db, sc)
    audit(db, "scorecard.create", "scorecard", sc.id, user_id=admin.id, ip=client_ip(request),
          after={"key": key, "name": d.name})
    db.commit()
    return out(sc)


class UpdateIn(BaseModel):
    definition: dict[str, Any]


@router.put("/{scorecard_id}")
def new_version(scorecard_id: int, body: UpdateIn, request: Request, admin: User = Depends(require_admin),
                db: Session = DB):
    """Save edits as a new version. Past evaluations keep pointing at the version they used."""
    base = db.get(Scorecard, scorecard_id)
    if not base:
        raise HTTPException(404, "Scorecard not found")
    d = _parse(body.definition)
    latest = db.scalar(select(func.max(Scorecard.version)).where(Scorecard.key == base.key)) or 0
    was_active = db.scalar(select(Scorecard.id).where(Scorecard.key == base.key, Scorecard.is_active.is_(True)))
    sc = Scorecard(key=base.key, name=d.name, version=latest + 1, definition=d.storage_dict(),
                   pass_threshold=d.pass_threshold, created_by_id=admin.id)
    db.add(sc)
    db.flush()
    if was_active:
        _activate(db, sc)
    audit(db, "scorecard.new_version", "scorecard", sc.id, user_id=admin.id, ip=client_ip(request),
          before={"id": base.id, "version": base.version}, after={"version": sc.version, "active": bool(was_active)})
    db.commit()
    return out(sc)


def _activate(db: Session, sc: Scorecard) -> None:
    db.execute(update(Scorecard).where(Scorecard.id != sc.id).values(is_active=False))
    sc.is_active = True


@router.post("/{scorecard_id}/activate")
def activate(scorecard_id: int, request: Request, admin: User = Depends(require_admin), db: Session = DB):
    sc = db.get(Scorecard, scorecard_id)
    if not sc:
        raise HTTPException(404, "Scorecard not found")
    _activate(db, sc)
    audit(db, "scorecard.activate", "scorecard", sc.id, user_id=admin.id, ip=client_ip(request))
    db.commit()
    return out(sc)
