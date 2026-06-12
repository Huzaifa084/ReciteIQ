"""Named hard-case fixtures from the plan — all must pass (Phase 2 gate)."""

from app.engine.detector import BASMALAH, ISTIADHA, RecitationTracker, RelocationIndex
from app.engine.events import EventState, EventType
from tests.conftest import tokens_of


def types(events, t, state=None):
    return [e for e in events if e.type == t and (state is None or e.state == state)]


def feed_ayahs(tracker, ref, ayahs):
    all_events = []
    for a in ayahs:
        all_events += tracker.feed_segment(tokens_of(ref, a))
    return all_events


# ---------------------------------------------------------------- basic flow


def test_perfect_recitation(ref_fatiha):
    tr = RecitationTracker(ref_fatiha, preamble=False)
    ev = feed_ayahs(tr, ref_fatiha, range(1, 8))
    assert len(types(ev, EventType.WORD_OK)) == len(ref_fatiha)
    assert not types(ev, EventType.MISSED_WORD)
    assert not types(ev, EventType.MISSED_AYAH)
    assert not types(ev, EventType.MUTASHABEH_JUMP)


def test_dropped_word(ref_fatiha):
    # Drop one word mid-ayah 6 (the longest); k subsequent matches confirm it
    tr = RecitationTracker(ref_fatiha, preamble=False)
    feed_ayahs(tr, ref_fatiha, range(1, 6))
    toks = tokens_of(ref_fatiha, 6)
    dropped = toks[1]
    ev = tr.feed_segment([toks[0]] + toks[2:])
    ev += tr.feed_segment(tokens_of(ref_fatiha, 7))
    prov = types(ev, EventType.MISSED_WORD, EventState.PROVISIONAL)
    conf = types(ev, EventType.MISSED_WORD, EventState.CONFIRMED)
    assert len(prov) == 1 and len(conf) == 1
    assert conf[0].refers_to == prov[0].event_id
    assert prov[0].payload["ayah"] == 6


def test_skipped_ayah(ref_fatiha):
    # Recite 1,2 then jump straight to 4: ayah 3 missed as a whole
    tr = RecitationTracker(ref_fatiha, preamble=False)
    ev = feed_ayahs(tr, ref_fatiha, [1, 2, 4, 5])
    prov = types(ev, EventType.MISSED_AYAH, EventState.PROVISIONAL)
    conf = types(ev, EventType.MISSED_AYAH, EventState.CONFIRMED)
    assert len(prov) == 1 and prov[0].payload["ayah"] == 3
    assert len(conf) == 1 and conf[0].refers_to == prov[0].event_id
    # the skipped ayah's words must NOT also fire word-level misses
    assert not types(ev, EventType.MISSED_WORD)


# ------------------------------------------------------------- repetition D2


def test_ayah_restart_is_benign(ref_fatiha):
    # Recite ayah 6 fully, then recite it again (full restart over recited
    # ground): corroborated backward run -> REPEAT, zero confirmed misses
    tr = RecitationTracker(ref_fatiha, preamble=False)
    feed_ayahs(tr, ref_fatiha, range(1, 7))
    ev = tr.feed_segment(tokens_of(ref_fatiha, 6))  # restart ayah 6
    ev += tr.feed_segment(tokens_of(ref_fatiha, 7))
    assert types(ev, EventType.REPEAT)
    assert not types(ev, EventType.MISSED_WORD, EventState.CONFIRMED)
    assert not types(ev, EventType.MISSED_AYAH, EventState.CONFIRMED)


def test_lone_backward_match_is_ignored(ref_fatiha):
    # Live-caught: a single stray token matching backward must NOT rewind the
    # pointer (it caused a spurious REPEAT then false misses after replay)
    tr = RecitationTracker(ref_fatiha, preamble=False)
    feed_ayahs(tr, ref_fatiha, range(1, 6))
    toks5 = tokens_of(ref_fatiha, 5)
    ev = tr.feed_segment([toks5[0]])  # re-hear of one earlier word (اياك)
    ev += tr.feed_segment(tokens_of(ref_fatiha, 6))
    ev += tr.feed_segment(tokens_of(ref_fatiha, 7))
    assert not types(ev, EventType.REPEAT)
    assert not types(ev, EventType.MISSED_WORD)
    assert not types(ev, EventType.MISSED_AYAH)


def test_phrase_repeat_is_benign(ref_ikhlas):
    tr = RecitationTracker(ref_ikhlas, preamble=False)
    toks1 = tokens_of(ref_ikhlas, 1)
    ev = tr.feed_segment(toks1)
    ev += tr.feed_segment(toks1[-2:])  # repeat the last two words
    ev += tr.feed_segment(tokens_of(ref_ikhlas, 2))
    assert types(ev, EventType.REPEAT)
    assert not types(ev, EventType.MISSED_WORD, EventState.CONFIRMED)


