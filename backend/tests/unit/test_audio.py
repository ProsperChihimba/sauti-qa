import numpy as np

from app.services.audio import MAX_GAIN_DB, normalize_gain
from app.services.audio.vad import energy_vad


def _tone(amplitude: float, seconds: float = 2.0, sr: int = 16000) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    burst = (t % 1.0) < 0.6  # speech-like bursts with gaps
    return (amplitude * np.sin(2 * np.pi * 300 * t) * burst).astype(np.float32)


def test_quiet_call_is_found_after_gain():
    quiet = _tone(0.002)  # about -54 dBFS: below the energy VAD threshold
    assert energy_vad(quiet) == []
    assert energy_vad(normalize_gain(quiet))


def test_gain_is_capped_and_loud_audio_untouched():
    silent = _tone(1e-5)
    assert np.abs(normalize_gain(silent)).max() <= 1e-5 * 10 ** (MAX_GAIN_DB / 20) + 1e-6
    loud = _tone(0.8)
    assert np.array_equal(normalize_gain(loud), loud)
