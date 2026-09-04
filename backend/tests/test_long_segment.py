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
from app.engine.events import EventType


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
