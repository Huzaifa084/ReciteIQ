"""Encoder-CTC phoneme/ID recognizer (Whisper-small encoder + CTC head).

Approach A: emits a stream of model token IDs (NOT words, NOT human phonemes).
No autoregressive decoder → cannot hallucinate text. Used both offline (reference
batch) and live (v1 ≤30s windows). Built from config + local checkpoint — no
network at runtime.

v1 constraint: a single forward pass covers Whisper's 30s window; callers must
keep windows ≤30s (no long-form stitcher yet — see plan D4).
"""

import threading

import numpy as np
import torch

from app.config import settings

_BLANK = 0  # CTC blank id (verified empirically in Phase 0.5)
_SR = 16000
_WIN_SAMPLES = 30 * _SR  # Whisper pads/truncates to 30s

# whisper-small encoder dims (hardcoded so we never need openai/whisper-small at runtime)
_WHISPER_SMALL = dict(
    vocab_size=51865, num_mel_bins=80, d_model=768, encoder_layers=12,
    encoder_attention_heads=12, encoder_ffn_dim=3072, max_source_positions=1500,
)


class PhonemeCTC:
    def __init__(self, ckpt_path: str | None = None):
        from transformers import WhisperConfig, WhisperFeatureExtractor, WhisperModel

        torch.set_num_threads(settings.asr_cpu_threads)
        path = ckpt_path or settings.phoneme_model_path
        sd = torch.load(path, map_location="cpu", weights_only=False)
        enc_sd = {k[len("encoder."):]: v for k, v in sd.items() if k.startswith("encoder.")}
        self._ctc_w = sd["ctc_head.weight"]
        self._ctc_b = sd["ctc_head.bias"]

        cfg = WhisperConfig(**_WHISPER_SMALL)
        enc = WhisperModel(cfg).encoder
        missing, unexpected = enc.load_state_dict(enc_sd, strict=False)
        if missing or unexpected:
            raise RuntimeError(f"encoder load mismatch: missing={missing} unexpected={unexpected}")
        enc.eval()
        self._enc = enc
        self._fe = WhisperFeatureExtractor(feature_size=80, sampling_rate=_SR, hop_length=160,
                                           chunk_length=30, n_fft=400)
        self._lock = threading.Lock()  # one shared model; serialize forward passes

    def ids(self, audio: np.ndarray) -> list[int]:
        """float32 16k mono (≤30s) → collapsed token-ID sequence."""
        if len(audio) == 0:
            return []
        audio = audio[: _WIN_SAMPLES]  # v1: hard 30s cap
        feats = self._fe(audio, sampling_rate=_SR, return_tensors="pt").input_features
        with self._lock, torch.no_grad():
            h = self._enc(feats).last_hidden_state
            logits = h @ self._ctc_w.T + self._ctc_b
        raw = torch.argmax(logits, dim=-1)[0].tolist()
        n_real = max(1, round(len(audio) / _SR / 30 * len(raw)))
        return collapse(raw[:n_real])


def collapse(ids: list[int], blank: int = _BLANK) -> list[int]:
    out, prev = [], None
    for i in ids:
        if i != prev and i != blank:
            out.append(i)
        prev = i
    return out


_model: PhonemeCTC | None = None


def get_phoneme_ctc() -> PhonemeCTC:
    global _model
    if _model is None:
        _model = PhonemeCTC()
    return _model
