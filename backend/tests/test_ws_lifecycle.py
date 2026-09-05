"""Integration tests for the live WebSocket session.

These drive the real `session_ws` handler through Starlette's test client. The
ASR and the VAD are stubbed — deliberately. What is under test here is the
session LIFECYCLE (admission, resume, finalisation, failure), which had no
coverage at all even though three critical audit findings lived in it; the
recogniser and the segmenter have their own measurements elsewhere.
"""

import json
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.asr.base import Transcript
from app.audio.vad import Segment
from app.db.models import Session as SessionRow
from app.db.models import SessionEvent, SessionSummary
from app.db.repo import load_reference
from app.db.session import SessionLocal
from app.main import app
from app.ws import session as ws_session


@pytest.fixture
def surah_words(db):
    """Al-Ikhlas: short enough to drive a whole session in a test."""
    return [w.norm for w in load_reference(db, 112)]


@pytest.fixture
def new_session():
    ids = []

    def _make():
        sid = uuid.uuid4()
        s = SessionLocal()
        try:
            s.add(SessionRow(id=sid, surah_id=112, start_ayah=1, status="active"))
            s.commit()
        finally:
            s.close()
        ids.append(sid)
        return sid

    yield _make
    s = SessionLocal()
    try:
        for sid in ids:
            s.query(SessionEvent).filter_by(session_id=sid).delete()
            s.query(SessionSummary).filter_by(session_id=sid).delete()
            s.query(SessionRow).filter_by(id=sid).delete()
        s.commit()
    finally:
        s.close()


class _ScriptedEngine:
    """Returns the next scripted transcript for each closed segment."""

    def __init__(self, lines):
        self.lines = list(lines)
        self.calls = 0
        self.raise_on = None

    async def transcribe(self, audio, duration):
        self.calls += 1
        if self.raise_on is not None and self.calls == self.raise_on:
            raise RuntimeError("simulated ASR failure")
        text = self.lines.pop(0) if self.lines else ""
        return Transcript(text, False, 0.0, 0.0, 0.0, 0.01)


class _ChunkSegmenter:
    """Closes one segment per audio frame, so tests control segmentation."""

    def __init__(self, *a, **kw):
        self._n = 0

    def feed(self, data: bytes):
        self._n += 1
        return [Segment(audio=np.zeros(16000, dtype=np.float32),
                        starts_with_overlap=False, duration=1.0,
                        closed_reason="silence")]

    def flush(self):
        return None

    @property
    def buffered_sec(self):
        return 0.0

    @property
    def in_silence(self):
        return True


@pytest.fixture
def wired(monkeypatch):
    """Install the stubs and hand back the engine so a test can script it."""
    engine = _ScriptedEngine([])
    monkeypatch.setattr(ws_session, "get_engine", lambda: engine)
    monkeypatch.setattr(ws_session, "StreamSegmenter", _ChunkSegmenter)
    ws_session.registry.active.clear()
    ws_session.registry.detached.clear()
    ws_session.registry.per_ip.clear()
    return engine


def _summary(sid):
    s = SessionLocal()
    try:
        return s.get(SessionSummary, sid)
    finally:
        s.close()


PCM = b"\x00\x00" * 1600


# ------------------------------------------------------------------ happy path


def test_a_whole_session_ends_with_a_consistent_summary(wired, new_session, surah_words):
    wired.lines = [" ".join(surah_words[:4]), " ".join(surah_words[4:])]
    sid = new_session()
    with TestClient(app) as c:
        with c.websocket_connect(f"/ws/session/{sid}") as ws:
            ws.send_bytes(PCM)
            ws.send_bytes(PCM)
            ws.send_text(json.dumps({"type": "end"}))
            while True:
                m = ws.receive_json()
                if m["type"] == "ended":
                    break
    s = _summary(sid)
    assert s is not None
    assert s.words_ok == len(surah_words)
    assert s.words_expected >= s.words_ok
    assert s.words_missed == 0 and s.ayahs_missed == 0


# ------------------------------------------------------------------ P0-4 resume


