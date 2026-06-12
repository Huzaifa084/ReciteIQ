"""faster-whisper engine: ONE shared model, bounded global queue (decision 9/12).

Inference runs in a small thread pool (`num_workers` threads against the shared
CTranslate2 model, each inference capped at `cpu_threads`). The bounded queue
applies backpressure: when the box is saturated, sessions wait — they do not
pile up unbounded work.

Hallucination gate (D5): segments failing no_speech/logprob/compression checks
are returned with gated=True and never reach the aligner.
"""

import asyncio
import time

import numpy as np

from app.asr.base import ASREngine, Transcript
from app.config import settings


class WhisperLocalEngine(ASREngine):
    def __init__(self):
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            settings.asr_model_path,
            device="cpu",
            compute_type=settings.asr_compute_type,
            cpu_threads=settings.asr_cpu_threads,
            num_workers=settings.asr_num_workers,
        )
        self._sem = asyncio.Semaphore(settings.asr_queue_max)
        self._pool_sem = asyncio.Semaphore(settings.asr_num_workers)

    async def transcribe(self, audio: np.ndarray, duration: float) -> Transcript:
        if duration < settings.asr_min_segment_sec:
            return Transcript("", True, 1.0, 0.0, 0.0, 0.0)
        if self._sem.locked():
            # Queue full — drop with gated=True rather than stall the session
            return Transcript("", True, 1.0, 0.0, 0.0, 0.0)
        async with self._sem, self._pool_sem:
            return await asyncio.to_thread(self._run, audio)

    def _run(self, audio: np.ndarray) -> Transcript:
        t0 = time.perf_counter()
        segments, _info = self._model.transcribe(
            audio,
            language="ar",
            beam_size=1,
            condition_on_previous_text=False,  # D5: no cross-segment hallucination seeding
            vad_filter=False,                  # we already segment upstream
        )
        texts, nsp, alp, cr = [], 0.0, 0.0, 0.0
        n = 0
        for seg in segments:
            texts.append(seg.text)
            nsp = max(nsp, seg.no_speech_prob)
            alp += seg.avg_logprob
            cr = max(cr, seg.compression_ratio)
            n += 1
        avg_logprob = alp / n if n else -10.0
        gated = (
            n == 0
            or nsp > settings.asr_no_speech_prob_max
            or avg_logprob < settings.asr_avg_logprob_min
            or cr > settings.asr_compression_ratio_max
        )
        return Transcript(
            text=" ".join(texts).strip(),
            gated=gated,
            no_speech_prob=nsp,
            avg_logprob=avg_logprob,
            compression_ratio=cr,
            asr_seconds=time.perf_counter() - t0,
        )


_engine: WhisperLocalEngine | None = None


def get_engine() -> WhisperLocalEngine:
    global _engine
    if _engine is None:
        _engine = WhisperLocalEngine()
    return _engine
