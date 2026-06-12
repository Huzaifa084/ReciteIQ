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
        self._word_pos: dict[str, list[tuple[int, int]]] = defaultdict(list)  # word -> [(surah, pos)]
        for surah, words in streams.items():
            self._stream_ayah[surah] = [a for _, a in words]
            for i, (w, _) in enumerate(words):
                self._word_pos[w].append((surah, i))
            for i in range(len(words) - _N + 1):
                gram = tuple(w for w, _ in words[i : i + _N])
                self._inv[gram].append((surah, i))
        self._vocab = list(self._word_pos.keys())

    def search(self, tokens: list[str]) -> list[tuple[int, int, int, float]]:
        grams = [tuple(tokens[i : i + _N]) for i in range(len(tokens) - _N + 1)]
        if not grams:
            return []
        # Seed-chain: same (surah, pos - gram_idx) diagonal = one contiguous run.
        # The bucket VALUE stores actual stream positions of matched grams: the
        # run anchor must be the first MATCHED gram's position, not min(pos-i) —
        # a leading junk token shifts the diagonal and would otherwise anchor
        # the run one+ words early (e.g. inside the basmalah of Al-Fatiha).
        diag: dict[tuple[int, int], list[int]] = defaultdict(list)  # (surah, diag bucket) -> [pos]
        for i, g in enumerate(grams):
            for surah, pos in self._inv.get(g, ()):
                diag[(surah, (pos - i) // (_DIAG_SLACK + 1))].append(pos)

        scored: list[tuple[int, int, int, float]] = []
        for (surah, _), positions in diag.items():
            score = len(positions) / len(grams)
            start_pos = min(positions)
            ayah_id = self._stream_ayah[surah][min(start_pos, len(self._stream_ayah[surah]) - 1)]
            s, n = self._meta[ayah_id]
            scored.append((ayah_id, s, n, score))
        scored.sort(key=lambda t: -t[3])
        return scored[:5]


    def search_words(self, tokens: list[str]) -> list[tuple[int, int, int, float]]:
        """Noise-tolerant location search for auto-detect: WORD-level diagonal
        chaining with fuzzy vocabulary correction.

        Exact 3-grams (search/relocation) are brittle for detection: every
        ASR-garbled token destroys up to three grams, and amateur-mic
        transcripts garble ~30% of tokens (live-caught on a Taha session that
        never locked). Here each token contributes individually — unknown
        tokens are first corrected against the Quran vocabulary — and the
        score is the fraction of tokens lying on one diagonal run.
        """
        from rapidfuzz import fuzz, process

        from app.config import settings

        if not tokens:
            return []
        # (surah, diag bucket) -> {token index} and min stream pos (run anchor)
        diag_tokens: dict[tuple[int, int], set[int]] = defaultdict(set)
        diag_anchor: dict[tuple[int, int], int] = {}
        for i, tok in enumerate(tokens):
            positions = self._word_pos.get(tok)
            if positions is None:
                corrected = process.extractOne(
                    tok, self._vocab, scorer=fuzz.ratio, score_cutoff=settings.match_score_min
                )
                if corrected is None:
                    continue  # true garbage: contributes nothing, breaks nothing
                positions = self._word_pos[corrected[0]]
            if len(positions) > 3000:
                continue  # ultra-common word: no locational evidence, pure noise
            for surah, pos in positions:
                key = (surah, (pos - i) // (_DIAG_SLACK + 1))
                diag_tokens[key].add(i)
                if key not in diag_anchor or pos < diag_anchor[key]:
                    diag_anchor[key] = pos

        scored: list[tuple[int, int, int, float]] = []
        for key, idxs in diag_tokens.items():
            if len(idxs) < 2:
                continue  # a single stray word never forms a run
            surah = key[0]
            score = len(idxs) / len(tokens)
            start = diag_anchor[key]
            ayah_id = self._stream_ayah[surah][min(start, len(self._stream_ayah[surah]) - 1)]
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
