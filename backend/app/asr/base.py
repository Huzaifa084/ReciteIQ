"""ASREngine interface. Implementations: whisper_local (v1), cloud (stub)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass
class Transcript:
    text: str
    gated: bool          # True = rejected by the hallucination gate (D5); ignore text
    no_speech_prob: float
    avg_logprob: float
    compression_ratio: float
    asr_seconds: float   # wall time spent in inference


class ASREngine(ABC):
    @abstractmethod
    async def transcribe(self, audio: np.ndarray, duration: float) -> Transcript:
        """Transcribe one float32 16kHz mono segment. Must be safe to call from
        multiple sessions concurrently (implementations bound their own queue)."""
