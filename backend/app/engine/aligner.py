"""Windowed fuzzy word alignment (the matching primitive under the detector).

The reference is a flat word list for the session (selected start ayah -> end of
surah). Matching searches a window around the pointer: forward for normal
progress, backward for repetition/restart (D2). Among equal-quality candidates
the NEAREST FORWARD position wins — this is what keeps repeated-refrain surahs
like Ar-Rahman (one ayah 31x) from teleporting the pointer (D8).
"""

from dataclasses import dataclass

from rapidfuzz import fuzz

from app.config import settings


@dataclass(frozen=True)
class RefWord:
    idx: int        # 0-based global index within the session reference
    word_id: int    # canonical QUL word id
    surah: int
    ayah: int       # ayah number within surah
    ayah_id: int    # global ayah id (1..6236)
    position: int   # 1-based within ayah
    norm: str       # normalized matching key

    def ref(self) -> dict:
        return {
            "surah": self.surah,
            "ayah": self.ayah,
            "position": self.position,
            "word_id": self.word_id,
            "idx": self.idx,
        }


@dataclass(frozen=True)
class Match:
    idx: int
    score: float


# Score ties within this epsilon are considered equal quality; position decides.
_TIE_EPSILON = 4.0


def find_match(
    token: str,
    ref: list[RefWord],
    pointer: int,
    *,
    min_score: float | None = None,
    window_fwd: int | None = None,
    window_back: int | None = None,
) -> Match | None:
    """Best acceptable match for one ASR token near the pointer, or None.

    Tie-break order within a score band: (1) smallest absolute distance from
    the pointer, (2) forward beats backward on exact distance ties. Nearest-
    absolute (not nearest-forward) matters: after Ikhlas ayah 1, a repeated
    "احد" must rewind 2 words, not leap 11 words to the final "احد" (D2),
    while at the pointer itself delta=0 always wins — which is what keeps
    refrains tracking forward (D8).
    """
    min_score = settings.match_score_min if min_score is None else min_score
    window_fwd = settings.align_window_fwd if window_fwd is None else window_fwd
    window_back = settings.align_window_back if window_back is None else window_back

    lo = max(0, pointer - window_back)
    hi = min(len(ref), pointer + window_fwd)
    if lo >= hi or not token:
        return None

    best: Match | None = None
    best_key: tuple | None = None
    for i in range(lo, hi):
        score = fuzz.ratio(token, ref[i].norm)
        if score < min_score:
            continue
        delta = i - pointer
        # Sort key: higher score band first, then nearest-absolute, forward on ties
        key = (-round(score / _TIE_EPSILON), abs(delta), delta < 0)
        if best_key is None or key < best_key:
            best_key = key
            best = Match(idx=i, score=score)
    return best
