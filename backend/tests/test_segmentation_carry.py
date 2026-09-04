"""Segmentation / partial-ayah handling (docs/experiment-segmentation.md).

A window is bounded by time, so it can be SHORTER than an ayah, and a sub-ayah
fragment can never match a whole-ayah reference. Measured on identical audio,
credited ayahs fell 7/7 -> 6/7 -> 4/7 -> 3/7 as windows shrank 31s -> 4.0s ->
2.5s -> 1.5s.

These tests drive the fragmentation at ID level rather than through audio: the
failure is purely about window length versus reference length, so synthetic
fragments reproduce it deterministically without a voice recording in the repo.
"""

import pytest

from app.config import settings
from app.engine.events import Event, EventState, EventType
from app.engine.phoneme_tracker import PhonemeTracker, RefAyah
from app.ws.phoneme_session import CarryBuffer, carry_should_reset

AYAH_LEN = 12          # reference length; must exceed the tracker's 4-id floor
N_AYAHS = 5


@pytest.fixture(autouse=True)
def flags():
    """Every test sets the flags it needs; restore production defaults after."""
    prev = (settings.phoneme_carry_forward, settings.phoneme_revoke_late_miss,
            settings.phoneme_carry_max_ids)
    yield
    (settings.phoneme_carry_forward, settings.phoneme_revoke_late_miss,
     settings.phoneme_carry_max_ids) = prev


def _refs(n=N_AYAHS):
    out = []
    for i in range(1, n + 1):
        ids = [i * 20 + j for j in range(AYAH_LEN)]     # disjoint per ayah
        out.append(RefAyah(ayah_id=i, surah=99, number=i, ids=ids,
                           word_refs=[{"surah": 99, "ayah": i, "position": 1,
                                       "word_id": i, "idx": i - 1}]))
    return out


def _fragment(ids, n_parts):
    step = (len(ids) + n_parts - 1) // n_parts
    return [ids[i:i + step] for i in range(0, len(ids), step)]


def _session(ref, windows, carry_on):
    """Mirror the session loop's carry handling (phoneme_session.py)."""
    settings.phoneme_carry_forward = carry_on
    tr = PhonemeTracker(ref=ref)
    carry = CarryBuffer()
    events = []
    for w in windows:
        match_ids = (carry.prefix() + w) if carry_on else w
        ev = tr.feed(match_ids)
        events += ev
        if carry_on:
            if carry_should_reset(ev, tr.last_diag):
                carry.reset()
            else:
                carry.extend(w)
    credited = sorted({e.payload["ayah"] for e in events
                       if e.type == EventType.WORD_OK and e.state == EventState.CONFIRMED})
    missed = sorted({e.payload["ayah"] for e in events
                     if e.type == EventType.MISSED_AYAH and e.state == EventState.CONFIRMED})
    revoked = sorted({e.payload["ayah"] for e in events
                      if e.type == EventType.MISSED_AYAH and e.state == EventState.REVOKED})
    return credited, missed, revoked, carry


# ---- fragmentation recovery -----------------------------------------------

@pytest.mark.parametrize("n_parts,label", [(2, "~4.0s"), (3, "~2.5s"), (4, "~1.5s")])
def test_carry_recovers_fragmented_ayahs(n_parts, label):
    """Splitting each ayah into n sub-ayah windows: baseline credits nothing
    because no single fragment reaches the reference, carry credits them all."""
    ref = _refs()
    windows = [f for a in ref for f in _fragment(a.ids, n_parts)]

    base_credited, base_missed, _, _ = _session(ref, windows, carry_on=False)
    carry_credited, carry_missed, _, _ = _session(ref, windows, carry_on=True)

    assert base_credited == [], f"{label}: baseline unexpectedly matched fragments"
    assert carry_credited == [a.number for a in ref], (
        f"{label}: carry credited {carry_credited}, expected all {N_AYAHS} ayahs")
    assert carry_missed == [], f"{label}: carry invented misses {carry_missed}"


def test_clean_recitation_unchanged_by_carry():
    """Whole-ayah windows must behave identically with the flag on or off — the
    fix may not cost anything on audio that already worked."""
    ref = _refs()
    windows = [a.ids for a in ref]
    assert _session(ref, windows, carry_on=False)[:3] == \
           _session(ref, windows, carry_on=True)[:3]


