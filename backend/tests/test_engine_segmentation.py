"""The segmentation window must follow the ASR engine, and stay overridable.

Shipping FastConformer on the Whisper window is a silent, expensive mistake:
measured on the release gate, 5s windows slice words at the boundary and produce
five false MISSED_WORDs across six clean recitations where 25s windows produce
none. Nothing in the code would have complained.
"""

import pytest

from app.config import Settings


def test_whisper_keeps_short_windows():
    s = Settings(asr_engine="whisper_local")
    assert (s.segment_max_sec, s.silence_cut_sec) == (5.0, 0.7)


def test_fastconformer_gets_long_windows():
    s = Settings(asr_engine="fastconformer")
    assert (s.segment_max_sec, s.silence_cut_sec) == (25.0, 0.5)


@pytest.mark.parametrize("field,value", [("segment_max_sec", 8.0), ("silence_cut_sec", 0.9)])
def test_an_explicit_setting_always_wins(field, value):
    s = Settings(asr_engine="fastconformer", **{field: value})
    assert getattr(s, field) == value


def test_env_override_is_respected(monkeypatch):
    """The operator's env var must beat the engine default — this is the knob
    the rollback runbook uses."""
    monkeypatch.setenv("RECITEIQ_SEGMENT_MAX_SEC", "7.5")
    s = Settings(asr_engine="fastconformer")
    assert s.segment_max_sec == 7.5
