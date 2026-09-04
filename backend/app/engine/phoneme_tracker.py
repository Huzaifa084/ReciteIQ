"""v1 conservative ayah-level tracker (encoder-CTC ID space).

Tracks recitation at AYAH granularity by matching the reciter's token-ID windows
against per-ayah reference ID sequences. Intentionally v1-limited:

- Emits WORD_OK for every word of a CONFIRMED-recited ayah — soft progress only
  (whole-ayah green), NEVER a word-level mistake judgement.
- **No MISSED_WORD** (word spans deferred to v2).
- MISSED_AYAH / REPEAT / MUTASHABEH_JUMP only at high confidence; otherwise stays
  "uncertain" (emits nothing) rather than committing a wrong lock.

Match quality is normalized ID edit-distance (rapidfuzz). A window "covers" an
ayah when its IDs align to that ayah's reference below `match_cer_max`.
"""

from dataclasses import dataclass, field

from rapidfuzz.distance import Levenshtein

from app.config import settings
from app.engine.events import Event, EventState, EventType


@dataclass
class RefAyah:
    ayah_id: int
    surah: int
    number: int
    ids: list[int]                  # canonical (legacy single-reciter) ID sequence
    word_refs: list[dict]           # [{surah,ayah,position,word_id,idx}] for WORD_OK bursts
    variants: list[list[int]] = field(default_factory=list)   # P0-1: per-reciter refs

    @property
    def candidates(self) -> list[list[int]]:
        """Sequences to score this ayah against, honouring the configured rule.

        `single` keeps the legacy behaviour exactly, so multi-reference storage
        can land before the rule is chosen.
        """
        if settings.phoneme_ref_rule == "single" or not self.variants:
            return [self.ids]
        return self.variants[: settings.phoneme_ref_max]