def test_reconnect_preserves_the_first_half_of_the_session(wired, new_session, surah_words):
    """The B-4 defect: a dropped socket rebuilt the session from scratch, so the
    summary counted only what came after the reconnect."""
    half = len(surah_words) // 2
    wired.lines = [" ".join(surah_words[:half])]
    sid = new_session()

    with TestClient(app) as c:
        with c.websocket_connect(f"/ws/session/{sid}") as ws:
            ws.send_bytes(PCM)
            ws.receive_json()                      # events for the first half
        # socket dropped without an "end" — the session must survive
        assert str(sid) in ws_session.registry.detached
        first_half = ws_session.registry.detached[str(sid)][0].counts["words_ok"]
        assert first_half == half

        wired.lines = [" ".join(surah_words[half:])]
        with c.websocket_connect(f"/ws/session/{sid}") as ws:
            assert ws.receive_json()["type"] == "resumed"
            ws.send_bytes(PCM)
            ws.send_text(json.dumps({"type": "end"}))
            while True:
                if ws.receive_json()["type"] == "ended":
                    break

    s = _summary(sid)
    assert s.words_ok == len(surah_words), (
        f"summary lost the first half: {s.words_ok} of {len(surah_words)}"
    )


def test_a_resumed_session_does_not_double_count(wired, new_session, surah_words):
    """Resuming must not re-credit words already counted before the drop."""
    wired.lines = [" ".join(surah_words)]
    sid = new_session()
    with TestClient(app) as c:
        with c.websocket_connect(f"/ws/session/{sid}") as ws:
            ws.send_bytes(PCM)
            ws.receive_json()
        wired.lines = [" ".join(surah_words)]       # the same words again
        with c.websocket_connect(f"/ws/session/{sid}") as ws:
            ws.receive_json()
            ws.send_bytes(PCM)
            ws.send_text(json.dumps({"type": "end"}))
            while True:
                if ws.receive_json()["type"] == "ended":
                    break
    s = _summary(sid)
    assert s.words_ok <= len(surah_words)


# ------------------------------------------------------------------ P0-5 failure


def test_an_asr_failure_still_finalises_and_tells_the_client(wired, new_session, surah_words):
    """B-5: an exception used to escape the handler — no summary, row stuck
    'active', nothing said to the reciter."""
    wired.lines = [" ".join(surah_words[:4])]
    wired.raise_on = 2
    sid = new_session()
    reasons = []
    with TestClient(app) as c:
        with c.websocket_connect(f"/ws/session/{sid}") as ws:
            ws.send_bytes(PCM)
            ws.receive_json()
            ws.send_bytes(PCM)                     # this one raises
            try:
                while True:
                    m = ws.receive_json()
                    if m["type"] == "ended":
                        reasons.append(m["reason"])
                        break
            except Exception:
                pass

    assert reasons == ["internal error"], "the client was not told the session failed"
    s = _summary(sid)
    assert s is not None, "a failed session must still leave a summary"
    assert s.words_ok == 4, "work done before the failure must be kept"

    db = SessionLocal()
    try:
        assert db.get(SessionRow, sid).status == "ended", "row left in 'active'"
    finally:
        db.close()


def test_a_malformed_control_frame_does_not_kill_the_session(wired, new_session, surah_words):
    wired.lines = [" ".join(surah_words[:4]), " ".join(surah_words[4:])]
    sid = new_session()
    with TestClient(app) as c:
        with c.websocket_connect(f"/ws/session/{sid}") as ws:
            ws.send_bytes(PCM)
            ws.receive_json()
            ws.send_text("{not valid json")
            m = ws.receive_json()
            assert m["type"] == "ended"
    s = _summary(sid)
    assert s is not None and s.words_ok == 4


# ------------------------------------------------------------------ admission


def test_a_finished_session_cannot_be_reopened(wired, new_session):
    sid = new_session()
    db = SessionLocal()
    try:
        db.get(SessionRow, sid).status = "ended"
        db.commit()
    finally:
        db.close()
    with TestClient(app) as c:
        with pytest.raises(Exception):
            with c.websocket_connect(f"/ws/session/{sid}"):
                pass
