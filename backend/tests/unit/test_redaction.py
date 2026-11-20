import pytest

from app.services.redaction import luhn_ok, redact, redact_words


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Namba yangu ni 0754 123 456.", "Namba yangu ni [PHONE]."),
        ("piga +255 754-123-456 sasa", "piga [PHONE] sasa"),
        ("namba 255712345678", "namba [PHONE]"),
        ("NIDA yangu ni 19900512-12345-00001-23", "NIDA yangu ni [NIDA]"),
        ("NIDA 19900512123450000123", "NIDA [NIDA]"),
        ("kadi 4111 1111 1111 1111 imekataliwa", "kadi [CARD] imekataliwa"),
        ("akaunti namba 01J1234567800", "akaunti namba 01J1234567800"),  # alphanumeric: left alone
        ("akaunti namba 0150123456789 ya CRDB", "akaunti namba [ACCOUNT] ya CRDB"),
        ("namba ni sifuri saba sita nne moja mbili tatu nne tano sita.",
         "namba ni [PHONE]."),
        ("ni zero seven five four, one two three, four five six", "ni [PHONE]"),
        ("sifuri 7 5 4 moja mbili tatu 4 5 6", "[PHONE]"),
        ("double seven five four one two three four five six", "[NUMBER]"),
        ("sifuri saba sita tano, kumi na mbili, thelathini na nne, hamsini na sita",
         "[PHONE]"),
        ("PIN yangu ni moja mbili tatu nne", "PIN yangu ni [PIN]"),
        ("password ni 4321", "password ni [PIN]"),
        ("tuma kwa juma.hassan@example.co.tz", "tuma kwa [EMAIL]"),
    ],
)
def test_redacts_identifiers(text, expected):
    assert redact(text).text == expected


@pytest.mark.parametrize(
    "text",
    [
        "Nimelipa shilingi elfu kumi jana.",
        "bando la GB tano kwa shilingi elfu kumi",
        "Tsh 1500000 zimekatwa",
        "nimetuma 2500000/= kwa wakala",
        "nimelipa 10,000 jana na 25,000 leo",
        "Ni tarehe kumi na mbili mwezi wa tano mwaka elfu moja mia tisa tisini.",
        "shilingi laki tano na elfu hamsini",
        "saa ishirini na nne",
        "nimepiga simu mara tatu leo, mara moja jana",
        "muamala wa 2026-11-19 saa 10",
        "elfu moja mia tisa tisini na tisa",
    ],
)
def test_keeps_amounts_dates_and_short_numbers(text):
    r = redact(text)
    assert r.text == text and not r.redacted


def test_spans_point_at_labels():
    r = redact("Simu 0754123456 na NIDA 19900512123450000123 sawa")
    assert [s.type for s in r.spans] == ["phone", "nida"]
    for s in r.spans:
        assert r.text[s.start:s.end].startswith("[")
    assert "0754" not in r.text


def test_word_timings_are_blanked_and_mute_spans_returned():
    text = "namba ni sifuri saba sita nne moja mbili tatu nne tano sita asante"
    words = [{"text": t, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, t in enumerate(text.split())]
    r = redact(text)
    cleaned, mute = redact_words(words, text, r)
    assert [w["text"] for w in cleaned][:2] == ["namba", "ni"]
    assert all(w["text"] == "[PHONE]" for w in cleaned[2:12])
    assert cleaned[-1]["text"] == "asante"
    assert len(mute) == 10 and mute[0] == (1.0, 1.4)


def test_luhn():
    assert luhn_ok("4111111111111111")
    assert not luhn_ok("4111111111111112")
