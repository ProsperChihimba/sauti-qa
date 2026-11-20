"""Report and dataset exports run as background jobs (large ranges take a while)."""

from __future__ import annotations

import logging
import traceback

from app.db import session_scope, utcnow
from app.models import Export, User
from app.models.enums import ExportKind, JobStatus
from app.services.call_query import CallFilters
from app.services.storage import get_storage
from app.workers.celery_app import celery

log = logging.getLogger(__name__)
CONTENT_TYPES = {
    ExportKind.excel: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ExportKind.csv: "text/csv",
    ExportKind.dataset: "application/zip",
}


def run_export(export_id: int) -> None:
    with session_scope() as db:
        ex = db.get(Export, export_id)
        if ex is None or ex.status == JobStatus.succeeded:
            return
        ex.status = JobStatus.running
    try:
        from app.services.datasets import build_dataset
        from app.services.reports import build_csv, build_excel

        with session_scope() as db:
            ex = db.get(Export, export_id)
            f = CallFilters.from_dict(ex.filters)
            user = db.get(User, ex.created_by_id) if ex.created_by_id else None
            stamp = utcnow().strftime("%Y%m%d-%H%M")
            if ex.kind == ExportKind.excel:
                data, stats = build_excel(db, f, generated_by=user.name if user else None)
                name = f"qa-report-{stamp}.xlsx"
            elif ex.kind == ExportKind.csv:
                data, stats = build_csv(db, f)
                name = f"qa-calls-{stamp}.csv"
            else:
                opts = ex.filters.get("_options", {})
                data, stats = build_dataset(db, f, include_unedited_reviewed=bool(opts.get("include_unedited_reviewed")),
                                            test_fraction=float(opts.get("test_fraction", 0.1)))
                name = f"asr-dataset-{stamp}.zip"
            key = f"exports/{export_id}/{name}"
            get_storage().put_bytes(key, data, CONTENT_TYPES[ExportKind(ex.kind)])
            ex.file_key, ex.filename, ex.stats, ex.status, ex.error = key, name, stats, JobStatus.succeeded, None
    except Exception as exc:  # noqa: BLE001
        log.exception("export %s failed", export_id)
        with session_scope() as db:
            ex = db.get(Export, export_id)
            ex.status, ex.error = JobStatus.failed, f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=5)}"


@celery.task(name="exports.run", acks_late=True)
def export_task(export_id: int) -> None:
    run_export(export_id)
