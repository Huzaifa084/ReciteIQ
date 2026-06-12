"""Streaming VAD segmenter (D4).

VAD = vendored silero ONNX model via onnxruntime directly — the silero-vad pip
package hard-imports torch (2.4GB) for a 2MB model; we only need per-window
speech probability, which is one ONNX session call.

Consumes 16kHz mono s16le PCM frames; yields segments cut either at natural
silence (`silence_cut_sec` of trailing non-speech) or at the hard cap
(`segment_max_sec`, with `segment_overlap_sec` carried into the next segment).
The hard cap is what keeps a fluent 60s breath-group from becoming one giant
laggy transcription. Silence cuts double as the "wait and listen" pause signal.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort

from app.config import settings

_WINDOW = 512  # silero requirement at 16kHz
_CONTEXT = 64  # silero v5+: each window must be prefixed with the previous window's tail
_HYSTERESIS = 0.15  # speech ends below (threshold - this), like silero's min_silence logic


class OnnxVAD:
    """Minimal streaming wrapper: feed 512-sample float32 windows, get P(speech)."""

    def __init__(self):
        path = Path(settings.asr_model_path).parent / "silero_vad.onnx"
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self._sess = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros(_CONTEXT, dtype=np.float32)

    def prob(self, window: np.ndarray) -> float:
        x = np.concatenate([self._context, window.astype(np.float32)]).reshape(1, -1)
        out, self._state = self._sess.run(
            None,
            {
                "input": x,
                "state": self._state,
                "sr": np.array(settings.sample_rate, dtype=np.int64),
            },
        )
        self._context = x[0, -_CONTEXT:]
        return float(out[0][0])


@dataclass
class Segment:
    audio: np.ndarray          # float32 mono 16kHz
    starts_with_overlap: bool  # True = begins with audio re-played from a forced cut
                               # -> detector must dedup leading duplicate words
    duration: float


class StreamSegmenter:
    def __init__(self):
        self._vad = OnnxVAD()
        self._buf = np.zeros(0, dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)
        self._speech_active = False
        self._had_speech = False
        self._silence_samples = 0
        self._starts_with_overlap = False  # state for the segment being built
        self._quiet_pos = -1               # sample offset in _buf of the latest low-prob window end
        self._max_samples = int(settings.segment_max_sec * settings.sample_rate)
        self._overlap_samples = int(settings.segment_overlap_sec * settings.sample_rate)
        self._silence_cut = int(settings.silence_cut_sec * settings.sample_rate)
        self._quiet_lookback = int(1.5 * settings.sample_rate)  # smart-cut search window

    def feed(self, pcm_s16le: bytes) -> list[Segment]:
        """Feed raw PCM bytes; return zero or more completed speech segments."""
        samples = np.frombuffer(pcm_s16le, dtype=np.int16).astype(np.float32) / 32768.0
        self._pending = np.concatenate([self._pending, samples])
        out: list[Segment] = []

        while len(self._pending) >= _WINDOW:
            window, self._pending = self._pending[:_WINDOW], self._pending[_WINDOW:]
            p = self._vad.prob(window)
            if p >= settings.vad_threshold:
                self._speech_active = True
                self._had_speech = True
            elif p < settings.vad_threshold - _HYSTERESIS:
                self._speech_active = False

            self._buf = np.concatenate([self._buf, window])
            if p < settings.vad_threshold - _HYSTERESIS:
                self._quiet_pos = len(self._buf)  # candidate word-boundary for smart cuts
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
        cut_at = len(self._buf)
        smart = False
        if forced and self._quiet_pos >= len(self._buf) - self._quiet_lookback and self._quiet_pos > self._overlap_samples:
            # Smart cut: slice at the most recent low-probability window — a
            # likely word boundary — instead of blindly mid-speech. Slicing a
            # word in half makes Whisper drop it on BOTH sides, which is how a
            # correctly-recited word ends up flagged as missed (live-caught:
            # الرحيم under slow tajweed recitation).
            cut_at = self._quiet_pos
            smart = True
        seg = Segment(
            audio=self._buf[:cut_at],
            starts_with_overlap=self._starts_with_overlap,
            duration=cut_at / settings.sample_rate,
        )
        if forced:
            if smart:
                # clean boundary: keep the remainder, no replayed overlap
                self._buf = self._buf[cut_at:].copy()
                self._starts_with_overlap = False
            else:
                self._buf = self._buf[-self._overlap_samples :].copy()  # carry overlap forward
                self._starts_with_overlap = True
            self._had_speech = True  # the remainder may still contain speech
        else:
            self._buf = np.zeros(0, dtype=np.float32)
            self._starts_with_overlap = False
            self._had_speech = False
        self._quiet_pos = -1
        self._silence_samples = 0
        return seg
