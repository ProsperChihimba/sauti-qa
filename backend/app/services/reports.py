"""Excel and CSV QA reports.

The workbook layout lives in seed/report_layout.yaml (or REPORT_LAYOUT_PATH), so it
can be changed to the client's exact template without code changes.

FIELDS_CALLS (Details): call_id, external_id, call_time, agent, queue, duration_min,
  score, result, passed, auto_fail, failed_items, critical_failures, call_reason,
  resolution, sentiment, flags, summary_sw, summary_en, review_status, reviewer,
  reviewer_notes, overridden_items, scorecard, link, filename, source, status,
  review_reasons, plus crit:<criterion_id> answers.
FIELDS_AGENTS: agent, calls, minutes, avg_score, pass_rate, critical_breaches.
FIELDS_CRITERIA: criterion_id, section, label, critical, critical_text, yes, no, na,
  pass_rate, overridden.
"""

from __future__ import annotations

import csv
import io
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models import Call, Evaluation, ReviewNote, User
from app.services.call_query import EAT, CallFilters, base_query
from app.services.dashboard import build_dashboard, criterion_labels

LAYOUT_PATH = Path(__file__).resolve().parents[2] / "seed" / "report_layout.yaml"
HEADER_FILL = PatternFill("solid", fgColor="1F4E5A")
HEADER_FONT = Font(bold=True, color="FFFFFF")
RESULT_FILL = {
    "Pass": PatternFill("solid", fgColor="D8F0E0"),
    "Fail": PatternFill("solid", fgColor="FCEBC9"),
    "Auto-fail": PatternFill("solid", fgColor="F8D4D4"),
}
ANSWER_TEXT = {"yes": "Y", "no": "N", "na": "N/A"}


def load_layout() -> dict[str, Any]:
    path = Path(os.environ.get("REPORT_LAYOUT_PATH") or LAYOUT_PATH)
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _human(s: str | None) -> str:
    return (s or "").replace("_", " ").capitalize()


def call_rows(db: Session, f: CallFilters, limit: int = 100_000) -> tuple[list[dict[str, Any]], list[str]]:
    """One row per call (current evaluation). Returns rows and the ordered criterion ids."""
    stmt, ev = base_query(f)
    rows = db.execute(stmt.order_by(Call.call_time).limit(limit)).all()
    eval_ids = [e.id for _, e in rows if e is not None]
    items_by_eval: dict[int, Evaluation] = {}
    if eval_ids:
        for e in db.scalars(select(Evaluation).options(selectinload(Evaluation.items)).where(Evaluation.id.in_(eval_ids))):
            items_by_eval[e.id] = e
    call_ids = [c.id for c, _ in rows]
    notes: dict[Any, list[str]] = {}
    if call_ids:
        for n in db.scalars(select(ReviewNote).where(ReviewNote.call_id.in_(call_ids)).order_by(ReviewNote.created_at)):
            author = n.author.name if n.author else "?"
            notes.setdefault(n.call_id, []).append(f"[{n.kind}] {author}: {n.body}")
    users = {u.id: u.name for u in db.scalars(select(User))}
    labels = criterion_labels(db)
    base_url = get_settings().public_base_url.rstrip("/")

    crit_order: list[str] = []
    out = []
    for call, e in rows:
        ev_full = items_by_eval.get(e.id) if e is not None else None
        items = ev_full.items if ev_full else []
        for it in items:
            if it.criterion_id not in crit_order:
                crit_order.append(it.criterion_id)
        lab = lambda cid: labels.get(cid, {}).get("label", cid)  # noqa: E731
        failed = [lab(i.criterion_id) for i in items if i.answer == "no"]
        critical = [lab(i.criterion_id) for i in items if i.answer == "no" and labels.get(i.criterion_id, {}).get("critical")]
        overridden = [f"{lab(i.criterion_id)}: {ANSWER_TEXT[i.ai_answer]} -> {ANSWER_TEXT[i.answer]}"
                      for i in items if i.overridden_by_id is not None]
        if e is None:
            result = "Not scored"
        elif e.auto_fail:
            result = "Auto-fail"
        else:
            result = "Pass" if e.passed else "Fail"
        row: dict[str, Any] = {
            "call_id": str(call.id),
            "external_id": call.external_id or call.original_filename or str(call.id)[:8],
            "filename": call.original_filename,
            "source": call.source,
            "status": call.status,
            "call_time": call.call_time.astimezone(EAT).replace(tzinfo=None),
            "agent": call.agent.name if call.agent else "",
            "queue": call.queue or "",
            "duration_min": round((call.duration_s or 0) / 60, 2),
            "score": e.score if e else None,
            "passed": e.passed if e else None,
            "auto_fail": e.auto_fail if e else None,
            "result": result,
            "failed_items": "; ".join(failed),
            "critical_failures": "; ".join(critical),
            "call_reason": e.call_reason if e else "",
            "resolution": _human(e.resolution_status) if e else "",
            "sentiment": _human(e.sentiment) if e else "",
            "flags": "; ".join(f"{_human(fl['type'])}: {fl.get('description', '')}" for fl in (e.flags or [])) if e else "",
            "summary_sw": e.summary_sw if e else "",
            "summary_en": e.summary_en if e else "",
            "review_status": _human(call.review_status),
            "review_reasons": ", ".join(call.review_reasons or []),
            "reviewer": users.get(call.reviewed_by_id, "") if call.reviewed_by_id else "",
            "reviewer_notes": "\n".join(notes.get(call.id, [])),
            "overridden_items": "; ".join(overridden),
            "scorecard": f"{ev_full.scorecard.name} v{ev_full.scorecard.version}" if ev_full else "",
            "link": f"{base_url}/calls/{call.id}",
        }
        for it in items:
            row[f"crit:{it.criterion_id}"] = ANSWER_TEXT.get(it.answer, it.answer)
        out.append(row)
    return out, crit_order


