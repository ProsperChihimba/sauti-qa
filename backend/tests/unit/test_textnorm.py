import pytest

from app.services.textnorm import normalize_sw, number_to_swahili


@pytest.mark.parametrize("n,words", [
    (7, "saba"), (12, "kumi na mbili"), (40, "arobaini"), (99, "tisini na tisa"), (100, "mia moja"),
    (250, "mia mbili na hamsini"), (1000, "elfu moja"), (10000, "elfu kumi"), (1990, "elfu moja na mia tisa na tisini"),
    (150000, "laki moja na elfu hamsini"), (2500000, "milioni mbili na laki tano"),
])
def test_number_to_swahili(n, words):
    assert number_to_swahili(n) == words


def test_normalize_matches_spoken_and_written_forms():
    assert normalize_sw("Nimelipa Tsh 10,000/= jana!") == normalize_sw("nimelipa tsh elfu kumi jana")
    assert normalize_sw("Eeh, ndio... sawa.") == "ndiyo sawa"
    assert normalize_sw("Namba yangu ni [PHONE].") == "namba yangu ni"
    assert normalize_sw("piga 0754") == "piga sifuri saba tano nne"
    assert normalize_sw("M-Pesa yangu, data ya GB 5") == "m-pesa yangu data ya gb tano"
