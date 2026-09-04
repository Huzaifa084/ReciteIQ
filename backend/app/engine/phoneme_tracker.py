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
    ids: list[int]                  # reference phoneme-ID sequence
    word_refs: list[dict]           # [{surah,ayah,position,word_id,idx}] for WORD_OK bursts


@dataclass
class PhonemeTracker:
    ref: list[RefAyah]                              # session reference, ordered
    index: object | None = None                     # PhonemeIndex for jump detection
    pointer: int = 0                                # index into self.ref (current ayah)
    _recited: set[int] = field(default_factory=set)  # ref indices confirmed recited
    _jump_cand: tuple[int, dict] | None = None
    _jump_segments: int = 0
    _jump_prov: Event | None = None

    # ---- tuning (conservative) ----
    MATCH_CER_MAX = 0.45          # window must align to an ayah at least this well to count
    JUMP_MARGIN = 0.25            # distant ayah must beat local by this (score) to be a jump
    JUMP_CONFIRM = 2              # consecutive windows before confirming a jump
    CHAIN_MAX = 12                # max ayahs one window may cover
    CHAIN_SKIP_MAX = 2            # unmatched refs tolerated inside a chain

    def feed(self, window_ids: list[int]) -> list[Event]:
        """Process one ≤30s window's collapsed token IDs.

        A window is bounded by time, not by ayah, so it routinely spans SEVERAL
        consecutive ayahs. We therefore chain-align consecutive references onto
        successive spans of the window and credit every ayah the window actually
        covered — only the ayahs the reciter genuinely skipped over are reported
        missed.
        """
        events: list[Event] = []
        if len(window_ids) < 4:
            return events

        chain = self._chain(window_ids)
        if chain:
            self._clear_jump(events)
            matched = {i for i in chain}
            first, last = chain[0], chain[-1]
            if first < self.pointer:
                events.append(Event(EventType.REPEAT, EventState.CONFIRMED,
                                    {**self.ref[first].word_refs[0], "from_idx": self.pointer}))
            # Skipped = inside the covered span but never aligned (leading gap
            # before the first match, or a hole between two matches).
            for k in range(self.pointer, last):
                if k not in matched and k not in self._recited:
                    a = self.ref[k]
                    events.append(Event(EventType.MISSED_AYAH, EventState.CONFIRMED,
                                        {"surah": a.surah, "ayah": a.number, "ayah_id": a.ayah_id}))
            for i in chain:
                self._confirm_ayah(i, events)
            self.pointer = last + 1
            cur = self.ref[min(self.pointer, len(self.ref) - 1)]
            events.append(Event(EventType.POSITION, EventState.CONFIRMED, cur.word_refs[0]))
            return events

        # Nothing in the local band aligned → consult global index for a jump
        self._check_jump(window_ids, events)
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
        for s in range(lo, hi):
            chain: list[int] = []
            cursor, misses, total = 0, 0, 0.0
            for i in range(s, min(len(self.ref), s + self.CHAIN_MAX)):
                if len(window) - cursor < 4:
                    break
                cer, _st, e = self._best_span(window[cursor:], self.ref[i].ids)
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
        return best

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

    def _confirm_ayah(self, i: int, events: list[Event]) -> None:
        if i in self._recited:
            return
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