def _style_header(ws, row: int, ncols: int) -> None:
    for col in range(1, ncols + 1):
        c = ws.cell(row=row, column=col)
        c.fill, c.font = HEADER_FILL, HEADER_FONT
        c.alignment = Alignment(vertical="center", wrap_text=True)


def _write_table(ws, spec: dict, rows: list[dict], extra_cols: list[dict] | None = None) -> None:
    cols = list(spec.get("columns", [])) + (extra_cols or [])
    r0 = int(spec.get("start_row", 1))
    if spec.get("write_headers", True):
        for j, col in enumerate(cols, 1):
            ws.cell(row=r0, column=j, value=col["header"])
            if col.get("width"):
                ws.column_dimensions[get_column_letter(j)].width = col["width"]
        _style_header(ws, r0, len(cols))
        ws.freeze_panes = ws.cell(row=r0 + 1, column=1)
        r0 += 1
    for i, row in enumerate(rows):
        for j, col in enumerate(cols, 1):
            v = row.get(col["field"])
            c = ws.cell(row=r0 + i, column=j, value=v)
            if col.get("format"):
                c.number_format = col["format"]
            if col.get("wrap"):
                c.alignment = Alignment(wrap_text=True, vertical="top")
            if col["field"] == "result" and v in RESULT_FILL:
                c.fill = RESULT_FILL[v]
    if rows and spec.get("write_headers", True):
        ws.auto_filter.ref = f"A{r0 - 1}:{get_column_letter(len(cols))}{r0 + len(rows) - 1}"


