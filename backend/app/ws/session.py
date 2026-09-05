"""WebSocket session handling: PCM in -> events out.

Abuse controls (D3): global session cap, per-IP cap, ingest rate cap at
~1.1x real-time, idle timeout, max duration, Origin allowlist.
Resume (D9): client echoes its session id + last confirmed idx on reconnect;
the tracker is rebuilt and repositioned — trust-the-client is fine pre-auth.
Privacy (D10): audio stays in memory; only text events are persisted.
"""

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.asr import get_engine
from app.audio.vad import StreamSegmenter
from app.config import settings
from app.db.models import Session as DBSessionRow
from app.db.models import SessionEvent, SessionSummary
from app.db.repo import load_reference
from app.db.session import SessionLocal
from app.engine.detector import RecitationTracker
from app.engine.events import Event, EventType
from app.nlp.normalize import tokenize

log = logging.getLogger("reciteiq.session")


def _audio_stats(audio) -> dict:
    """Level stats per window. Ported from the phoneme path, where they were what
    finally separated 'bad audio in' from 'model failing on good audio' — the
    browser takes had healthy level and token rate, which is what redirected the
    investigation away from the microphone and onto the recogniser."""
    import numpy as _np

    if audio is None or len(audio) == 0:
        return {"rms_dbfs": None, "peak_dbfs": None, "clip_frac": None}
    a = _np.asarray(audio, dtype=_np.float32)
    to_db = lambda v: round(20.0 * float(_np.log10(v)), 1) if v > 1e-9 else -120.0
    return {
        "rms_dbfs": to_db(float(_np.sqrt(_np.mean(a * a)))),
        "peak_dbfs": to_db(float(_np.max(_np.abs(a)))),
        "clip_frac": round(float(_np.mean(_np.abs(a) > 0.99)), 5),
    }


