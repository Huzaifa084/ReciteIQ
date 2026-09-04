"""RecitationTracker — the detection state machine.

Consumes normalized ASR token segments, emits Events (see events.py).

Design decisions encoded here (do not regress — see plan):
- D2  repetition is benign: backward matches emit REPEAT and rewind the pointer;
      pending missed-word provisionals in the re-recited span are revoked.
- D7  isti'adha/basmalah at session start are consumed by the preamble matcher.
- D8  refrains: nearest-forward matching lives in aligner.find_match; relocation
      hits inside the current surah's local neighborhood never raise JUMP.
- D13 lifecycle: WORD_OK is emitted confirmed (segments are final, not partial
      hypotheses); MISSED_WORD / MISSED_AYAH are provisional until k subsequent
      confirmed matches; MUTASHABEH_JUMP is provisional on the first supporting
      segment and confirmed after `jump_confirm_segments` consecutive ones.
- Pause-awareness ("wait and listen") is structural: detection only runs when
  speech tokens arrive, so silence alone can never confirm anything.
"""

from dataclasses import dataclass, field

from app.config import settings
from app.engine.aligner import Match, RefWord, find_match
from app.engine.events import Event, EventState, EventType
from app.nlp.normalize import tokenize

ISTIADHA = tokenize("أعوذ بالله من الشيطان الرجيم")
BASMALAH = tokenize("بسم الله الرحمن الرحيم")

# Tokens of garbage before we consult the relocation index
RELOCATION_MIN_STREAK = 4


class RelocationIndex:
    """Phase 5 implements this over the n-gram inverted index; Phase 2 stubs it."""

    def search(self, tokens: list[str]) -> list[tuple[int, int, int, float]]:
        """Return [(ayah_id, surah, ayah_number, score 0..1)] best-first."""
        return []


@dataclass
class _PendingMiss:
    event: Event                      # the provisional MISSED_WORD / MISSED_AYAH
    confirms_left: int = field(default_factory=lambda: settings.confirm_window_k)


