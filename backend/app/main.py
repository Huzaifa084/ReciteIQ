"""ReciteIQ backend entrypoint."""

import logging

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings
from app.ws.session import session_ws

logging.basicConfig(level=logging.INFO, format='{"t":"%(asctime)s","lvl":"%(levelname)s","msg":"%(message)s"}')

app = FastAPI(title="ReciteIQ", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.websocket("/ws/session/{session_id}")
async def ws_endpoint(ws: WebSocket, session_id: str):
    if settings.tracker_mode == "phoneme":
        from app.ws.phoneme_session import phoneme_ws

        await phoneme_ws(ws, session_id)
    else:
        await session_ws(ws, session_id)


@app.on_event("startup")
async def retention_sweeper():
    """Enforce the stated retention window from inside the app.

    The policy shipped as a cron file that was never installed, so nothing
    enforced it (docs/audit-as-built.md, S-3). Runs once at boot and daily
    after — a privacy guarantee should not depend on an operator remembering
    to copy a crontab.
    """
    import asyncio

    from app.db.repo import purge_expired_events

    async def loop():
        while True:
            try:
                n = await asyncio.to_thread(purge_expired_events)
                if n:
                    log = logging.getLogger("reciteiq.retention")
                    log.info("retention purge removed %s event rows older than %s days",
                             n, settings.anonymous_events_retention_days)
            except Exception:
                logging.getLogger("reciteiq.retention").exception("retention purge failed")
            await asyncio.sleep(24 * 3600)

    asyncio.create_task(loop())


@app.on_event("startup")
def warm():
    """Warm the active recognizer + index at boot so the first reciter doesn't pay."""
    if settings.tracker_mode == "phoneme":
        from app.asr.phoneme_ctc import get_phoneme_ctc
        from app.engine.phoneme_index import get_phoneme_index

        get_phoneme_ctc()
        get_phoneme_index()
    else:
        from app.asr import get_engine
        from app.mutashabeh.index import get_relocation_index
        from app.audio.vad import OnnxVAD

        get_engine()
        get_relocation_index()
        OnnxVAD()