class SessionRegistry:
    def __init__(self):
        self.active: dict[str, "LiveSession"] = {}
        self.per_ip: dict[str, int] = defaultdict(int)
        self.lock = asyncio.Lock()
        # Sessions whose socket dropped but which are not finished. A reconnect
        # re-attaches to the SAME LiveSession, so its counts, matched words and
        # tracker survive. Rebuilding from scratch made the final summary count
        # only what came after the drop (docs/audit-as-built.md, B-4).
        self.detached: dict[str, tuple["LiveSession", float]] = {}

    async def try_admit(self, session_id: str, ip: str) -> str | None:
        """Returns a rejection reason, or None if admitted.

        The slot is RESERVED here, inside the same lock that checks the caps.
        Reserving afterwards left a window in which concurrent connects all
        passed `len(self.active)` before any of them inserted, so the global cap
        could be exceeded and a duplicate id orphaned a LiveSession
        (docs/audit-as-built.md, B-10). `attach` swaps the placeholder for the
        real object once it is built, which takes long enough (it loads the
        surah reference) that the window was genuinely reachable.
        """
        async with self.lock:
            if session_id in self.active:
                return "session already connected"
            if len(self.active) >= settings.max_concurrent_sessions:
                return "busy"
            if self.per_ip[ip] >= settings.max_sessions_per_ip:
                return "too many sessions from this device"
            self.per_ip[ip] += 1
            self.active[session_id] = None      # reservation: counts toward the cap
            return None

    async def attach(self, session_id: str, live: "LiveSession") -> None:
        async with self.lock:
            self.active[session_id] = live

    async def reclaim(self, session_id: str) -> "LiveSession | None":
        """Take back a session whose socket dropped, if it is still within the
        grace window. Anything older is discarded so a stale tracker can never
        be resumed into."""
        async with self.lock:
            found = self.detached.pop(session_id, None)
            cutoff = time.monotonic() - settings.resume_grace_sec
            self.detached = {k: v for k, v in self.detached.items() if v[1] >= cutoff}
        if found is None:
            return None
        live, when = found
        return live if when >= cutoff else None

    async def detach(self, session_id: str, live: "LiveSession | None") -> None:
        async with self.lock:
            if live is not None:
                self.detached[session_id] = (live, time.monotonic())

    def get(self, session_id: str) -> "LiveSession | None":
        return self.active.get(session_id)

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
        self.counts = {"words_ok": 0, "words_missed": 0, "ayahs_missed": 0, "jumps": 0,
                       "repeats": 0, "uncertain": 0, "words_expected": 0}
        self.no_match_run = 0        # consecutive windows we heard but could not place
        self._ok_idx: set[int] = set()       # distinct reference words confirmed
        # Reference words we returned a VERDICT on, so accuracy has an honest
        # denominator. words_ok/(words_ok+words_missed) was wrong: the words
        # inside a skipped ayah aggregate into MISSED_AYAH and never reach
        # words_missed, so they vanished from the denominator entirely and a
        # reciter who skipped three ayahs of Al-Fatihah was told 100%
        # (docs/audit-as-built.md, B-2).
        #
        # UNCERTAIN words are deliberately excluded from BOTH sides: an
        # unconfirmed word is our uncertainty, not the reciter's mistake, and
        # counting it against them would contradict the rule the rest of the
        # system follows. It is reported on its own instead.
        self._missed_word_idx: set[int] = set()
        self._missed_ayah_idx: set[int] = set()
        self.last_heard = 0.0            # throttle for the "we can hear you" frame
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

    _COUNT_KEY = {
        EventType.MISSED_WORD: "words_missed",
        EventType.MISSED_AYAH: "ayahs_missed",
        EventType.MUTASHABEH_JUMP: "jumps",
    }

    def record(self, events: list[Event]) -> None:
        for e in events:
            if e.state.value == "confirmed":
                if e.type == EventType.WORD_OK:
                    # DISTINCT words, not WORD_OK events: a rewind clears the
                    # matched set so the re-recited words are credited again, and
                    # counting events reported 109 words for a 107-word surah.
                    self._ok_idx.add(e.payload.get("idx"))
                    self.counts["words_ok"] = len(self._ok_idx)
                elif e.type in self._COUNT_KEY:
                    self.counts[self._COUNT_KEY[e.type]] += 1
                    self.detail.append(e.to_dict())
                    self._track_expected(e, add=True)
                elif e.type == EventType.REPEAT:
                    self.counts["repeats"] += 1      # benign: counted, never an error
                elif e.type == EventType.UNCERTAIN:
                    self.counts["uncertain"] += 1
            elif e.state.value == "revoked" and e.type in self._COUNT_KEY:
                # late-match revocation withdraws an earlier confirmed verdict
                before = len(self.detail)
                self.detail = [d for d in self.detail if d["event_id"] != e.refers_to]
                if len(self.detail) < before:
                    self.counts[self._COUNT_KEY[e.type]] -= 1
                    self._track_expected(e, add=False)
        self.counts["words_expected"] = len(
            self._ok_idx | self._missed_word_idx | self._missed_ayah_idx
        )

    def _track_expected(self, e: Event, *, add: bool) -> None:
        """Remember which reference words a verdict covered, so a withdrawn
        verdict also leaves the denominator."""
        if e.type == EventType.MISSED_WORD:
            idx = e.payload.get("idx")
            if idx is not None:
                self._missed_word_idx.add(idx) if add else self._missed_word_idx.discard(idx)
        elif e.type == EventType.MISSED_AYAH:
            ayah_id = e.payload.get("ayah_id")
            ref = getattr(self, "ref", None)
            if ayah_id is None or not ref:
                return
            for w in ref:
                if w.ayah_id == ayah_id:
                    self._missed_ayah_idx.add(w.idx) if add else self._missed_ayah_idx.discard(w.idx)


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


