"""Cloud ASR engine — deliberate stub (plan: 'cut from v1').

The interface slot exists so a GPU/cloud engine can be swapped in via
RECITEIQ_ASR_ENGINE without touching the pipeline. Generic cloud STT
underperforms Quran-tuned local models on tajweed recitation; the real
fallback ladder is tiny -> base -> small locally.
"""

import numpy as np

from app.asr.base import ASREngine, Transcript


class CloudEngine(ASREngine):
    async def transcribe(self, audio: np.ndarray, duration: float) -> Transcript:
        raise NotImplementedError("Cloud ASR is not implemented in v1")
