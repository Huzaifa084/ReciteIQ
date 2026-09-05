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


class _W:
    """Minimal RefWord stand-in: the denominator only needs idx and ayah_id."""
    def __init__(self, idx, ayah_id):
        self.idx, self.ayah_id = idx, ayah_id


def _live(ref=None):
    live = LiveSession.__new__(LiveSession)
    live.counts = {"words_ok": 0, "words_missed": 0, "ayahs_missed": 0, "jumps": 0,
                   "repeats": 0, "uncertain": 0, "words_expected": 0}
    live.detail = []
    live._ok_idx = set()
    live._missed_word_idx = set()
    live._missed_ayah_idx = set()
    if ref is not None:
        live.ref = ref
    return live


def _ev(t, state=EventState.CONFIRMED, **payload):
    return Event(t, state, payload)


def test_counts_separate_every_category(ref_fatiha):
    live = _live()
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
                           "jumps": 1, "repeats": 1, "uncertain": 1,
                           # ayah 3 has no ref here, so only the word verdicts
                           # contribute; the denominator is covered in its own tests
                           "words_expected": 3}


def test_benign_events_are_not_filed_as_errors(ref_fatiha):
    """REPEAT and UNCERTAIN must stay out of `detail.errors`, which drives the
    red 'things to review' list."""
    live = _live()
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
    live = _live()
    live.record([_ev(EventType.WORD_OK, idx=i) for i in (0, 1, 2)])
    live.record([_ev(EventType.WORD_OK, idx=i) for i in (1, 2, 3)])   # ayah repeated
    assert live.counts["words_ok"] == 4


def test_provisional_events_are_not_counted(ref_fatiha):
    live = _live()
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


# --------------------------------------------------- accuracy denominator (B-2)


def test_skipped_ayah_words_enter_the_denominator():
    """The defect this test exists for: words inside a skipped ayah aggregate
    into MISSED_AYAH and never reach words_missed. Deriving accuracy from
    words_ok + words_missed therefore reported 100% for a recitation that
    skipped three ayahs of Al-Fatihah — verified against live production data.
    """
    # ayah 7 has four words (idx 5..8); the reciter said idx 0..4 and skipped it
    ref = [_W(i, 1) for i in range(5)] + [_W(i, 7) for i in range(5, 9)]
    live = _live(ref)
    live.record([_ev(EventType.WORD_OK, idx=i) for i in range(5)])
    live.record([_ev(EventType.MISSED_AYAH, ayah=7, ayah_id=7)])

    assert live.counts["words_ok"] == 5
    assert live.counts["words_missed"] == 0      # exactly the trap
    assert live.counts["words_expected"] == 9    # 5 recited + 4 skipped
    assert live.counts["words_expected"] > live.counts["words_ok"]


def test_a_session_with_a_skipped_ayah_cannot_report_100_percent():
    ref = [_W(i, 1) for i in range(5)] + [_W(i, 7) for i in range(5, 9)]
    live = _live(ref)
    live.record([_ev(EventType.WORD_OK, idx=i) for i in range(5)])
    live.record([_ev(EventType.MISSED_AYAH, ayah=7, ayah_id=7)])

    pct = round(100.0 * live.counts["words_ok"] / live.counts["words_expected"])
    assert pct < 100, f"skipped ayah still reported {pct}%"
    assert pct == 56


def test_missed_words_also_enter_the_denominator():
    live = _live([_W(i, 1) for i in range(4)])
    live.record([_ev(EventType.WORD_OK, idx=0), _ev(EventType.WORD_OK, idx=1)])
    live.record([_ev(EventType.MISSED_WORD, idx=2)])
    assert live.counts["words_expected"] == 3
    assert round(100.0 * 2 / 3) == 67


def test_uncertain_stays_out_of_both_sides():
    """An unconfirmed word is our uncertainty, not the reciter's mistake — it
    must not quietly lower their accuracy."""
    live = _live([_W(i, 1) for i in range(3)])
    live.record([_ev(EventType.WORD_OK, idx=0), _ev(EventType.WORD_OK, idx=1)])
    live.record([_ev(EventType.UNCERTAIN, idx=2, ayah=1)])
    assert live.counts["words_expected"] == 2
    assert live.counts["uncertain"] == 1
    assert round(100.0 * live.counts["words_ok"] / live.counts["words_expected"]) == 100


def test_revoked_verdict_leaves_the_denominator():
    """A withdrawn MISSED_WORD must not keep penalising the denominator."""
    live = _live([_W(i, 1) for i in range(4)])
    live.record([_ev(EventType.WORD_OK, idx=0)])
    miss = _ev(EventType.MISSED_WORD, idx=1)
    live.record([miss])
    assert live.counts["words_expected"] == 2
    live.record([Event(EventType.MISSED_WORD, EventState.REVOKED,
                       {"idx": 1}, refers_to=miss.event_id)])
    assert live.counts["words_missed"] == 0
    assert live.counts["words_expected"] == 1