def test_real_skip_still_reported_with_carry():
    """Carry must not blind the detector: reciting ayahs 1,2,4 inside one window
    still reports ayah 3 missed."""
    ref = _refs()
    window = ref[0].ids + ref[1].ids + ref[3].ids
    credited, missed, _, _ = _session(ref, [window], carry_on=True)
    assert missed == [ref[2].number]
    assert ref[3].number in credited


# ---- late-match revocation ------------------------------------------------

def test_late_miss_revoked_when_ayah_later_matches():
    """An ayah flagged missed, then proved recited by a later window, must have
    the miss WITHDRAWN. Measured with carry at 4.0s fragmentation: all 7 ayahs
    credited yet one still showed missed, because nothing ever revoked it."""
    settings.phoneme_revoke_late_miss = True
    ref = _refs()
    tr = PhonemeTracker(ref=ref)
    # one window covering ayahs 1,2,4 -> ayah 3 confirmed missed
    ev = tr.feed(ref[0].ids + ref[1].ids + ref[3].ids)
    assert [e.payload["ayah"] for e in ev
            if e.type == EventType.MISSED_AYAH and e.state == EventState.CONFIRMED] \
        == [ref[2].number]
    # the reciter goes back and recites ayah 3 after all
    ev2 = tr.feed(ref[2].ids)
    revoked = [e for e in ev2 if e.type == EventType.MISSED_AYAH
               and e.state == EventState.REVOKED]
    assert revoked, "a proven-recited ayah must have its MISSED_AYAH revoked"
    assert revoked[0].payload["ayah"] == ref[2].number
    assert revoked[0].refers_to is not None, "revocation must reference the miss"


def test_late_miss_not_revoked_when_flag_off():
    """Production default: behaviour unchanged."""
    settings.phoneme_revoke_late_miss = False
    ref = _refs()
    tr = PhonemeTracker(ref=ref)
    tr.feed(ref[0].ids + ref[1].ids + ref[3].ids)
    ev2 = tr.feed(ref[2].ids)
    assert not [e for e in ev2 if e.type == EventType.MISSED_AYAH
                and e.state == EventState.REVOKED]


# ---- carry buffer lifecycle ----------------------------------------------

def test_carry_resets_after_confident_chain():
    ref = _refs()
    windows = _fragment(ref[0].ids, 2) + [ref[1].ids]
    _, _, _, carry = _session(ref, windows, carry_on=True)
    assert len(carry) == 0, "carry must be dropped once a window chains"


def test_carry_resets_after_confirmed_jump():
    """A confirmed jump relocates the pointer outright, so speculative carry is
    stale and must be dropped."""
    diag = {"outcome": "no_match"}
    jump = Event(EventType.MUTASHABEH_JUMP, EventState.CONFIRMED, {"dest_surah": 112})
    assert carry_should_reset([jump], diag) is True
    prov = Event(EventType.MUTASHABEH_JUMP, EventState.PROVISIONAL, {"dest_surah": 112})
    assert carry_should_reset([prov], diag) is False, "provisional is not confidence"
    assert carry_should_reset([], {"outcome": "chained"}) is True
    assert carry_should_reset([], {"outcome": "no_match"}) is False


def test_carry_reset_on_session_end():
    c = CarryBuffer(cap=100)
    c.extend([1, 2, 3])
    assert len(c) == 3
    c.reset()
    assert len(c) == 0 and c.prefix() == []


def test_carry_never_exceeds_cap():
    """The safety cap bounds unbounded accumulation during a long unplaced run,
    keeping the MOST RECENT ids."""
    c = CarryBuffer(cap=10)
    for i in range(20):
        c.extend([i] * 3)
        assert len(c) <= 10, f"carry grew to {len(c)}, cap is 10"
    assert c.prefix() == c.prefix()[-10:]
    assert c.prefix()[-1] == 19, "cap must keep the newest ids, not the oldest"


def test_carry_cap_defaults_from_config():
    settings.phoneme_carry_max_ids = 7
    c = CarryBuffer()
    c.extend(list(range(50)))
    assert len(c) == 7


def test_flags_are_off_by_default():
    """Production must be unchanged until the A/B says otherwise."""
    from app.config import Settings
    fresh = Settings()
    assert fresh.phoneme_carry_forward is False
    assert fresh.phoneme_revoke_late_miss is False
    assert fresh.phoneme_silence_cut_sec == 0.5
