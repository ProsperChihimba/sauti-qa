"""End-to-end with mock ASR + mock LLM:
upload -> transcribe -> score -> override -> re-score -> review -> Excel export -> dataset export."""

import csv
import io
import json
import zipfile

from openpyxl import load_workbook

from tests.conftest import make_wav


def _upload(client, tmp_path, name, variant, agent, stereo=False, seconds=12):
    w = make_wav(tmp_path / f"{name}.wav", seconds=seconds, stereo=stereo, freq=200 + sum(map(ord, name)) * 3)
    meta = {"mock_variant": variant, "agent_name": agent, "queue": "Prepaid", "external_id": f"REC-{name}",
            "call_time": "2026-11-18T09:30:00"}
    files = [("files", (w.name, w.read_bytes(), "audio/wav")),
             ("files", (f"{name}.json", json.dumps(meta), "application/json"))]
    r = client.post("/api/calls/upload", files=files)
    assert r.status_code == 200 and r.json()["accepted"], r.text
    return r.json()["accepted"][0]["id"]


def _export(client, kind, **extra):
    r = client.post("/api/exports", json={"kind": kind, "filters": {"date_from": "2026-11-18", "date_to": "2026-11-18"},
                                          **extra})
    assert r.status_code == 202, r.text
    ex = client.get(f"/api/exports/{r.json()['id']}").json()
    assert ex["status"] == "succeeded", ex
    dl = client.get(f"/api/exports/{ex['id']}/download")
    assert dl.status_code == 200
    return ex, dl.content


def test_full_flow(admin_client, tmp_path):
    c = admin_client
    good = _upload(c, tmp_path, "good1", "good", "Neema")
    poor = _upload(c, tmp_path, "poor1", "poor", "Juma")
    esc = _upload(c, tmp_path, "esc1", "escalation", "Baraka", stereo=True)

    # Transcribed + scored automatically.
    for cid in (good, poor, esc):
        assert c.get(f"/api/calls/{cid}").json()["status"] == "done"

    # Analyst picks the most urgent call.
    nxt = c.post("/api/review/next").json()["call_id"]
    assert nxt == poor
    call = c.get(f"/api/calls/{poor}").json()

    # Correct the transcript (two lines) and override one answer.
    seg0, seg2 = call["segments"][0], call["segments"][2]
    c.patch(f"/api/calls/{poor}/segments/{seg0['id']}",
            json={"text": "Ndiyo, karibu Vodacom, jina langu ni Juma. Nikusaidie vipi?"})
    c.patch(f"/api/calls/{poor}/segments/{seg2['id']}", json={"text": "Aah sijui, labda. Nipe namba yako tafadhali."})
    ev = c.patch(f"/api/calls/{poor}/evaluation/items/empathy", json={"answer": "yes", "reason": "Tone was kind"}).json()
    assert next(i for i in ev["items"] if i["criterion_id"] == "empathy")["overridden_by_id"]

    # Re-score from the corrected transcript.
    assert c.post(f"/api/calls/{poor}/rescore").status_code == 202
    ev2 = c.get(f"/api/calls/{poor}").json()["evaluation"]
    assert ev2["rev"] == 2
    by = {i["criterion_id"]: i for i in ev2["items"]}
    assert by["greeting"]["answer"] == "yes" and by["empathy"]["answer"] == "yes"
    assert ev2["auto_fail"]  # still asked for the PIN: stays a critical failure

    # Review, note, next.
    r = c.post(f"/api/calls/{poor}/review/complete", json={"note": "Escalate to team lead: PIN request"})
    assert r.json()["next_call_id"] == esc
    c.post(f"/api/calls/{esc}/review/complete", json={"next": False})

    # Excel export.
    ex, content = _export(c, "excel")
    assert ex["stats"]["calls"] == 3
    wb = load_workbook(io.BytesIO(content))
    assert wb.sheetnames == ["Summary", "Agents", "Criteria", "Details"]
    s = wb["Summary"]
    assert s["A1"].value == "Call Quality Assurance Report"
    kv = {s.cell(row=r, column=1).value: s.cell(row=r, column=2).value for r in range(1, 30)}
    assert kv["Calls evaluated"] == 3 and kv["Critical breaches (auto-fail)"] == 1 and kv["Reviewed by analysts"] == 2
    d = wb["Details"]
    headers = [cell.value for cell in d[1]]
    for h in ("Call ID", "Failed items", "Muhtasari (Kiswahili)", "Summary (English)", "Reviewer notes",
              "Greets with brand" if False else "Professional greeting with brand"):
        assert h in headers
    rows = {r[0]: dict(zip(headers, r, strict=False)) for r in d.iter_rows(min_row=2, values_only=True)}
    p = rows["REC-poor1"]
    assert p["Result"] == "Auto-fail" and "Never asks for PIN" in p["Critical failures"]
    assert "PIN request" in p["Reviewer notes"] and p["Reviewed by"] == "Admin"
    assert "Shows empathy: N -> Y" in p["Overridden items"]
    assert rows["REC-good1"]["Result"] == "Pass" and rows["REC-good1"]["Professional greeting with brand"] == "Y"
    assert wb["Agents"].max_row == 4

    # CSV export.
    _, csv_bytes = _export(c, "csv")
    reader = list(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig"))))
    assert len(reader) == 3 and "summary_sw" in reader[0]

    # Dataset export: only corrected lines, never redacted ones.
    ex, z = _export(c, "dataset", test_fraction=0.0)
    assert ex["stats"]["clips"] == 2
    zf = zipfile.ZipFile(io.BytesIO(z))
    meta = [json.loads(line) for line in zf.read("train/metadata.jsonl").decode().splitlines()]
    assert {m["transcription"] for m in meta} == {
        "Ndiyo, karibu Vodacom, jina langu ni Juma. Nikusaidie vipi?", "Aah sijui, labda. Nipe namba yako tafadhali."}
    assert all(m["file_name"] in zf.namelist() or f"train/{m['file_name']}" in zf.namelist() for m in meta)
    wav = zf.read(f"train/{meta[0]['file_name']}")
    assert wav[:4] == b"RIFF" and len(wav) > 16000  # at least ~0.5 s of 16 kHz 16-bit audio
    assert "README.md" in zf.namelist()

    # Every human action is in the audit log.
    actions = {a["action"] for a in c.get("/api/audit", params={"page_size": 200}).json()["items"]}
    assert {"transcript.edit", "evaluation.override", "evaluation.rescore", "review.complete", "export.excel",
            "export.dataset", "export.download"} <= actions


def test_analyst_cannot_export_dataset(analyst_client):
    r = analyst_client.post("/api/exports", json={"kind": "dataset"})
    assert r.status_code == 403
