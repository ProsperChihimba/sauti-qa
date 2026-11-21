from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_TMP = Path(os.environ.get("SAUTI_TEST_TMP", "/tmp/sauti-test"))
os.environ.update(
    ENV="test",
    DATABASE_URL=os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://sauti:sauti@localhost:5432/sauti_test"),
    CELERY_EAGER="true",
    STORAGE_BACKEND="local",
    STORAGE_LOCAL_ROOT=str(_TMP / "storage"),
    INBOX_DIR=str(_TMP / "inbox"),
    ASR_PROVIDER="mock",
    LLM_PROVIDER="mock",
    VAD_BACKEND="energy",
    DIARIZATION_BACKEND="mock",
    SECRET_KEY="test-secret-key-test-secret-key-0123456789",
    BOOTSTRAP_ADMIN_EMAIL="",
    AUDIO_RETENTION_DAYS="90",
)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

import app.models  # noqa: E402,F401
from app.db import Base, SessionLocal, get_engine  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def _schema():
    engine = get_engine()
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    # Build the schema through the real migrations so they are tested too.
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True,
                   env=os.environ.copy(), capture_output=True)
    yield


@pytest.fixture(autouse=True)
def _clean(_schema):
    import shutil

    engine = get_engine()
    names = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    for d in ("storage", "inbox"):
        shutil.rmtree(_TMP / d, ignore_errors=True)
    from app.services.storage import get_storage

    get_storage.cache_clear()
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def make_user(email="admin@example.com", role="admin", password="correct-horse-1", name="Admin"):
    from app.models import User
    from app.security import hash_password

    with SessionLocal() as s:
        u = User(email=email, name=name, role=role, password_hash=hash_password(password))
        s.add(u)
        s.commit()
        return u.id


def login(client, email="admin@example.com", password="correct-horse-1"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r


@pytest.fixture
def admin_client(client):
    make_user()
    login(client)
    return client


@pytest.fixture
def analyst_client():
    from app.main import app

    make_user("ana@example.com", "analyst", name="Ana Analyst")
    with TestClient(app) as c:
        login(c, "ana@example.com")
        yield c


def make_wav(path: Path, seconds: float = 3.0, stereo: bool = False, freq: int = 440) -> Path:
    """Synthesise a telephone-like test tone with gaps (so VAD finds speech regions)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    expr = f"if(lt(mod(t\\,1.5)\\,1.0)\\,0.5*sin(2*PI*{freq}*t)\\,0)"
    if stereo:
        expr2 = f"if(gte(mod(t\\,1.5)\\,0.5)\\,0.5*sin(2*PI*{freq * 2}*t)\\,0)"
        src = f"aevalsrc={expr}|{expr2}:s=8000:d={seconds}"
    else:
        src = f"aevalsrc={expr}:s=8000:d={seconds}"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", src, str(path)], check=True)
    return path


@pytest.fixture
def wav(tmp_path) -> Path:
    return make_wav(tmp_path / "call1.wav")
