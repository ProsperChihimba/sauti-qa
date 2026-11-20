"""Swahili-aware text normalisation for WER/CER (benchmark and fine-tuning).

Both the reference and the hypothesis go through the same steps:
  lowercase, unify apostrophes, drop redaction tags and hesitation fillers,
  spell digits as Swahili words (so "10,000" == "elfu kumi"), map common
  spelling variants, strip punctuation, collapse whitespace.
"""

from __future__ import annotations

import re
import unicodedata

UNITS = ["", "moja", "mbili", "tatu", "nne", "tano", "sita", "saba", "nane", "tisa"]
TENS = ["", "kumi", "ishirini", "thelathini", "arobaini", "hamsini", "sitini", "sabini", "themanini", "tisini"]

FILLERS = {"eeh", "eh", "ehh", "aah", "ah", "ahh", "mmh", "mm", "mmm", "hmm", "uhm", "um", "uh", "ee", "aa"}
VARIANTS = {
    "ndio": "ndiyo", "sawasawa": "sawa sawa", "okay": "ok", "okey": "ok", "sorry": "samahani_en",
    "mpesa": "m-pesa", "mpeza": "m-pesa", "simu yako": "simu yako",
}
# "samahani_en" keeps English "sorry" distinct from Swahili; only unify true variants.
VARIANTS.pop("sorry")


def number_to_swahili(n: int) -> str:
    if n < 0:
        return "hasi " + number_to_swahili(-n)
    if n == 0:
        return "sifuri"
    if n < 10:
        return UNITS[n]
    if n < 100:
        t, u = divmod(n, 10)
        return TENS[t] + (f" na {UNITS[u]}" if u else "")
    for size, word in ((10**9, "bilioni"), (10**6, "milioni"), (10**5, "laki"), (1000, "elfu"), (100, "mia")):
        if n >= size:
            q, r = divmod(n, size)
            head = f"{word} {number_to_swahili(q)}"
            return head + (f" na {number_to_swahili(r)}" if r else "")
    return str(n)


def _digits_to_words(m: re.Match) -> str:
    raw = m.group(0).replace(",", "")
    if len(raw) > 1 and raw.startswith("0"):
        # Phone-style digit strings are read digit by digit.
        return " ".join("sifuri" if d == "0" else UNITS[int(d)] for d in raw)
    try:
        return number_to_swahili(int(raw))
    except ValueError:
        return raw


def normalize_sw(text: str, *, numbers: bool = True) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    t = t.replace("’", "'").replace("‘", "'").replace("`", "'")
    t = re.sub(r"\[(phone|nida|card|account|number|pin|email)\]", " ", t)
    t = re.sub(r"(\d+)\s*/=", r"\1", t)  # 5000/= -> 5000
    if numbers:
        t = re.sub(r"\d{1,3}(?:,\d{3})+|\d+", _digits_to_words, t)
    t = re.sub(r"[^\w\s'-]", " ", t)
    t = re.sub(r"(?<!\w)['-]|['-](?!\w)", " ", t)
    words = [VARIANTS.get(w, w) for w in t.split() if w not in FILLERS]
    return " ".join(" ".join(words).split())
