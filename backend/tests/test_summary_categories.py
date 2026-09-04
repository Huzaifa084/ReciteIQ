"""The summary must distinguish correct / missed word / missed ayah / repeat /
jump / unplaced — and must not file the benign ones as errors.

Before this, `repeats` was not counted at all and `uncertain` was buried in the
JSON detail blob where the summary view could not read it, so a reciter who
restarted an ayah saw exactly the same screen as one who recited it once.
"""

import uuid

import pytest

from app.db.models import Session as SessionRow, SessionSummary
from app.db.session import SessionLocal
from app.engine.events import Event, EventState, EventType
from app.ws.session import LiveSession


def _ev(t, state=EventState.CONFIRMED, **payload):
    return Event(t, state, payload)


def test_counts_separate_every_category(ref_fatiha):
    live = LiveSession.__new__(LiveSession)
    live.counts = {"words_ok": 0, "words_missed": 0, "ayahs_missed": 0, "jumps": 0,
                   "repeats": 0, "uncertain": 0}
    live.detail = []
    live._ok_idx = set()
    live.record([
        _ev(EventType.WORD_OK, idx=0),
        _ev(EventType.WORD_OK, idx=1),
        _ev(EventType.MISSED_WORD, idx=2),
        _ev(EventType.MISSED_AYAH, ayah=3, ayah_id=3),
        _ev(EventType.REPEAT, idx=1),
        _ev(EventType.MUTASHABEH_JUMP, dest_surah=2, dest_ayah=5),
        _ev(EventType.UNCERTAIN, ayah=4),
    ])
    assert live.counts == {"words_ok": 2, "words_missed": 1, "ayahs_missed": 1,
                           "jumps": 1, "repeats": 1, "uncertain": 1}


def test_benign_events_are_not_filed_as_errors(ref_fatiha):
    """REPEAT and UNCERTAIN must stay out of `detail.errors`, which drives the
    red 'things to review' list."""
    live = LiveSession.__new__(LiveSession)
    live.counts = {"words_ok": 0, "words_missed": 0, "ayahs_missed": 0, "jumps": 0,
                   "repeats": 0, "uncertain": 0}
    live.detail = []
    live._ok_idx = set()
    live.record([
        _ev(EventType.REPEAT, idx=1),
        _ev(EventType.UNCERTAIN, ayah=4),
    ])
    assert live.detail == []
    assert live.counts["repeats"] == 1
    assert live.counts["uncertain"] == 1


def test_words_ok_counts_distinct_words(ref_fatiha):
    """A rewind clears the matched set, so the re-recited words are credited
    again. Counting WORD_OK events reported 109 words for a 107-word surah."""
    live = LiveSession.__new__(LiveSession)
    live.counts = {"words_ok": 0, "words_missed": 0, "ayahs_missed": 0, "jumps": 0,
                   "repeats": 0, "uncertain": 0}
    live.detail = []
    live._ok_idx = set()
    live.record([_ev(EventType.WORD_OK, idx=i) for i in (0, 1, 2)])
    live.record([_ev(EventType.WORD_OK, idx=i) for i in (1, 2, 3)])   # ayah repeated
    assert live.counts["words_ok"] == 4


def test_provisional_events_are_not_counted(ref_fatiha):
    live = LiveSession.__new__(LiveSession)
    live.counts = {"words_ok": 0, "words_missed": 0, "ayahs_missed": 0, "jumps": 0,
                   "repeats": 0, "uncertain": 0}
    live.detail = []
    live._ok_idx = set()
    live.record([
        _ev(EventType.MISSED_WORD, EventState.PROVISIONAL, idx=2),
        _ev(EventType.REPEAT, EventState.PROVISIONAL, idx=1),
    ])
    assert live.counts["words_missed"] == 0
    assert live.counts["repeats"] == 0


def test_summary_row_persists_the_new_columns():
    """The columns exist and round-trip — the migration is real, not just a model
    attribute the API would read as None."""
    db = SessionLocal()
    sid = uuid.uuid4()
    try:
        db.add(SessionRow(id=sid, surah_id=1, start_ayah=1, status="active"))
        db.commit()
        db.merge(SessionSummary(session_id=sid, words_ok=5, repeats=2, uncertain=3,
                                detail={"errors": []}))
        db.commit()
        db.expire_all()
        got = db.get(SessionSummary, sid)
        assert (got.repeats, got.uncertain) == (2, 3)
    finally:
        db.query(SessionSummary).filter_by(session_id=sid).delete()
        db.query(SessionRow).filter_by(id=sid).delete()
        db.commit()
        db.close()
