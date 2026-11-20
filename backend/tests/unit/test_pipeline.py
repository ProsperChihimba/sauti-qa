import json

from tests.conftest import make_wav


def _upload(client, path, **meta):
    files = [("files", (path.name, path.read_bytes(), "audio/wav"))]
    if meta:
        files.append(("files", (path.stem + ".json", json.dumps(meta), "application/json")))
    r = client.post("/api/calls/upload", files=files)
    assert r.status_code == 200, r.text
    return r.json()["accepted"][0]["id"]


def test_mono_good_call_end_to_end(admin_client, tmp_path):
    cid = _upload(admin_client, make_wav(tmp_path / "good.wav", seconds=12), mock_variant="good")
    c = admin_client.get(f"/api/calls/{cid}").json()
    assert c["status"] == "done", c["error"]
    assert c["channels"] == 1 and c["duration_s"] == 12 and c["speech_s"] > 0
    assert c["speaker_method"] == "llm"  # the (mock) LLM identified the agent speaker
    segs = c["segments"]
    assert segs[0]["speaker"] == "agent" and segs[1]["speaker"] == "customer"
    # Phone number spoken in Swahili words was redacted before storage; money kept.
    phone = next(s for s in segs if "[PHONE]" in s["text"])
    assert "sifuri saba" not in phone["text"] and phone["has_redaction"]
    assert any("shilingi elfu kumi" in s["text"] for s in segs)
    ev = c["evaluation"]
    assert ev["score"] == 100 and ev["passed"] and not ev["auto_fail"]
    assert ev["call_reason"] == "Data bundle" and ev["resolution_status"] == "resolved"
    assert c["review_status"] == "not_required"
    greet = next(i for i in ev["items"] if i["criterion_id"] == "greeting")
    assert greet["answer"] == "yes" and greet["segment_idx"] == 0
    assert c["scorecard"]["criteria"]


def test_poor_call_is_auto_failed_and_flagged(admin_client, tmp_path):
    cid = _upload(admin_client, make_wav(tmp_path / "poor.wav", seconds=8), mock_variant="poor")
    c = admin_client.get(f"/api/calls/{cid}").json()
    ev = c["evaluation"]
    assert ev["auto_fail"] and ev["score"] == 0
    assert {f["type"] for f in ev["flags"]} == {"fraud"}
    assert c["review_status"] == "pending"
    assert "auto_fail" in c["review_reasons"] and "flag:fraud" in c["review_reasons"]
    # The PIN and phone digits never reach storage.
    texts = " ".join(s["text"] for s in c["segments"])
    assert "0754" not in texts and "[PHONE]" in texts and "[PIN]" in texts


def test_stereo_uses_channels_for_speakers(admin_client, tmp_path):
    w = make_wav(tmp_path / "st.wav", seconds=9, stereo=True)
    cid = _upload(admin_client, w, mock_variant="escalation", agent_channel="right")
    c = admin_client.get(f"/api/calls/{cid}").json()
    assert c["channels"] == 2 and c["speaker_method"] == "stereo"
    first = c["segments"][0]
    assert first["speaker"] == "agent" and first["speaker_raw"] == "channel_right"
    assert all(s["speaker"] in ("agent", "customer") for s in c["segments"])
    ev = c["evaluation"]
    assert ev["resolution_status"] == "escalated"
    assert "flag:escalation_risk" in c["review_reasons"]


def test_unreadable_audio_fails_permanently(admin_client, tmp_path):
    p = tmp_path / "junk.wav"
    p.write_bytes(b"RIFF" + b"\0" * 100)
    cid = admin_client.post("/api/calls/upload", files=[("files", ("junk.wav", p.read_bytes()))]).json()["accepted"][0]["id"]
    c = admin_client.get(f"/api/calls/{cid}").json()
    assert c["status"] == "failed" and "prepare" in c["error"]


def test_llm_speaker_identification_used_when_available(admin_client, tmp_path, monkeypatch):
    from app.services.scoring.mock_llm import MockLLM

    monkeypatch.setattr(MockLLM, "identify_agent",
                        lambda self, segs: {"agent_speaker": "SPEAKER_00", "confidence": 0.9, "reasoning": "x"})
    cid = _upload(admin_client, make_wav(tmp_path / "g.wav", seconds=10), mock_variant="good")
    c = admin_client.get(f"/api/calls/{cid}").json()
    assert c["speaker_method"] == "llm" and c["segments"][0]["speaker"] == "agent"


def test_vad_regions_respect_model_window():
    """Models without timestamp tokens get shorter regions, one transcript line each."""
    from app.services.audio.vad import merge_regions

    regions = merge_regions([(0.0, 40.0)], duration=40.0, max_len=12.0)
    assert all(b - a <= 12.0 for a, b in regions)
    assert regions[0][0] == 0.0 and regions[-1][1] == 40.0


def test_asr_presets_carry_model_card_options():
    from app.services.asr import PRESET_OPTIONS, PRESETS

    assert PRESETS["buzzasr"] == "BuzzASR/swahili"
    assert PRESET_OPTIONS["buzzasr"]["language"] is None  # language is baked into its generation config
    assert PRESET_OPTIONS["buzzasr"]["generate_kwargs"]["no_repeat_ngram_size"] == 3
