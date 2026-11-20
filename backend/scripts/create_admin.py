#!/usr/bin/env python
"""Create (or reset) an admin account.

  python scripts/create_admin.py --email admin@example.co.tz --name "QA Admin"
The password is read from the prompt (or --password for automation).
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.db import session_scope  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password, validate_password_strength  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", default="Administrator")
    ap.add_argument("--password")
    args = ap.parse_args()
    pw = args.password or getpass.getpass("Password (min. 10 characters): ")
    validate_password_strength(pw)
    with session_scope() as db:
        u = db.scalar(select(User).where(func.lower(User.email) == args.email.lower()))
        if u:
            u.password_hash, u.role, u.is_active = hash_password(pw), "admin", True
            u.token_version += 1
            print(f"Reset password and admin role for {u.email}")
        else:
            db.add(User(email=args.email.lower(), name=args.name, role="admin", password_hash=hash_password(pw)))
            print(f"Created admin {args.email}")


if __name__ == "__main__":
    main()
