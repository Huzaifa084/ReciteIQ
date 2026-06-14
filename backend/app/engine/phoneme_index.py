"""Phoneme-ID n-gram location index (v1 auto-detect, ID-space).

Same diagonal-vote idea as app/mutashabeh/index.py but over model token-ID
sequences (Ayah.phoneme_ids) instead of word text. Built once from the DB at
startup. Conservative by design — callers require length + margin before locking.
"""

from collections import defaultdict

from sqlalchemy import select

from app.db.models import Ayah
from app.db.session import SessionLocal

_N = 4  # ID n-gram size (pilot used 4; IDs are finer-grained than words)


class PhonemeIndex:
    def __init__(self):
        db = SessionLocal()
        try:
            rows = db.execute(
                select(Ayah.id, Ayah.surah_id, Ayah.number, Ayah.phoneme_ids, Ayah.phoneme_unstable)
                .where(Ayah.phoneme_ids.isnot(None))
                .order_by(Ayah.surah_id, Ayah.number)
            ).all()
        finally:
            db.close()
        self.refs: dict[int, list[int]] = {}          # ayah_id -> id seq
        self.meta: dict[int, tuple[int, int]] = {}     # ayah_id -> (surah, number)
        self._inv: dict[tuple[int, ...], list[int]] = defaultdict(list)  # gram -> [ayah_id]
        for ayah_id, surah, number, ids, unstable in rows:
            if unstable or not ids:
                continue  # skip low-consensus references
            self.refs[ayah_id] = ids
            self.meta[ayah_id] = (surah, number)
            for i in range(len(ids) - _N + 1):
                self._inv[tuple(ids[i:i + _N])].append(ayah_id)

    @property
    def size(self) -> int:
        return len(self.refs)

    def vote(self, query_ids: list[int]) -> list[tuple[int, int, int, float]]:
        """Rank (ayah_id, surah, number, score) by fraction of query n-grams that
        hit each ayah. Score in 0..1."""
        grams = [tuple(query_ids[i:i + _N]) for i in range(len(query_ids) - _N + 1)]
        if not grams:
            return []
        tally: dict[int, int] = defaultdict(int)
        for g in grams:
            for ayah_id in set(self._inv.get(g, ())):
                tally[ayah_id] += 1
        scored = [(aid, *self.meta[aid], n / len(grams)) for aid, n in tally.items()]
        scored.sort(key=lambda t: -t[3])
        return scored[:5]


_index: PhonemeIndex | None = None


def get_phoneme_index() -> PhonemeIndex:
    global _index
    if _index is None:
        _index = PhonemeIndex()
    return _index
