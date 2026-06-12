"""Offline Mutashabeh pair builder (decision D6: lexical, not embeddings).

Two-stage: (1) word-3-gram inverted index generates candidate pairs (any two
ayahs sharing a non-ubiquitous 3-gram); (2) candidates are scored with fuzzy
substring similarity (rapidfuzz partial_ratio on the normalized text). Stage 2
matters: famous twins like 6:151 / 17:31 share a phrase but differ in single
words (من/خشية, نرزقكم/نرزقهم) — exact n-gram containment scores them near
zero while fuzzy substring similarity scores them high.

Usage: python -m scripts.build_mutashabeh [--threshold 72] [--verify]
"""

import argparse
import sys
from collections import defaultdict

sys.path.insert(0, ".")

from sqlalchemy import func, select, text  # noqa: E402

from app.db.models import Ayah, MutashabehPair, Word  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402

MIN_NGRAMS = 2  # ayahs shorter than N+2 words can't form 2 distinct 3-grams; skip 1-2 word ayahs


def ayah_ngrams(words: list[str], n: int = 3) -> set[tuple[str, ...]]:
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def load_ayah_words(db) -> dict[int, list[str]]:
    rows = db.execute(
        select(Word.ayah_id, Word.text_normalized).order_by(Word.ayah_id, Word.position)
    ).all()
    out: dict[int, list[str]] = defaultdict(list)
    for ayah_id, norm in rows:
        out[ayah_id].append(norm)
    return out


def build(threshold: float) -> None:
    db = SessionLocal()
    ayah_words = load_ayah_words(db)
    grams: dict[int, set] = {a: ayah_ngrams(w) for a, w in ayah_words.items()}

    # Inverted index: 3-gram -> ayahs containing it
    inv: dict[tuple, list[int]] = defaultdict(list)
    for a, gs in grams.items():
        for g in gs:
            inv[g].append(a)

    # Stage 1: candidate pairs share >= 1 non-ubiquitous gram
    candidates: set[tuple[int, int]] = set()
    for g, ayahs in inv.items():
        if len(ayahs) > 60:
            continue  # ubiquitous formulae (e.g. ان الله) — pure noise, O(n^2) blowup
        for i in range(len(ayahs)):
            for j in range(i + 1, len(ayahs)):
                candidates.add((ayahs[i], ayahs[j]))

    # Stage 2: fuzzy score of WORD WINDOWS anchored at the first shared gram.
    # Mutashabeh confusion is phrase-level: whole-ayah comparison dilutes the
    # confusable phrase with unrelated text (6:151 is 30+ words around a
    # 9-word twin of 17:31), so we compare W words from the anchor instead.
    from rapidfuzz import fuzz

    W = 10
    gram_pos: dict[int, dict[tuple, int]] = {}  # ayah -> gram -> first position
    for a, words in ayah_words.items():
        pos: dict[tuple, int] = {}
        for i in range(len(words) - 2):
            pos.setdefault(tuple(words[i : i + 3]), i)
        gram_pos[a] = pos

    db.execute(text("TRUNCATE mutashabeh_pairs RESTART IDENTITY"))
    kept = 0
    for a, b in candidates:
        ga, gb = grams[a], grams[b]
        if len(ga) < MIN_NGRAMS or len(gb) < MIN_NGRAMS:
            continue
        shared = ga & gb
        best = 0.0
        for g in shared:
            pa, pb = gram_pos[a][g], gram_pos[b][g]
            wa = " ".join(ayah_words[a][pa : pa + W])
            wb = " ".join(ayah_words[b][pb : pb + W])
            best = max(best, fuzz.ratio(wa, wb))
        if best >= threshold:
            db.add(MutashabehPair(source_ayah_id=a, target_ayah_id=b, score=round(best / 100, 4)))
            db.add(MutashabehPair(source_ayah_id=b, target_ayah_id=a, score=round(best / 100, 4)))
            kept += 1
    db.commit()
    print(f"candidate pairs: {len(candidates)}, kept (>= {threshold}): {kept} (x2 directed rows)")
    db.close()


def verify() -> int:
    db = SessionLocal()
    n = db.scalar(select(func.count(MutashabehPair.id)))
    print(f"mutashabeh_pairs rows: {n}")
    ok = bool(n) and n > 1000

    # Famous twins must be present: Baqarah 2:58 vs A'raf 7:161 (ادخلوا/اسكنوا القرية...),
    # and Ar-Rahman refrain ayahs pair with each other
    def has_pair(key_a: str, key_b: str) -> bool:
        a = db.scalar(select(Ayah.id).where(Ayah.verse_key == key_a))
        b = db.scalar(select(Ayah.id).where(Ayah.verse_key == key_b))
        return (
            db.scalar(
                select(func.count(MutashabehPair.id)).where(
                    MutashabehPair.source_ayah_id == a, MutashabehPair.target_ayah_id == b
                )
            )
            > 0
        )

    for ka, kb in [("55:13", "55:16"), ("2:48", "2:123"), ("6:151", "17:31")]:
        present = has_pair(ka, kb)
        print(f"twin {ka} <-> {kb}: {'present' if present else 'MISSING'}")
        ok &= present
    db.close()
    print("VERIFY:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=72.0)  # partial_ratio 0..100
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    if args.verify:
        raise SystemExit(verify())
    build(args.threshold)
    raise SystemExit(verify())
