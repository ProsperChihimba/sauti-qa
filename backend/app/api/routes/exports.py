from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DB, client_ip, current_user
from app.models import Export, User
from app.models.enums import ExportKind, Role
from app.services.audit import audit
from app.services.call_query import CallFilters
from app.services.storage import get_storage

router = APIRouter(prefix="/exports", tags=["exports"])


class FiltersIn(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    agent_ids: list[int] = []
    queues: list[str] = []
    review_status: list[str] = []
    passed: bool | None = None
    auto_fail: bool | None = None
    flagged: bool | None = None


class ExportIn(BaseModel):
    kind: Literal["excel", "csv", "dataset"]
    filters: FiltersIn = FiltersIn()
    include_unedited_reviewed: bool = False
    test_fraction: float = Field(default=0.1, ge=0, le=0.5)


def out(e: Export) -> dict:
    return {"id": e.id, "kind": e.kind, "status": e.status, "filename": e.filename, "filters": e.filters,
            "stats": e.stats, "error": (e.error or "").split("\n")[0] or None, "created_at": e.created_at,
            "created_by_id": e.created_by_id}


@router.post("", status_code=202)
def create_export(body: ExportIn, request: Request, user: User = Depends(current_user), db: Session = DB):
    if body.kind == "dataset" and user.role != Role.admin:
        raise HTTPException(403, "Only admins can export training datasets")
    f = CallFilters.from_dict(body.filters.model_dump(exclude_none=True))
    filters = f.to_dict()
    if body.kind == "dataset":
        filters["_options"] = {"include_unedited_reviewed": body.include_unedited_reviewed,
                               "test_fraction": body.test_fraction}
    ex = Export(kind=body.kind, filters=filters, created_by_id=user.id)
    db.add(ex)
    db.flush()
    audit(db, f"export.{body.kind}", "export", ex.id, user_id=user.id, ip=client_ip(request), after=filters)
    db.commit()
    from app.workers.tasks.exports import export_task

    export_task.delay(ex.id)
    db.refresh(ex)
    return out(ex)


@router.get("")
def list_exports(kind: list[str] = Query(default=[]), user: User = Depends(current_user), db: Session = DB):
    stmt = select(Export).order_by(Export.created_at.desc()).limit(50)
    if kind:
        stmt = stmt.where(Export.kind.in_(kind))
    if user.role != Role.admin:
        stmt = stmt.where(Export.kind != ExportKind.dataset)
    return [out(e) for e in db.scalars(stmt)]


@router.get("/{export_id}")
def get_export(export_id: int, _: User = Depends(current_user), db: Session = DB):
    e = db.get(Export, export_id)
    if not e:
        raise HTTPException(404, "Export not found")
    return out(e)


@router.get("/{export_id}/download")
def download(export_id: int, request: Request, user: User = Depends(current_user), db: Session = DB):
    from app.workers.tasks.exports import CONTENT_TYPES

    e = db.get(Export, export_id)
    if not e or not e.file_key:
        raise HTTPException(404, "Export not ready")
    if e.kind == ExportKind.dataset and user.role != Role.admin:
        raise HTTPException(403, "Only admins can download training datasets")
    audit(db, "export.download", "export", e.id, user_id=user.id, ip=client_ip(request))
    db.commit()
    data = get_storage().get_bytes(e.file_key)
    return Response(data, media_type=CONTENT_TYPES[ExportKind(e.kind)],
                    headers={"Content-Disposition": f'attachment; filename="{e.filename}"'})
