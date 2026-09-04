"""Encoder-CTC phoneme/ID recognizer (Whisper-small encoder + CTC head).

Approach A: emits a stream of model token IDs (NOT words, NOT human phonemes).
No autoregressive decoder → cannot hallucinate text. Used both offline (reference
batch) and live (v1 ≤30s windows). Built from config + local checkpoint — no
network at runtime.

v1 constraint: a single forward pass covers Whisper's 30s window; callers must
keep windows ≤30s (no long-form stitcher yet — see plan D4).
"""

import threading
from typing import NamedTuple

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


class PhonemeResult(NamedTuple):
    """Recognition output plus the confidence the CTC head already computed.

    `c_ctc` is a HEURISTIC, not a calibrated probability: it is the mean posterior
    of the winning class over the frames that survived collapsing. Nothing is
    fitted against observed correctness (that is plan task P2-3), so it must not
    be described as calibrated.
    """
    ids: list[int]
    c_ctc: float                # mean posterior over emitted tokens, 0..1
    token_conf: list[float]     # per-emitted-token posterior
    blank_frac: float           # share of frames the model called blank


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

    def _encode(self, feats: torch.Tensor) -> torch.Tensor:
        """Encoder forward over ONLY the frames that carry audio (P1-9).

        `WhisperEncoder.forward` hard-requires exactly 3000 mel frames and adds
        all 1500 positional embeddings, so a shorter input cannot be passed to it.
        We therefore drive the encoder's own submodules and slice the positions to
        match — same weights, same maths, just fewer time steps. Measured before
        this: a 5s window cost the same ~4s as a 22s one, because every window was
        padded to 30s (see docs/baseline-m0-pre-serverside.md).
        """
        enc = self._enc
        x = torch.nn.functional.gelu(enc.conv1(feats))
        x = torch.nn.functional.gelu(enc.conv2(x))
        x = x.permute(0, 2, 1)                      # (1, n_out, d_model)
        n = x.shape[1]
        pos = enc.embed_positions.weight[:n]
        if n > pos.shape[0]:                        # never expected; fail loudly
            raise ValueError(f"encoder got {n} positions, model has {pos.shape[0]}")
        x = x + pos
        for layer in enc.layers:
            x = layer(x, None)
        return enc.layer_norm(x)

    def ids(self, audio: np.ndarray) -> list[int]:
        """float32 16k mono (≤30s) → collapsed token-ID sequence."""
        return self.recognize(audio).ids

    def recognize(self, audio: np.ndarray) -> PhonemeResult:
        """float32 16k mono (≤30s) → IDs + CTC posterior confidence (P0-3)."""
        if len(audio) == 0:
            return PhonemeResult([], 0.0, [], 1.0)
        audio = audio[: _WIN_SAMPLES]  # v1: hard 30s cap
        feats = self._fe(audio, sampling_rate=_SR, return_tensors="pt").input_features
        if settings.phoneme_variable_length:
            # Trim the padded mel frames to the real audio, rounded UP to an even
            # count so conv2's stride-2 downsampling lands exactly. 100 frames/sec.
            n_mel = min(feats.shape[-1], int(np.ceil(len(audio) / _SR * 100)))
            n_mel = max(2, n_mel + (n_mel % 2))
            feats = feats[..., :n_mel]
        with self._lock, torch.no_grad():
            h = self._encode(feats) if settings.phoneme_variable_length \
                else self._enc(feats).last_hidden_state
            logits = h @ self._ctc_w.T + self._ctc_b
            probs = torch.softmax(logits, dim=-1)
            conf, cls = probs.max(dim=-1)
        raw = cls[0].tolist()
        frame_conf = conf[0].tolist()
        if not settings.phoneme_variable_length:
            n_real = max(1, round(len(audio) / _SR / 30 * len(raw)))
            raw, frame_conf = raw[:n_real], frame_conf[:n_real]
        return _collapse_with_conf(raw, frame_conf)


def _collapse_with_conf(raw: list[int], frame_conf: list[float]) -> PhonemeResult:
    """CTC collapse that also averages each emitted token's frame posteriors."""
    ids: list[int] = []
    token_conf: list[float] = []
    run: list[float] = []
    prev = None
    blanks = 0
    for i, c in zip(raw, frame_conf):
        if i == _BLANK:
            blanks += 1
        if i != prev and i != _BLANK:
            ids.append(i)
            if run:
                token_conf.append(sum(run) / len(run))
            run = [c]
        elif i == prev and i != _BLANK:
            run.append(c)
        prev = i
    if run:
        token_conf.append(sum(run) / len(run))
    c_ctc = sum(token_conf) / len(token_conf) if token_conf else 0.0
    blank_frac = blanks / len(raw) if raw else 1.0
    return PhonemeResult(ids, round(c_ctc, 4), [round(x, 3) for x in token_conf],
                         round(blank_frac, 4))


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
