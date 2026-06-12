"""WebSocket session handling: PCM in -> events out.

Abuse controls (D3): global session cap, per-IP cap, ingest rate cap at
~1.1x real-time, idle timeout, max duration, Origin allowlist.
Resume (D9): client echoes its session id + last confirmed idx on reconnect;
the tracker is rebuilt and repositioned — trust-the-client is fine pre-auth.
Privacy (D10): audio stays in memory; only text events are persisted.
"""

import asyncio
import json
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.asr.whisper_local import get_engine
from app.audio.vad import StreamSegmenter
from app.config import settings
from app.db.models import Session as DBSessionRow
from app.db.models import SessionEvent, SessionSummary
from app.db.repo import load_reference
from app.db.session import SessionLocal
from app.engine.detector import RecitationTracker
from app.engine.events import Event, EventType
from app.nlp.normalize import tokenize


class SessionRegistry:
    def __init__(self):
        self.active: dict[str, "LiveSession"] = {}
        self.per_ip: dict[str, int] = defaultdict(int)
        self.lock = asyncio.Lock()

    async def try_admit(self, session_id: str, ip: str) -> str | None:
        """Returns a rejection reason, or None if admitted."""
        async with self.lock:
            if session_id in self.active:
                return "session already connected"
            if len(self.active) >= settings.max_concurrent_sessions:
                return "busy"
            if self.per_ip[ip] >= settings.max_sessions_per_ip:
                return "too many sessions from this address"
            self.per_ip[ip] += 1
            return None

    async def release(self, session_id: str, ip: str) -> None:
        async with self.lock:
            self.active.pop(session_id, None)
            self.per_ip[ip] -= 1
            if self.per_ip[ip] <= 0:
                del self.per_ip[ip]


registry = SessionRegistry()


class LiveSession:
    def __init__(self, session_id: uuid.UUID, surah_id: int | None, start_ayah: int | None):
        self.id = session_id
        self.surah_id = surah_id
        self.start_ayah = start_ayah
        from app.engine.locate import LocationDetector
        from app.mutashabeh.index import get_relocation_index

        self.tracker: RecitationTracker | None = None
        self.detector: LocationDetector | None = None
        if surah_id is not None:
            self._init_tracker(surah_id, start_ayah or 1, preamble=True)
        else:
            self.detector = LocationDetector(get_relocation_index())
        self.segmenter = StreamSegmenter()
        self.started = time.monotonic()
        self.last_frame = time.monotonic()
        self.bytes_received = 0
        self.counts = {"words_ok": 0, "words_missed": 0, "ayahs_missed": 0, "jumps": 0}
        self.detail: list[dict] = []

    def _init_tracker(self, surah_id: int, start_ayah: int, *, preamble: bool) -> None:
        from app.mutashabeh.index import get_relocation_index

        db = SessionLocal()
        try:
            self.ref = load_reference(db, surah_id, start_ayah)
        finally:
            db.close()
        self.surah_id = surah_id
        self.start_ayah = start_ayah
        self.tracker = RecitationTracker(
            self.ref, relocation=get_relocation_index(), preamble=preamble
        )

    def lock_location(self, surah: int, ayah: int) -> None:
        """Auto-detect resolved: build the tracker (preamble already consumed by
        the detector) and persist the location on the session row."""
        self._init_tracker(surah, ayah, preamble=False)
        db = SessionLocal()
        try:
            row = db.get(DBSessionRow, self.id)
            row.surah_id = surah
            row.start_ayah = ayah
            db.commit()
        finally:
            db.close()
        self.detector = None

    # --- ingest rate cap (D3): mic audio cannot arrive faster than real time.
    # A 3s burst allowance absorbs send-then-sleep jitter and reconnect bursts;
    # a sustained >1.1x sender still trips within seconds.
    def rate_exceeded(self) -> bool:
        elapsed = time.monotonic() - self.started
        rate = settings.sample_rate * 2  # bytes/sec of real-time audio
        max_bytes = rate * settings.ingest_rate_factor * elapsed + rate * 3
        return self.bytes_received > max_bytes

    def over_duration(self) -> bool:
        return time.monotonic() - self.started > settings.max_session_minutes * 60

    def record(self, events: list[Event]) -> None:
        for e in events:
            if e.state.value != "confirmed":
                continue
            if e.type == EventType.WORD_OK:
                self.counts["words_ok"] += 1
            elif e.type == EventType.MISSED_WORD:
                self.counts["words_missed"] += 1
                self.detail.append(e.to_dict())
            elif e.type == EventType.MISSED_AYAH:
                self.counts["ayahs_missed"] += 1
                self.detail.append(e.to_dict())
            elif e.type == EventType.MUTASHABEH_JUMP:
                self.counts["jumps"] += 1
                self.detail.append(e.to_dict())


def _persist_events(session_id: uuid.UUID, events: list[Event]) -> None:
    if not events:
        return
    db = SessionLocal()
    try:
        for e in events:
            if e.type == EventType.POSITION:
                continue  # high-volume noise; live-only
            db.add(SessionEvent(session_id=session_id, type=e.type.value, payload=e.to_dict()))
        db.commit()
    finally:
        db.close()


def _finalize(live: LiveSession) -> None:
    db = SessionLocal()
    try:
        row = db.get(DBSessionRow, live.id)
        if row and row.status != "ended":
            row.status = "ended"
            row.ended_at = datetime.now(timezone.utc)
            db.merge(
                SessionSummary(
                    session_id=live.id,
                    duration_sec=round(time.monotonic() - live.started, 1),
                    **live.counts,
                    detail={"errors": live.detail},
                )
            )
            db.commit()
    finally:
        db.close()


