import json

from tests.conftest import make_wav


def _upload(client, tmp_path, name, variant, agent="Neema", queue="Prepaid", seconds=10):
    w = make_wav(tmp_path / f"{name}.wav", seconds=seconds, freq=300 + sum(map(ord, name)) * 3)
    files = [("files", (w.name, w.read_bytes(), "audio/wav")),
             ("files", (f"{name}.json", json.dumps({"mock_variant": variant, "agent_name": agent, "queue": queue}),
                        "application/json"))]
    return client.post("/api/calls/upload", files=files).json()["accepted"][0]["id"]


def test_review_queue_priority_and_claiming(admin_client, analyst_client, tmp_path):
    good = _upload(admin_client, tmp_path, "g1", "good")
    poor = _upload(admin_client, tmp_path, "p1", "poor", agent="Juma")
    esc = _upload(admin_client, tmp_path, "e1", "escalation", agent="Baraka")
    q = admin_client.get("/api/review/queue").json()
    ids = [c["id"] for c in q["items"]]
    assert good not in ids and ids[0] == poor and esc in ids  # auto-fail first

    first = analyst_client.post("/api/review/next").json()["call_id"]
    assert first == poor
    # A second analyst gets the next one, not the claimed call.
    second = admin_client.post("/api/review/next").json()["call_id"]
    assert second == esc
    assert admin_client.post(f"/api/calls/{poor}/review/claim").status_code == 200  # admins may take over


def test_override_edit_rescore_complete(analyst_client, tmp_path):
    cid = _upload(analyst_client, tmp_path, "p2", "poor")
    c = analyst_client.get(f"/api/calls/{cid}").json()
    assert c["evaluation"]["auto_fail"]

    # Override both critical failures -> live recalculation, no longer auto-fail.
    for crit in ("no_confidential_request", "accurate_information"):
        r = analyst_client.patch(f"/api/calls/{cid}/evaluation/items/{crit}",
                                 json={"answer": "yes", "reason": "Checked audio"})
        assert r.status_code == 200
    ev = r.json()
    assert not ev["auto_fail"] and ev["score"] > 0
    item = next(i for i in ev["items"] if i["criterion_id"] == "accurate_information")
    assert item["answer"] == "yes" and item["ai_answer"] == "no" and item["overridden_by_id"]

    bad = analyst_client.patch(f"/api/calls/{cid}/evaluation/items/greeting", json={"answer": "na"})
    assert bad.status_code == 400  # N/A not allowed

    # Correct a transcript line: agent greets properly. Numbers typed by the analyst are redacted.
    seg0 = c["segments"][0]
    r = analyst_client.patch(f"/api/calls/{cid}/segments/{seg0['id']}",
                             json={"text": "Habari, karibu Vodacom, jina langu ni Juma. Nikusaidie nini? Namba 0754123456"})
    seg = r.json()
    assert "[PHONE]" in seg["text"] and seg["asr_text"] == "Ndiyo, sema."
    analyst_client.patch(f"/api/calls/{cid}/segments/{c['segments'][1]['id']}", json={"speaker": "customer"})

    # Re-score from the corrected transcript: greeting now met, overrides kept.
    assert analyst_client.post(f"/api/calls/{cid}/rescore").status_code == 202
    c2 = analyst_client.get(f"/api/calls/{cid}").json()
    ev2 = c2["evaluation"]
    assert ev2["rev"] == 2 and ev2["trigger"] == "rescore"
    by = {i["criterion_id"]: i for i in ev2["items"]}
    assert by["greeting"]["answer"] == "yes" and by["self_introduction"]["answer"] == "yes"
    assert by["accurate_information"]["answer"] == "yes" and by["accurate_information"]["overridden_by_id"]
    assert not ev2["auto_fail"]

    # Notes, then mark reviewed and go to next.
    r = analyst_client.post(f"/api/calls/{cid}/notes", json={"body": "Coach on PIN policy", "kind": "coaching"})
    assert r.status_code == 201
    r = analyst_client.post(f"/api/calls/{cid}/review/complete", json={"note": "Reviewed with audio"})
    assert r.json() == {"next_call_id": None}
    c3 = analyst_client.get(f"/api/calls/{cid}").json()
    assert c3["review_status"] == "reviewed" and len(c3["notes"]) == 2

    hist = analyst_client.get(f"/api/calls/{cid}/history").json()
    assert [e["rev"] for e in hist["evaluations"]] == [2, 1]
    actions = {a["action"] for a in hist["audit"]}
    assert {"evaluation.override", "transcript.edit", "evaluation.rescore", "review.complete", "note.add"} <= actions


def test_swap_speakers(admin_client, tmp_path):
    cid = _upload(admin_client, tmp_path, "g2", "good")
    before = [s["speaker"] for s in admin_client.get(f"/api/calls/{cid}").json()["segments"]]
    after = [s["speaker"] for s in admin_client.post(f"/api/calls/{cid}/speakers/swap").json()]
    assert after == [{"agent": "customer", "customer": "agent"}[s] for s in before]


def test_scorecard_versioning(admin_client, analyst_client, tmp_path):
    cards = admin_client.get("/api/scorecards").json()
    assert len(cards) == 1 and cards[0]["is_active"] and cards[0]["version"] == 1
    d = cards[0]["definition"]
    d["criteria"][0]["weight"] = 7
    d["pass_threshold"] = 85
    assert analyst_client.put(f"/api/scorecards/{cards[0]['id']}", json={"definition": d}).status_code == 403
    r = admin_client.put(f"/api/scorecards/{cards[0]['id']}", json={"definition": d})
    v2 = r.json()
    assert v2["version"] == 2 and v2["is_active"] and v2["pass_threshold"] == 85
    cards = admin_client.get("/api/scorecards").json()
    assert [c["is_active"] for c in cards] == [True, False]

    d["criteria"].append(dict(d["criteria"][0]))  # duplicate id
    r = admin_client.post("/api/scorecards/validate", json={"definition": d})
    assert r.status_code == 422 and "Duplicate" in json.dumps(r.json())

    cid = _upload(admin_client, tmp_path, "g3", "good")
    ev = admin_client.get(f"/api/calls/{cid}").json()["evaluation"]
    assert ev["scorecard_version"] == 2

    r = admin_client.post(f"/api/scorecards/{cards[1]['id']}/activate")
    assert r.json()["is_active"]


def test_dashboard(admin_client, tmp_path):
    _upload(admin_client, tmp_path, "g4", "good", agent="Neema")
    _upload(admin_client, tmp_path, "p4", "poor", agent="Juma")
    _upload(admin_client, tmp_path, "e4", "escalation", agent="Baraka", queue="M-Pesa")
    d = admin_client.get("/api/dashboard").json()
    k = d["kpis"]
    assert k["calls_evaluated"] == 3 and k["critical_breaches"] == 1 and k["pending_review"] == 2
    assert k["minutes"] == 0.5 and k["pass_rate"] is not None
    assert d["criteria"][0]["pass_rate"] <= d["criteria"][-1]["pass_rate"]  # weakest first
    assert d["agents"][0]["agent"] == "Neema"
    assert {r["name"] for r in d["call_reasons"]} >= {"Data bundle"}
    assert sum(t["calls"] for t in d["trend"]) == 3
    only = admin_client.get("/api/dashboard", params={"queue": "M-Pesa"}).json()
    assert only["kpis"]["calls_evaluated"] == 1
