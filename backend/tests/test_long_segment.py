"""Long-segment regression: a faithful but LONG window must not be blocked.

Al-Inshiqaq (84) live: the text path credited 7/25 ayahs even though the ASR
transcript scored WER 0.0654. Cause was the segment-level pre-pass in
`feed_segment`, which counted hits against a FIXED pointer. `find_match` only
searches [pointer-back, pointer+fwd) = 20 ref words, so a 34-token window could
score at most 20/34 = 0.59 and fell under the 0.5 block threshold *for being
long*. The pointer then froze and every later window really was off-reference —
7/25, a cascade from one bad ratio.
"""

import pytest

from app.config import settings
from app.db.repo import load_reference
from app.engine.detector import RecitationTracker
from app.engine.events import EventState, EventType


@pytest.fixture(scope="module")
def ref_inshiqaq(db):
    return load_reference(db, 84)


def _ok_words(events):
    """Ref indices confirmed WORD_OK (an ayah is 'credited' when all of its
    words appear here — the same rule the live summary uses)."""
    return {e.payload["idx"] for e in events if e.type == EventType.WORD_OK}


def _full_ayahs(ref, ok: set[int]) -> set[int]:
    per: dict[int, list[int]] = {}
    for w in ref:
        per.setdefault(w.ayah, []).append(w.idx)
    return {a for a, idxs in per.items() if all(i in ok for i in idxs)}


def test_long_faithful_segment_is_not_blocked(ref_inshiqaq):
    """One window spanning many ayahs, perfectly recited, must be fully credited."""
    tr = RecitationTracker(ref_inshiqaq, preamble=False)
    window = [w.norm for w in ref_inshiqaq if w.ayah <= 9]   # ~34 words, 9 ayahs
    assert len(window) > settings.align_window_fwd + settings.align_window_back
    ev = tr.feed_segment(window)
    assert _full_ayahs(ref_inshiqaq, _ok_words(ev)) == set(range(1, 10))
    assert tr.pointer == len(window)


def test_whole_surah_in_long_windows(ref_inshiqaq):
    """The live failure shape: 25 ayahs delivered as four ~30-token windows."""
    words = list(ref_inshiqaq)
    windows = [words[i:i + 30] for i in range(0, len(words), 30)]
    tr = RecitationTracker(ref_inshiqaq, preamble=False)
    ok: set[int] = set()
    for w in windows:
        ok |= _ok_words(tr.feed_segment([x.norm for x in w]))
    assert _full_ayahs(ref_inshiqaq, ok) == set(range(1, 26))


def test_off_reference_long_segment_is_still_blocked(ref_inshiqaq, ref_fatiha):
    """The guard the pre-pass exists for must survive: a segment that belongs
    to a different surah advances nothing, however long it is."""
    tr = RecitationTracker(ref_inshiqaq, preamble=False)
    tr.feed_segment([w.norm for w in ref_inshiqaq if w.ayah <= 3])
    before = tr.pointer
    ev = tr.feed_segment([w.norm for w in ref_fatiha if w.ayah in (6, 7)])
    assert tr.pointer == before
    assert not _ok_words(ev)


def test_prepass_ratio_scores_a_long_faithful_window_near_one(ref_inshiqaq):
    """Direct unit check on the counter itself — the fixed-pointer version
    capped this at (fwd+back)/len; the dry run must not."""
    tr = RecitationTracker(ref_inshiqaq, preamble=False)
    toks = [w.norm for w in ref_inshiqaq if w.ayah <= 9]
    assert tr._prepass_hits(toks) == len(toks)


# --------------------------------------------------------- mutashabeh shift


@pytest.fixture(scope="module")
def ref_kafirun(db):
    return load_reference(db, 109)


def test_skipped_ayah_is_one_event_when_the_next_ayah_starts_the_same(ref_kafirun):
    """Al-Kafirun 3 -> 5, a named release gate.

    Ayahs 4 and 5 both open with وَلَا, so the resumed ayah's opening word
    matches the SKIPPED ayah's opening word and the gap comes out as 4:2..5:1 —
    a suffix plus a prefix, never 'a whole ayah'. That produced five scattered
    MISSED_WORDs instead of one MISSED_AYAH.
    """
    tr = RecitationTracker(ref_kafirun, preamble=False)
    ev = []
    for ayah in (1, 2, 3, 5, 6):                       # ayah 4 skipped
        ev += tr.feed_segment([w.norm for w in ref_kafirun if w.ayah == ayah])

    missed_ayahs = {e.payload["ayah"] for e in ev
                    if e.type == EventType.MISSED_AYAH
                    and e.state == EventState.CONFIRMED}
    missed_words = [e for e in ev if e.type == EventType.MISSED_WORD
                    and e.state == EventState.CONFIRMED]
    assert missed_ayahs == {4}
    assert not missed_words
    # the resumed ayah was actually recited — it must be credited, not eaten
    ok = _ok_words(ev)
    assert _full_ayahs(ref_kafirun, ok) >= {5, 6}


def test_rebalance_does_not_fire_without_a_textual_duplicate(ref_inshiqaq):
    """The shift is only undone when the displaced words are genuinely identical;
    an ordinary mid-ayah skip must still report words, not a whole ayah."""
    tr = RecitationTracker(ref_inshiqaq, preamble=False)
    words = [w for w in ref_inshiqaq if w.ayah <= 4]
    said = [w.norm for w in words if not (w.ayah == 2 and w.position == 2)]
    ev = tr.feed_segment(said)
    ev += tr.feed_segment([w.norm for w in ref_inshiqaq if w.ayah in (5, 6)])
    missed_ayahs = {e.payload["ayah"] for e in ev
                    if e.type == EventType.MISSED_AYAH
                    and e.state == EventState.CONFIRMED}
    assert 2 not in missed_ayahs


def test_near_miss_word_is_uncertain_not_silent(ref_inshiqaq):
    """A word the ASR nearly got is neither confirmed nor an error — it must
    still say something, or the Mushaf leaves it grey and looks stalled."""
    tr = RecitationTracker(ref_inshiqaq, preamble=False)
    from rapidfuzz import fuzz
    from app.config import settings

    words = [w for w in ref_inshiqaq if w.ayah <= 3]
    said = [w.norm for w in words]
    target = words[4]
    # A token in the band that is "an attempt" but not "a match": above the
    # attribution floor, below the accept threshold. Built by search so the test
    # cannot silently drift to one side of either bound.
    def _candidates(w):
        for i in range(len(w)):
            yield w[:i] + "ق" + w[i + 1:]
        for k in range(1, len(w)):
            yield w[:k] + "ق" * (len(w) - k)

    garbled = next(
        c for c in _candidates(target.norm)
        if settings.garbled_attribution_min <= fuzz.ratio(c, target.norm)
        < settings.match_score_min
    )
    said[4] = garbled
    ev = tr.feed_segment(said)
    unc = [e for e in ev if e.type == EventType.UNCERTAIN
           and e.payload.get("idx") == target.idx]
    assert unc, "a heard-but-unconfirmed word must emit UNCERTAIN"
    assert not [e for e in ev if e.type == EventType.MISSED_WORD
                and e.state == EventState.CONFIRMED]