def client_ip(ws: WebSocket) -> str:
    """The address the per-client cap should be counted against.

    Behind the compose nginx, ws.client.host is the PROXY's container address
    for every visitor, so `max_sessions_per_ip` stopped separating users and
    became a global cap of 2 for the entire site — the third visitor anywhere
    was told "too many sessions from this address" (audit B-3).

    X-Forwarded-For is only believed when the immediate peer is a trusted
    proxy; otherwise a client could lift its own cap by inventing the header.
    The left-most entry is the original client, and it is validated as an IP so
    a malformed header degrades to the peer address rather than creating an
    unbounded bucket key.
    """
    import ipaddress

    peer = ws.client.host if ws.client else "?"
    fwd = ws.headers.get("x-forwarded-for", "")
    if not fwd:
        return peer
    try:
        peer_addr = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    for net in settings.trusted_proxy_ips:
        try:
            trusted = (peer_addr in ipaddress.ip_network(net, strict=False)
                       if "/" in net else peer_addr == ipaddress.ip_address(net))
        except ValueError:
            continue
        if trusted:
            candidate = fwd.split(",")[0].strip()
            try:
                ipaddress.ip_address(candidate)
            except ValueError:
                return peer          # unparseable header: fall back, never trust
            return candidate
    return peer


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

    ip = client_ip(ws)
    reason = await registry.try_admit(session_id, ip)
    if reason is not None:
        await ws.accept()
        await ws.send_json({"type": "rejected", "reason": reason})
        await ws.close(code=4429)
        return

    await ws.accept()
    # A reconnect must resume the SAME session object: its counts, its matched
    # words and its tracker. Building a fresh one discarded everything recited
    # before the drop, so the summary silently undercounted (B-4).
    live = await registry.reclaim(session_id)
    resumed = live is not None
    if live is None:
        live = LiveSession(row.id, row.surah_id, row.start_ayah)
    await registry.attach(session_id, live)
    if resumed:
        log.info("session resumed session=%s words_ok=%s pointer=%s",
                 session_id, live.counts["words_ok"],
                 live.tracker.pointer if live.tracker else None)
        await ws.send_json({
            "type": "resumed",
            "idx": live.tracker.pointer if live.tracker else 0,
            "words_ok": live.counts["words_ok"],
        })
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
                closed = live.segmenter.feed(data)
                if not closed:
                    # Nothing to report yet. With a 25s window that silence lasts
                    # up to ~28s, and for a short surah the whole recitation fits
                    # in one window — the screen never changes and the app reads
                    # as broken. Say that we can hear them, at most once a second,
                    # WITHOUT inventing a verdict: this frame carries no events.
                    buffered = live.segmenter.buffered_sec
                    now = time.monotonic()
                    if buffered > 0 and now - live.last_heard >= 1.0:
                        live.last_heard = now
                        await ws.send_json({
                            "type": "buffering",
                            "buffered_sec": round(buffered, 1),
                            "in_silence": live.segmenter.in_silence,
                        })
                for seg in closed:
                    tr = await engine.transcribe(seg.audio, seg.duration)
                    if tr.gated:
                        # The reciter spoke; we simply have no transcript for it
                        # (too short, or the queue shed it). Dropping it silently
                        # left a gap the NEXT window had to explain, which could
                        # confirm a MISSED_WORD nobody made (B-6). Say so, and
                        # hold miss-confirmation across the blind spot.
                        if live.tracker is not None:
                            live.tracker.hold_confirmations()
                        log.info("asr window gated session=%s window_sec=%s reason=%s",
                                 live.id, round(seg.duration, 2), seg.closed_reason)
                        await ws.send_json({
                            "type": "unheard",
                            "seconds": round(seg.duration, 2),
                        })
                        continue
                    tokens = tokenize(tr.text)

                    if live.tracker is None:  # auto-detect: still locating
                        loc = live.detector.feed(tokens)
                        if loc is None:
                            # Diagnostic (text-only, rotated with container logs):
                            # without this, a session that never locks is undebuggable.
                            top = live.detector.last_hits[:3] if hasattr(live.detector, "last_hits") else []
                            log.info(
                                "detect miss session=%s tokens=%s top=%s",
                                live.id,
                                tokens,
                                [(s, a, round(sc, 2)) for _, s, a, sc in top],
                            )
                            await ws.send_json({"type": "detecting"})
                            continue
                        log.info("detect lock session=%s -> %s:%s score=%s", live.id, loc.surah, loc.ayah, loc.score)
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
                    # Per-window diagnostics, ported from the phoneme path (P1-7).
                    # Every diagnosis on that path — the one-ayah-per-window bug,
                    # the ayah-7 length gate, the 1:3-inside-1:1 anchor case — was
                    # only findable because each window left a structured record.
                    # The text path must be measurable from day one.
                    log.info("asr window %s", {
                        "session": str(live.id),
                        "window_sec": round(seg.duration, 2),
                        "closed": seg.closed_reason,
                        "asr_ms": round(tr.asr_seconds * 1000),
                        "n_tokens": len(tokens),
                        "tokens_per_sec": round(len(tokens) / max(seg.duration, 1e-6), 2),
                        "gated": tr.gated,
                        "pointer": live.tracker.pointer,
                        "n_events": len(events),
                        "types": sorted({e.type.value for e in events}),
                        **_audio_stats(seg.audio),
                    })
                    await asyncio.to_thread(_persist_events, live.id, events)
                    await ws.send_json(
                        {
                            "type": "events",
                            "events": [e.to_dict() for e in events],
                            "asr_ms": round(tr.asr_seconds * 1000),
                            "segment_s": round(seg.duration, 2),
                        }
                    )
                    # Transport-level signal so the UI can say "heard you but
                    # cannot place you" instead of sitting on "listening"
                    # forever. The phoneme path has always sent this; without it
                    # the FastConformer path leaves an off-reference reciter with
                    # no feedback at all. A window with speech that produced no
                    # WORD_OK is exactly that case — including a segment the
                    # pre-pass blocked as predominantly off-reference.
                    if tokens and not any(e.type == EventType.WORD_OK for e in events):
                        live.no_match_run += 1
                        await ws.send_json({
                            "type": "no_match",
                            "run": live.no_match_run,
                            "tokens": len(tokens),
                            "pointer": live.tracker.pointer if live.tracker else None,
                        })
                    elif tokens:
                        live.no_match_run = 0

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
                            # The final segment carries the same replayed overlap
                            # as any other segment after a hard cut, and dropping
                            # the flag here meant neither dedup nor the rewind
                            # guard ran on it — which is exactly where a clean
                            # Al-Inshiqaq produced its REPEAT.
                            events = live.tracker.feed_segment(
                                tokenize(tr.text), forced_cut=seg.starts_with_overlap
                            )
                            live.record(events)
                            await asyncio.to_thread(_persist_events, live.id, events)
                            await ws.send_json(
                                {"type": "events", "events": [e.to_dict() for e in events]}
                            )
                    if live.tracker is not None:
                        # resolve dangling provisionals before the summary
                        events = live.tracker.finish()
                        if events:
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
    except Exception:
        # Anything else — an ASR failure, a DB error, a malformed control frame
        # — used to propagate out of the handler: the session died with the row
        # stuck 'active', no summary, and nothing said to the reciter (B-5).
        # Their recitation is real work; finalise it and tell them.
        log.exception("session failed session=%s", session_id)
        try:
            await ws.send_json({"type": "ended", "reason": "internal error"})
        except Exception:
            pass  # socket may already be gone; the summary still gets written
        finalize = True
    finally:
        await registry.release(session_id, ip)
        if finalize:
            _finalize(live)
        else:
            # Socket dropped mid-session: hold the state so a reconnect can
            # resume into it rather than starting over.
            await registry.detach(session_id, live)


