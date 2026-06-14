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

    def feed(self, window_ids: list[int]) -> list[Event]:
        """Process one ≤30s window's collapsed token IDs."""
        events: list[Event] = []
        if len(window_ids) < 4:
            return events

        # Best-matching ayah in a LOCAL band around the pointer. Backward reach (−3)
        # catches repeats/restarts; forward reach (+4) catches skips.
        lo = max(0, self.pointer - 3)
        hi = min(len(self.ref), self.pointer + 4)
        local_best, local_cer = None, 1.0
        for i in range(lo, hi):
            cer = self._cover_cer(window_ids, self.ref[i].ids)
            if cer < local_cer:
                local_cer, local_best = cer, i

        if local_best is not None and local_cer <= self.MATCH_CER_MAX:
            self._clear_jump(events)
            if local_best < self.pointer:
                events.append(Event(EventType.REPEAT, EventState.CONFIRMED,
                                    {**self.ref[local_best].word_refs[0], "from_idx": self.pointer}))
            elif local_best > self.pointer:
                # ayahs strictly between pointer and local_best were skipped
                for k in range(self.pointer, local_best):
                    if k not in self._recited:
                        a = self.ref[k]
                        events.append(Event(EventType.MISSED_AYAH, EventState.CONFIRMED,
                                            {"surah": a.surah, "ayah": a.number, "ayah_id": a.ayah_id}))
            self._confirm_ayah(local_best, events)
            self.pointer = local_best + 1
            cur = self.ref[min(self.pointer, len(self.ref) - 1)]
            events.append(Event(EventType.POSITION, EventState.CONFIRMED, cur.word_refs[0]))
            return events

        # Local match failed → consult global index for a conservative jump
        self._check_jump(window_ids, events)
        return events

    # ---------------------------------------------------------------- internals

    def _cover_cer(self, window: list[int], ref_ids: list[int]) -> float:
        """How well the reference ayah is covered by the window. If the window is
        much longer (covers several ayahs), score the best ref-length sub-span."""
        if not ref_ids:
            return 1.0
        L = len(ref_ids)
        if len(window) <= L * 1.4:
            return Levenshtein.normalized_distance(window, ref_ids)
        best = 1.0
        for start in range(0, len(window) - L + 1, max(1, L // 3)):
            best = min(best, Levenshtein.normalized_distance(window[start:start + L], ref_ids))
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
