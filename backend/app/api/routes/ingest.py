from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DB, ApiClient, api_key_client, current_user
from app.config import get_settings
from app.models import Call, Evaluation, User
from app.models.enums import CallSource
from app.schemas import ApiCallStatus, IngestOut, UploadResult
from app.services.ingest import CallMetadata, IngestError, ingest_file

router = APIRouter(tags=["ingest"])


def _spool(upload: UploadFile, tmpdir: Path) -> Path:
    limit = get_settings().max_upload_mb * 1024 * 1024
    dest = tmpdir / Path(upload.filename or "upload").name
    written = 0
    with dest.open("wb") as out:
        while chunk := upload.file.read(1 << 20):
            written += len(chunk)
            if written > limit:
                raise IngestError(f"File larger than {get_settings().max_upload_mb} MB")
            out.write(chunk)
    return dest


def _out(result, filename=None) -> IngestOut:
    c = result.call
    return IngestOut(id=c.id, external_id=c.external_id, status=c.status, created=result.created,
                     duplicate_of=result.duplicate_of, filename=filename)


@router.post("/calls/upload", response_model=UploadResult)
def upload_calls(
    files: list[UploadFile] = File(...),
    agent_name: str | None = Form(default=None),
    queue: str | None = Form(default=None),
    call_time: str | None = Form(default=None),
    user: User = Depends(current_user),
    db: Session = DB,
):
    """Bulk browser upload. Form fields apply to every file; a .json sidecar with the
    same stem as an audio file (uploaded in the same batch) overrides them per file."""
    sidecars: dict[str, dict] = {}
    audio: list[UploadFile] = []
    rejected: list[dict[str, str]] = []
    for f in files:
        name = f.filename or ""
        if name.lower().endswith(".json"):
            try:
                sidecars[Path(name).stem] = json.loads(f.file.read())
            except json.JSONDecodeError:
                rejected.append({"filename": name, "error": "Invalid JSON sidecar"})
        else:
            audio.append(f)

    base = {k: v for k, v in {"agent_name": agent_name, "queue": queue, "call_time": call_time}.items() if v}
    accepted: list[IngestOut] = []
    with tempfile.TemporaryDirectory() as tmp:
        for f in audio:
            name = f.filename or "upload"
            try:
                meta = CallMetadata(**{**base, **sidecars.get(Path(name).stem, {})})
                path = _spool(f, Path(tmp))
                res = ingest_file(db, path, filename=name, source=CallSource.upload, meta=meta, user_id=user.id)
                accepted.append(_out(res, name))
            except (IngestError, ValidationError) as exc:
                db.rollback()
                rejected.append({"filename": name, "error": str(exc)})
            finally:
                p = Path(tmp) / Path(name).name
                if p.exists():
                    p.unlink()
    if not accepted and not rejected:
        raise HTTPException(400, "No audio files received")
    return UploadResult(accepted=accepted, rejected=rejected)


@router.post("/v1/calls", response_model=IngestOut, status_code=201, tags=["integration"])
def api_ingest(
    request: Request,
    file: UploadFile = File(..., description="Call recording"),
    metadata: str | None = Form(default=None, description='JSON: {"agent_name","queue","call_time","external_id"}'),
    client: ApiClient = Depends(api_key_client),
    db: Session = DB,
):
    """Integration endpoint for the call recorder (X-API-Key auth). Idempotent on external_id."""
    try:
        meta = CallMetadata(**(json.loads(metadata) if metadata else {}))
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise HTTPException(422, f"Invalid metadata: {exc}") from exc
    tmp = Path(tempfile.mkdtemp())
    try:
        path = _spool(file, tmp)
        res = ingest_file(db, path, filename=file.filename or "upload", source=CallSource.api, meta=meta,
                          api_key_id=client.key.id)
    except IngestError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return _out(res, file.filename)


@router.get("/v1/calls/{external_id}", response_model=ApiCallStatus, tags=["integration"])
def api_status(external_id: str, client: ApiClient = Depends(api_key_client), db: Session = DB):
    call = db.scalar(select(Call).where(Call.external_id == external_id))
    if not call:
        raise HTTPException(404, "Unknown external_id")
    ev = db.scalar(select(Evaluation).where(Evaluation.call_id == call.id, Evaluation.is_current.is_(True)))
    return ApiCallStatus(
        id=call.id, external_id=call.external_id, status=call.status, review_status=call.review_status,
        score=ev.score if ev else None, passed=ev.passed if ev else None, auto_fail=ev.auto_fail if ev else None,
        error=call.error,
    )
