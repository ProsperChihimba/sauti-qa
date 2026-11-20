"""Watched inbox folder for SFTP drops from the call recorder.

Run with:  python -m app.services.ingest.inbox

Layout (created automatically):
    <INBOX_DIR>/               recorder drops files here
    <INBOX_DIR>/processed/     ingested files are moved here (dated sub-folders)
    <INBOX_DIR>/failed/        rejected files + a .error.txt explaining why

Each audio file may have a JSON sidecar with the same stem, e.g. call123.wav and
call123.json containing {"agent_name", "queue", "call_time", "external_id"}.
A file is only picked up once its size has not changed for INBOX_STABLE_SECONDS,
so half-uploaded SFTP transfers are never ingested. Files starting with "." or
ending in .part/.tmp/.filepart are ignored.
"""

from __future__ import annotations

import json
import logging
import shutil
import signal
import time
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings
from app.db import SessionLocal
from app.models.enums import CallSource
from app.services.ingest import CallMetadata, IngestError, ingest_file

log = logging.getLogger("sauti.inbox")
PARTIAL_SUFFIXES = (".part", ".tmp", ".filepart", ".partial", ".crdownload")


class InboxWatcher:
    def __init__(self, root: Path | None = None, stable_seconds: float | None = None):
        s = get_settings()
        self.root = (root or s.inbox_dir).resolve()
        self.stable_seconds = s.inbox_stable_seconds if stable_seconds is None else stable_seconds
        self.processed = self.root / "processed"
        self.failed = self.root / "failed"
        for d in (self.root, self.processed, self.failed):
            d.mkdir(parents=True, exist_ok=True)
        self._seen: dict[Path, tuple[int, float]] = {}  # path -> (size, first time at that size)
        self._stop = False

    def _candidates(self) -> list[Path]:
        exts = set(get_settings().allowed_audio_ext)
        out = []
        for p in sorted(self.root.iterdir()):
            if not p.is_file() or p.name.startswith(".") or p.name.endswith(PARTIAL_SUFFIXES):
                continue
            if p.suffix.lower() in exts:
                out.append(p)
        return out

    def _is_stable(self, p: Path, now: float) -> bool:
        size = p.stat().st_size
        prev = self._seen.get(p)
        if prev is None or prev[0] != size:
            self._seen[p] = (size, now)
            return self.stable_seconds <= 0 and size > 0
        return size > 0 and now - prev[1] >= self.stable_seconds

    def _move(self, p: Path, dest_root: Path) -> Path:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        dest_dir = dest_root / day
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / p.name
        if dest.exists():
            dest = dest_dir / f"{p.stem}-{int(time.time())}{p.suffix}"
        shutil.move(str(p), dest)
        return dest

    def _read_sidecar(self, audio: Path) -> tuple[CallMetadata, Path | None]:
        sidecar = audio.with_suffix(".json")
        if not sidecar.exists():
            return CallMetadata(), None
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise IngestError("Sidecar JSON must be an object")
        return CallMetadata(**data), sidecar

    def process_file(self, p: Path) -> str:
        sidecar = None
        db = SessionLocal()
        try:
            meta, sidecar = self._read_sidecar(p)
            result = ingest_file(db, p, filename=p.name, source=CallSource.inbox, meta=meta)
            outcome = "ingested" if result.created else f"duplicate of {result.duplicate_of}"
            self._move(p, self.processed)
            if sidecar:
                self._move(sidecar, self.processed)
            log.info("inbox %s: %s (call %s)", p.name, outcome, result.call.id)
            return outcome
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the watcher
            db.rollback()
            log.warning("inbox %s rejected: %s", p.name, exc)
            moved = self._move(p, self.failed)
            moved.with_name(moved.name + ".error.txt").write_text(f"{type(exc).__name__}: {exc}\n")
            if sidecar and sidecar.exists():
                self._move(sidecar, self.failed)
            return f"failed: {exc}"
        finally:
            db.close()
            self._seen.pop(p, None)

    def scan_once(self) -> dict[str, str]:
        now = time.monotonic()
        results = {}
        current = set()
        for p in self._candidates():
            current.add(p)
            if self._is_stable(p, now):
                results[p.name] = self.process_file(p)
        for gone in set(self._seen) - current:
            self._seen.pop(gone, None)
        return results

    def run_forever(self) -> None:
        interval = get_settings().inbox_poll_seconds
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "_stop", True))
        log.info("watching %s every %.1fs", self.root, interval)
        while not self._stop:
            try:
                self.scan_once()
            except Exception:  # noqa: BLE001
                log.exception("inbox scan failed")
            time.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    InboxWatcher().run_forever()