def _origin_allowed(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin", "")
    return not origin or origin in settings.allowed_origins


async def session_ws(ws: WebSocket, session_id: str) -> None:
    if not _origin_allowed(ws):
        await ws.close(code=4403)
        return

    db = SessionLocal()
    try:
        row = db.get(DBSessionRow, uuid.UUID(session_id))
    except ValueError:
        row = None
    finally:
        db.close()
    if row is None or row.status == "ended":
        await ws.close(code=4404)
        return

    ip = ws.client.host if ws.client else "?"
    reason = await registry.try_admit(session_id, ip)
    if reason is not None:
        await ws.accept()
        await ws.send_json({"type": "rejected", "reason": reason})
        await ws.close(code=4429)
        return

    await ws.accept()
    live = LiveSession(row.id, row.surah_id, row.start_ayah)
    registry.active[session_id] = live
    engine = get_engine()

    db = SessionLocal()
    try:
        row = db.get(DBSessionRow, live.id)
        row.status = "active"
        db.commit()
    finally:
        db.close()

    finalize = False
    try:
        while True:
            if live.over_duration():
                await ws.send_json({"type": "ended", "reason": "max duration"})
                finalize = True
                break
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=settings.idle_timeout_sec)
            except asyncio.TimeoutError:
                await ws.send_json({"type": "ended", "reason": "idle timeout"})
                finalize = True
                break
            if msg.get("type") == "websocket.disconnect":
                break

            if (data := msg.get("bytes")) is not None:
                live.last_frame = time.monotonic()
                live.bytes_received += len(data)
                if live.rate_exceeded():
                    await ws.send_json({"type": "ended", "reason": "rate limit"})
                    finalize = True
                    break
                for seg in live.segmenter.feed(data):
                    tr = await engine.transcribe(seg.audio, seg.duration)
                    if tr.gated:
                        continue
                    tokens = tokenize(tr.text)

                    if live.tracker is None:  # auto-detect: still locating
                        loc = live.detector.feed(tokens)
                        if loc is None:
                            await ws.send_json({"type": "detecting"})
                            continue
                        replay = live.detector.tokens
                        live.lock_location(loc.surah, loc.ayah)
                        await ws.send_json(
                            {
                                "type": "detected",
                                "surah": loc.surah,
                                "ayah": loc.ayah,
                                "score": round(loc.score, 3),
                            }
                        )
                        tokens, forced = replay, False  # replay opening through the tracker
                    else:
                        forced = seg.starts_with_overlap

                    events = live.tracker.feed_segment(tokens, forced_cut=forced)
                    live.record(events)
                    await asyncio.to_thread(_persist_events, live.id, events)
                    await ws.send_json(
                        {
                            "type": "events",
                            "events": [e.to_dict() for e in events],
                            "asr_ms": round(tr.asr_seconds * 1000),
                            "segment_s": round(seg.duration, 2),
                        }
                    )

            elif (text := msg.get("text")) is not None:
                ctl = json.loads(text)
                if ctl.get("type") in ("resume", "reposition") and live.tracker is not None:
                    live.tracker.reposition(int(ctl.get("idx", 0)))
                    await ws.send_json({"type": "resumed", "idx": live.tracker.pointer})
                elif ctl.get("type") == "end":
                    if (
                        live.tracker is not None
                        and (seg := live.segmenter.flush()) is not None
                        and seg.duration > 0.3
                    ):
                        tr = await engine.transcribe(seg.audio, seg.duration)
                        if not tr.gated:
                            events = live.tracker.feed_segment(tokenize(tr.text))
                            live.record(events)
                            await asyncio.to_thread(_persist_events, live.id, events)
                            await ws.send_json(
                                {"type": "events", "events": [e.to_dict() for e in events]}
                            )
                    await ws.send_json({"type": "ended", "reason": "user"})
                    finalize = True
                    break
    except WebSocketDisconnect:
        pass  # plain disconnect: leave row 'active' so the client can reconnect+resume
    finally:
        await registry.release(session_id, ip)
        if finalize:
            _finalize(live)


def finalize_session(session_id: uuid.UUID) -> None:
    """Explicit finalize from the REST layer (POST /sessions/{id}/end)."""
    live = registry.active.get(str(session_id))
    if live is not None:
        _finalize(live)
    else:
        # offline finalize: aggregate from persisted events
        db = SessionLocal()
        try:
            row = db.get(DBSessionRow, session_id)
            if row is None:
                return
            events = db.execute(
                select(SessionEvent).where(SessionEvent.session_id == session_id)
            ).scalars().all()
            counts = {"words_ok": 0, "words_missed": 0, "ayahs_missed": 0, "jumps": 0}
            detail = []
            for e in events:
                if e.payload.get("state") != "confirmed":
                    continue
                if e.type == "WORD_OK":
                    counts["words_ok"] += 1
                elif e.type == "MISSED_WORD":
                    counts["words_missed"] += 1
                    detail.append(e.payload)
                elif e.type == "MISSED_AYAH":
                    counts["ayahs_missed"] += 1
                    detail.append(e.payload)
                elif e.type == "MUTASHABEH_JUMP":
                    counts["jumps"] += 1
                    detail.append(e.payload)
            row.status = "ended"
            row.ended_at = datetime.now(timezone.utc)
            db.merge(SessionSummary(session_id=session_id, **counts, detail={"errors": detail}))
            db.commit()
        finally:
            db.close()