@dataclass
class PhonemeTracker:
    ref: list[RefAyah]                              # session reference, ordered
    index: object | None = None                     # PhonemeIndex for jump detection
    pointer: int = 0                                # index into self.ref (current ayah)
    _recited: set[int] = field(default_factory=set)  # ref indices confirmed recited
    _jump_cand: tuple[int, dict] | None = None
    _jump_segments: int = 0
    # Per-window diagnostics for P1-7 instrumentation. Written by every feed();
    # read by the session layer for logging. Never influences matching.
    last_diag: dict = field(default_factory=dict)
    _jump_prov: Event | None = None
    _no_match_run: int = 0                          # consecutive windows that matched nothing
    _uncertain: dict = field(default_factory=dict)  # ref idx -> its provisional UNCERTAIN event

    # ---- tuning (conservative) ----
    MATCH_CER_MAX = 0.45          # window must align to an ayah at least this well to count
    JUMP_MARGIN = 0.25            # distant ayah must beat local by this (score) to be a jump
    JUMP_CONFIRM = 2              # consecutive windows before confirming a jump
    CHAIN_MAX = 12                # max ayahs one window may cover
    CHAIN_SKIP_MAX = 2            # unmatched refs tolerated inside a chain

    def feed(self, window_ids: list[int], c_ctc: float | None = None) -> list[Event]:
        """Process one ≤30s window's collapsed token IDs.

        A window is bounded by time, not by ayah, so it routinely spans SEVERAL
        consecutive ayahs. We therefore chain-align consecutive references onto
        successive spans of the window and credit every ayah the window covered.

        A miss is only ever claimed on POSITIVE evidence that the reciter moved
        on — an ayah skipped over *inside* a window that otherwise aligned well.
        Ayahs spanned by windows we simply could not place are UNCERTAIN, never
        MISSED_AYAH: absence of a match is not evidence of a skip (P0-4).
        """
        events: list[Event] = []
        self.last_diag = {"n_ids": len(window_ids), "pointer": self.pointer}
        if len(window_ids) < 4:
            self.last_diag["outcome"] = "too_short"
            return events

        chain = self._chain(window_ids)
        self.last_diag["chain_len"] = len(chain)
        self.last_diag["matched_ayahs"] = [self.ref[i].number for i in chain]
        low_conf = c_ctc is not None and c_ctc < settings.phoneme_conf_floor
        if chain:
            self._clear_jump(events)
            matched = {i for i in chain}
            first, last = chain[0], chain[-1]
            if first < self.pointer:
                events.append(Event(EventType.REPEAT, EventState.CONFIRMED,
                                    {**self.ref[first].word_refs[0], "from_idx": self.pointer}))
            # An unaligned ayah inside the covered span splits two ways:
            #
            #  * BETWEEN two matched ayahs of this window (first < k < last): the
            #    window covered that stretch of audio and the ayah still did not
            #    align, so the reciter demonstrably moved past it. A real miss.
            #  * BEFORE the first match (k < first), reached across windows we
            #    could not place at all: we heard speech and failed to place it,
            #    which says nothing about whether it was recited. UNCERTAIN.
            #
            # Live-caught: a take that recited all 7 ayahs of Al-Fatihah chained
            # only [4] and [6], and the old rule turned ayahs 1, 2, 3 and 5 red.
            unplaced = self._no_match_run > 0 or low_conf
            for k in range(self.pointer, last):
                if k in matched or k in self._recited:
                    continue
                a = self.ref[k]
                if k < first and unplaced:
                    self._mark_uncertain(k, events)
                else:
                    events.append(Event(EventType.MISSED_AYAH, EventState.CONFIRMED,
                                        {"surah": a.surah, "ayah": a.number, "ayah_id": a.ayah_id}))
            for i in chain:
                self._confirm_ayah(i, events)
            self._no_match_run = 0
            self.pointer = last + 1
            cur = self.ref[min(self.pointer, len(self.ref) - 1)]
            events.append(Event(EventType.POSITION, EventState.CONFIRMED, cur.word_refs[0]))
            self.last_diag["outcome"] = "chained"
            return events

        # Nothing aligned → consult the global index for a jump, then surface the
        # uncertainty instead of staying silent (P0-4).
        self.last_diag["outcome"] = "no_match"
        self._no_match_run += 1
        self.last_diag["no_match_run"] = self._no_match_run
        self._check_jump(window_ids, events)
        if self._no_match_run >= settings.phoneme_uncertain_after:
            self._mark_uncertain(self.pointer, events)
        return events

    # ---------------------------------------------------------------- internals

    def _chain(self, window: list[int]) -> list[int]:
        """Align a run of consecutive references onto successive spans of `window`.

        Returns the matched reference indices in recitation order. A window is
        bounded by time, so it usually holds several ayahs; a purely greedy scan
        from the band start derails when an early reference matches spuriously and
        eats part of the window. So we ANCHOR: try every start in the band, extend
        each candidate as far as it will go, and keep the longest chain (lowest
        mean CER breaks ties). The anchor itself must match, which is what keeps
        noise from producing a chain at all.

        Backward reach (-3) catches repeats/restarts; the forward reach is wide
        because one bounded window can hold many short ayahs.
        """
        lo = max(0, self.pointer - 3)
        hi = min(len(self.ref), self.pointer + 12)
        best: list[int] = []
        best_cer = 1.0
        probe_best = 1.0          # closest single-ayah CER seen anywhere in the band
        probe_ayah = None
        for s in range(lo, hi):
            chain: list[int] = []
            cursor, misses, total = 0, 0, 0.0
            for i in range(s, min(len(self.ref), s + self.CHAIN_MAX)):
                if len(window) - cursor < 4:
                    break
                cer, _st, e = self._best_span_ref(window[cursor:], self.ref[i])
                if cer < probe_best:
                    probe_best, probe_ayah = cer, self.ref[i].number
                if cer <= self.MATCH_CER_MAX:
                    chain.append(i)
                    total += cer
                    cursor += e
                    misses = 0
                    continue
                if not chain:
                    break                    # anchor must match — no chain from here
                misses += 1
                if misses > self.CHAIN_SKIP_MAX:
                    break                    # too much unmatched: stop extending
            if not chain:
                continue
            mean = total / len(chain)
            if len(chain) > len(best) or (len(chain) == len(best) and mean < best_cer):
                best, best_cer = chain, mean
        self.last_diag.update(
            chain_mean_cer=round(best_cer, 3) if best else None,
            closest_cer=round(probe_best, 3),
            closest_ayah=probe_ayah,
            cer_max=self.MATCH_CER_MAX,
        )
        return best

    def _reduce(self, cers: list[float]) -> float:
        """Reduce K per-reciter CERs to the one score that gates a match.

        The rule is configuration, not a decision baked into the code: `min` is
        the most permissive (and so the most exposed to false acceptance), while
        `second`/`median` demand agreement between independent reciters. The
        corpus chooses (plan §P0-1).
        """
        if not cers:
            return 1.0
        if len(cers) == 1:
            return cers[0]
        rule = settings.phoneme_ref_rule
        ordered = sorted(cers)
        if rule == "second":
            return ordered[1]
        if rule == "median":
            return ordered[len(ordered) // 2]
        return ordered[0]                      # "min", and the default fallback

    def _best_span_ref(self, window: list[int], ref: RefAyah) -> tuple[float, int, int]:
        """Best span for an ayah across all of its candidate references."""
        cands = ref.candidates
        if len(cands) == 1:
            return self._best_span(window, cands[0])
        scored = [self._best_span(window, c) for c in cands]
        cer = self._reduce([s[0] for s in scored])
        # keep the span of the reference that actually achieved the chosen score
        best = min(scored, key=lambda t: abs(t[0] - cer))
        return (cer, best[1], best[2])

    def _best_span(self, window: list[int], ref_ids: list[int]) -> tuple[float, int, int]:
        """Best-matching contiguous span of `window` for one ayah reference.

        Returns (cer, start, end). Span length is scanned around the reference
        length because recitation tempo (and so ID count) varies by reciter.
        """
        if not ref_ids or not window:
            return 1.0, 0, 0
        L = len(ref_ids)
        best = (1.0, 0, 0)
        lengths = sorted({max(1, int(L * f)) for f in (0.75, 0.9, 1.0, 1.15, 1.35)})
        stride = max(1, L // 4)
        for ln in lengths:
            if ln > len(window):
                continue
            for start in range(0, len(window) - ln + 1, stride):
                cer = Levenshtein.normalized_distance(window[start:start + ln], ref_ids)
                if cer < best[0]:
                    best = (cer, start, start + ln)
        return best

    def _mark_uncertain(self, i: int, events: list[Event]) -> None:
        """Flag an ayah as heard-but-unplaced. PROVISIONAL by construction — it is
        a statement about our own confidence, never a verdict on the reciter."""
        if i in self._uncertain or i in self._recited or not 0 <= i < len(self.ref):
            return
        a = self.ref[i]
        ev = Event(EventType.UNCERTAIN, EventState.PROVISIONAL,
                   {"surah": a.surah, "ayah": a.number, "ayah_id": a.ayah_id})
        self._uncertain[i] = ev
        events.append(ev)

    def _clear_uncertain(self, i: int, events: list[Event]) -> None:
        if (ev := self._uncertain.pop(i, None)) is not None:
            events.append(Event(EventType.UNCERTAIN, EventState.REVOKED,
                                ev.payload, refers_to=ev.event_id))

    def _confirm_ayah(self, i: int, events: list[Event]) -> None:
        if i in self._recited:
            return
        self._clear_uncertain(i, events)   # a later match resolves it for the reciter
        self._recited.add(i)
        # soft progress: whole-ayah green (NOT a word-level judgement)
        for wr in self.ref[i].word_refs:
            events.append(Event(EventType.WORD_OK, EventState.CONFIRMED, wr))

    def _check_jump(self, window: list[int], events: list[Event]) -> None:
        if self.index is None:
            return
        hits = self.index.vote(window)
        if not hits:
            self._clear_jump(events)
            return
        ayah_id, surah, number, score = hits[0]
        cur = self.ref[min(self.pointer, len(self.ref) - 1)]
        # ignore hits in the local neighborhood (that's normal tracking, not a jump)
        if surah == cur.surah and abs(number - cur.number) <= 2:
            self._clear_jump(events)
            return
        second = hits[1][3] if len(hits) > 1 else 0.0
        if score < settings.relocation_score_min or score - second < self.JUMP_MARGIN:
            return  # uncertain → stay listening, do not commit
        payload = {"dest_surah": surah, "dest_ayah": number, "dest_ayah_id": ayah_id, "score": round(score, 3)}
        if self._jump_cand and self._jump_cand[0] == ayah_id:
            self._jump_segments += 1
        else:
            self._jump_cand = (ayah_id, payload)
            self._jump_segments = 1
            self._jump_prov = Event(EventType.MUTASHABEH_JUMP, EventState.PROVISIONAL, payload)
            events.append(self._jump_prov)
        if self._jump_segments >= self.JUMP_CONFIRM and self._jump_prov:
            events.append(Event(EventType.MUTASHABEH_JUMP, EventState.CONFIRMED, payload,
                                refers_to=self._jump_prov.event_id))
            self._jump_cand = None
            self._jump_segments = 0
            self._jump_prov = None

    def _clear_jump(self, events: list[Event]) -> None:
        if self._jump_prov is not None:
            events.append(Event(EventType.MUTASHABEH_JUMP, EventState.REVOKED,
                                self._jump_prov.payload, refers_to=self._jump_prov.event_id))
        self._jump_cand = None
        self._jump_segments = 0
        self._jump_prov = None
