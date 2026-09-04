"""The exact Al-Fatihah 1:1 -> 1:3 anchor case, on the REAL references.

1:1 = بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ   (27 ids)
1:3 =            الرَّحْمَٰنِ الرَّحِيمِ   (16 ids)

1:3 is literally the last two words of 1:1, and its reference sits INSIDE ayah
1's at CER 0.125 against a 0.45 gate. So the first window of a session, holding
only the basmalah, can legitimately chain to ayah 3 — and the old rule then
reported ayahs 1-2 as missed. Observed live in 2 of 6 browser takes.

Synthetic references cannot reproduce this: it depends on one real ayah being a
substring of another, so these tests load surah 1 from the database.
"""

import pytest

from app.config import settings
from app.db.repo import load_phoneme_reference
from app.db.session import SessionLocal
from app.engine.events import EventState, EventType
from app.engine.phoneme_tracker import PhonemeTracker


@pytest.fixture(scope="module")
def fatiha():
    db = SessionLocal()
    try:
        ref = load_phoneme_reference(db, 1)
    finally:
        db.close()
    if len(ref) < 7:
        pytest.skip("Al-Fatihah phoneme refs not built")
    return ref


@pytest.fixture(autouse=True)
def revoke_on():
    prev = settings.phoneme_revoke_late_miss
    settings.phoneme_revoke_late_miss = True
    yield
    settings.phoneme_revoke_late_miss = prev


def of(events, t, state=None):
    return [e for e in events if e.type == t and (state is None or e.state == state)]


def test_ayah3_reference_really_is_inside_ayah1(fatiha):
    """Guard the premise: if this stops holding the tests below are meaningless."""
    tr = PhonemeTracker(ref=fatiha)
    cer, _s, _e = tr._best_span(fatiha[0].ids, fatiha[2].ids)
    assert cer <= tr.MATCH_CER_MAX, (
        f"1:3 no longer matches inside 1:1 (CER {cer:.3f}) — the anchor case has "
        f"changed and these tests need revisiting")


def test_first_window_anchoring_on_ayah3_creates_no_false_miss(fatiha):
    """THE live bug. The session's first window chains ayah 3; ayahs 1-2 must be
    UNCERTAIN, never MISSED — nothing yet establishes where the reciter began."""
    tr = PhonemeTracker(ref=fatiha)
    ev = tr.feed(fatiha[2].ids)                      # first window -> ayah 3

    assert tr.last_diag["matched_ayahs"] == [3], "expected the anchor case"
    assert not of(ev, EventType.MISSED_AYAH, EventState.CONFIRMED), (
        "ayahs 1-2 were reported missed although nothing establishes that the "
        "recitation started at ayah 3")
    unc = {e.payload["ayah"] for e in of(ev, EventType.UNCERTAIN, EventState.PROVISIONAL)}
    assert unc == {1, 2}, f"expected ayahs 1 and 2 uncertain, got {unc}"


def test_next_window_matching_ayah2_resolves_the_uncertainty(fatiha):
    """The reciter was on ayah 2 all along: crediting it must withdraw its
    uncertainty and leave no error behind."""
    tr = PhonemeTracker(ref=fatiha)
    tr.feed(fatiha[2].ids)                           # anchor on ayah 3
    ev = tr.feed(fatiha[1].ids)                      # ...then ayah 2 arrives

    ok = {e.payload["ayah"] for e in of(ev, EventType.WORD_OK, EventState.CONFIRMED)}
    assert 2 in ok, "ayah 2 should be credited"
    revoked = {e.payload["ayah"] for e in of(ev, EventType.UNCERTAIN, EventState.REVOKED)}
    assert 2 in revoked, "ayah 2's uncertainty should be withdrawn once credited"
    assert not of(ev, EventType.MISSED_AYAH, EventState.CONFIRMED)


def test_genuine_skip_of_ayah3_still_reported(fatiha):
    """Control: the fix must not blind the detector. One window covering ayahs
    1, 2 and 4 is positive evidence that ayah 3 was passed over."""
    tr = PhonemeTracker(ref=fatiha)
    ev = tr.feed(fatiha[0].ids + fatiha[1].ids + fatiha[3].ids)
    missed = of(ev, EventType.MISSED_AYAH, EventState.CONFIRMED)
    assert [e.payload["ayah"] for e in missed] == [3], (
        f"expected exactly ayah 3 missed, got {[e.payload['ayah'] for e in missed]}")


def test_skip_after_a_valid_anchor_is_still_a_miss(fatiha):
    """Normal skip detection must resume once an anchor exists: recite ayah 1,
    then jump to ayah 4, and ayahs 2-3 are genuinely skipped."""
    tr = PhonemeTracker(ref=fatiha)
    tr.feed(fatiha[0].ids)                           # valid anchor at ayah 1
    ev = tr.feed(fatiha[3].ids)                      # ...then ayah 4
    missed = {e.payload["ayah"] for e in of(ev, EventType.MISSED_AYAH, EventState.CONFIRMED)}
    assert missed == {2, 3}, f"expected ayahs 2-3 missed after a valid anchor, got {missed}"


def test_late_match_revokes_a_standing_miss(fatiha):
    """The other half of the live failure: ayah 2 was flagged missed and then
    credited by the next window, and the red stood because nothing revoked it."""
    tr = PhonemeTracker(ref=fatiha)
    tr.feed(fatiha[0].ids)                           # anchor
    ev1 = tr.feed(fatiha[3].ids)                     # skip to ayah 4 -> 2,3 missed
    assert {e.payload["ayah"] for e in of(ev1, EventType.MISSED_AYAH, EventState.CONFIRMED)} == {2, 3}
    ev2 = tr.feed(fatiha[1].ids)                     # the reciter goes back to ayah 2
    revoked = {e.payload["ayah"] for e in of(ev2, EventType.MISSED_AYAH, EventState.REVOKED)}
    assert revoked == {2}, f"ayah 2's miss should be withdrawn, got {revoked}"


def test_revocation_is_enabled_by_default():
    from app.config import Settings
    assert Settings().phoneme_revoke_late_miss is True
    assert Settings().phoneme_carry_forward is False    # unchanged
