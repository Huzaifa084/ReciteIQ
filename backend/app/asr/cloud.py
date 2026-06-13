"""Cloud ASR engine — Groq (OpenAI-compatible Whisper) with local fallback.

Why Groq: whisper-large-v3-turbo is a far bigger model than our local
Quran-tuned `base`, so it holds up better on amateur mics and slow tajweed —
exactly where the local model struggled. The API is OpenAI-compatible and the
free tier (2,000 req/day) makes A/B testing cost nothing.

Selected via RECITEIQ_ASR_ENGINE=cloud. If the cloud call errors or no key is
set, we fall back to the local engine so a session never dies on a network
blip. Set RECITEIQ_GROQ_API_KEY (get one free at https://console.groq.com).
"""

import io
import logging
import wave

import httpx
import numpy as np

from app.asr.base import ASREngine, Transcript
from app.config import settings

log = logging.getLogger("reciteiq.asr.cloud")

# NOTE: a Quranic-context `prompt` was tried and removed — whisper-large-v3
# echoes the prompt text back on short/quiet segments, which is worse than the
# spam it suppresses. We gate the spam directly instead. The deeper limitation
# remains: general whisper-large-v3 is NOT Quran-tuned, so it drifts on Uthmani
# orthography and hallucinates on very short openings (e.g. طه). The local
# Quran-tuned model is more accurate for this domain — cloud is opt-in for
# users who prioritise latency on known-surah tracking.

# Known whisper-large-v3 Arabic hallucinations on quiet / ambiguous audio
# (YouTube-caption training artifacts). Normalized; dropped before alignment.
_HALLUCINATIONS = {
    "اشتركوا في القناه",
    "اشتركوا في القناه وفعلوا الجرس",
    "لا تنسوا الاشتراك في القناه",
    "ترجمه نانسي قنقر",
    "ترجمه",
    "اشتركوا في القناه ليصلكم كل جديد",
    "شكرا للمشاهده",
    "شكرا لكم على المشاهده",
}
# NOTE: never blocklist real Quranic phrases (e.g. الحمد لله رب العالمين) — they
# are legitimate ayat; gating them would break recitation of those verses.


def _pcm_to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    pcm = np.clip(audio * 32768.0, -32768, 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _is_hallucination(text: str) -> bool:
    from app.nlp.normalize import normalize

    return normalize(text) in _HALLUCINATIONS


class CloudEngine(ASREngine):
    def __init__(self):
        self._key = settings.groq_api_key
        self._model = settings.groq_model
        self._url = "https://api.groq.com/openai/v1/audio/transcriptions"
        self._client = httpx.AsyncClient(timeout=settings.cloud_timeout_sec)
        self._fallback: ASREngine | None = None
        if not self._key:
            log.warning("RECITEIQ_GROQ_API_KEY not set — cloud engine will always fall back to local")

    def _local(self) -> ASREngine:
        if self._fallback is None:
            from app.asr.whisper_local import get_engine

            self._fallback = get_engine()
        return self._fallback

    async def transcribe(self, audio: np.ndarray, duration: float) -> Transcript:
        if duration < settings.asr_min_segment_sec:
            return Transcript("", True, 1.0, 0.0, 0.0, 0.0)
        if not self._key:
            return await self._local().transcribe(audio, duration)

        import time

        t0 = time.perf_counter()
        try:
            wav = _pcm_to_wav_bytes(audio, settings.sample_rate)
            resp = await self._client.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}"},
                files={"file": ("segment.wav", wav, "audio/wav")},
                data={
                    "model": self._model,
                    "language": "ar",
                    "temperature": "0",
                    "response_format": "json",
                },
            )
            resp.raise_for_status()
            text = (resp.json().get("text") or "").strip()
            if _is_hallucination(text):
                log.info("cloud ASR hallucination gated: %r", text)
                return Transcript("", True, 1.0, 0.0, 0.0, 0.0)
        except Exception as e:  # network / rate-limit / 5xx → never kill the session
            log.warning("cloud ASR failed (%s); falling back to local", type(e).__name__)
            return await self._local().transcribe(audio, duration)

        # Cloud APIs don't expose Whisper's per-segment confidences, so the
        # local hallucination gate's logprob/compression checks don't apply.
        # We gate only on emptiness; the alignment engine's fuzzy matching and
        # confirmation windows already absorb the occasional bad token.
        return Transcript(
            text=text,
            gated=not text,
            no_speech_prob=0.0,
            avg_logprob=0.0,
            compression_ratio=0.0,
            asr_seconds=time.perf_counter() - t0,
        )


_engine: CloudEngine | None = None


def get_engine() -> CloudEngine:
    global _engine
    if _engine is None:
        _engine = CloudEngine()
    return _engine
