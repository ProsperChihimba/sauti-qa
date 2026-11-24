"""The scoring evaluation set and harness stay valid."""

import importlib.util
from pathlib import Path

from app.services.scoring.scorecard import load_seed

ROOT = Path(__file__).resolve().parents[2]


def _harness():
    spec = importlib.util.spec_from_file_location("eval_scoring", ROOT / "scripts" / "eval_scoring.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cases_reference_real_criteria_and_valid_answers():
    h = _harness()
    sc = load_seed()
    ids = set(sc.by_id())
    cases = h.load_cases(h.CASES, None)
    assert len(cases) >= 30
    for c in cases:
        assert set(c["expected_norm"]) <= ids, c["id"]
        for cid, ans in c["expected_norm"].items():
            assert ans != "na" or sc.by_id()[cid].allow_na, f"{c['id']}: {cid} cannot be N/A"
        assert all(s["speaker"] in ("agent", "customer", "unknown") for s in c["segments"])


def test_harness_runs_end_to_end_with_mock():
    from app.services.scoring.mock_llm import MockLLM

    h = _harness()
    sc = load_seed()
    cases = h.load_cases(h.CASES, ["C01", "C03", "C05"])
    summary = h.evaluate([h.run_case(MockLLM(), sc, c) for c in cases], sc)
    assert summary["cases"] == 3 and summary["errors"] == 0
    assert summary["critical_failures_caught"] == "1/1"  # C03 asks for the PIN
    assert summary["forbidden_flags_raised"].startswith("1/")  # mock's keyword fraud flag on C05: a real trap
    assert "Scoring evaluation" in h.markdown(summary, "mock", "m")
