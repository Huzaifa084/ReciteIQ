"""Partial-coverage matching (the ayah-7 fix).

`_best_span` compares a window against the WHOLE ayah, so below 0.75L no
candidate span exists and the score is 1.0 by construction. Ayah 7 of Al-Fatihah
is 63 ids, needing >=47 in one window (~7.8s unbroken) against live browser
windows of ~26 — it scored 1.0 in all six takes because it could not be scored,
not because it was mis-recited (docs/analysis-ayah7.md).
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
def flags():
    prev = (settings.phoneme_partial_coverage, settings.phoneme_revoke_late_miss)
    yield
    (settings.phoneme_partial_coverage, settings.phoneme_revoke_late_miss) = prev


def test_symmetric_scoring_cannot_score_a_short_window(fatiha):
    """Guard the premise: this is the cliff the fix exists for."""
    tr = PhonemeTracker(ref=fatiha)
    a7 = fatiha[6].ids
    assert len(a7) > 40, "ayah 7 should be the long one"
    assert tr._best_span(a7[:26], a7)[0] == 1.0, (
        "a 26-id window should be unscoreable against ayah 7 under _best_span")


def test_coverage_scores_a_partial_window(fatiha):
    """Asymmetric coverage gives a real number where _best_span gives 1.0."""
    tr = PhonemeTracker(ref=fatiha)
    a7 = fatiha[6].ids
    cer, covered = tr.coverage(a7[:26], a7)
    assert cer < 0.2, f"a clean 26-id prefix of ayah 7 should match well, got {cer:.3f}"
    assert 0.3 < covered < 0.5, f"26/63 should report ~0.41 coverage, got {covered:.3f}"


def test_coverage_still_rejects_the_wrong_ayah(fatiha):
    """Partial credit must not become 'matches anything'."""
    tr = PhonemeTracker(ref=fatiha)
    cer, _ = tr.coverage(fatiha[1].ids[:12], fatiha[6].ids)   # ayah 2 vs ayah 7
    assert cer > tr.MATCH_CER_MAX, f"unrelated content scored {cer:.3f}"


def test_partial_window_holds_position_without_crediting_or_flagging(fatiha):
    """THE fix. A window covering part of ayah 7 must neither credit it, nor
    advance the pointer, nor report anything missed."""
    settings.phoneme_partial_coverage = True
    tr = PhonemeTracker(ref=fatiha)
    for a in fatiha[:6]:                       # recite ayahs 1-6 normally
        tr.feed(a.ids)
    assert tr.pointer == 6, "expected to be sitting at ayah 7"

    ev = tr.feed(fatiha[6].ids[:26])           # only part of ayah 7 arrives

    assert tr.last_diag["outcome"] == "partial"
    assert tr.last_diag["partial_ayah"] == 7
    assert not [e for e in ev if e.type == EventType.MISSED_AYAH
                and e.state == EventState.CONFIRMED], "partial audio is not a mistake"
    assert not [e for e in ev if e.type == EventType.WORD_OK], "ayah 7 was not completed"
    assert tr.pointer == 6, "a partial match must not advance past the ayah"


def test_partial_then_full_completes_the_ayah(fatiha):
    """Once enough of the ayah arrives it credits normally."""
    settings.phoneme_partial_coverage = True
    tr = PhonemeTracker(ref=fatiha)
    for a in fatiha[:6]:
        tr.feed(a.ids)
    tr.feed(fatiha[6].ids[:26])                # partial
    ev = tr.feed(fatiha[6].ids)                # then the whole ayah
    ok = {e.payload["ayah"] for e in ev if e.type == EventType.WORD_OK
          and e.state == EventState.CONFIRMED}
    assert 7 in ok, "ayah 7 should be credited once fully recited"
    assert tr.pointer == 7


def test_disabled_by_default_reproduces_old_behaviour(fatiha):
    settings.phoneme_partial_coverage = False
    tr = PhonemeTracker(ref=fatiha)
    for a in fatiha[:6]:
        tr.feed(a.ids)
    tr.feed(fatiha[6].ids[:26])
    assert tr.last_diag["outcome"] == "no_match"
    from app.config import Settings
    assert Settings().phoneme_partial_coverage is False


def test_genuine_skip_still_reported_with_partial_on(fatiha):
    """Control: partial matching must not blind skip detection."""
    settings.phoneme_partial_coverage = True
    tr = PhonemeTracker(ref=fatiha)
    ev = tr.feed(fatiha[0].ids + fatiha[1].ids + fatiha[3].ids)
    missed = [e.payload["ayah"] for e in ev if e.type == EventType.MISSED_AYAH
              and e.state == EventState.CONFIRMED]
    assert missed == [3], f"expected ayah 3 missed, got {missed}"
