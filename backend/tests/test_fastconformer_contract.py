"""FastConformer engine contract — no NeMo required.

The model itself is validated by the six-Surah and deliberate-error gates
(docs/experiment-fastconformer-six-surahs.md, docs/gate-deliberate-errors.md).
What is tested here is the wrapper: serialisation, failure recovery, shedding,
and the privacy rule that a segment never outlives its own call.
"""

import asyncio

import numpy as np
import pytest

from app.asr.fastconformer import FastConformerEngine
from app.config import settings


class _FakeModel:
    """Stands in for the NeMo model; records concurrency and can be made to fail."""

    def __init__(self):
        self.inflight = 0
        self.max_inflight = 0
        self.paths_seen: list[str] = []
        self.fail_next = 0

    def transcribe(self, paths, batch_size=1, verbose=False):
        self.paths_seen.append(paths[0])
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            import time
            time.sleep(0.05)
            if self.fail_next > 0:
                self.fail_next -= 1
                raise RuntimeError("inference blew up")
            return ["نص"]
        finally:
            self.inflight -= 1


def _engine() -> FastConformerEngine:
    """Build the wrapper without loading NeMo (restore_from takes ~15 s / 1.2 GB)."""
    e = object.__new__(FastConformerEngine)
    e._model = _FakeModel()
    e._sem = asyncio.Semaphore(settings.asr_queue_max)
    e._lock = asyncio.Lock()
    return e


def _audio(seconds: float = 3.0) -> np.ndarray:
    return np.zeros(int(seconds * settings.sample_rate), dtype=np.float32)


@pytest.mark.asyncio
async def test_inference_is_serialised():
    """NeMo transcribe() is not re-entrant on a shared model."""
    e = _engine()
    await asyncio.gather(*(e.transcribe(_audio(), 3.0) for _ in range(4)))
    assert e._model.max_inflight == 1


@pytest.mark.asyncio
async def test_failed_inference_releases_the_lock():
    """One exploding window must not wedge the session for every later one."""
    e = _engine()
    e._model.fail_next = 1
    with pytest.raises(RuntimeError):
        await e.transcribe(_audio(), 3.0)
    assert not e._lock.locked()
    t = await e.transcribe(_audio(), 3.0)
    assert t.text == "نص"


@pytest.mark.asyncio
async def test_failed_inference_releases_the_queue_slot():
    e = _engine()
    e._model.fail_next = 1
    with pytest.raises(RuntimeError):
        await e.transcribe(_audio(), 3.0)
    assert not e._sem.locked()


@pytest.mark.asyncio
async def test_short_segment_is_dropped_without_touching_the_model():
    e = _engine()
    t = await e.transcribe(_audio(0.05), settings.asr_min_segment_sec / 2)
    assert t.text == ""
    assert t.gated is True
    assert not e._model.paths_seen


@pytest.mark.asyncio
async def test_temp_audio_never_outlives_the_call():
    """Privacy D10: the segment wav is deleted with its TemporaryDirectory."""
    import os
    e = _engine()
    await e.transcribe(_audio(), 3.0)
    assert e._model.paths_seen
    for p in e._model.paths_seen:
        assert not os.path.exists(p)
