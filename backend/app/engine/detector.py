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

    # ------------------------------------------------------------------ API

    def feed_segment(self, tokens: list[str], *, forced_cut: bool = False) -> list[Event]:
        """Process one final ASR segment. `forced_cut=True` means this segment
        follows a hard 5s cut and may start with overlap-duplicated words."""
        events: list[Event] = []
        if forced_cut:
            tokens = self._dedup_overlap(tokens)

        segment_matched_any = False
        for token in tokens:
            if self._preamble_active and self._try_preamble(token, events):
                continue
            m = find_match(token, self.ref, self.pointer)
            if m is None:
                self.unmatched_streak.append(token)
                continue
            segment_matched_any = True
            garbled = len(self.unmatched_streak)  # unmatched tokens consumed since last match
            self.unmatched_streak.clear()
            if self._preamble_active:
                self._preamble_active = False  # real recitation has begun
            if m.idx >= self.pointer:
                self._advance(m, events, garbled=garbled)
            else:
                self._rewind(m, events)

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

    def _advance(self, m: Match, events: list[Event], *, garbled: int = 0) -> None:
        # Gap words between pointer and the match become provisional misses,
        # aggregated to MISSED_AYAH when a complete ayah is skipped.
        # Garbled-token credit: each unmatched token consumed since the last
        # match represents an *attempted* word the ASR mangled — those gap
        # words were (badly) recited, not skipped, so they raise nothing.
        gap = [self.ref[i] for i in range(self.pointer, m.idx) if i not in self.matched]
        if garbled:
            gap = gap[garbled:]
        if gap:
            self._emit_gap(gap, resumed_at=self.ref[m.idx], events=events)
        w = self.ref[m.idx]
        self.matched.add(m.idx)
        events.append(
            Event(EventType.WORD_OK, EventState.CONFIRMED, {**w.ref(), "score": round(m.score, 1)})
        )
        self.pointer = m.idx + 1
        self._tick_confirmations(events)

    def _rewind(self, m: Match, events: list[Event]) -> None:
        # D2: backward match = repetition/restart, never an error.
        w = self.ref[m.idx]
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
            if first_idx >= m.idx:
                events.append(
                    Event(pend.event.type, EventState.REVOKED, pend.event.payload, refers_to=pend.event.event_id)
                )
                del self.pending[key]
        self.matched = {i for i in self.matched if i < m.idx}
        self.matched.add(m.idx)
        events.append(Event(EventType.WORD_OK, EventState.CONFIRMED, {**w.ref(), "score": round(m.score, 1)}))
        self.pointer = m.idx + 1

    def _emit_gap(self, gap: list[RefWord], resumed_at: RefWord, events: list[Event]) -> None:
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
                events.append(
                    Event(pend.event.type, EventState.CONFIRMED, pend.event.payload, refers_to=pend.event.event_id)
                )
                del self.pending[key]

    def _check_relocation(self, events: list[Event]) -> None:
        tokens = self.unmatched_streak[-12:]
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
            if self._jump_candidate and self._jump_candidate[0] == ayah_id:
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
        overlap, D4). At most 2 tokens — the 0.5s overlap can't hold more."""
        from rapidfuzz import fuzz

        recent = [
            self.ref[i].norm
            for i in (self.pointer - 2, self.pointer - 1)
            if i >= 0 and i in self.matched
        ]
        dropped = 0
        while (
            tokens
            and dropped < 2
            and any(fuzz.ratio(tokens[0], r) >= settings.match_score_min for r in recent)
        ):
            tokens = tokens[1:]
            dropped += 1
        return tokens
