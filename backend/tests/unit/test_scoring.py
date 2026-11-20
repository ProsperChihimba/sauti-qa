from types import SimpleNamespace as NS

import pytest

from app.services.app_settings import defaults
from app.services.scoring.compute import compute_score
from app.services.scoring.llm import extract_json
from app.services.scoring.prompts import build_eval_prompt
from app.services.scoring.routing import review_reasons
from app.services.scoring.scorecard import Criterion, ScorecardDefinition, load_seed
from app.services.scoring.validate import validate_and_repair


def card(**kw):
    crit = [
        Criterion(id="greet", section="Opening", label="Greets", weight=10),
        Criterion(id="verify", section="Verification", label="Verifies", weight=20, allow_na=True),
        Criterion(id="no_pin", section="Compliance", label="No PIN", weight=30, critical=True),
        Criterion(id="close", section="Closing", label="Closes", weight=40),
    ]
    return ScorecardDefinition(name="t", pass_threshold=kw.get("threshold", 80), criteria=crit)


def items(**answers):
    return [NS(criterion_id=k, answer=v, confidence=0.9) for k, v in answers.items()]


# ---------- score maths ----------
def test_all_yes_is_100():
    r = compute_score(card(), items(greet="yes", verify="yes", no_pin="yes", close="yes"))
    assert (r.score, r.points_earned, r.points_applicable, r.passed) == (100.0, 100, 100, True)


def test_na_is_excluded_from_denominator():
    r = compute_score(card(), items(greet="no", verify="na", no_pin="yes", close="yes"))
    assert r.points_applicable == 80 and r.points_earned == 70
    assert r.score == 87.5 and r.passed


def test_below_threshold_fails():
    r = compute_score(card(), items(greet="yes", verify="no", no_pin="yes", close="no"))
    assert r.score == 40.0 and not r.passed and not r.auto_fail


def test_critical_no_is_auto_fail_with_zero_score():
    r = compute_score(card(), items(greet="yes", verify="yes", no_pin="no", close="yes"))
    assert r.auto_fail and r.score == 0 and not r.passed and r.failed_critical == ["no_pin"]


def test_nothing_applicable_is_unscorable():
    c = ScorecardDefinition(name="t", criteria=[Criterion(id="a", section="s", label="a", weight=1, allow_na=True)])
    r = compute_score(c, items(a="na"))
    assert r.score is None and not r.passed


def test_unknown_criteria_are_ignored():
    r = compute_score(card(), items(greet="yes", verify="yes", no_pin="yes", close="yes", bogus="no"))
    assert r.score == 100


# ---------- validation / repair ----------
SEGS = [
    {"idx": 0, "speaker": "agent", "text": "Habari za asubuhi, karibu Vodacom, naitwa Neema.", "start_s": 0},
    {"idx": 1, "speaker": "customer", "text": "Nina tatizo na bando langu.", "start_s": 3},
    {"idx": 2, "speaker": "agent", "text": "Asante kwa kupiga simu Vodacom, kwaheri.", "start_s": 6},
]


def good_raw():
    return {
        "criteria": [
            {"criterion_id": "greet", "answer": "yes", "evidence_quote": "karibu Vodacom", "segment_idx": 0,
             "reasoning": "ok", "confidence": 0.9},
            {"criterion_id": "verify", "answer": "na", "evidence_quote": None, "segment_idx": None,
             "reasoning": "no account access", "confidence": 0.8},
            {"criterion_id": "no_pin", "answer": "yes", "evidence_quote": None, "segment_idx": None,
             "reasoning": "none", "confidence": 0.95},
            {"criterion_id": "close", "answer": "yes", "evidence_quote": "Asante kwa kupiga simu Vodacom",
             "segment_idx": 2, "reasoning": "ok", "confidence": 0.9},
        ],
        "call_reason": "Data bundle", "resolution_status": "resolved", "customer_sentiment": "positive",
        "summary_sw": "Muhtasari", "summary_en": "Summary", "flags": [],
    }


def test_valid_output_passes_through_unchanged():
    v = validate_and_repair(good_raw(), card(), SEGS)
    assert v.repair_log == []
    assert [i.answer for i in v.items] == ["yes", "na", "yes", "yes"]
    assert v.items[3].segment_idx == 2 and v.sentiment == "positive"


