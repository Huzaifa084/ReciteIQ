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


def test_multi_ayah_window_credits_every_covered_ayah(ref78):
    """A window is bounded by time, not by ayah, so continuous recitation puts
    several consecutive ayahs in ONE window. Every covered ayah must be credited
    — crediting only the best-matching one made clean recitation report the rest
    as MISSED_AYAH (seen live on a full Al-Fatihah clip: ayahs 3, 4, 5 flagged).
    """
    tr = PhonemeTracker(ref=ref78)
    window = [i for a in ref78[:4] for i in a.ids]      # 4 ayahs, one window
    ev = tr.feed(window)
    assert not types(ev, EventType.MISSED_AYAH, EventState.CONFIRMED)
    assert tr.pointer >= 4


def test_multi_ayah_window_still_flags_a_real_skip(ref78):
    """The multi-ayah fix must not blind the tracker to a genuine skip: recite
    ayahs 1,2,4 in one window and ayah 3 is still reported missed."""
    tr = PhonemeTracker(ref=ref78)
    window = ref78[0].ids + ref78[1].ids + ref78[3].ids   # ayah 3 skipped
    ev = tr.feed(window)
    missed = types(ev, EventType.MISSED_AYAH, EventState.CONFIRMED)
    assert len(missed) == 1 and missed[0].payload["ayah"] == ref78[2].number


# ---- P1-7 instrumentation -------------------------------------------------

def test_diag_reports_chain_on_match(ref78):
    """feed() must record per-window diagnostics for the session layer to log."""
    tr = PhonemeTracker(ref=ref78)
    window = [i for a in ref78[:3] for i in a.ids]
    tr.feed(window)
    d = tr.last_diag
    assert d["outcome"] == "chained"
    assert d["chain_len"] == 3
    assert d["matched_ayahs"] == [a.number for a in ref78[:3]]
    assert d["n_ids"] == len(window)
    assert 0.0 <= d["chain_mean_cer"] <= 1.0


def test_diag_reports_closest_cer_on_no_match(ref78):
    """A no-match must be diagnosable: record how close the best candidate got,
    otherwise a failed window leaves no trace to tune against."""
    import random
    tr = PhonemeTracker(ref=ref78)
    rng = random.Random(7)
    tr.feed([rng.randint(1, 38) for _ in range(40)])
    d = tr.last_diag
    assert d["outcome"] == "no_match"
    assert d["chain_len"] == 0 and d["chain_mean_cer"] is None
    # the closest miss is recorded, and it is genuinely a miss
    assert d["closest_cer"] > d["cer_max"]
    assert d["closest_ayah"] is not None


def test_diag_flags_too_short_window(ref78):
    tr = PhonemeTracker(ref=ref78)
    assert tr.feed([1, 2]) == []
    assert tr.last_diag["outcome"] == "too_short"


# ---- P0-4: absence of a match is not evidence of a skip -------------------

def test_unplaced_windows_yield_uncertain_not_missed(ref78):
    """THE bug this fixes. A live take recited all 7 ayahs of Al-Fatihah; the
    tracker chained only [4] and [6] and turned ayahs 1, 2, 3, 5 red. Windows we
    cannot place say nothing about whether the reciter recited them."""
    import random
    tr = PhonemeTracker(ref=ref78)
    rng = random.Random(3)
    # two windows we cannot place at all (as in the live session)
    for _ in range(2):
        tr.feed([rng.randint(1, 38) for _ in range(30)])
    # now a window that aligns to a LATER ayah
    ev = tr.feed(ref78[3].ids)
    assert not types(ev, EventType.MISSED_AYAH, EventState.CONFIRMED), \
        "ayahs spanned by unplaced windows must never be reported missed"
    unc = types(ev, EventType.UNCERTAIN, EventState.PROVISIONAL)
    assert unc, "the skipped-over span should be surfaced as UNCERTAIN"
    assert {u.payload["ayah"] for u in unc} <= {a.number for a in ref78[:3]}


def test_real_skip_inside_one_window_is_still_missed(ref78):
    """The fix must not blind us to a genuine skip: when ONE window covers the
    audio and an interior ayah fails to align, the reciter did move past it."""
    tr = PhonemeTracker(ref=ref78)
    window = ref78[0].ids + ref78[1].ids + ref78[3].ids      # ayah 3 skipped
    ev = tr.feed(window)
    missed = types(ev, EventType.MISSED_AYAH, EventState.CONFIRMED)
    assert len(missed) == 1 and missed[0].payload["ayah"] == ref78[2].number
    assert not types(ev, EventType.UNCERTAIN, EventState.PROVISIONAL)


def test_uncertain_revoked_when_ayah_later_matches(ref78):
    """Resolve in the reciter's favour: an ayah flagged uncertain that later
    aligns must have its flag withdrawn."""
    import random
    tr = PhonemeTracker(ref=ref78)
    rng = random.Random(5)
    for _ in range(2):
        tr.feed([rng.randint(1, 38) for _ in range(30)])
    ev = tr.feed(ref78[0].ids)                # ayah 1 arrives after the confusion
    assert types(ev, EventType.UNCERTAIN, EventState.REVOKED) or \
        not types(ev, EventType.UNCERTAIN, EventState.PROVISIONAL)
    assert not types(ev, EventType.MISSED_AYAH, EventState.CONFIRMED)


def test_uncertain_is_debounced(ref78):
    """A single unplaced window must not flag anything — only a run does."""
    import random
    tr = PhonemeTracker(ref=ref78)
    rng = random.Random(11)
    ev = tr.feed([rng.randint(1, 38) for _ in range(30)])
    assert not types(ev, EventType.UNCERTAIN, EventState.PROVISIONAL)


def test_low_confidence_blocks_missed_ayah(ref78):
    """With c_ctc under the floor the model barely heard anything placeable, so
    a leading gap must be uncertain even without a prior no-match run."""
    tr = PhonemeTracker(ref=ref78)
    ev = tr.feed(ref78[3].ids, c_ctc=0.05)
    assert not types(ev, EventType.MISSED_AYAH, EventState.CONFIRMED)
