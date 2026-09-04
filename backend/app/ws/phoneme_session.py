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


def _audio_stats(audio) -> dict:
    """Level stats for the window (P1-7 extension).

    Live-caught: amateur browser takes produced ~0.6 IDs/sec where qari audio
    gives ~4.5, with closest_cer 0.63-1.00. Token starvation like that is either
    too little signal reaching the model or the model failing on adequate signal,
    and the two demand opposite fixes — so log the level and stop guessing.
    """
    import numpy as _np

    if audio is None or len(audio) == 0:
        return {"rms_dbfs": None, "peak_dbfs": None, "clip_frac": None}
    a = _np.asarray(audio, dtype=_np.float32)
    rms = float(_np.sqrt(_np.mean(a * a)))
    peak = float(_np.max(_np.abs(a)))
    to_db = lambda v: round(20.0 * float(_np.log10(v)), 1) if v > 1e-9 else -120.0
    return {
        "rms_dbfs": to_db(rms),
        "peak_dbfs": to_db(peak),
        "clip_frac": round(float(_np.mean(_np.abs(a) > 0.99)), 5),
    }


class _Detector:
    """Conservative ID-space auto-detect via the phoneme index.

    Votes at the SURAH level over a sliding window (same fix as the whisper
    LocationDetector): same-surah ties don't block the margin, and consensus is
    a surah leading the recent windows — then lock at its best-scoring ayah.
    """

    INSTANT_LOCK = 0.85   # one very-confident window locks immediately
    VOTE_FLOOR = 0.35     # a window's top surah counts toward frequency consensus above this

    def __init__(self):
        self.index = get_phoneme_index()
        self._votes: list[int] = []                       # top surah per window (margin-free)
        self._min_ayah: dict[int, int] = {}               # surah -> earliest matched ayah
        self._best_score: dict[int, float] = {}
        self.last_hits: list = []                         # diagnostics

    def feed(self, ids: list[int]) -> tuple[int, int, float] | None:
        if len(ids) < settings.phoneme_detect_min_ids:
            return None
        hits = self.index.vote(ids)
        self.last_hits = hits[:3]
        if not hits:
            return None
        _aid, surah, ayah, score = hits[0]
        if score < self.VOTE_FLOOR:
            return None  # nothing matched well enough to even vote

        self._min_ayah[surah] = min(self._min_ayah.get(surah, ayah), ayah)
        self._best_score[surah] = max(self._best_score.get(surah, 0.0), score)

        # Path 1 — instant lock on a single high-confidence, unambiguous window
        other = next((h[3] for h in hits[1:] if h[1] != surah), 0.0)
        if score >= self.INSTANT_LOCK and score - other >= settings.phoneme_detect_margin:
            return (surah, self._min_ayah[surah], round(score, 3))

        # Path 2 — frequency consensus: count top-surah across windows (margin-free),
        # so a surah that keeps leading locks even when single-window margins are weak
        # (live-caught on Taha: surah 20 led 2 windows but no window passed the margin).
        self._votes.append(surah)
        self._votes = self._votes[-5:]
        lead = max(set(self._votes), key=self._votes.count)
        if self._votes.count(lead) >= settings.phoneme_detect_consensus:
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

    counts = {"words_ok": 0, "ayahs_missed": 0, "jumps": 0, "uncertain": 0}
    detail: list[dict] = []

    def tally(events: list) -> None:
        for e in events:
            # UNCERTAIN is a statement about our confidence, not a mistake by the
            # reciter — count it for diagnostics but keep it out of `errors`.
            if e.type == EventType.UNCERTAIN:
                if e.state == EventState.PROVISIONAL:
                    counts["uncertain"] += 1
                continue
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
                    _t0 = time.perf_counter()
                    res = model.recognize(s.audio)
                    ids = res.ids
                    infer_ms = int((time.perf_counter() - _t0) * 1000)
                    win = {
                        "session": session_id,
                        "window_sec": round(s.duration, 2),
                        "closed": s.closed_reason,
                        "infer_ms": infer_ms,
                        "n_ids": len(ids),
                        "ids_per_sec": round(len(ids) / max(s.duration, 1e-6), 2),
                        "c_ctc": res.c_ctc,
                        "blank_frac": res.blank_frac,
                        **_audio_stats(s.audio),
                    }
                    if len(ids) < 4:
                        log.info("phoneme window %s", {**win, "outcome": "too_few_ids"})
                        continue
                    if tracker is None:  # auto-detect
                        pending.append(ids)
                        loc = detector.feed(ids)
                        if loc is None:
                            log.info("phoneme window %s", {
                                **win, "outcome": "detecting",
                                "top": [(h[1], h[2], round(h[3], 2)) for h in detector.last_hits],
                            })
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
                        log.info("phoneme window %s", {
                            **win, "outcome": "detect_lock",
                            "locked": f"{d_surah}:{start}", "score": d_score,
                        })
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
                    events = tracker.feed(ids, c_ctc=res.c_ctc)
                    tally(events)
                    log.info("phoneme window %s", {**win, **tracker.last_diag})
                    if events:
                        await ws.send_json({
                            "type": "events",
                            "events": [e.to_dict() for e in events],
                            "infer_ms": infer_ms,
                        })
                    if tracker.last_diag.get("outcome") == "no_match":
                        # Transport-level signal so the UI can say "heard you but
                        # cannot place you" instead of sitting on "listening"
                        # forever. The verdict itself stays in the tracker.
                        await ws.send_json({
                            "type": "no_match",
                            "c_ctc": res.c_ctc,
                            "closest_cer": tracker.last_diag.get("closest_cer"),
                            "closest_ayah": tracker.last_diag.get("closest_ayah"),
                            "run": tracker.last_diag.get("no_match_run"),
                        })

            elif (text := msg.get("text")) is not None:
                ctl = json.loads(text)
                if ctl.get("type") == "end":
                    if (s := seg.flush()) is not None and tracker is not None:
                        _t0 = time.perf_counter()
                        _res = model.recognize(s.audio)
                        _ids = _res.ids
                        _ms = int((time.perf_counter() - _t0) * 1000)
                        ev = tracker.feed(_ids, c_ctc=_res.c_ctc)
                        tally(ev)
                        log.info("phoneme window %s", {
                            "session": session_id, "window_sec": round(s.duration, 2),
                            "closed": s.closed_reason, "infer_ms": _ms,
                            "n_ids": len(_ids), "c_ctc": _res.c_ctc,
                            "blank_frac": _res.blank_frac,
                            **_audio_stats(s.audio), **tracker.last_diag,
                        })
                        if ev:
                            await ws.send_json({
                                "type": "events",
                                "events": [e.to_dict() for e in ev],
                                "infer_ms": _ms,
                            })
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
                detail={"errors": detail or [], "mode": "phoneme_v1",
                        # kept separate from `errors`: unplaced audio is our
                        # uncertainty, not a mistake by the reciter (P0-4)
                        "uncertain": c.get("uncertain", 0)},
            ))
            db.commit()
    finally:
        db.close()
