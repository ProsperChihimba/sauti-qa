"""Heuristic stand-in for the LLM, used in tests and GPU/API-free demos.

It matches the scorecard's example phrases against the agent's lines. It is not a
real judge, but it exercises every code path (quotes, segment refs, N/A,
critical failures, flags, routing).
"""

from __future__ import annotations

import re
import unicodedata

from app.services.scoring.llm import LLMProvider
from app.services.scoring.scorecard import ScorecardDefinition
from app.services.speakers import heuristic_agent


def _norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9\[\] ]+", " ", s).split())


def _find(phrases: list[str], segs: list[dict]) -> dict | None:
    for seg in segs:
        t = _norm_text(seg["text"])
        for p in phrases:
            if _norm_text(p) and _norm_text(p) in t:
                return seg
    return None


REASONS = [
    (r"bando|data|internet|gb", "Data bundle"),
    (r"m-?pesa.*(rudish|kosea)|kosea kutuma|reversal", "M-Pesa reversal"),
    (r"m-?pesa|muamala", "M-Pesa transaction"),
    (r"zawadi|shinda|promo", "Prize / promotion enquiry"),
    (r"salio|vocha|airtime", "Airtime / balance"),
    (r"sim|puk", "SIM / PUK / SIM swap"),
    (r"mtandao|network", "Network / coverage"),
]


class MockLLM(LLMProvider):
    name = "mock"
    model = "mock-heuristic-scorer"

    def complete_json(self, prompt, schema, schema_name, max_tokens):  # pragma: no cover - not used
        raise NotImplementedError

    def evaluate(self, sc: ScorecardDefinition, segments: list[dict], meta: dict | None = None) -> dict:
        agent = [s for s in segments if s["speaker"] == "agent"] or segments
        customer = [s for s in segments if s["speaker"] == "customer"]
        results = []
        for c in sc.criteria:
            neg = _find(c.negative_examples, agent) if c.negative_examples else None
            pos = _find(c.examples, agent) if c.examples else None
            if neg:
                r = ("no", neg, "The agent used wording that breaks this criterion.", 0.9)
            elif pos:
                r = ("yes", pos, "The agent clearly did this.", 0.88)
            elif c.negative_examples:
                r = ("yes", None, "No breach of this criterion was found.", 0.8)
            elif c.allow_na:
                r = ("na", None, "This did not come up in the call.", 0.7)
            else:
                r = ("no", None, "The agent did not do this.", 0.62)
            answer, seg, why, conf = r
            results.append({"criterion_id": c.id, "answer": answer,
                            "evidence_quote": seg["text"] if seg else None,
                            "segment_idx": seg["idx"] if seg else None, "reasoning": why, "confidence": conf})

        all_text = " ".join(_norm_text(s["text"]) for s in segments)
        cust_text = " ".join(_norm_text(s["text"]) for s in customer)
        reason = next((label for pat, label in REASONS if re.search(pat, all_text)), "Other")
        if re.search(r"supervisor|nakuunganisha", all_text):
            resolution = "escalated"
        elif re.search(r"inafanya kazi|nimelirekebisha|imetatuliwa", all_text):
            resolution = "resolved"
        elif re.search(r"litashughulikiwa|nimefungua ombi", all_text):
            resolution = "partially_resolved"
        else:
            resolution = "unresolved"
        if re.search(r"huduma mbaya|nimechoka|hasira", cust_text):
            sentiment = "negative"
        elif re.search(r"asante sana|inafanya kazi", cust_text):
            sentiment = "positive"
        else:
            sentiment = "neutral"
        flags = []
        pin = _find(["PIN yako", "namba ya siri", "nenosiri", "OTP"], agent)
        if pin:
            flags.append({"type": "fraud", "description": "Agent asked the customer for a confidential PIN.",
                          "segment_idx": pin["idx"]})
        angry = _find(["supervisor", "huduma mbaya", "TCRA", "nitahama"], customer)
        if angry:
            flags.append({"type": "escalation_risk", "description": "Customer is unhappy and asked to escalate.",
                          "segment_idx": angry["idx"]})
        return {
            "criteria": results,
            "call_reason": reason,
            "resolution_status": resolution,
            "customer_sentiment": sentiment,
            "summary_sw": f"Mteja alipiga simu kuhusu: {reason}. Hali ya suluhisho: {resolution}.",
            "summary_en": f"The customer called about: {reason}. Resolution status: {resolution}.",
            "flags": flags,
        }

    def identify_agent(self, segments: list[dict]) -> dict:
        label, conf = heuristic_agent(segments)
        return {"agent_speaker": label or "", "confidence": conf, "reasoning": "keyword heuristic"}
