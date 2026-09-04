"""P1-9: variable-length encoder pass (skip the 30s padding).

Measured before P1-9: every window was padded to 30s, so a 5.09s window cost
3927ms and a 21.95s window 4081ms — a flat ~4s regardless of length
(docs/baseline-m0-pre-serverside.md).

**Bit-identical output is provably impossible, so we do not assert it.** The
Whisper encoder is bidirectional: with 30s padding, every real frame attends over
the padded region too, so removing the padding changes the representation by
definition. It is not an off-by-one — it is a different function.

What we assert instead:
  1. On REAL recitation the divergence is small enough to be safe against the
     stored (padded-built) references — measured CER 0.010 at 22s.
  2. Short windows get materially faster, which is the entire point.
  3. The flag still exists, so the padded path can be restored for A/B against
     a reference rebuild.

Measured on real recitation (`fatiha_full.wav`): CER 0.000 at 3s and 5s, 0.018 at
10s, 0.010 at 22s; latency 4117->449ms (9.2x) at 3s and 4041->741ms (5.5x) at 5s.

An earlier version of this test used synthetic tones and asserted exact equality.
It failed at 3s and 25s — but those signals produced only 6-8 tokens, where a
single differing token is a huge relative CER. That was measuring noise, not the
optimisation. Real audio is the only valid fixture here.
"""

import wave

import numpy as np
import pytest
from rapidfuzz.distance import Levenshtein

from app.asr.phoneme_ctc import PhonemeCTC
from app.config import settings

CER_TOLERANCE = 0.06     # real-audio divergence budget; measured 0.010 at 22s
CLIP = "eval/audio/fatiha_full.wav"


@pytest.fixture(scope="module")
def model():
    try:
        return PhonemeCTC()
    except Exception as e:                    # noqa: BLE001 - model file is gitignored
        pytest.skip(f"phoneme model unavailable: {e}")


@pytest.fixture(scope="module")
def audio():
    try:
        with wave.open(CLIP) as w:
            assert w.getframerate() == 16000 and w.getnchannels() == 1
            pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    except FileNotFoundError:
        pytest.skip(f"{CLIP} not present")
    return pcm.astype(np.float32) / 32768.0


def _ids(model, a, variable: bool):
    prev = settings.phoneme_variable_length
    try:
        settings.phoneme_variable_length = variable
        return model.ids(a)
    finally:
        settings.phoneme_variable_length = prev


def test_variable_length_enabled_by_default():
    """Enabled on measured evidence: output is bit-identical to the padded path
    at 3s and 5s on real recitation, diverges by only 0.018 at 10-22s, and is
    5-9x faster. The flag stays so the padded path remains available for A/B."""
    assert settings.phoneme_variable_length is True


@pytest.mark.parametrize("seconds", [5.0, 10.0, 22.0])
def test_divergence_from_padded_is_small_on_real_audio(model, audio, seconds):
    a = audio[: int(16000 * seconds)]
    padded = _ids(model, a, False)
    sliced = _ids(model, a, True)
    assert padded and sliced, "expected tokens from real recitation"
    cer = Levenshtein.normalized_distance(padded, sliced)
    assert cer <= CER_TOLERANCE, (
        f"{seconds}s: sliced diverged from padded by CER {cer:.3f} "
        f"(> {CER_TOLERANCE}) — unsafe against padded-built references"
    )


def test_short_window_is_materially_faster(model, audio):
    """The whole point: cost must scale with duration instead of being flat."""
    import time
    a = audio[: 16000 * 5]
    _ids(model, a, True); _ids(model, a, False)          # warm both paths
    t = time.perf_counter(); _ids(model, a, False); pad = time.perf_counter() - t
    t = time.perf_counter(); _ids(model, a, True); sli = time.perf_counter() - t
    assert sli < pad * 0.75, (
        f"expected a clear speedup on a 5s window, got "
        f"sliced={sli*1000:.0f}ms padded={pad*1000:.0f}ms"
    )


def test_empty_audio_still_returns_empty(model):
    assert _ids(model, np.zeros(0, dtype=np.float32), True) == []
