"""LocationDetector — auto-detect Surah/Ayah from the opening recitation.

Reuses the global relocation index (surah-continuous 3-grams, diagonal
chaining). Accumulates normalized tokens across segments, strips the
isti'adha/basmalah preamble, and accepts a location once the best hit is
both strong and UNAMBIGUOUS:

- Ambiguity is real: الحمد لله opens surahs 1, 6, 18, 34 and 35 — the detector
  must keep listening until one location clearly wins (margin over the best
  hit at any *other* location; nearby ayahs of the same surah count as the
  same location, since diagonal buckets can split a run).
- Basmalah is consumed as preamble. For Al-Fatiha that means detection locks
  onto 1:2 — correct behavior: that's where the reciter actually is.
"""

from dataclasses import dataclass

from rapidfuzz import fuzz

from app.config import settings
from app.engine.detector import BASMALAH, ISTIADHA, RelocationIndex


@dataclass(frozen=True)
class DetectedLocation:
    surah: int
    ayah: int
    ayah_id: int
    score: float


class LocationDetector:
    def __init__(self, index: RelocationIndex):
        self._index = index
        self._tokens: list[str] = []
        self._preamble = list(ISTIADHA) + list(BASMALAH)
        self.last_hits: list[tuple[int, int, int, float]] = []  # diagnostics for logging
        self._votes: list[tuple[int, int, int, float]] = []  # (surah, ayah, ayah_id, score) per window

    @property
    def tokens(self) -> list[str]:
        """The detection window (for tracker replay) — the SLIDING last-N
        tokens, matching what the location was actually detected from. Earlier
        tokens may be pre-warmup junk and must not be replayed."""
        return list(self._tokens[-settings.detect_max_tokens :])

    def feed(self, tokens: list[str]) -> DetectedLocation | None:
        """Accumulate one segment's tokens; return a location once confident."""
        for t in tokens:
            if self._preamble and self._try_preamble(t):
                continue
            self._preamble = []  # real recitation has begun — stop preamble matching
            self._tokens.append(t)

        if len(self._tokens) < settings.detect_min_tokens:
            return None
        # Sliding window (not the head): early junk tokens age out instead of
        # permanently poisoning detection. Fuzzy word-level search tolerates
        # the garbled tokens that break exact n-grams (see search_words).
        window = self._tokens[-settings.detect_max_tokens :]
        search = getattr(self._index, "search_words", self._index.search)
        hits = search(window)
        self.last_hits = hits
        if not hits:
            return None
        top_id, top_surah, top_ayah, top_score = hits[0]

        # Margin vs the best hit at a genuinely different location (ambiguity guard)
        unambiguous = True
        for _ayah_id, surah, ayah, score in hits[1:]:
            if surah == top_surah and abs(ayah - top_ayah) <= 2:
                continue  # same location, split across diagonals
            if top_score - score < settings.detect_margin:
                unambiguous = False
            break

        # Path 1 — instant lock on a single strong, unambiguous window (clean audio)
        if top_score >= settings.detect_score_min and unambiguous:
            return DetectedLocation(top_surah, top_ayah, top_id, top_score)

        # Path 2 — consensus lock by VOTE over a sliding window. A garbled
        # recitation rarely yields one perfect window, and per-segment margins
        # oscillate (ties, near-ties), so a consecutive-streak rule keeps
        # resetting. Instead, count which surah leads the recent segments: if
        # one dominates, lock it regardless of any single window's margin.
        # (Live-caught: An-Naba led 7 of 9 segments but a lone margin=0.19
        # segment kept resetting the old streak.)
        if top_score >= settings.detect_consensus_floor:
            self._votes.append((top_surah, top_ayah, top_id, top_score))
            self._votes = self._votes[-settings.detect_vote_window :]
            tally: dict[int, int] = {}
            best: dict[int, tuple[float, int, int]] = {}  # surah -> (score, ayah_id, ayah)
            for surah, ayah, ayah_id, score in self._votes:
                tally[surah] = tally.get(surah, 0) + 1
                if score > best.get(surah, (0.0, 0, 0))[0]:
                    best[surah] = (score, ayah_id, ayah)
            ranked = sorted(tally.items(), key=lambda kv: -kv[1])
            leader, lead_votes = ranked[0]
            second_votes = ranked[1][1] if len(ranked) > 1 else 0
            if lead_votes >= settings.detect_consensus and lead_votes - second_votes >= 2:
                score, ayah_id, ayah = best[leader]
                return DetectedLocation(leader, ayah, ayah_id, score)
        return None

    def _try_preamble(self, token: str) -> bool:
        for j, p in enumerate(self._preamble):
            if fuzz.ratio(token, p) >= settings.match_score_min:
                self._preamble = self._preamble[j + 1 :]
                return True
        return False
