"""v1 phoneme WS handler (encoder-CTC ID tracker, ≤30s bounded windows).

Parallel to ws/session.py's Whisper path, selected by RECITEIQ_TRACKER_MODE=phoneme.
Reuses the abuse-control registry and DB session rows. Emits the SAME event
contract (ayah-level WORD_OK progress, MISSED_AYAH, REPEAT, MUTASHABEH_JUMP,
POSITION) — but NO MISSED_WORD (v1 scope).
"""

import asyncio
import json
import logging
import time
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from app.asr.phoneme_ctc import get_phoneme_ctc
from app.audio.vad import StreamSegmenter
from app.config import settings
from app.db.models import Session as DBSessionRow
from app.db.repo import load_phoneme_reference
from app.db.session import SessionLocal
from app.engine.events import Event, EventState, EventType
from app.engine.phoneme_index import get_phoneme_index
from app.engine.phoneme_tracker import PhonemeTracker
from app.ws.session import _origin_allowed, registry  # reuse abuse-control registry

log = logging.getLogger("reciteiq.phoneme_session")


class _Detector:
    """Conservative ID-space auto-detect via the phoneme index.

    Votes at the SURAH level over a sliding window (same fix as the whisper
    LocationDetector): same-surah ties don't block the margin, and consensus is
    a surah leading the recent windows — then lock at its best-scoring ayah.
    """

    def __init__(self):
        self.index = get_phoneme_index()
        self._votes: list[int] = []                       # surah per qualifying window
        self._min_ayah: dict[int, int] = {}               # surah -> earliest matched ayah
        self._best_score: dict[int, float] = {}

    def feed(self, ids: list[int]) -> tuple[int, int, float] | None:
        if len(ids) < settings.phoneme_detect_min_ids:
            return None
        hits = self.index.vote(ids)
        if not hits:
            return None
        _aid, surah, ayah, score = hits[0]
        # margin vs the best hit at a DIFFERENT surah (same-surah ayah ties don't count)
        other = next((h[3] for h in hits[1:] if h[1] != surah), 0.0)
        if score < settings.phoneme_detect_score_min or score - other < settings.phoneme_detect_margin:
            return None  # uncertain → keep listening
        self._votes.append(surah)
        self._votes = self._votes[-5:]
        self._min_ayah[surah] = min(self._min_ayah.get(surah, ayah), ayah)
        self._best_score[surah] = max(self._best_score.get(surah, 0.0), score)
        lead = max(set(self._votes), key=self._votes.count)
        if self._votes.count(lead) >= settings.phoneme_detect_consensus:
            # lock at the EARLIEST matched ayah (reciter's start), not the best-scoring one
            return (lead, self._min_ayah[lead], round(self._best_score[lead], 3))
        return None


async def phoneme_ws(ws: WebSocket, session_id: str) -> None:
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
    registry.active[session_id] = object()  # occupy a slot

    model = get_phoneme_ctc()
    seg = StreamSegmenter(max_sec=settings.phoneme_segment_max_sec,
                          silence_cut_sec=settings.phoneme_silence_cut_sec)
    tracker: PhonemeTracker | None = None
    detector: _Detector | None = None
    surah_id = row.surah_id
    start_ayah = row.start_ayah or 1

    def build_tracker(sid: int, a0: int) -> PhonemeTracker | None:
        d = SessionLocal()
        try:
            ref = load_phoneme_reference(d, sid, a0)
        finally:
            d.close()
        if not ref:
            return None
        return PhonemeTracker(ref=ref, index=get_phoneme_index())

    pending: list[list[int]] = []  # window IDs buffered during auto-detect, replayed on lock
    if surah_id is not None:
        tracker = build_tracker(surah_id, start_ayah)
    else:
        detector = _Detector()

    counts = {"words_ok": 0, "ayahs_missed": 0, "jumps": 0}
    detail: list[dict] = []

    def tally(events: list) -> None:
        for e in events:
            if e.state != EventState.CONFIRMED:
                continue
            if e.type == EventType.WORD_OK:
                counts["words_ok"] += 1
            elif e.type == EventType.MISSED_AYAH:
                counts["ayahs_missed"] += 1
                detail.append(e.to_dict())
            elif e.type == EventType.MUTASHABEH_JUMP:
                counts["jumps"] += 1
                detail.append(e.to_dict())

    started = time.monotonic()
    try:
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=settings.idle_timeout_sec)
            except asyncio.TimeoutError:
                await ws.send_json({"type": "ended", "reason": "idle timeout"})
                break
            if msg.get("type") == "websocket.disconnect":
                break

            if (data := msg.get("bytes")) is not None:
                for s in seg.feed(data):
                    ids = model.ids(s.audio)
                    if len(ids) < 4:
                        continue
                    if tracker is None:  # auto-detect
                        pending.append(ids)
                        loc = detector.feed(ids)
                        if loc is None:
                            await ws.send_json({"type": "detecting"})
                            continue
                        d_surah, d_ayah, d_score = loc
                        # start a little before the earliest match so nothing is clipped;
                        # report THIS start ayah so the SPA fetches matching text and the
                        # word-idx enumeration aligns with the tracker's word_refs.
                        start = max(1, d_ayah - 1)
                        tracker = build_tracker(d_surah, start)
                        if tracker is None:
                            await ws.send_json({"type": "detecting"})
                            continue
                        log.info("phoneme detect lock session=%s -> %s:%s", session_id, d_surah, start)
                        await ws.send_json({"type": "detected", "surah": d_surah, "ayah": start, "score": d_score})
                        # replay all windows buffered during detection so nothing is lost
                        replay: list = []
                        for w in pending:
                            replay += tracker.feed(w)
                        pending.clear()
                        tally(replay)
                        if replay:
                            await ws.send_json({"type": "events", "events": [e.to_dict() for e in replay]})
                        continue
                    events = tracker.feed(ids)
                    tally(events)
                    if events:
                        await ws.send_json({"type": "events", "events": [e.to_dict() for e in events]})

            elif (text := msg.get("text")) is not None:
                ctl = json.loads(text)
                if ctl.get("type") == "end":
                    if (s := seg.flush()) is not None and tracker is not None:
                        ev = tracker.feed(model.ids(s.audio))
                        tally(ev)
                        if ev:
                            await ws.send_json({"type": "events", "events": [e.to_dict() for e in ev]})
                    await ws.send_json({"type": "ended", "reason": "user"})
                    break
    except WebSocketDisconnect:
        pass
    finally:
        await registry.release(session_id, ip)
        _finalize(session_id, round(time.monotonic() - started, 1), counts, detail)


def _finalize(session_id: str, duration: float = 0.0, counts: dict | None = None,
              detail: list | None = None) -> None:
    from datetime import datetime, timezone

    from app.db.models import SessionSummary
    db = SessionLocal()
    try:
        row = db.get(DBSessionRow, uuid.UUID(session_id))
        if row and row.status != "ended":
            row.status = "ended"
            row.ended_at = datetime.now(timezone.utc)
            c = counts or {}
            db.merge(SessionSummary(
                session_id=uuid.UUID(session_id),
                duration_sec=duration,
                words_ok=c.get("words_ok", 0),
                words_missed=0,                       # v1: MISSED_WORD intentionally disabled
                ayahs_missed=c.get("ayahs_missed", 0),
                jumps=c.get("jumps", 0),
                detail={"errors": detail or [], "mode": "phoneme_v1"},
            ))
            db.commit()
    finally:
        db.close()
