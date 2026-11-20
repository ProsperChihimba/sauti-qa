import json
import time

from tests.conftest import make_wav


def test_bulk_upload_with_sidecar_and_rejections(admin_client, tmp_path):
    a = make_wav(tmp_path / "a.wav")
    b = make_wav(tmp_path / "b.wav", freq=600)
    files = [
        ("files", ("a.wav", a.read_bytes(), "audio/wav")),
        ("files", ("b.wav", b.read_bytes(), "audio/wav")),
        ("files", ("b.json", json.dumps({"agent_name": "Neema", "external_id": "REC-B"}), "application/json")),
        ("files", ("notes.txt", b"hello", "text/plain")),
    ]
    r = admin_client.post("/api/calls/upload", files=files, data={"agent_name": "Juma", "queue": "Prepaid"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["accepted"]) == 2 and len(body["rejected"]) == 1
    calls = admin_client.get("/api/calls").json()["items"]
    by_ext = {c["external_id"]: c for c in calls}
    assert by_ext["REC-B"]["agent"]["name"] == "Neema"
    assert by_ext[None]["agent"]["name"] == "Juma"
    assert all(c["queue"] == "Prepaid" for c in calls)

    # Same bytes again: not processed twice.
    r = admin_client.post("/api/calls/upload", files=[("files", ("again.wav", a.read_bytes(), "audio/wav"))])
    acc = r.json()["accepted"][0]
    assert acc["created"] is False and acc["duplicate_of"]


def test_api_ingest_is_idempotent_and_reports_status(admin_client, tmp_path):
    key = admin_client.post("/api/api-keys", json={"name": "rec"}).json()["key"]
    w = make_wav(tmp_path / "x.wav")
    meta = json.dumps({"external_id": "CALL-001", "agent_name": "Asha", "queue": "Data",
                       "call_time": "2026-11-19T10:15:00"})
    h = {"X-API-Key": key}
    r = admin_client.post("/api/v1/calls", files={"file": ("x.wav", w.read_bytes())}, data={"metadata": meta}, headers=h)
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["created"] is True
    r2 = admin_client.post("/api/v1/calls", files={"file": ("x.wav", w.read_bytes())}, data={"metadata": meta}, headers=h)
    assert r2.json()["created"] is False and r2.json()["id"] == first["id"]
    st = admin_client.get("/api/v1/calls/CALL-001", headers=h).json()
    assert st["status"] == "done"
    detail = admin_client.get(f"/api/calls/{first['id']}").json()
    assert detail["call_time"].startswith("2026-11-19T07:15:00")  # EAT assumed, stored as UTC
    # Unauthenticated / bad metadata
    assert admin_client.post("/api/v1/calls", files={"file": ("x.wav", b"1")}).status_code == 401
    r = admin_client.post("/api/v1/calls", files={"file": ("y.wav", w.read_bytes())}, data={"metadata": "{bad"},
                          headers=h)
    assert r.status_code == 422


def test_inbox_watcher(tmp_path, db):
    from app.models import Call
    from app.services.ingest.inbox import InboxWatcher

    w = InboxWatcher(stable_seconds=0.2)
    make_wav(w.root / "rec1.wav")
    (w.root / "rec1.json").write_text(json.dumps({"agent_name": "Baraka", "external_id": "SFTP-1", "queue": "Postpaid"}))
    (w.root / "half.wav.part").write_bytes(b"partial")
    (w.root / "bad.mp3").write_bytes(b"not really audio, but accepted at intake")
    (w.root / "broken.wav").write_bytes(b"x")
    (w.root / "broken.json").write_text("{not json")

    assert w.scan_once() == {}  # first sighting: wait until size is stable
    time.sleep(0.3)
    res = w.scan_once()
    assert res["rec1.wav"] == "ingested"
    assert res["broken.wav"].startswith("failed")
    assert (w.root / "half.wav.part").exists()
    call = db.query(Call).filter_by(external_id="SFTP-1").one()
    assert call.source == "inbox" and call.queue == "Postpaid" and call.agent.name == "Baraka"
    assert list(w.processed.rglob("rec1.json"))
    assert list(w.failed.rglob("broken.wav.error.txt"))
    assert not (w.root / "rec1.wav").exists()
