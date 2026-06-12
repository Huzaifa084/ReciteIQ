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
        if top_score < settings.detect_score_min:
            return None
        # Margin vs the best hit at a genuinely different location
        for ayah_id, surah, ayah, score in hits[1:]:
            same_location = surah == top_surah and abs(ayah - top_ayah) <= 2
            if same_location:
                continue
            if top_score - score < settings.detect_margin:
                return None  # ambiguous (e.g. الحمد لله) — keep listening
            break
        return DetectedLocation(surah=top_surah, ayah=top_ayah, ayah_id=top_id, score=top_score)

    def _try_preamble(self, token: str) -> bool:
        for j, p in enumerate(self._preamble):
            if fuzz.ratio(token, p) >= settings.match_score_min:
                self._preamble = self._preamble[j + 1 :]
                return True
        return False
