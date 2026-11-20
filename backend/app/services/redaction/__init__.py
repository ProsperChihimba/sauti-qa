"""PII redaction for Swahili / English call transcripts.

Redacted before anything is stored:
  - Tanzanian phone numbers (+255 / 0 followed by 6xx/7xx), in digits or spoken
  - NIDA national ID numbers (20 digits, usually 8-5-5-2)
  - payment card numbers (13-19 digits passing the Luhn check)
  - account / reference numbers (long digit runs, default 7+ digits)
  - numbers dictated as words, in Swahili or English ("sifuri saba sita ...",
    "double seven"), including mixed words and digits
  - PINs / passwords mentioned after a keyword ("PIN yangu ni moja mbili tatu nne")
  - e-mail addresses

Kept on purpose (they matter for QA): money amounts ("shilingi elfu kumi",
"Tsh 10,000", "5000/="), dates, times, durations, bundle sizes and other short
numbers. Spoken numbers that use magnitude words (mia, elfu, laki, milioni)
are amounts, not identifiers, and are never redacted.

Only the redacted text is stored; the original values are never persisted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MIN_DIGITS = 7  # digit runs at least this long are treated as identifiers
PIN_MIN_DIGITS = 4

LABELS = {
    "phone": "[PHONE]",
    "nida": "[NIDA]",
    "card": "[CARD]",
    "account": "[ACCOUNT]",
    "number": "[NUMBER]",
    "pin": "[PIN]",
    "email": "[EMAIL]",
}

DIGIT_WORDS = {
    # Swahili
    "sifuri": 0, "sufuri": 0, "ziro": 0, "zero": 0,
    "moja": 1, "mbili": 2, "tatu": 3, "nne": 4, "tano": 5, "sita": 6, "saba": 7, "nane": 8, "tisa": 9,
    # English (code-switching)
    "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
}
TENS_WORDS = {
    "kumi": 10, "ishirini": 20, "thelathini": 30, "arobaini": 40, "hamsini": 50, "sitini": 60,
    "sabini": 70, "themanini": 80, "tisini": 90,
    "ten": 10, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90,
}
REPEAT_WORDS = {"double": 2, "dabo": 2, "triple": 3, "tripo": 3}
MAGNITUDE_WORDS = {"mia", "elfu", "laki", "milioni", "bilioni", "hundred", "thousand", "million", "billion"}
CONNECTORS = {"na", "and", "-", ","}
PIN_KEYWORDS = re.compile(r"\b(pin|nenosiri|nywila|password|namba\s+ya\s+siri|siri)\b", re.I)

PUNCT = ".,;:!?\"'()[]{}…"

MONEY_BEFORE = re.compile(r"(tsh|tzs|sh|shs|shilingi|bei|kiasi|gharama|salio|usd|\$)\.?\s*$", re.I)
MONEY_AFTER = re.compile(r"^\s*(/=|/-|=/|shilingi|tsh|tzs|bob|za\s+kitanzania)", re.I)

DATE_RE = re.compile(r"^(\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}[-./]\d{1,2}[-./]\d{2,4})$")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b")
# A digit run: digits possibly separated by single spaces / dashes / dots (not commas: "10,000" is money).
DIGIT_RUN_RE = re.compile(r"(?<![\w/])\+?\d(?:[\s\-.]?\d)+(?![\w/])")


@dataclass
class Span:
    start: int
    end: int
    type: str


@dataclass
class RedactionResult:
    text: str
    spans: list[Span] = field(default_factory=list)  # in the redacted text
    original_spans: list[Span] = field(default_factory=list)  # in the input text (never stored)

    @property
    def redacted(self) -> bool:
        return bool(self.spans)

    def as_json(self) -> list[dict]:
        return [{"type": s.type, "start": s.start, "end": s.end} for s in self.spans]


def luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def classify_digits(digits: str) -> str:
    d = digits.lstrip("+")
    if (len(d) == 10 and d[0] == "0" and d[1] in "67") or (len(d) == 12 and d.startswith("255") and d[3] in "67"):
        return "phone"
    if len(d) == 9 and d[0] in "67":
        return "phone"  # dialled without the leading 0
    if len(d) == 20:
        return "nida"
    if 13 <= len(d) <= 19 and luhn_ok(d):
        return "card"
    return "account"


def _is_money_context(text: str, start: int, end: int) -> bool:
    return bool(MONEY_BEFORE.search(text[max(0, start - 14): start]) or MONEY_AFTER.search(text[end: end + 20]))


def _pin_context(text: str, start: int) -> bool:
    return bool(PIN_KEYWORDS.search(text[max(0, start - 40): start]))


# ---------- spoken numbers ----------
_TOKEN_RE = re.compile(r"\S+")


def _core(tok: str) -> str:
    return tok.lower().strip(PUNCT)


def _token_kind(core: str) -> str | None:
    if core in DIGIT_WORDS:
        return "digit"
    if core in TENS_WORDS:
        return "tens"
    if core in REPEAT_WORDS:
        return "repeat"
    if core in MAGNITUDE_WORDS:
        return "magnitude"
    if core.isdigit():
        return "digits"
    if core in CONNECTORS:
        return "connector"
    return None


def _run_to_digits(cores: list[str]) -> str | None:
    """Convert a run of number tokens to a digit string, or None if it is an amount."""
    out: list[str] = []
    repeat = 1
    i = 0
    while i < len(cores):
        c = cores[i]
        k = _token_kind(c)
        if k == "magnitude":
            return None
        if k == "repeat":
            repeat = REPEAT_WORDS[c]
        elif k == "digit":
            out.append(str(DIGIT_WORDS[c]) * repeat)
            repeat = 1
        elif k == "digits":
            out.append(c * repeat if repeat > 1 and len(c) == 1 else c)
            repeat = 1
        elif k == "tens":
            val = TENS_WORDS[c]
            # "kumi na mbili" -> 12, "thelathini na tano" -> 35
            if i + 2 < len(cores) and cores[i + 1] in ("na", "and") and _token_kind(cores[i + 2]) == "digit":
                val += DIGIT_WORDS[cores[i + 2]]
                i += 2
            elif i + 1 < len(cores) and _token_kind(cores[i + 1]) == "digit" and c in ("twenty", "thirty", "forty",
                                                                                       "fifty", "sixty", "seventy",
                                                                                       "eighty", "ninety"):
                val += DIGIT_WORDS[cores[i + 1]]
                i += 1
            out.append(f"{val:02d}")
            repeat = 1
        i += 1
    return "".join(out)


def _spoken_number_spans(text: str) -> list[Span]:
    toks = [(m.start(), m.end(), m.group()) for m in _TOKEN_RE.finditer(text)]
    spans: list[Span] = []
    i = 0
    while i < len(toks):
        kind = _token_kind(_core(toks[i][2]))
        if kind not in ("digit", "tens", "repeat", "digits", "magnitude"):
            i += 1
            continue
        j = i
        last_num = i
        while j + 1 < len(toks):
            nk = _token_kind(_core(toks[j + 1][2]))
            if nk is None:
                break
            j += 1
            if nk != "connector":
                last_num = j
            # A sentence end inside the run ("... tano. Sita ...") breaks it.
            if toks[j - 1][2].rstrip()[-1:] in ".?!" and nk != "connector":
                last_num = j - 1
                j -= 1
                break
        cores = [_core(t[2]) for t in toks[i: last_num + 1]]
        has_words = any(_token_kind(c) in ("digit", "tens", "repeat") for c in cores)
        digits = _run_to_digits(cores)
        if has_words and digits:
            start = toks[i][0]
            end = toks[last_num][0] + len(toks[last_num][2].rstrip(PUNCT))
            if len(digits) >= MIN_DIGITS:
                kind_ = classify_digits(digits)
                spans.append(Span(start, end, "number" if kind_ == "account" else kind_))
            elif len(digits) >= PIN_MIN_DIGITS and _pin_context(text, start):
                spans.append(Span(start, end, "pin"))
        i = last_num + 1
    return spans


def _digit_spans(text: str) -> list[Span]:
    spans = []
    for m in DIGIT_RUN_RE.finditer(text):
        raw = m.group()
        digits = re.sub(r"\D", "", raw)
        start, end = m.start(), m.end()
        # Trailing dot belongs to the sentence.
        while end > start and text[end - 1] in ".-":
            end -= 1
        if DATE_RE.match(text[start:end]):
            continue
        if len(digits) >= MIN_DIGITS:
            if _is_money_context(text, start, end):
                continue
            spans.append(Span(start, end, classify_digits(digits)))
        elif len(digits) >= PIN_MIN_DIGITS and _pin_context(text, start) and not _is_money_context(text, start, end):
            spans.append(Span(start, end, "pin"))
    return spans


def _merge(spans: list[Span]) -> list[Span]:
    spans = sorted(spans, key=lambda s: (s.start, -s.end))
    out: list[Span] = []
    for s in spans:
        if out and s.start <= out[-1].end:
            if s.end > out[-1].end:
                out[-1].end = s.end
            continue
        out.append(Span(s.start, s.end, s.type))
    return out


def find_pii(text: str) -> list[Span]:
    spans = [Span(m.start(), m.end(), "email") for m in EMAIL_RE.finditer(text)]
    spans += _digit_spans(text)
    spans += _spoken_number_spans(text)
    return _merge(spans)


def redact(text: str) -> RedactionResult:
    spans = find_pii(text)
    if not spans:
        return RedactionResult(text)
    parts, new_spans, pos, shift = [], [], 0, 0
    for s in spans:
        parts.append(text[pos: s.start])
        label = LABELS[s.type]
        new_start = s.start + shift
        parts.append(label)
        new_spans.append(Span(new_start, new_start + len(label), s.type))
        shift += len(label) - (s.end - s.start)
        pos = s.end
    parts.append(text[pos:])
    return RedactionResult("".join(parts), new_spans, spans)


def redact_words(words: list[dict], original_text: str, result: RedactionResult) -> tuple[list[dict], list[tuple[float, float]]]:
    """Blank word-level timings that fall inside redacted spans.

    Returns the cleaned word list and the time spans to mute in the audio."""
    if not words or not result.original_spans:
        return words, []
    out, mute = [], []
    cursor = 0
    for w in words:
        token = str(w.get("text", "")).strip()
        idx = original_text.find(token, cursor) if token else -1
        if idx >= 0:
            w_start, w_end = idx, idx + len(token)
            cursor = w_end
        else:
            w_start = w_end = -1
        hit = next((s for s in result.original_spans if w_start >= 0 and w_start < s.end and w_end > s.start), None)
        if hit:
            out.append({**w, "text": LABELS[hit.type]})
            mute.append((float(w["start"]), float(w["end"])))
        else:
            out.append(w)
    return out, mute
