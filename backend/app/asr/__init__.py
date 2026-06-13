"""ASR engine selector. RECITEIQ_ASR_ENGINE picks the implementation;
everything else imports get_engine() from here, never from a concrete module."""

from app.asr.base import ASREngine
from app.config import settings


def get_engine() -> ASREngine:
    if settings.asr_engine == "cloud":
        from app.asr.cloud import get_engine as _cloud

        return _cloud()
    from app.asr.whisper_local import get_engine as _local

    return _local()
