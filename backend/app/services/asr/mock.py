"""Mock ASR: returns a realistic Swahili customer-care dialogue (with code-switching,
spoken phone numbers and money amounts) so the whole platform runs without a GPU.

The dialogue variant is chosen by call metadata `mock_variant` (good / poor /
escalation) or deterministically from the call id.
"""

from __future__ import annotations

import hashlib

import numpy as np

from app.services.asr.base import ASRContext, ASRProvider, ASRSegment, Region, Word

A, C = "agent", "customer"

DIALOGUES: dict[str, list[tuple[str, str]]] = {
    "good": [
        (A, "Habari za asubuhi, karibu Vodacom, naitwa Neema. Nikusaidie nini leo?"),
        (C, "Habari dada. Nina tatizo na bando langu la internet, nililipia jana lakini halifanyi kazi."),
        (A, "Pole sana kwa usumbufu huo. Naomba majina yako kamili na namba yako ya simu tafadhali."),
        (C, "Naitwa Juma Hassan, namba ni sifuri saba sita nne moja mbili tatu nne tano sita."),
        (A, "Asante bwana Juma. Kwa usalama, naomba unithibitishie tarehe yako ya kuzaliwa."),
        (C, "Ni tarehe kumi na mbili mwezi wa tano mwaka elfu moja mia tisa tisini."),
        (A, "Asante kwa kuthibitisha. Naona ulinunua bando la GB tano kwa shilingi elfu kumi jana saa nne usiku."),
        (C, "Ndiyo exactly, lakini data haifanyi kazi kabisa since jana."),
        (A, "Nimeona tatizo, bando halikuwa activated vizuri kwenye system. Nimelirekebisha sasa hivi, tafadhali jaribu."),
        (C, "Sawa ngoja nijaribu. Eeh, sasa inafanya kazi."),
        (A, "Vizuri sana. Kuna kingine chochote naweza kukusaidia nacho leo?"),
        (C, "Hapana, ni hicho tu. Asante sana."),
        (A, "Asante kwa kupiga simu Vodacom, uwe na siku njema. Kwaheri."),
    ],
    "poor": [
        (A, "Ndiyo, sema."),
        (C, "Habari, nimetumiwa ujumbe kwamba nimeshinda zawadi ya shilingi laki tano, ni kweli?"),
        (A, "Aah sijui, labda. Nipe namba yako."),
        (C, "Ni 0754 123 456."),
        (A, "Ok, na PIN yako ya M-Pesa ili nihakikishe akaunti."),
        (C, "PIN yangu? Ni moja mbili tatu nne."),
        (A, "Sawa, utapokea zawadi yako baadaye. Kitu kingine?"),
        (C, "Hapana."),
    ],
    "escalation": [
        (A, "Karibu Vodacom, naitwa Baraka, nikusaidie vipi?"),
        (C, "Nimekosea kutuma pesa M-Pesa, shilingi elfu hamsini kwa namba isiyo sahihi, nataka zirudishwe sasa hivi!"),
        (A, "Pole sana kwa hilo. Naomba namba uliyotuma kwayo na muda wa muamala."),
        (C, "Nimetuma kwa sifuri saba moja tano tisa nane saba sita tano nne tatu, saa tatu asubuhi."),
        (A, "Asante. Nimeona muamala. Nitaufungua ombi la kurudisha pesa, litashughulikiwa ndani ya saa ishirini na nne."),
        (C, "Saa ishirini na nne? Hii ni huduma mbaya sana, nataka kuongea na supervisor wako."),
        (A, "Naelewa hasira yako bwana. Nitakuunganisha na supervisor, tafadhali subiri kidogo."),
        (C, "Haraka basi, nimechoka na hii network yenu."),
        (A, "Samahani kwa kukusubirisha, nakuunganisha sasa. Asante kwa uvumilivu wako."),
    ],
}

VARIANTS = list(DIALOGUES)


def pick_variant(ctx: ASRContext) -> str:
    v = (ctx.meta or {}).get("mock_variant")
    if v in DIALOGUES:
        return v
    h = int(hashlib.sha256(ctx.call_id.encode()).hexdigest(), 16)
    return VARIANTS[h % len(VARIANTS)]


def timeline(ctx: ASRContext) -> list[tuple[float, float, str, str]]:
    """(start, end, role, text) spread evenly across the call duration."""
    lines = DIALOGUES[pick_variant(ctx)]
    dur = max(ctx.duration, 0.1 * len(lines))
    step = dur / len(lines)
    return [(round(i * step, 2), round((i + 0.92) * step, 2), role, text) for i, (role, text) in enumerate(lines)]


def _words(text: str, start: float, end: float) -> list[Word]:
    toks = text.split()
    step = (end - start) / max(len(toks), 1)
    return [Word(t, round(start + i * step, 3), round(start + (i + 1) * step, 3), 0.9) for i, t in enumerate(toks)]


class MockASR(ASRProvider):
    name = "mock"
    model_id = "mock-swahili-dialogue"

    def transcribe(self, audio: np.ndarray, regions: list[Region], ctx: ASRContext, sr: int = 16000):
        out = []
        for i, (start, end, role, text) in enumerate(timeline(ctx)):
            if ctx.role and role != ctx.role:
                continue
            conf = 0.72 + 0.2 * ((i * 7) % 5) / 4  # deterministic 0.72-0.92
            out.append(ASRSegment(start, end, text, round(conf, 3), _words(text, start, end)))
        return out
