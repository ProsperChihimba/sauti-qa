from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text

from app.api.routes import auth, calls, ingest, ops, users
from app.config import get_settings
from app.db import SessionLocal

log = logging.getLogger("sauti")


def bootstrap_admin() -> None:
    """Create the first admin from BOOTSTRAP_ADMIN_* if the users table is empty."""
    s = get_settings()
    if not (s.bootstrap_admin_email and s.bootstrap_admin_password):
        return
    from app.models import User
    from app.security import hash_password

    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)) is None:
            db.add(User(email=s.bootstrap_admin_email.lower(), name="Administrator", role="admin",
                        password_hash=hash_password(s.bootstrap_admin_password)))
            db.commit()
            log.warning("Created bootstrap admin %s - change the password after first login", s.bootstrap_admin_email)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        bootstrap_admin()
    except Exception:  # noqa: BLE001 - DB may not be migrated yet
        log.exception("bootstrap admin failed")
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Sauti QA API", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    for r in (auth.router, users.router, ingest.router, calls.router, ops.router):
        app.include_router(r, prefix="/api")

    @app.get("/api/health", tags=["ops"])
    def health():
        return {"status": "ok"}

    @app.get("/api/ready", tags=["ops"])
    def ready():
        checks = {}
        try:
            with SessionLocal() as db:
                db.execute(text("select 1"))
            checks["database"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["database"] = f"error: {exc}"
        try:
            import redis

            redis.Redis.from_url(s.redis_url, socket_timeout=2).ping()
            checks["redis"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = f"error: {exc}"
        checks["asr_provider"] = s.asr_provider
        checks["llm_provider"] = s.llm_provider
        checks["storage"] = s.storage_backend
        return checks

    return app


app = create_app()
