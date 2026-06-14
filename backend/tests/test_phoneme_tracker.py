"""v1 conservative ayah-tracker tests (encoder-CTC ID space).

Deterministic: uses stored reference phoneme_ids as the query (reference-reciter
case) plus controlled perturbations, so no audio/model is needed at test time.
Requires the pilot surahs (1, 78, 112) to have phoneme_ids — built by
scripts.build_phoneme_refs. Skips cleanly if absent.
"""

import random

import pytest

from app.db.repo import load_phoneme_reference
from app.db.session import SessionLocal
from app.engine.phoneme_index import PhonemeIndex
from app.engine.phoneme_tracker import PhonemeTracker
from app.engine.events import EventState, EventType


@pytest.fixture(scope="module")
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture(scope="module")
def ref78(db):
    ref = load_phoneme_reference(db, 78)
    if len(ref) < 5:
        pytest.skip("Surah 78 phoneme refs not built yet")
    return ref


def types(events, t, state=None):
    return [e for e in events if e.type == t and (state is None or e.state == state)]


def test_perfect_recitation_all_ayahs_progress(ref78):
    tr = PhonemeTracker(ref=ref78)
    ev = []
    for a in ref78[:6]:
        ev += tr.feed(a.ids)
    # every fed ayah's words turn green (soft progress); no misses, no jumps
    assert types(ev, EventType.WORD_OK)
    assert not types(ev, EventType.MISSED_AYAH, EventState.CONFIRMED)
    assert not types(ev, EventType.MUTASHABEH_JUMP)
    assert tr.pointer >= 6


def test_skipped_ayah_detected(ref78):
    tr = PhonemeTracker(ref=ref78)
    tr.feed(ref78[0].ids)            # ayah 1
    tr.feed(ref78[1].ids)            # ayah 2
    ev = tr.feed(ref78[3].ids)       # jump to ayah 4 → ayah 3 skipped
    missed = types(ev, EventType.MISSED_AYAH, EventState.CONFIRMED)
    assert len(missed) == 1 and missed[0].payload["ayah"] == ref78[2].number


def test_repeat_detected(ref78):
    tr = PhonemeTracker(ref=ref78)
    tr.feed(ref78[0].ids)
    tr.feed(ref78[1].ids)
    ev = tr.feed(ref78[0].ids)       # back to ayah 1
    assert types(ev, EventType.REPEAT)


def test_garbage_is_uncertain_not_wrong_lock(ref78):
    tr = PhonemeTracker(ref=ref78)
    rng = random.Random(0)
    junk = [rng.randint(1, 38) for _ in range(25)]
    ev = tr.feed(junk)
    # conservative: no progress, no missed-ayah, no confirmed jump on noise
    assert not types(ev, EventType.WORD_OK)
    assert not types(ev, EventType.MISSED_AYAH, EventState.CONFIRMED)
    assert not types(ev, EventType.MUTASHABEH_JUMP, EventState.CONFIRMED)


def test_perturbed_reciter_still_tracks(ref78):
    # simulate a different reciter: drop ~10% of IDs from each ayah
    tr = PhonemeTracker(ref=ref78)
    rng = random.Random(1)
    ev = []
    for a in ref78[:5]:
        perturbed = [x for x in a.ids if rng.random() > 0.10]
        ev += tr.feed(perturbed)
    assert len(types(ev, EventType.WORD_OK)) > 0
    assert not types(ev, EventType.MISSED_AYAH, EventState.CONFIRMED)
    assert tr.pointer >= 4


def test_no_missed_word_events_ever(ref78):
    # v1 invariant: MISSED_WORD must never be emitted
    tr = PhonemeTracker(ref=ref78)
    ev = []
    for a in ref78[:5]:
        ev += tr.feed(a.ids[:-2])    # truncate each ayah a bit
    assert not types(ev, EventType.MISSED_WORD)


def test_conservative_jump(db, ref78):
    # tracking An-Naba but reciter says Ikhlas 112:1 → conservative jump (needs index)
    idx = PhonemeIndex()
    ikhlas = load_phoneme_reference(db, 112)
    if len(ikhlas) < 1 or idx.size < 10:
        pytest.skip("Ikhlas refs / index not built yet")
    tr = PhonemeTracker(ref=ref78, index=idx)
    tr.feed(ref78[0].ids)
    ev = tr.feed(ikhlas[0].ids)      # off-reference → vote
    ev += tr.feed(ikhlas[0].ids)     # second window confirms
    conf = types(ev, EventType.MUTASHABEH_JUMP, EventState.CONFIRMED)
    assert conf and conf[0].payload["dest_surah"] == 112
