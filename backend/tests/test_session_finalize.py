"""The REST end endpoint must not destroy the summary the WS handler wrote.

Live failure: a browser session tracked 15 ayahs of Al-Baqarah (CER 0.047-0.375)
and the summary screen said "No recitation captured". The phoneme tracker
finalises its own summary when the socket closes and persists NO session_events
rows, but POST /sessions/{id}/end ran the Whisper finaliser, whose offline branch
aggregates from session_events, found zero, and overwrote the summary with zeros.
`ws_client` never calls that endpoint, so every CLI run looked correct.
"""

import uuid

import pytest

from app.config import settings
from app.db.models import Session as SessionRow
from app.db.models import SessionSummary
from app.db.session import SessionLocal


@pytest.fixture
def session_with_summary():
    """A finished phoneme session with a good summary already persisted."""
    db = SessionLocal()
    row = SessionRow(surah_id=1, start_ayah=1)
    db.add(row)
    db.commit()
    sid = row.id
    db.merge(SessionSummary(session_id=sid, duration_sec=42.0, words_ok=29,
                            words_missed=0, ayahs_missed=0, jumps=0,
                            detail={"errors": [], "mode": "phoneme_v1"}))
    db.commit()
    db.close()
    yield sid
    db = SessionLocal()
    try:
        if (s := db.get(SessionSummary, sid)) is not None:
            db.delete(s)
        if (r := db.get(SessionRow, sid)) is not None:
            db.delete(r)
        db.commit()
    finally:
        db.close()


def _summary(sid):
    db = SessionLocal()
    try:
        s = db.get(SessionSummary, sid)
        return None if s is None else s.words_ok
    finally:
        db.close()


def test_end_endpoint_preserves_phoneme_summary(session_with_summary):
    """THE live bug: ending the session must not zero what was tracked."""
    from app.api.routes import end_session
    prev = settings.tracker_mode
    try:
        settings.tracker_mode = "phoneme"
        end_session(session_with_summary)
    finally:
        settings.tracker_mode = prev
    assert _summary(session_with_summary) == 29, (
        "the REST end endpoint destroyed the summary written by the WS handler")


def test_end_endpoint_marks_the_row_ended(session_with_summary):
    from app.api.routes import end_session
    prev = settings.tracker_mode
    try:
        settings.tracker_mode = "phoneme"
        end_session(session_with_summary)
    finally:
        settings.tracker_mode = prev
    db = SessionLocal()
    try:
        assert db.get(SessionRow, session_with_summary).status == "ended"
    finally:
        db.close()


def test_offline_aggregation_never_clobbers_an_existing_summary(session_with_summary):
    """Defence in depth: even routed to the Whisper finaliser, an aggregation
    that found no events must not overwrite a summary someone else wrote."""
    from app.ws.session import finalize_session
    finalize_session(session_with_summary)
    assert _summary(session_with_summary) == 29


def test_offline_aggregation_still_writes_when_no_summary_exists():
    """It must remain able to create a summary for a genuinely empty session."""
    from app.ws.session import finalize_session
    db = SessionLocal()
    row = SessionRow(surah_id=1, start_ayah=1)
    db.add(row); db.commit()
    sid = row.id
    db.close()
    try:
        finalize_session(sid)
        assert _summary(sid) == 0, "expected a zero summary to be created"
    finally:
        db = SessionLocal()
        try:
            if (s := db.get(SessionSummary, sid)) is not None:
                db.delete(s)
            if (r := db.get(SessionRow, sid)) is not None:
                db.delete(r)
            db.commit()
        finally:
            db.close()