def test_missing_invalid_and_disallowed_na_are_repaired():
    raw = good_raw()
    raw["criteria"] = [
        {"criterion_id": "greet", "answer": "maybe", "confidence": 0.9},
        {"criterion_id": "close", "answer": "na", "confidence": 0.9},  # N/A not allowed
        {"criterion_id": "GREET", "answer": "no", "confidence": 0.9},  # duplicate (case-insensitive)
        {"criterion_id": "made_up", "answer": "yes", "confidence": 1},
    ]
    v = validate_and_repair(raw, card(), SEGS)
    by = {i.criterion_id: i for i in v.items}
    assert by["greet"].answer == "no" and by["greet"].repaired and by["greet"].confidence == 0
    assert by["close"].answer == "no" and by["close"].repaired
    assert by["verify"].repaired and by["no_pin"].repaired  # missing
    assert any("made_up" in m for m in v.repair_log)
    assert any("duplicate" in m for m in v.repair_log)


def test_segment_references_are_fixed_from_quotes():
    raw = good_raw()
    raw["criteria"][0]["segment_idx"] = 99  # does not exist
    raw["criteria"][3]["segment_idx"] = 0  # wrong segment, quote is in 2
    v = validate_and_repair(raw, card(), SEGS)
    by = {i.criterion_id: i for i in v.items}
    assert by["greet"].segment_idx == 0
    assert by["close"].segment_idx == 2
    assert by["close"].confidence == 0.9  # verbatim quote: no penalty


def test_paraphrased_quote_caps_confidence():
    raw = good_raw()
    raw["criteria"][0]["evidence_quote"] = "Good morning, welcome to Vodacom"  # translated, not verbatim
    v = validate_and_repair(raw, card(), SEGS)
    assert v.items[0].confidence == 0.5
    assert any("not found verbatim" in m for m in v.repair_log)


def test_confidence_and_enums_are_normalised():
    raw = good_raw()
    raw["criteria"][0]["confidence"] = 85  # percent
    raw["criteria"][1]["confidence"] = "high"
    raw["resolution_status"] = "Partially Resolved"
    raw["customer_sentiment"] = "angry"
    raw["flags"] = [{"type": "FRAUD", "description": "x", "segment_idx": 7}, "junk"]
    v = validate_and_repair(raw, card(), SEGS)
    assert v.items[0].confidence == 0.85
    assert v.items[1].confidence == 0 and v.items[1].repaired
    assert v.resolution_status == "partially_resolved" and v.sentiment == "neutral"
    assert v.flags == [{"type": "fraud", "description": "x", "segment_idx": None}]


def test_garbage_output_routes_everything_to_review():
    v = validate_and_repair({"oops": True}, card(), SEGS)
    assert all(i.repaired and i.answer == "no" for i in v.items)
    r = compute_score(card(), v.items)
    reasons = review_reasons(r, v.items, v.flags, defaults(), v.repair_log)
    assert {"auto_fail", "low_confidence", "repaired_output"} <= set(reasons)


@pytest.mark.parametrize("text", [
    '```json\n{"a": 1}\n```', '<think>hmm {"no": 1}</think>{"a": 1}', 'Here you go: {"a": 1} done',
])
def test_extract_json(text):
    assert extract_json(text) == {"a": 1}


# ---------- routing ----------
def test_routing_reasons():
    cfg = defaults()
    sc = card()
    ok = items(greet="yes", verify="yes", no_pin="yes", close="yes")
    assert review_reasons(compute_score(sc, ok), ok, [], cfg) == []
    assert review_reasons(compute_score(sc, ok), ok, [{"type": "escalation_risk"}], cfg) == ["flag:escalation_risk"]
    low = items(greet="yes", verify="yes", no_pin="yes", close="yes")
    low[0].confidence = 0.3
    assert review_reasons(compute_score(sc, low), low, [], cfg) == ["low_confidence"]
    bad = items(greet="no", verify="no", no_pin="yes", close="yes")
    assert review_reasons(compute_score(sc, bad), bad, [], cfg) == ["low_score"]
    cfg2 = cfg.model_copy(update={"review_on_flags": False})
    assert review_reasons(compute_score(sc, ok), ok, [{"type": "fraud"}], cfg2) == []


# ---------- prompt ----------
def test_prompt_contains_rules_and_scorecard():
    p = build_eval_prompt(load_seed(), SEGS, {"queue": "Prepaid"})
    for needle in ("Judge only the AGENT", "Do not penalise the agent for transcription errors",
                   "lower the confidence", "VERBATIM", "criterion_id: no_confidential_request", "CRITICAL"):
        assert needle in p.system
    assert "[0] AGENT (00:00): Habari" in p.user and "Queue: Prepaid" in p.user
