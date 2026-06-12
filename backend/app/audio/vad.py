"""Streaming VAD segmenter (D4).

Consumes 16kHz mono s16le PCM frames; yields segments cut either at natural
silence (`silence_cut_sec` of trailing non-speech) or at the hard cap
(`segment_max_sec`, with `segment_overlap_sec` carried into the next segment).
The hard cap is what keeps a fluent 60s breath-group from becoming one giant
laggy transcription. Silence cuts double as the "wait and listen" pause signal.
"""

from dataclasses import dataclass

import numpy as np
from silero_vad import VADIterator, load_silero_vad

from app.config import settings

_WINDOW = 512  # silero requirement at 16kHz


@dataclass
class Segment:
    audio: np.ndarray          # float32 mono 16kHz
    starts_with_overlap: bool  # True = begins with audio re-played from a forced cut
                               # -> detector must dedup leading duplicate words
    duration: float


class StreamSegmenter:
    def __init__(self):
        self._model = load_silero_vad()
        self._vad = VADIterator(
            self._model, threshold=settings.vad_threshold, sampling_rate=settings.sample_rate
        )
        self._buf = np.zeros(0, dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)
        self._speech_active = False
        self._had_speech = False
        self._silence_samples = 0
        self._starts_with_overlap = False  # state for the segment being built
        self._max_samples = int(settings.segment_max_sec * settings.sample_rate)
        self._overlap_samples = int(settings.segment_overlap_sec * settings.sample_rate)
        self._silence_cut = int(settings.silence_cut_sec * settings.sample_rate)

    def feed(self, pcm_s16le: bytes) -> list[Segment]:
        """Feed raw PCM bytes; return zero or more completed speech segments."""
        samples = np.frombuffer(pcm_s16le, dtype=np.int16).astype(np.float32) / 32768.0
        self._pending = np.concatenate([self._pending, samples])
        out: list[Segment] = []

        while len(self._pending) >= _WINDOW:
            window, self._pending = self._pending[:_WINDOW], self._pending[_WINDOW:]
            event = self._vad(window)
            if event is not None:
                if "start" in event:
                    self._speech_active = True
                    self._had_speech = True
                    self._silence_samples = 0
                elif "end" in event:
                    self._speech_active = False
            self._buf = np.concatenate([self._buf, window])
            self._silence_samples = 0 if self._speech_active else self._silence_samples + _WINDOW

            if self._had_speech and not self._speech_active and self._silence_samples >= self._silence_cut:
                out.append(self._cut(forced=False))
            elif len(self._buf) >= self._max_samples:
                if self._had_speech:
                    out.append(self._cut(forced=True))
                else:
                    self._buf = np.zeros(0, dtype=np.float32)  # drop pure silence
        return out

    def flush(self) -> Segment | None:
        """End of stream: emit whatever speech remains."""
        if self._had_speech and len(self._buf) > 0:
            return self._cut(forced=False)
        self._buf = np.zeros(0, dtype=np.float32)
        return None

    @property
    def in_silence(self) -> bool:
        return not self._speech_active

    def _cut(self, forced: bool) -> Segment:
        seg = Segment(
            audio=self._buf,
            starts_with_overlap=self._starts_with_overlap,
            duration=len(self._buf) / settings.sample_rate,
        )
        if forced:
            self._buf = self._buf[-self._overlap_samples :].copy()  # carry overlap forward
            self._starts_with_overlap = True
            self._had_speech = True  # the overlap may still contain speech
        else:
            self._buf = np.zeros(0, dtype=np.float32)
            self._starts_with_overlap = False
            self._had_speech = False
        self._silence_samples = 0
        return seg
