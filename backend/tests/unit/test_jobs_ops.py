from datetime import timedelta

import pytest

from tests.conftest import make_wav


def _upload(client, path):
    r = client.post("/api/calls/upload", files=[("files", (path.name, path.read_bytes(), "audio/wav"))])
    return r.json()["accepted"][0]["id"]


def test_pipeline_runs_all_stages(admin_client, wav):
    cid = _upload(admin_client, wav)
    jobs = admin_client.get("/api/jobs", params={"call_id": cid}).json()["items"]
    assert sorted(j["kind"] for j in jobs) == ["label", "prepare", "score", "transcribe"]
    assert all(j["status"] == "succeeded" for j in jobs)


def test_failed_stage_is_visible_and_retryable(admin_client, wav, monkeypatch):
    from app.services import pipeline

    def boom(db, call, hb):
        raise RuntimeError("GPU fell over")

    monkeypatch.setattr(pipeline, "transcribe", boom)
    cid = _upload(admin_client, wav)
    call = admin_client.get(f"/api/calls/{cid}").json()
    assert call["status"] == "failed" and "GPU fell over" in call["error"]
    failed = admin_client.get("/api/jobs", params={"status": "failed"}).json()["items"]
    assert len(failed) == 1 and failed[0]["kind"] == "transcribe"

    monkeypatch.undo()
    r = admin_client.post(f"/api/jobs/{failed[0]['id']}/retry")
    assert r.status_code == 202
    assert admin_client.get(f"/api/calls/{cid}").json()["status"] == "done"


def test_stuck_job_recovery(admin_client, wav, db, monkeypatch):
    from app.db import utcnow
    from app.models import Job
    from app.workers.tasks import maintenance

    cid = _upload(admin_client, wav)
    job = db.query(Job).filter_by(call_id=cid, kind="score").one()
    job.status = "running"
    job.attempts = 1
    job.heartbeat_at = utcnow() - timedelta(hours=2)
    db.commit()
    sent = []
    monkeypatch.setattr(maintenance, "_send", lambda kind, call_id, job_id: sent.append((kind, job_id)))
    assert maintenance.recover_stuck_jobs_now() == [job.id]
    assert sent == [("score", job.id)]


def test_settings_validation(admin_client):
    s = admin_client.get("/api/settings").json()
    assert s["review_score_threshold"] == 80
    r = admin_client.put("/api/settings", json={"review_score_threshold": 75, "stereo_agent_channel": "right"})
    assert r.status_code == 200 and r.json()["stereo_agent_channel"] == "right"
    assert admin_client.put("/api/settings", json={"review_confidence_threshold": 3}).status_code == 422
    audit = admin_client.get("/api/audit", params={"action": "settings"}).json()
    assert audit["total"] == 1


def test_audio_range_and_retention(admin_client, wav, db):
    from app.models import Call
    from app.services.retention import purge_expired_audio

    cid = _upload(admin_client, wav)
    full = admin_client.get(f"/api/calls/{cid}/audio")
    assert full.status_code == 200
    part = admin_client.get(f"/api/calls/{cid}/audio", headers={"Range": "bytes=10-19"})
    assert part.status_code == 206 and part.content == full.content[10:20]
    assert part.headers["content-range"].endswith(f"/{len(full.content)}")

    call = db.get(Call, __import__("uuid").UUID(cid))
    call.created_at = call.created_at - timedelta(days=91)
    db.commit()
    assert purge_expired_audio() == 1
    assert admin_client.get(f"/api/calls/{cid}/audio").status_code == 410
    assert admin_client.get(f"/api/calls/{cid}").json()["has_audio"] is False


@pytest.mark.parametrize("q,expected", [("Juma", 1), ("nobody", 0)])
def test_calls_filters(admin_client, tmp_path, q, expected):
    w = make_wav(tmp_path / "f.wav")
    admin_client.post("/api/calls/upload", files=[("files", ("f.wav", w.read_bytes(), "audio/wav"))],
                      data={"agent_name": "Juma", "queue": "Prepaid"})
    assert admin_client.get("/api/calls", params={"q": q}).json()["total"] == expected
    assert admin_client.get("/api/calls", params={"queue": "Other"}).json()["total"] == 0
