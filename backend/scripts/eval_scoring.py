#!/usr/bin/env python
"""Measure how well an LLM scores calls, against analyst answers.

Runs every case in evals/scoring/cases.yaml through the production scoring path
(prompt -> provider -> validate/repair -> score maths) and compares the result
with the expected analyst answers.

  python scripts/eval_scoring.py --provider mock
  python scripts/eval_scoring.py --provider anthropic                 # claude-sonnet-5-5
  python scripts/eval_scoring.py --provider openai --model Qwen/Qwen3-32B \
      --base-url http://vllm:8000/v1                                   # on-prem model

Reports criterion agreement (overall and per criterion), critical failures caught
and missed, false auto-fails, flags, resolution and sentiment accuracy, verbatim
evidence rate and repairs, plus every disagreement with the model's reasoning.
Writes results.json and report.md to --out.

Cloud providers receive the (synthetic, already-redacted) case transcripts only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402

from app.services.scoring.compute import compute_score  # noqa: E402
from app.services.scoring.scorecard import load_seed  # noqa: E402
from app.services.scoring.validate import validate_and_repair  # noqa: E402

CASES = Path(__file__).resolve().parents[1] / "evals" / "scoring" / "cases.yaml"
SPEAKERS = {"A": "agent", "C": "customer", "U": "unknown"}
GOOD_DEFAULTS = {
    "greeting": "yes", "self_introduction": "yes", "offer_help": "yes", "verification": "yes",
    "no_confidential_request": "yes", "probing": "yes", "empathy": "yes", "accurate_information": "yes",
    "resolution": "yes", "hold_etiquette": "na", "professional_language": "yes", "escalation_handling": "na",
    "further_assistance": "yes", "closing": "yes",
}


def norm_answer(v) -> str | None:
    if v is True:
        return "yes"
    if v is False:
        return "no"
    v = str(v).strip().lower()
    return v if v in ("yes", "no", "na") else None  # "?" and anything else: not scored


def load_cases(path: Path, only: list[str] | None) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = []
    for c in data["cases"]:
        if only and not any(c["id"].startswith(o) for o in only):
            continue
        expected = dict(GOOD_DEFAULTS) if c.get("defaults") == "good" else {}
        expected.update(c.get("expected") or {})
        c["expected_norm"] = {k: a for k, v in expected.items() if (a := norm_answer(v))}
        c["segments"] = [
            {"idx": i, "speaker": SPEAKERS[s], "speaker_raw": None, "start_s": i * 6.0, "end_s": i * 6.0 + 5.0,
             "text": t}
            for i, (s, t) in enumerate(c["lines"])
        ]
        cases.append(c)
    return cases


def build_provider(args):
    if args.provider == "mock":
        from app.services.scoring.mock_llm import MockLLM

        return MockLLM()
    if args.provider == "anthropic":
        from app.services.scoring.llm import AnthropicProvider

        return AnthropicProvider(args.model)
    if args.base_url:
        os.environ["LLM_OPENAI_BASE_URL"] = args.base_url
        from app.config import get_settings

        get_settings.cache_clear()
    from app.services.scoring.llm import OpenAICompatProvider

    return OpenAICompatProvider(args.model)


def run_case(provider, sc, case) -> dict:
    t0 = time.perf_counter()
    meta = {"speaker_method": "none"} if any(s["speaker"] == "unknown" for s in case["segments"]) else {}
    try:
        raw = provider.evaluate(sc, case["segments"], meta)
        error = None
    except Exception as exc:  # noqa: BLE001 - one failing case must not stop the run
        raw, error = None, f"{type(exc).__name__}: {exc}"
    v = validate_and_repair(raw, sc, case["segments"])
    score = compute_score(sc, v.items)
    return {"case": case, "raw": raw, "validated": v, "score": score, "error": error,
            "seconds": time.perf_counter() - t0}


def evaluate(results: list[dict], sc) -> dict:
    crit = sc.by_id()
    per_crit = defaultdict(lambda: {"n": 0, "agree": 0, "confusion": Counter()})
    disagreements = []
    critical_expected = critical_caught = false_autofail = 0
    flag_req = flag_hit = flag_forb = flag_false = 0
    res_n = res_ok = sent_n = sent_ok = 0
    quotes = not_verbatim = repaired_items = errors = 0
    low_conf_on_wrong = 0
    case_rows = []

    for r in results:
        c, v = r["case"], r["validated"]
        if r["error"]:
            errors += 1
        got = {i.criterion_id: i for i in v.items}
        exp = c["expected_norm"]
        agree = 0
        for cid, want in exp.items():
            it = got.get(cid)
            have = it.answer if it else "missing"
            pc = per_crit[cid]
            pc["n"] += 1
            pc["confusion"][f"{want}->{have}"] += 1
            if have == want:
                pc["agree"] += 1
                agree += 1
            else:
                low_conf_on_wrong += int(bool(it) and it.confidence < 0.6)
                disagreements.append({"case": c["id"], "criterion": cid, "expected": want, "got": have,
                                      "confidence": it.confidence if it else None,
                                      "quote": it.evidence_quote if it else None,
                                      "reasoning": it.reasoning if it else None})
        exp_autofail = any(exp.get(k) == "no" for k, cr in crit.items() if cr.critical)
        if exp_autofail:
            critical_expected += 1
            critical_caught += int(r["score"].auto_fail)
        elif r["score"].auto_fail and all(exp.get(k) == "yes" for k, cr in crit.items() if cr.critical):
            false_autofail += 1
        raised = {f["type"] for f in v.flags}
        for f in c.get("flags_required") or []:
            flag_req += 1
            flag_hit += int(f in raised)
        for f in c.get("flags_forbidden") or []:
            flag_forb += 1
            flag_false += int(f in raised)
        if c.get("resolution"):
            res_n += 1
            res_ok += int(v.resolution_status in c["resolution"])
        if c.get("sentiment"):
            sent_n += 1
            sent_ok += int(v.sentiment in c["sentiment"])
        for it in v.items:
            repaired_items += int(it.repaired)
            if it.evidence_quote:
                quotes += 1
        not_verbatim += sum(1 for m in v.repair_log if "not found verbatim" in m)
        case_rows.append({"case": c["id"], "agreement": f"{agree}/{len(exp)}", "score": r["score"].score,
                          "auto_fail": r["score"].auto_fail, "expected_auto_fail": exp_autofail,
                          "flags": sorted(raised), "resolution": v.resolution_status, "sentiment": v.sentiment,
                          "seconds": round(r["seconds"], 1), "error": r["error"], "repairs": len(v.repair_log)})

    total_n = sum(p["n"] for p in per_crit.values())
    total_agree = sum(p["agree"] for p in per_crit.values())
    pct = lambda a, b: round(100 * a / b, 1) if b else None  # noqa: E731
    return {
        "cases": len(results),
        "errors": errors,
        "criterion_agreement_pct": pct(total_agree, total_n),
        "criterion_labels": total_n,
        "critical_failures_caught": f"{critical_caught}/{critical_expected}",
        "false_auto_fails": false_autofail,
        "required_flags_raised": f"{flag_hit}/{flag_req}",
        "forbidden_flags_raised": f"{flag_false}/{flag_forb}",
        "resolution_accuracy_pct": pct(res_ok, res_n),
        "sentiment_accuracy_pct": pct(sent_ok, sent_n),
        "evidence_quotes": quotes,
        "evidence_verbatim_pct": pct(quotes - not_verbatim, quotes),
        "repaired_items": repaired_items,
        "wrong_answers_flagged_low_confidence": f"{low_conf_on_wrong}/{len(disagreements)}",
        "avg_seconds_per_call": round(sum(r["seconds"] for r in results) / max(len(results), 1), 1),
        "per_criterion": {
            cid: {"label": crit[cid].label, "critical": crit[cid].critical, "n": p["n"],
                  "agreement_pct": pct(p["agree"], p["n"]), "confusion": dict(p["confusion"])}
            for cid, p in sorted(per_crit.items(), key=lambda kv: (kv[1]["agree"] / kv[1]["n"], kv[0]))
        },
        "per_case": case_rows,
        "disagreements": disagreements,
    }


def markdown(summary: dict, provider_name: str, model: str) -> str:
    s = summary
    lines = [f"# Scoring evaluation: {provider_name} {model}", "",
             "| Metric | Result |", "|---|---|"]
    for key, label in [
        ("cases", "Cases"), ("errors", "Provider errors"),
        ("criterion_agreement_pct", "Criterion agreement with analyst (%)"),
        ("critical_failures_caught", "Critical failures caught"), ("false_auto_fails", "False auto-fails"),
        ("required_flags_raised", "Required flags raised"), ("forbidden_flags_raised", "Wrong flags raised"),
        ("resolution_accuracy_pct", "Resolution status accuracy (%)"),
        ("sentiment_accuracy_pct", "Sentiment accuracy (%)"),
        ("evidence_verbatim_pct", "Evidence quotes found verbatim (%)"), ("repaired_items", "Repaired answers"),
        ("wrong_answers_flagged_low_confidence", "Wrong answers with low confidence (would go to review)"),
        ("avg_seconds_per_call", "Average seconds per call"),
    ]:
        lines.append(f"| {label} | {s[key]} |")
    lines += ["", "## Per criterion (weakest first)", "", "| Criterion | Labels | Agreement | Mistakes |",
              "|---|---|---|---|"]
    for p in s["per_criterion"].values():
        mistakes = ", ".join(f"{k} x{n}" for k, n in p["confusion"].items() if k.split("->")[0] != k.split("->")[1])
        lines.append(f"| {p['label']}{' (critical)' if p['critical'] else ''} | {p['n']} | {p['agreement_pct']}% "
                     f"| {mistakes or '-'} |")
    lines += ["", "## Per case", "", "| Case | Agreement | Score | Auto-fail (expected) | Flags | Resolution | s |",
              "|---|---|---|---|---|---|---|"]
    for r in s["per_case"]:
        af = f"{'yes' if r['auto_fail'] else 'no'} ({'yes' if r['expected_auto_fail'] else 'no'})"
        lines.append(f"| {r['case']} | {r['agreement']} | {r['score']} | {af} | {', '.join(r['flags']) or '-'} "
                     f"| {r['resolution']} | {r['seconds']} |" + (f" ERROR {r['error']}" if r["error"] else ""))
    lines += ["", "## Disagreements", ""]
    for d in s["disagreements"]:
        lines.append(f"- **{d['case']} / {d['criterion']}**: expected {d['expected']}, got {d['got']} "
                     f"(confidence {d['confidence']}). {d['reasoning'] or ''}"
                     + (f" Quote: \"{d['quote']}\"" if d["quote"] else ""))
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", choices=["mock", "anthropic", "openai"], default="mock")
    ap.add_argument("--model", help="anthropic default claude-sonnet-5-5; required for openai")
    ap.add_argument("--base-url", help="OpenAI-compatible base URL (overrides LLM_OPENAI_BASE_URL)")
    ap.add_argument("--cases", default=str(CASES))
    ap.add_argument("--only", nargs="*", help="case id prefixes, e.g. C03 C04")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out", default="eval-results")
    args = ap.parse_args()

    sc = load_seed()
    cases = load_cases(Path(args.cases), args.only)
    provider = build_provider(args)
    print(f"Scoring {len(cases)} cases with {provider.name} {provider.model} ...", flush=True)
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        results = list(pool.map(lambda c: run_case(provider, sc, c), cases))
    summary = evaluate(results, sc)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    raw = [{"case": r["case"]["id"], "raw_output": r["raw"], "repair_log": r["validated"].repair_log}
           for r in results]
    (out / "results.json").write_text(json.dumps({"summary": summary, "raw": raw}, ensure_ascii=False, indent=2,
                                                 default=str), encoding="utf-8")
    report = markdown(summary, provider.name, provider.model)
    (out / "report.md").write_text(report, encoding="utf-8")
    print(report.split("## Per criterion")[0])
    print(f"Full report: {out / 'report.md'}")


if __name__ == "__main__":
    main()
