#!/usr/bin/env python
"""Seed a fresh install: default Swahili telecom scorecard, users, and (optionally)
demo calls so the dashboard and review screens have something to show.

  python scripts/seed.py                       # scorecard + admin from env/args
  python scripts/seed.py --demo-calls 40       # plus 40 synthetic demo calls

Demo calls use synthetic audio and are meaningful only with ASR_PROVIDER=mock and
LLM_PROVIDER=mock (they carry a mock_variant so the mock dialogue matches).
"""

from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

AGENTS = ["Neema Mushi", "Juma Hassan", "Baraka Mwakyusa", "Asha Mohamed", "Rehema Kweka", "Daudi Mollel"]
QUEUES = ["Prepaid", "M-Pesa", "Data", "Postpaid"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--admin-email", default=os.environ.get("BOOTSTRAP_ADMIN_EMAIL") or "admin@sauti.local")
    ap.add_argument("--admin-password", default=os.environ.get("BOOTSTRAP_ADMIN_PASSWORD"))
    ap.add_argument("--analyst-email", default="analyst@sauti.local")
    ap.add_argument("--analyst-password")
    ap.add_argument("--demo-calls", type=int, default=0)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--inline", action="store_true", help="process demo calls in this process (no workers needed)")
    args = ap.parse_args()
    if args.inline:
        os.environ["CELERY_EAGER"] = "true"

    from sqlalchemy import func, select

    from app.db import SessionLocal, session_scope
    from app.models import Call, User
    from app.models.enums import CallSource
    from app.security import hash_password
    from app.services.ingest import CallMetadata, ingest_file
    from app.services.scoring import ensure_default_scorecard

    with session_scope() as db:
        sc = ensure_default_scorecard(db)
        print(f"Scorecard: {sc.name} v{sc.version} (active)")
        for email, pw, role, name in ((args.admin_email, args.admin_password, "admin", "QA Administrator"),
                                      (args.analyst_email, args.analyst_password, "analyst", "QA Analyst")):
            if not pw:
                continue
            if db.scalar(select(User).where(func.lower(User.email) == email.lower())):
                print(f"User exists: {email}")
                continue
            db.add(User(email=email.lower(), name=name, role=role, password_hash=hash_password(pw)))
            print(f"Created {role}: {email}")

    if not args.demo_calls:
        return
    rng = random.Random(7)
    variants = ["good"] * 6 + ["escalation"] * 3 + ["poor"] * 2
    now = datetime.now(UTC)
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(args.demo_calls):
            stereo = rng.random() < 0.5
            seconds = rng.randint(45, 240)
            freq = 180 + i * 7
            path = Path(tmp) / f"demo-{i:04d}.wav"
            expr = f"if(lt(mod(t\\,2.5)\\,1.8)\\,0.4*sin(2*PI*{freq}*t)*(0.6+0.4*sin(2*PI*3*t))\\,0)"
            src = f"aevalsrc={expr}|{expr}:s=8000:d={seconds}" if stereo else f"aevalsrc={expr}:s=8000:d={seconds}"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", src, str(path)], check=True)
            when = now - timedelta(days=rng.randint(0, args.days - 1), hours=rng.randint(0, 9), minutes=rng.randint(0, 59))
            meta = CallMetadata(agent_name=rng.choice(AGENTS), queue=rng.choice(QUEUES), call_time=when,
                                external_id=f"DEMO-{i:05d}", mock_variant=rng.choice(variants))
            with SessionLocal() as db:
                if db.scalar(select(Call.id).where(Call.external_id == meta.external_id)):
                    continue
                res = ingest_file(db, path, filename=path.name, source=CallSource.upload, meta=meta)
                print(f"  demo call {i + 1}/{args.demo_calls}: {res.call.external_id} -> {res.call.status}")


if __name__ == "__main__":
    main()
