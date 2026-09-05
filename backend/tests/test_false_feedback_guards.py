"""Guards against the system telling a reciter something untrue.

A false "you missed this" is the worst output this product has: it corrects
someone who was right. These tests pin the three mechanisms that produced one.
"""

import pytest

from app.config import settings
from app.db.repo import load_reference
from app.engine.detector import RecitationTracker
from app.engine.events import Event, EventState, EventType


@pytest.fixture(scope="module")
def ref_kafirun(db):
    return load_reference(db, 109)


def _confirmed(ev, t):
    return [e for e in ev if e.type == t and e.state == EventState.CONFIRMED]


# ------------------------------------------------------------------- B-6


def test_a_gated_window_does_not_confirm_a_miss(ref_kafirun):
    """A window we could not transcribe is a blind spot, not silence.

    The words that would have cleared a pending miss may have been spoken into
    it, so confirming across the gap accuses a reciter on evidence we never
    heard. `hold_confirmations` resets the countdown instead.
    """
    tr = RecitationTracker(ref_kafirun, preamble=False)
    words = [w.norm for w in ref_kafirun]
    tr.feed_segment(words[:3])

    # a dropped word raises a provisional miss
    ev = tr.feed_segment([words[4], words[5]])
    assert tr.pending, "expected a pending miss to test against"

    # the next window never reaches the recogniser
    tr.hold_confirmations()
    for pend in tr.pending.values():
        assert pend.confirms_left == settings.confirm_window_k, \
            "the countdown must restart, not continue through the blind spot"


def test_hold_confirmations_is_a_delay_not_an_amnesty(ref_kafirun):
    """Holding must not lose a real miss — enough later evidence still confirms."""
    tr = RecitationTracker(ref_kafirun, preamble=False)
    words = [w.norm for w in ref_kafirun]
    tr.feed_segment(words[:3])
    tr.feed_segment([words[4], words[5]])
    tr.hold_confirmations()
    ev = []
    for w in words[6:]:
        ev += tr.feed_segment([w])
    assert _confirmed(ev, EventType.MISSED_WORD), \
        "a genuine miss must still be reported once the evidence arrives"


# ------------------------------------------------------------------- B-9


class _AlwaysJumps:
    """Relocation that keeps pointing at the same distant destination."""

    def search(self, tokens):
        return [(9999, 55, 40, 0.99)]


def test_one_divergence_produces_one_jump(ref_kafirun):
    """Measured before the fix: a single skipped ayah in Al-Baqarah confirmed 58
    MUTASHABEH_JUMP events. The banner would flap and the summary would fill
    with jumps the reciter never made."""
    tr = RecitationTracker(ref_kafirun, relocation=_AlwaysJumps(), preamble=False)
    ev = []
    for _ in range(12):
        ev += tr.feed_segment(["زقزق", "زقزق", "زقزق", "زقزق", "زقزق"])
    jumps = _confirmed(ev, EventType.MUTASHABEH_JUMP)
    assert len(jumps) == 1, f"expected one verdict per divergence, got {len(jumps)}"


def test_repositioning_makes_a_destination_news_again(ref_kafirun):
    """After the reciter accepts a move, arriving there later is a new event."""
    tr = RecitationTracker(ref_kafirun, relocation=_AlwaysJumps(), preamble=False)
    for _ in range(12):
        tr.feed_segment(["زقزق"] * 5)
    tr.reposition(0)
    ev = []
    for _ in range(12):
        ev += tr.feed_segment(["زقزق"] * 5)
    assert _confirmed(ev, EventType.MUTASHABEH_JUMP), \
        "a jump after repositioning is a genuinely new divergence"
