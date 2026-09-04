"""NeMo FastConformer engine (Quran-fine-tuned, RNN-T/CTC hybrid).

Chosen on measurement, not reputation. On six real amateur recitations by one
reciter it transcribed 289/299 words (mean WER 0.0443, CER 0.0120) — better than
its authors' published 0.079 on *professional* qari clips — and, critically, it
transcribes what was SPOKEN rather than what was expected:

  Az-Zalzalah 2  اثقالها -> spoken زلسالها -> transcribed زلسالها
                 (a word that occurs nowhere in the Qur'an)
  Az-Zalzalah 4  اخبارها -> spoken اثقالها -> transcribed اثقالها
                 (context makes the expected word overwhelmingly predictable)

See docs/gate-deliberate-errors.md. A recogniser that repairs mistakes is
useless here: the system can only flag what the model is willing to report.

Uses NeMo's `transcribe()` deliberately. A direct
preprocess -> encoder -> RNN-T decode path was implemented and benchmarked to
remove its per-call manifest/dataloader overhead, and **it was rejected**: warm,
it is 0.71-1.00x the speed of `transcribe()` at 4/10/20/30 s windows (never
faster) and it changes the recognised text (WER 0.10-0.38 against the
`transcribe()` output), failing the equivalence criterion. The overhead that
motivated it turned out to be a measurement artifact of an unpinned thread budget
on a contended box. See docs/fastconformer-ops.md.

Same contract as whisper_local — one shared model, bounded queue, backpressure
rather than unbounded pile-up. NeMo has no `no_speech_prob` / `avg_logprob`, so
those Transcript fields carry neutral values and the hallucination gate that
depends on them is inert for this engine (it exists for Whisper's failure mode,
which an RNN-T without a language-model decoder does not share).
"""

import asyncio
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

from app.asr.base import ASREngine, Transcript
from app.config import settings


class FastConformerEngine(ASREngine):
    def __init__(self):
        from huggingface_hub import hf_hub_download
        from nemo.collections.asr.models import ASRModel

        import torch

        # Pin the thread budget the same way whisper_local does. Measured: with
        # threads unset and the box contended, a 4s window took 2.70s; pinned and
        # warm it takes 584ms (RTF 0.146). The earlier figure was a measurement
        # artifact, not a property of the engine.
        torch.set_num_threads(settings.asr_cpu_threads)

        path = hf_hub_download(repo_id=settings.fastconformer_repo,
                               filename=settings.fastconformer_checkpoint)
        self._model = ASRModel.restore_from(path, map_location="cpu")
        self._model.eval()
        # transcribe() sets these internally per call; setting them once is
        # harmless and keeps behaviour explicit. dither injects noise.
        self._model.preprocessor.featurizer.dither = 0.0
        self._model.preprocessor.featurizer.pad_to = 0
        self._sem = asyncio.Semaphore(settings.asr_queue_max)
        # NeMo's transcribe() is not re-entrant on a shared model; serialise it.
        self._lock = asyncio.Lock()

    async def transcribe(self, audio: np.ndarray, duration: float) -> Transcript:
        if duration < settings.asr_min_segment_sec:
            return Transcript("", True, 0.0, 0.0, 0.0, 0.0)
        if self._sem.locked():
            # queue full — shed rather than stall the session (same policy as whisper)
            return Transcript("", True, 0.0, 0.0, 0.0, 0.0)
        async with self._sem:
            t0 = time.perf_counter()
            text = await asyncio.to_thread(self._transcribe_sync, audio)
            return Transcript(text, False, 0.0, 0.0, 0.0, time.perf_counter() - t0)

    def _transcribe_sync(self, audio: np.ndarray) -> str:
        # NeMo's transcribe() takes paths, so the segment goes to a temp wav that
        # is deleted immediately — audio is never persisted (privacy D10).
        pcm = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "seg.wav"
            with wave.open(str(p), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(settings.sample_rate)
                w.writeframes(pcm.tobytes())
            out = self._model.transcribe([str(p)], batch_size=1, verbose=False)[0]
        return out.text if hasattr(out, "text") else str(out)


_engine: FastConformerEngine | None = None


def get_engine() -> FastConformerEngine:
    global _engine
    if _engine is None:
        _engine = FastConformerEngine()
    return _engine