class RecitationTracker:
    def __init__(
        self,
        ref: list[RefWord],
        *,
        relocation: RelocationIndex | None = None,
        preamble: bool = True,
    ):
        self.ref = ref
        self.pointer = 0
        self.matched: set[int] = set()
        self.pending: dict[int, _PendingMiss] = {}     # ref idx (or -ayah_id for ayah) -> pending
        # Confirmed misses kept for late-match revocation: if the "missed" word
        # is matched afterwards (ASR recovered it, or the reciter went back),
        # the verdict was wrong — withdraw it.
        self.confirmed_missed: dict[int, Event] = {}   # ref idx -> confirmed MISSED_WORD
        self.confirmed_missed_ayahs: dict[int, Event] = {}  # ayah_id -> confirmed MISSED_AYAH
        self._rewind_candidate: Match | None = None    # lone backward match awaiting corroboration
        self.relocation = relocation or RelocationIndex()
        self.unmatched_streak: list[str] = []
        self._jump_candidate: tuple[int, dict] | None = None  # (ayah_id, payload)
        self._jump_segments = 0
        self._jump_provisional: Event | None = None
        # Preamble (D7): isti'adha then basmalah. Surah 1 ayah 1 IS the basmalah —
        # there the basmalah must match the reference, so only isti'adha is preamble.
        pre = list(ISTIADHA)
        if preamble and not (ref and ref[0].surah == 1 and ref[0].ayah == 1):
            pre += list(BASMALAH)
        self._preamble: list[str] = pre if preamble else []
        self._preamble_active = bool(self._preamble)
        self._ayah_word_count: dict[int, int] = {}
        for w in ref:
            self._ayah_word_count[w.ayah_id] = self._ayah_word_count.get(w.ayah_id, 0) + 1
        # QUL word units are not always one whitespace token: the vocative
        # يَا أَيُّهَا is ONE unit with one word_id and one UI cell, but every ASR
        # emits it as two tokens. Rare (3 of 665 words across the curated
        # surahs) and it lands on Al-Kafirun 1 and Al-Inshiqaq 6.
        self._multiword: list[str] = sorted({w.norm for w in ref if " " in w.norm})

    # ------------------------------------------------------------------ API

    def _merge_multiword(self, tokens: list[str]) -> list[str]:
        """Join adjacent ASR tokens that a multi-word reference unit expects as one.

        Only a pair whose JOIN closely matches an actual multi-word unit of this
        session's reference is merged, so this cannot invent merges: the surahs
        that have no such unit are untouched, and a reciter who says only "يا"
        still produces one unmatched token. Without it neither half of
        يَا أَيُّهَا matched (best 72.7 against a threshold of 78) and the unit
        stayed uncredited on a perfectly clean recitation.
        """
        if not self._multiword or len(tokens) < 2:
            return tokens
        from rapidfuzz import fuzz

        out: list[str] = []
        i = 0
        while i < len(tokens):
            if i + 1 < len(tokens):
                joined = f"{tokens[i]} {tokens[i + 1]}"
                # The join must RECONSTRUCT the unit, not overshoot it. Ratio
                # alone is not enough: "قل يا ايها" scores 82 against "يا ايها"
                # simply by containing it, which would swallow the قل before it.
                if any(fuzz.ratio(joined, u) >= settings.match_score_min
                       and abs(len(joined) - len(u)) <= 2
                       for u in self._multiword):
                    out.append(joined)
                    i += 2
                    continue
            out.append(tokens[i])
            i += 1
        return out

    def _prepass_hits(self, tokens: list[str]) -> int:
        """Count how many segment tokens follow the reference, dry-running the
        pointer the way `feed_segment` actually advances it.

        Measuring against a FIXED pointer was wrong for long segments:
        `find_match` only searches [pointer-back, pointer+fwd), so at most
        back+fwd (20) ref words are ever reachable. A 34-token window is
        therefore capped at 20/34 = 0.59 hits and falls under the 0.5 block
        threshold for being LONG, not for being off-reference -- which froze
        the pointer on Al-Inshiqaq and then cascaded (every later window really
        was off-reference by then). The dry run advances a local pointer on
        each forward match, so a long but faithful recitation scores ~1.0 while
        a genuine jump still scores near 0: nothing matches, so nothing
        advances.
        """
        probe = self.pointer
        hits = 0
        for t in tokens:
            m = find_match(t, self.ref, probe)
            if m is None:
                continue
            hits += 1
            if m.idx >= probe:
                probe = m.idx + 1
        return hits

    def feed_segment(self, tokens: list[str], *, forced_cut: bool = False) -> list[Event]:
        """Process one final ASR segment. `forced_cut=True` means this segment
        follows a hard 5s cut and may start with overlap-duplicated words."""
        events: list[Event] = []
        if forced_cut:
            tokens = self._dedup_overlap(tokens)
        tokens = self._merge_multiword(tokens)

        # Segment-level pre-pass: a predominantly off-reference segment is
        # treated as a block — no per-token advance/rewind. Without this, a
        # jumped reciter's ubiquitous words (الله fuzzy-matching لله) fire
        # spurious REPEATs and keep "rescuing" a genuine MUTASHABEH_JUMP.
        if tokens and not self._preamble_active:
            hits = self._prepass_hits(tokens)
            if hits / len(tokens) < 0.5 and len(tokens) >= RELOCATION_MIN_STREAK:
                self.unmatched_streak.extend(tokens)
                self._check_relocation(events)
                if self.ref:
                    cur = self.ref[min(self.pointer, len(self.ref) - 1)]
                    events.append(Event(EventType.POSITION, EventState.CONFIRMED, cur.ref()))
                return events

        segment_matched_any = False
        for token in tokens:
            if self._preamble_active and self._try_preamble(token, events):
                continue
            m = find_match(token, self.ref, self.pointer)
            if m is None:
                self.unmatched_streak.append(token)
                self._rewind_candidate = None  # only the very next token corroborates
                continue
            segment_matched_any = True
            garbled = list(self.unmatched_streak)  # unmatched tokens consumed since last match
            self.unmatched_streak.clear()
            if self._preamble_active:
                self._preamble_active = False  # real recitation has begun
            if m.idx >= self.pointer:
                self._rewind_candidate = None
                self._advance(m, events, garbled=garbled)
            elif m.idx in self.confirmed_missed or m.idx in self.pending:
                # Backward hit on a word we called missed = RECOVERY, not
                # repetition: withdraw the verdict, no pointer rewind.
                self._recover(m, events)
            else:
                # Backward hit on already-recited ground: only a CORROBORATED
                # run (two consecutive backward tokens) is a real restart —
                # a lone stray match must not rewind (live-caught: spurious
                # REPEAT then false misses right after auto-detect replay).
                cand = self._rewind_candidate
                if cand is not None and 1 <= m.idx - cand.idx <= 2:
                    self._rewind_candidate = None
                    self._rewind(cand, m, events)
                else:
                    self._rewind_candidate = m

        # Relocation / Mutashabeh check on sustained garbage (D5: never on one token)
        if len(self.unmatched_streak) >= RELOCATION_MIN_STREAK:
            self._check_relocation(events)
        elif segment_matched_any:
            self._clear_jump_candidate(events)

        if self.ref:
            cur = self.ref[min(self.pointer, len(self.ref) - 1)]
            events.append(Event(EventType.POSITION, EventState.CONFIRMED, cur.ref()))
        return events

    def reposition(self, idx: int) -> None:
        """User accepted a jump ('continue from here') or manual reposition."""
        self.pointer = max(0, min(idx, len(self.ref)))
        self.pending.clear()
        self.unmatched_streak.clear()
        self._jump_candidate = None
        self._jump_segments = 0
        self._jump_provisional = None

    # ------------------------------------------------------------- internals

    def _try_preamble(self, token: str, events: list[Event]) -> bool:
        from rapidfuzz import fuzz

        # If the token matches the actual reference at least as well as the
        # preamble, recitation has started — stop preamble matching.
        ref_match = find_match(token, self.ref, self.pointer)
        for j, p in enumerate(self._preamble):
            if fuzz.ratio(token, p) >= settings.match_score_min:
                if ref_match is not None and ref_match.idx == self.pointer and ref_match.score >= fuzz.ratio(token, p):
                    return False
                kind = "istiadha" if p in ISTIADHA else "basmalah"
                self._preamble = self._preamble[j + 1 :]
                if not self._preamble:
                    self._preamble_active = False
                events.append(
                    Event(EventType.PREAMBLE, EventState.CONFIRMED, {"kind": kind, "token": p})
                )
                return True
        return False

    def _advance(self, m: Match, events: list[Event], *, garbled: list[str] | None = None) -> None:
        # Gap words between pointer and the match become provisional misses,
        # aggregated to MISSED_AYAH when a complete ayah is skipped.
        # Garbled-token credit: an unmatched token consumed since the last match
        # is evidence the reciter SAID something there, so the word it was
        # attempting was (badly) recited rather than skipped.
        gap = [self.ref[i] for i in range(self.pointer, m.idx) if i not in self.matched]
        if gap and garbled:
            gap = self._unattributed(gap, garbled, events)
        if gap:
            self._emit_gap(gap, resumed_at=self.ref[m.idx], events=events)
        w = self.ref[m.idx]
        self.matched.add(m.idx)
        self._revoke_if_recovered(m.idx, events)
        events.append(
            Event(EventType.WORD_OK, EventState.CONFIRMED, {**w.ref(), "score": round(m.score, 1)})
        )
        self.pointer = m.idx + 1
        self._tick_confirmations(events)

    def _unattributed(self, gap: list[RefWord], garbled: list[str],
                      events: list[Event] | None = None) -> list[RefWord]:
        """Gap words that no unmatched token can account for — the real misses.

        The credit used to be positional: drop the first len(garbled) gap words,
        whatever they were. That was wrong in both directions. It ABSOLVED a
        genuinely skipped word whenever the ASR happened to mangle something
        nearby (Al-Kafirun: the dropped word went unreported), and it BLAMED the
        wrong word when the mangled one was not first in the gap (Al-Inshiqaq:
        a MISSED_WORD on a clean recitation).

        Pair each unmatched token with the gap word it most resembles instead.
        A token only absolves a word it actually sounds like, and absolves at
        most one — so a skipped word with no lookalike token is still reported.
        The pairing threshold is deliberately BELOW `match_score_min`: these are
        tokens already rejected as matches, and the question here is the weaker
        "was this an attempt at that word", not "is this that word".
        """
        from rapidfuzz import fuzz

        pool = list(garbled)
        unblamed: list[RefWord] = []
        for w in gap:
            best_i, best_score = None, 0.0
            for i, tok in enumerate(pool):
                score = fuzz.ratio(tok, w.norm)
                if score > best_score:
                    best_i, best_score = i, score
            if best_i is not None and best_score >= settings.garbled_attribution_min:
                pool.pop(best_i)      # one token accounts for at most one word
                if events is not None:
                    # Not an error — but not confirmed either. Saying nothing
                    # leaves the word grey forever, which reads as "tracking
                    # stopped"; this is the honest third state: we heard
                    # something here that resembles this word.
                    events.append(Event(EventType.UNCERTAIN, EventState.CONFIRMED,
                                        {**w.ref(), "heard_score": round(best_score, 1)}))
            else:
                unblamed.append(w)
        return unblamed

    def _recover(self, m: Match, events: list[Event]) -> None:
        """Late match on a word previously called missed: withdraw the verdict
        and mark it recited — the pointer does not move."""
        if m.idx in self.pending:
            pend = self.pending.pop(m.idx)
            events.append(
                Event(pend.event.type, EventState.REVOKED, pend.event.payload, refers_to=pend.event.event_id)
            )
        self._revoke_if_recovered(m.idx, events)
        self.matched.add(m.idx)
        w = self.ref[m.idx]
        events.append(Event(EventType.WORD_OK, EventState.CONFIRMED, {**w.ref(), "score": round(m.score, 1)}))

    def _rewind(self, first: Match, second: Match, events: list[Event]) -> None:
        # D2: corroborated backward run = repetition/restart, never an error.
        w = self.ref[first.idx]
        events.append(
            Event(
                EventType.REPEAT,
                EventState.CONFIRMED,
                {"from_idx": self.pointer, **w.ref()},
            )
        )
        # Words being re-recited get a clean slate: revoke their pending misses,
        # and forget matches at/after the rewind point so gaps re-evaluate.
        for key, pend in list(self.pending.items()):
            first_idx = pend.event.payload.get("idx", pend.event.payload.get("first_idx", 0))
            if first_idx >= first.idx:
                events.append(
                    Event(pend.event.type, EventState.REVOKED, pend.event.payload, refers_to=pend.event.event_id)
                )
                del self.pending[key]
        self.matched = {i for i in self.matched if i < first.idx}
        for m in (first, second):
            self.matched.add(m.idx)
            self._revoke_if_recovered(m.idx, events)
            events.append(
                Event(EventType.WORD_OK, EventState.CONFIRMED, {**self.ref[m.idx].ref(), "score": round(m.score, 1)})
            )
        self.pointer = second.idx + 1

    def _rebalance_gap(self, gap: list[RefWord], events: list[Event]) -> list[RefWord]:
        """Undo a one-sided mutashabeh shift so a skipped ayah still reads as one.

        Al-Kafirun 3 -> 5 (a named release gate): ayahs 4 and 5 both open with
        وَلَا, so when the reciter skips ayah 4 the resumed ayah's opening word
        matches ayah 4's opening word instead of its own. The gap then runs
        4:2..5:1 — a suffix of the skipped ayah plus a prefix of the resumed one
        — which is never "a whole ayah", so five scattered MISSED_WORDs were
        reported where the truth is one skipped ayah.

        When the gap is exactly one ayah long and its leading words were merely
        displaced by textually identical ones, shift it back: the skipped ayah
        becomes whole, and the resumed ayah's opening words are credited, since
        the reciter did say them.
        """
        if len(gap) < 2:
            return gap
        first_id = gap[0].ayah_id
        head = [w for w in gap if w.ayah_id == first_id]
        tail = [w for w in gap if w.ayah_id != first_id]
        n_skipped = self._ayah_word_count.get(first_id, -1)
        # The gap must be exactly one ayah's worth, split across two ayahs, with
        # the missing leading words of the first accounted for by the tail.
        if not tail or len(gap) != n_skipped or len(head) == n_skipped:
            return gap
        k = n_skipped - len(head)                     # displaced leading words
        if k != len(tail) or gap[0].position != k + 1:
            return gap
        lead = [self.ref[i] for i in range(gap[0].idx - k, gap[0].idx)]
        if len(lead) != k or any(a.norm != b.norm for a, b in zip(lead, tail)):
            return gap                                # not a textual duplicate
        for w in tail:                                # the reciter DID say these
            self.matched.add(w.idx)
            events.append(Event(EventType.WORD_OK, EventState.CONFIRMED,
                                {**w.ref(), "score": 100.0}))
        return lead + head

    def _emit_gap(self, gap: list[RefWord], resumed_at: RefWord, events: list[Event]) -> None:
        gap = self._rebalance_gap(gap, events)
        # Group gap words by ayah; whole-ayah groups become MISSED_AYAH.
        by_ayah: dict[int, list[RefWord]] = {}
        for w in gap:
            by_ayah.setdefault(w.ayah_id, []).append(w)

        for ayah_id, words in by_ayah.items():
            whole_ayah = len(words) == self._ayah_word_count.get(ayah_id, -1)
            if whole_ayah:
                ev = Event(
                    EventType.MISSED_AYAH,
                    EventState.PROVISIONAL,
                    {
                        "surah": words[0].surah,
                        "ayah": words[0].ayah,
                        "ayah_id": ayah_id,
                        "first_idx": words[0].idx,
                        "resumed_at": resumed_at.ref(),
                    },
                )
                events.append(ev)
                self.pending[-ayah_id] = _PendingMiss(ev)
            else:
                for w in words:
                    ev = Event(EventType.MISSED_WORD, EventState.PROVISIONAL, w.ref())
                    events.append(ev)
                    self.pending[w.idx] = _PendingMiss(ev)

    def _tick_confirmations(self, events: list[Event]) -> None:
        for key, pend in list(self.pending.items()):
            pend.confirms_left -= 1
            if pend.confirms_left <= 0:
                conf = Event(
                    pend.event.type, EventState.CONFIRMED, pend.event.payload, refers_to=pend.event.event_id
                )
                events.append(conf)
                if conf.type == EventType.MISSED_WORD:
                    self.confirmed_missed[conf.payload["idx"]] = conf
                elif conf.type == EventType.MISSED_AYAH:
                    self.confirmed_missed_ayahs[conf.payload["ayah_id"]] = conf
                del self.pending[key]

    def _revoke_if_recovered(self, idx: int, events: list[Event]) -> None:
        """A match landed on `idx`: withdraw any earlier missed verdict it disproves."""
        if idx in self.confirmed_missed:
            ev = self.confirmed_missed.pop(idx)
            events.append(Event(EventType.MISSED_WORD, EventState.REVOKED, ev.payload, refers_to=ev.event_id))
        ayah_id = self.ref[idx].ayah_id
        if ayah_id in self.confirmed_missed_ayahs:
            ev = self.confirmed_missed_ayahs.pop(ayah_id)
            events.append(Event(EventType.MISSED_AYAH, EventState.REVOKED, ev.payload, refers_to=ev.event_id))

    def finish(self) -> list[Event]:
        """Session ending: resolve dangling provisionals. They never met the
        evidence bar (k confirming matches), so the benefit of the doubt goes
        to the reciter — revoke rather than leave 'checking…' forever."""
        events: list[Event] = []
        for pend in self.pending.values():
            events.append(
                Event(pend.event.type, EventState.REVOKED, pend.event.payload, refers_to=pend.event.event_id)
            )
        self.pending.clear()
        return events

    def _check_relocation(self, events: list[Event]) -> None:
        tokens = self.unmatched_streak[-8:]  # ~one breath group; longer windows dilute scores
        hits = self.relocation.search(tokens)
        cur = self.ref[min(self.pointer, len(self.ref) - 1)] if self.ref else None
        for ayah_id, surah, ayah_number, score in hits:
            if score < settings.relocation_score_min:
                continue
            # D8: never JUMP to the local neighborhood of the current position
            if cur and surah == cur.surah and abs(ayah_number - cur.ayah) <= 2:
                continue
            payload = {
                "dest_surah": surah,
                "dest_ayah": ayah_number,
                "dest_ayah_id": ayah_id,
                "score": round(score, 3),
                "tokens": tokens,
            }
            # A jumped reciter keeps reciting FORWARD in the destination, so a
            # hit in the same surah within a few ayahs ahead of the candidate
            # is the same jump, not a new one.
            same_jump = False
            if self._jump_candidate is not None:
                cand_payload = self._jump_candidate[1]
                same_jump = (
                    surah == cand_payload["dest_surah"]
                    and -1 <= ayah_number - cand_payload["dest_ayah"] <= 3
                )
            if same_jump:
                self._jump_segments += 1
            else:
                self._jump_candidate = (ayah_id, payload)
                self._jump_segments = 1
                self._jump_provisional = Event(EventType.MUTASHABEH_JUMP, EventState.PROVISIONAL, payload)
                events.append(self._jump_provisional)
            if self._jump_segments >= settings.jump_confirm_segments and self._jump_provisional:
                events.append(
                    Event(
                        EventType.MUTASHABEH_JUMP,
                        EventState.CONFIRMED,
                        payload,
                        refers_to=self._jump_provisional.event_id,
                    )
                )
                self._jump_candidate = None
                self._jump_segments = 0
                self._jump_provisional = None
                self.unmatched_streak.clear()
            return

    def _clear_jump_candidate(self, events: list[Event]) -> None:
        if self._jump_provisional is not None:
            events.append(
                Event(
                    EventType.MUTASHABEH_JUMP,
                    EventState.REVOKED,
                    self._jump_provisional.payload,
                    refers_to=self._jump_provisional.event_id,
                )
            )
        self._jump_candidate = None
        self._jump_segments = 0
        self._jump_provisional = None

    def _dedup_overlap(self, tokens: list[str]) -> list[str]:
        """Drop leading tokens that duplicate the words just matched (forced-cut
        overlap, D4). Bounded by how many words the overlap can actually hold:
        at ~1.3 words/sec of measured recitation a 1.5s overlap is ~2 words, so
        allow 3 with margin."""
        from rapidfuzz import fuzz

        max_drop = max(2, int(settings.segment_overlap_sec * 2) + 1)
        recent = [
            self.ref[i].norm
            for i in range(max(0, self.pointer - max_drop), self.pointer)
            if i in self.matched
        ]
        expected = self.ref[self.pointer].norm if self.pointer < len(self.ref) else ""
        dropped = 0
        while tokens and dropped < max_drop and recent:
            recent_score = max(fuzz.ratio(tokens[0], r) for r in recent)
            # Only a *better* match against the just-matched words than against
            # the expected next word counts as overlap residue — adjacent ayahs
            # share near-identical words (الصراط 6:2 vs صراط 7:1) and the
            # expected word must never be eaten by dedup.
            if recent_score >= settings.match_score_min and recent_score > fuzz.ratio(tokens[0], expected):
                tokens = tokens[1:]
                dropped += 1
            else:
                break
        return tokens