# --------------------------------------------------------------- preamble D7


def test_istiadha_basmalah_opening(ref_ikhlas):
    tr = RecitationTracker(ref_ikhlas)  # preamble on
    ev = tr.feed_segment(list(ISTIADHA))
    ev += tr.feed_segment(list(BASMALAH))
    ev += tr.feed_segment(tokens_of(ref_ikhlas, 1))
    pre = types(ev, EventType.PREAMBLE)
    assert len(pre) == len(ISTIADHA) + len(BASMALAH)
    assert not types(ev, EventType.MISSED_WORD)
    # ayah 1 fully matched after the preamble
    assert len(types(ev, EventType.WORD_OK)) == len(tokens_of(ref_ikhlas, 1))


def test_fatiha_basmalah_is_ayah_not_preamble(ref_fatiha):
    # Surah 1: basmalah IS ayah 1:1 — it must match reference, not preamble
    tr = RecitationTracker(ref_fatiha)
    ev = tr.feed_segment(tokens_of(ref_fatiha, 1))
    assert len(types(ev, EventType.WORD_OK)) == len(tokens_of(ref_fatiha, 1))
    assert not [e for e in types(ev, EventType.PREAMBLE) if e.payload["kind"] == "basmalah"]


def test_tawbah_starts_clean(ref_tawbah):
    # Surah 9 has no basmalah; starting directly must not misalign
    tr = RecitationTracker(ref_tawbah)
    ev = tr.feed_segment(tokens_of(ref_tawbah, 1)[:6])
    assert len(types(ev, EventType.WORD_OK)) == 6
    assert not types(ev, EventType.MISSED_WORD)


# ---------------------------------------------------------------- refrain D8


def test_rahman_refrain_run(ref_rahman):
    # Ayahs 13,16,18,21 are the identical refrain; recite 13..21 correctly —
    # the pointer must track forward with zero errors and zero jumps
    tr = RecitationTracker(ref_rahman, preamble=False)
    feed_ayahs(tr, ref_rahman, range(1, 13))
    ev = feed_ayahs(tr, ref_rahman, range(13, 22))
    assert not types(ev, EventType.MISSED_WORD, EventState.CONFIRMED)
    assert not types(ev, EventType.MISSED_AYAH, EventState.CONFIRMED)
    assert not types(ev, EventType.MUTASHABEH_JUMP)
    pos = types(ev, EventType.POSITION)[-1]
    assert pos.payload["ayah"] >= 21


# ------------------------------------------------------------- ASR noise D5


def test_single_garbled_token_no_error(ref_fatiha):
    # ASR mangles one word beyond recognition: attempted ≠ skipped → no events
    tr = RecitationTracker(ref_fatiha, preamble=False)
    feed_ayahs(tr, ref_fatiha, range(1, 6))
    toks = tokens_of(ref_fatiha, 6)
    toks[1] = "زقزقزق"  # unrecognizable garbage in place of a real word
    ev = tr.feed_segment(toks)
    ev += tr.feed_segment(tokens_of(ref_fatiha, 7))
    assert not types(ev, EventType.MISSED_WORD)
    assert not types(ev, EventType.MISSED_AYAH)


class _FakeIndex(RelocationIndex):
    def __init__(self, hits):
        self.hits = hits

    def search(self, tokens):
        return self.hits


def test_hallucinated_segment_no_confirmed_jump(ref_fatiha):
    # One garbage segment points at another surah; the next segment matches
    # normally → the provisional jump must be REVOKED, never confirmed (D5)
    idx = _FakeIndex([(2030, 2, 285, 0.9)])
    tr = RecitationTracker(ref_fatiha, preamble=False, relocation=idx)
    ev = feed_ayahs(tr, ref_fatiha, [1, 2])
    ev += tr.feed_segment(["كلام", "اخر", "تماما", "مختلف", "غريب"])  # hallucination
    ev += tr.feed_segment(tokens_of(ref_fatiha, 3))  # back to normal
    prov = types(ev, EventType.MUTASHABEH_JUMP, EventState.PROVISIONAL)
    conf = types(ev, EventType.MUTASHABEH_JUMP, EventState.CONFIRMED)
    rev = types(ev, EventType.MUTASHABEH_JUMP, EventState.REVOKED)
    assert len(prov) == 1 and not conf
    assert len(rev) == 1 and rev[0].refers_to == prov[0].event_id


