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
    await session_ws(ws, session_id)


@app.on_event("startup")
def warm():
    """Load the Whisper model and relocation index at boot so the first
    reciter doesn't pay for either."""
    from app.asr.whisper_local import get_engine
    from app.mutashabeh.index import get_relocation_index

    get_engine()
    get_relocation_index()
