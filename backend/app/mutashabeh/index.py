"""Runtime relocation index (D6): word-3-gram inverted index over surah-
continuous word streams, scored by diagonal seed-chaining.

Why not per-ayah hit counting: a jumped reciter flows ACROSS ayah boundaries.
Query grams from "…احد الله الصمد لم يلد…" land in three consecutive ayahs of
Al-Ikhlas; bucketing per ayah splits one strong signal into several weak ones
that all miss the threshold. Chaining (surah, stream_pos - gram_idx) diagonals
scores the contiguous run as a whole and reports the ayah where the run starts.

Memory: ~77k stream positions, ~75k grams — a few tens of MB, built once at
process start; the static text never changes.
"""

from collections import defaultdict

from sqlalchemy import select

from app.db.models import Ayah, Word
from app.db.session import SessionLocal
from app.engine.detector import RelocationIndex

_N = 3
_DIAG_SLACK = 2  # merge diagonals within ±2 (tolerates one ASR insertion/deletion)


class NgramRelocationIndex(RelocationIndex):
    def __init__(self):
        db = SessionLocal()
        try:
            rows = db.execute(
                select(Word.ayah_id, Word.text_normalized, Ayah.surah_id, Ayah.number)
                .join(Ayah, Word.ayah_id == Ayah.id)
                .order_by(Ayah.surah_id, Ayah.number, Word.position)
            ).all()
        finally:
            db.close()

        self._meta: dict[int, tuple[int, int]] = {}          # ayah_id -> (surah, ayah_number)
        streams: dict[int, list[tuple[str, int]]] = defaultdict(list)  # surah -> [(word, ayah_id)]
        for ayah_id, norm, surah_id, number in rows:
            streams[surah_id].append((norm, ayah_id))
            self._meta[ayah_id] = (surah_id, number)

        self._inv: dict[tuple[str, ...], list[tuple[int, int]]] = defaultdict(list)  # gram -> [(surah, pos)]
        self._stream_ayah: dict[int, list[int]] = {}          # surah -> ayah_id per stream pos
        for surah, words in streams.items():
            self._stream_ayah[surah] = [a for _, a in words]
            for i in range(len(words) - _N + 1):
                gram = tuple(w for w, _ in words[i : i + _N])
                self._inv[gram].append((surah, i))

    def search(self, tokens: list[str]) -> list[tuple[int, int, int, float]]:
        grams = [tuple(tokens[i : i + _N]) for i in range(len(tokens) - _N + 1)]
        if not grams:
            return []
        # Seed-chain: same (surah, pos - gram_idx) diagonal = one contiguous run
        diag: dict[tuple[int, int], list[int]] = defaultdict(list)  # (surah, diagonal) -> [start pos]
        for i, g in enumerate(grams):
            for surah, pos in self._inv.get(g, ()):
                diag[(surah, (pos - i) // (_DIAG_SLACK + 1))].append(pos - i)

        scored: list[tuple[int, int, int, float]] = []
        for (surah, _), starts in diag.items():
            score = len(starts) / len(grams)
            start_pos = max(0, min(starts))
            ayah_id = self._stream_ayah[surah][min(start_pos, len(self._stream_ayah[surah]) - 1)]
            s, n = self._meta[ayah_id]
            scored.append((ayah_id, s, n, score))
        scored.sort(key=lambda t: -t[3])
        return scored[:5]


_index: NgramRelocationIndex | None = None


def get_relocation_index() -> NgramRelocationIndex:
    global _index
    if _index is None:
        _index = NgramRelocationIndex()
    return _index