def test_sustained_jump_confirmed(ref_fatiha):
    # Two consecutive off-reference segments at the same destination → CONFIRMED
    idx = _FakeIndex([(2030, 2, 285, 0.9)])
    tr = RecitationTracker(ref_fatiha, preamble=False, relocation=idx)
    feed_ayahs(tr, ref_fatiha, [1, 2])
    ev = tr.feed_segment(["كلام", "اخر", "تماما", "مختلف", "غريب"])
    ev += tr.feed_segment(["جمله", "ثانيه", "بعيده", "عن", "النص"])
    prov = types(ev, EventType.MUTASHABEH_JUMP, EventState.PROVISIONAL)
    conf = types(ev, EventType.MUTASHABEH_JUMP, EventState.CONFIRMED)
    assert len(prov) == 1 and len(conf) == 1
    assert conf[0].payload["dest_surah"] == 2 and conf[0].payload["dest_ayah"] == 285
    assert conf[0].refers_to == prov[0].event_id


def test_jump_suppressed_in_local_neighborhood(ref_fatiha):
    # D8: relocation hit inside the current surah's local window never JUMPs
    idx = _FakeIndex([(4, 1, 4, 0.95)])  # "destination" = next ayah of Fatiha
    tr = RecitationTracker(ref_fatiha, preamble=False, relocation=idx)
    feed_ayahs(tr, ref_fatiha, [1, 2, 3])
    ev = tr.feed_segment(["كلام", "اخر", "تماما", "مختلف", "غريب"])
    assert not types(ev, EventType.MUTASHABEH_JUMP)


# ------------------------------------------- live-caught: false-miss recovery


def test_late_match_revokes_confirmed_miss(ref_fatiha):
    # Live-caught: a mid-word segment cut made ASR drop الرحيم -> MISSED_WORD
    # confirmed. If the word IS matched later (overlap recovery / reciter goes
    # back), the verdict must be withdrawn and the summary corrected.
    tr = RecitationTracker(ref_fatiha, preamble=False)
    feed_ayahs(tr, ref_fatiha, [1, 2])
    toks3 = tokens_of(ref_fatiha, 3)  # الرحمن الرحيم
    ev = tr.feed_segment([toks3[0]])  # الرحيم dropped by ASR
    ev += tr.feed_segment(tokens_of(ref_fatiha, 4))
    ev += tr.feed_segment(tokens_of(ref_fatiha, 5))
    conf = types(ev, EventType.MISSED_WORD, EventState.CONFIRMED)
    assert len(conf) == 1  # verdict issued...
    ev2 = tr.feed_segment([toks3[1], *tokens_of(ref_fatiha, 6)])  # الرحيم heard late
    rev = types(ev2, EventType.MISSED_WORD, EventState.REVOKED)
    assert len(rev) == 1 and rev[0].refers_to == conf[0].event_id  # ...and withdrawn


def test_finish_revokes_dangling_provisionals(ref_fatiha):
    # Live-caught: session ended while غير المغضوب عليهم ولا sat 'checking…' —
    # provisionals that never reach k confirmations are dropped at finish().
    tr = RecitationTracker(ref_fatiha, preamble=False)
    feed_ayahs(tr, ref_fatiha, range(1, 7))
    toks7 = tokens_of(ref_fatiha, 7)
    ev = tr.feed_segment(toks7[:4] + [toks7[-1]])  # tail garbled: jump to last word
    prov = types(ev, EventType.MISSED_WORD, EventState.PROVISIONAL)
    assert prov  # words 5..8 provisional
    ev2 = tr.finish()
    rev = types(ev2, EventType.MISSED_WORD, EventState.REVOKED)
    assert {e.refers_to for e in rev} == {e.event_id for e in prov}
    assert not tr.pending


# ----------------------------------------------------------- overlap dedup D4


def test_overlap_dedup_never_eats_expected_word(ref_fatiha):
    # Live-caught regression: segment boundary at Fatiha 6/7 — the new segment
    # starts with صراط (7:1, the expected word) which fuzzy-matches the
    # already-matched الصراط (6:2). Dedup must NOT swallow it.
    tr = RecitationTracker(ref_fatiha, preamble=False)
    feed_ayahs(tr, ref_fatiha, range(1, 7))  # through ayah 6 (… الصراط المستقيم)
    toks7 = tokens_of(ref_fatiha, 7)
    ev = tr.feed_segment(toks7, forced_cut=True)  # starts with صراط
    assert not types(ev, EventType.MISSED_WORD)
    assert len(types(ev, EventType.WORD_OK)) == len(toks7)


def test_forced_cut_overlap_dedup(ref_fatiha):
    tr = RecitationTracker(ref_fatiha, preamble=False)
    toks = tokens_of(ref_fatiha, 1) + tokens_of(ref_fatiha, 2)
    tr.feed_segment(toks[:5])
    # forced cut: next segment re-hears the last word
    ev = tr.feed_segment([toks[4]] + toks[5:], forced_cut=True)
    # the duplicated word must not produce REPEAT noise or double WORD_OK
    assert not types(ev, EventType.REPEAT)
    ok_idx = [e.payload["idx"] for e in types(ev, EventType.WORD_OK)]
    assert len(ok_idx) == len(set(ok_idx)) == len(toks) - 5