def _write_summary(ws, layout: dict, dash: dict, f: CallFilters, generated_by: str | None) -> None:
    k = dash["kpis"]
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["D"].width = 28
    ws.column_dimensions["E"].width = 10
    ws["A1"] = layout.get("title", "QA Report")
    ws["A1"].font = Font(bold=True, size=16)
    period = f"{f.date_from or 'start'} to {f.date_to or 'today'}"
    meta = [("Period", period), ("Generated", datetime.now(EAT).strftime("%Y-%m-%d %H:%M EAT")),
            ("Generated by", generated_by or "")]
    filt = {k2: v for k2, v in f.to_dict().items() if k2 not in ("date_from", "date_to")}
    if filt:
        meta.append(("Filters", ", ".join(f"{a}={b}" for a, b in filt.items())))
    r = 3
    for a, b in meta:
        ws.cell(row=r, column=1, value=a).font = Font(bold=True)
        ws.cell(row=r, column=2, value=b)
        r += 1
    r += 1
    ws.cell(row=r, column=1, value="Key figures").font = Font(bold=True, size=12)
    r += 1
    figures = [
        ("Calls evaluated", k["calls_evaluated"], "0"), ("Minutes analysed", k["minutes"], "0.0"),
        ("Average score (%)", k["avg_score"], "0.0"), ("Pass rate (%)", k["pass_rate"], "0.0"),
        ("Critical breaches (auto-fail)", k["critical_breaches"], "0"), ("Flagged calls", k["flagged"], "0"),
        ("Sent to human review", k["pending_review"] + k["reviewed"], "0"), ("Reviewed by analysts", k["reviewed"], "0"),
        ("Pending review", k["pending_review"], "0"),
    ]
    for a, b, fmt in figures:
        ws.cell(row=r, column=1, value=a)
        c = ws.cell(row=r, column=2, value=b)
        c.number_format = fmt
        r += 1

    def block(title: str, items: list[dict], row: int) -> int:
        ws.cell(row=row, column=4, value=title).font = Font(bold=True, size=12)
        row += 1
        total = sum(i["count"] for i in items) or 1
        for it in items:
            ws.cell(row=row, column=4, value=_human(it["name"]) if "_" in (it["name"] or "") else it["name"])
            ws.cell(row=row, column=5, value=it["count"])
            c = ws.cell(row=row, column=6, value=it["count"] / total)
            c.number_format = "0%"
            row += 1
        return row + 1

    rr = 7
    rr = block("Call reasons", dash["call_reasons"], rr)
    rr = block("Resolution", dash["resolution"], rr)
    block("Customer sentiment", dash["sentiment"], rr)


def build_excel(db: Session, f: CallFilters, generated_by: str | None = None) -> tuple[bytes, dict[str, Any]]:
    layout = load_layout()
    dash = build_dashboard(db, f)
    calls, crit_order = call_rows(db, f)
    labels = criterion_labels(db)
    sources = {
        "agents": dash["agents"],
        "criteria": [{**c, "critical_text": "Yes" if c.get("critical") else ""} for c in dash["criteria"]],
        "calls": calls,
    }
    template = layout.get("template")
    if template:
        wb = load_workbook(template)
    else:
        wb = Workbook()
        wb.remove(wb.active)
    for spec in layout["sheets"]:
        ws = wb[spec["name"]] if spec["name"] in wb.sheetnames else wb.create_sheet(spec["name"])
        if spec.get("kind") == "summary":
            _write_summary(ws, layout, dash, f, generated_by)
            continue
        extra = None
        if spec.get("criteria_columns"):
            extra = [{"header": labels.get(cid, {}).get("label", cid), "field": f"crit:{cid}", "width": 12}
                     for cid in crit_order]
        _write_table(ws, spec, sources.get(spec.get("source", ""), []), extra)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), {"calls": len(calls), "agents": len(dash["agents"])}


CSV_FIELDS = ["external_id", "call_time", "agent", "queue", "duration_min", "score", "result", "failed_items",
              "critical_failures", "call_reason", "resolution", "sentiment", "flags", "summary_sw", "summary_en",
              "review_status", "reviewer", "reviewer_notes", "overridden_items", "scorecard", "call_id", "link"]


def build_csv(db: Session, f: CallFilters) -> tuple[bytes, dict[str, Any]]:
    calls, crit_order = call_rows(db, f)
    fields = CSV_FIELDS + [f"crit:{c}" for c in crit_order]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for row in calls:
        w.writerow({**row, "call_time": row["call_time"].strftime("%Y-%m-%d %H:%M")})
    # UTF-8 with BOM so Excel opens Swahili text correctly.
    return ("﻿" + buf.getvalue()).encode("utf-8"), {"calls": len(calls)}
