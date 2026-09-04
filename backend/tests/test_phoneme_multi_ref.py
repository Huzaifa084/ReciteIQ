"""P0-1: multi-reciter references and the pluggable reduction rule.

The rule is deliberately NOT decided in code. These tests pin the SEMANTICS of
each candidate so the corpus comparison is meaningful — `min` is permissive and
so most exposed to false acceptance, `second`/`median` require agreement between
independent reciters. Measured motivation: an amateur scores CER 0.45-0.50
against Husary alone where a qari scores 0.04-0.21
(docs/baseline-m0-amateur-first.md).
"""

import pytest

from app.config import settings
from app.engine.events import EventState, EventType
from app.engine.phoneme_tracker import PhonemeTracker, RefAyah


@pytest.fixture(autouse=True)
def restore_rule():
    prev = settings.phoneme_ref_rule
    yield
    settings.phoneme_ref_rule = prev


def _ref(n: int, ids: list[int], variants=None) -> RefAyah:
    return RefAyah(ayah_id=n, surah=99, number=n, ids=ids,
                   word_refs=[{"surah": 99, "ayah": n, "position": 1, "word_id": n, "idx": n - 1}],
                   variants=variants or [])


def test_single_rule_ignores_variants():
    """Legacy behaviour must be reproducible exactly, so storage can land before
    the rule is chosen."""
    settings.phoneme_ref_rule = "single"
    r = _ref(1, [1, 2, 3, 4, 5, 6], variants=[[1, 2, 3, 4, 5, 6], [9, 9, 9, 9, 9, 9]])
    assert r.candidates == [[1, 2, 3, 4, 5, 6]]


def test_min_rule_scores_against_the_closest_reciter():
    """A query matching only the SECOND reciter still matches under `min`."""
    settings.phoneme_ref_rule = "min"
    far, near = [9, 9, 9, 9, 9, 9, 9, 9], [1, 2, 3, 4, 5, 6, 7, 8]
    tr = PhonemeTracker(ref=[_ref(1, far, variants=[far, near])])
    cer, _s, _e = tr._best_span_ref(near, tr.ref[0])
    assert cer == pytest.approx(0.0), "min must take the closest reference"


def test_consensus_rules_need_two_references_to_agree():
    """`second` and `median` must NOT reward a lone matching reference — that is
    the whole point of having them as alternatives to `min`."""
    far, near = [9, 9, 9, 9, 9, 9, 9, 9], [1, 2, 3, 4, 5, 6, 7, 8]
    tr = PhonemeTracker(ref=[_ref(1, far, variants=[far, near, far])])
    for rule in ("second", "median"):
        settings.phoneme_ref_rule = rule
        cer, _s, _e = tr._best_span_ref(near, tr.ref[0])
        assert cer > tr.MATCH_CER_MAX, f"{rule} accepted a single agreeing reference"


def test_reduce_semantics():
    tr = PhonemeTracker(ref=[])
    cers = [0.10, 0.40, 0.90]
    settings.phoneme_ref_rule = "min";    assert tr._reduce(cers) == 0.10
    settings.phoneme_ref_rule = "second"; assert tr._reduce(cers) == 0.40
    settings.phoneme_ref_rule = "median"; assert tr._reduce(cers) == 0.40
    settings.phoneme_ref_rule = "min";    assert tr._reduce([0.3]) == 0.3
    assert tr._reduce([]) == 1.0


def test_min_rule_still_rejects_an_unrelated_ayah():
    """Permissiveness must not become 'matches anything' — the guard against the
    false-acceptance risk that `min` carries."""
    settings.phoneme_ref_rule = "min"
    a, b = [1, 2, 3, 4, 5, 6, 7, 8], [2, 4, 6, 8, 10, 12, 14, 16]
    tr = PhonemeTracker(ref=[_ref(1, a, variants=[a, b])])
    cer, _s, _e = tr._best_span_ref([31, 33, 35, 37, 21, 23, 25, 27], tr.ref[0])
    assert cer > tr.MATCH_CER_MAX


def test_tracking_works_end_to_end_under_min_rule():
    """A three-ayah surah where the reciter matches a different reciter for each
    ayah still tracks cleanly, with no false misses."""
    settings.phoneme_ref_rule = "min"
    refs = []
    for n in range(1, 4):
        base = [n * 10 + i for i in range(8)]
        alt = [n * 10 + i for i in range(8)][::-1]
        refs.append(_ref(n, alt, variants=[alt, base]))
    tr = PhonemeTracker(ref=refs)
    ev = []
    for n in range(1, 4):
        ev += tr.feed([n * 10 + i for i in range(8)])
    assert not [e for e in ev if e.type == EventType.MISSED_AYAH
                and e.state == EventState.CONFIRMED]
    assert tr.pointer >= 3