def finalize_session(session_id: uuid.UUID) -> None:
    """Explicit finalize from the REST layer (POST /sessions/{id}/end)."""
    live = registry.get(str(session_id))
    if live is not None:
        _finalize(live)
    else:
        # offline finalize: aggregate from persisted events
        db = SessionLocal()
        try:
            row = db.get(DBSessionRow, session_id)
            if row is None:
                return
            # A summary the live finaliser already wrote is better than anything
            # that can be reconstructed here: it saw the provisional/confirmed/
            # revoked lifecycle as it happened. Re-aggregating over it is how the
            # phoneme summary got clobbered with zeros once, and how a correct
            # distinct-word count got replaced by an event count.
            if db.get(SessionSummary, session_id) is not None:
                if row.status != "ended":
                    row.status = "ended"
                    row.ended_at = datetime.now(timezone.utc)
                    db.commit()
                return
            events = db.execute(
                select(SessionEvent).where(SessionEvent.session_id == session_id)
            ).scalars().all()
            counts = {"words_ok": 0, "words_missed": 0, "ayahs_missed": 0, "jumps": 0,
                      "repeats": 0, "uncertain": 0, "words_expected": 0}
            ok_idx: set = set()
            missed_idx: set = set()
            missed_ayah_ids: set = set()
            detail = []
            for e in events:
                if e.payload.get("state") != "confirmed":
                    continue
                if e.type == "WORD_OK":
                    # DISTINCT words. The stored row nests the word ref under
                    # `payload`, so reading idx off the top level silently gave
                    # None for every event and counted 109 words for a 107-word
                    # surah.
                    ok_idx.add(e.payload.get("payload", {}).get("idx"))
                    counts["words_ok"] = len(ok_idx)
                elif e.type == "MISSED_WORD":
                    counts["words_missed"] += 1
                    detail.append(e.payload)
                    missed_idx.add(e.payload.get("payload", {}).get("idx"))
                elif e.type == "MISSED_AYAH":
                    counts["ayahs_missed"] += 1
                    detail.append(e.payload)
                    missed_ayah_ids.add(e.payload.get("payload", {}).get("ayah_id"))
                elif e.type == "MUTASHABEH_JUMP":
                    counts["jumps"] += 1
                    detail.append(e.payload)
                elif e.type == "REPEAT":
                    counts["repeats"] += 1     # benign: counted, never an error
                elif e.type == "UNCERTAIN":
                    counts["uncertain"] += 1
            # Words inside a skipped ayah belong in the accuracy denominator,
            # so resolve those ayah ids to their word counts here too.
            if missed_ayah_ids:
                from app.db.models import Word
                n = db.execute(
                    select(Word.id).where(Word.ayah_id.in_(
                        {a for a in missed_ayah_ids if a is not None}))
                ).scalars().all()
                counts["words_expected"] = len(ok_idx | missed_idx) + len(n)
            else:
                counts["words_expected"] = len(ok_idx | missed_idx)

            row.status = "ended"
            row.ended_at = datetime.now(timezone.utc)
            # An aggregation that found nothing is not evidence the session was
            # empty — it can simply mean this tracker persists no event rows.
            # Never overwrite a summary that another finaliser already wrote.
            if not events and db.get(SessionSummary, session_id) is not None:
                db.commit()
                return
            db.merge(SessionSummary(session_id=session_id, **counts, detail={"errors": detail}))
            db.commit()
        finally:
            db.close()
