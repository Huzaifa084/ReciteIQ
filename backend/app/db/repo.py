"""Read helpers over the static Quran tables."""

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.db.models import Ayah, Surah, Word
from app.engine.aligner import RefWord


def load_reference(db: DBSession, surah_id: int, start_ayah: int = 1) -> list[RefWord]:
    """Flat session reference: words of `surah_id` from `start_ayah` to surah end."""
    rows = db.execute(
        select(
            Word.id,
            Word.position,
            Word.text_normalized,
            Ayah.id.label("ayah_id"),
            Ayah.number,
            Ayah.surah_id,
        )
        .join(Ayah, Word.ayah_id == Ayah.id)
        .where(Ayah.surah_id == surah_id, Ayah.number >= start_ayah)
        .order_by(Ayah.number, Word.position)
    ).all()
    return [
        RefWord(
            idx=i,
            word_id=r.id,
            surah=r.surah_id,
            ayah=r.number,
            ayah_id=r.ayah_id,
            position=r.position,
            norm=r.text_normalized,
        )
        for i, r in enumerate(rows)
    ]


def load_phoneme_reference(db: DBSession, surah_id: int, start_ayah: int = 1):
    """Session reference for the phoneme tracker: ordered RefAyah list with each
    ayah's model-derived IDs + its word refs (for WORD_OK bursts).

    An ayah is trackable if it has ANY reference — either a per-reciter row
    (P0-1) or the legacy canonical. `phoneme_unstable` is a confidence signal,
    not an exclusion: it was excluding ayah 1 in 29 surahs (25.4% unstable vs
    14.3% elsewhere, from cross-reciter basmalah stripping), i.e. exactly where
    reciters start. Ayahs with no reference at all are still skipped."""
    from app.engine.phoneme_tracker import RefAyah

    # Enumerate idx across ALL ayahs from start_ayah so word_refs.idx matches the
    # SPA's MushafView enumeration (which renders every ayah). An ayah with no
    # reference still consumes its idx range — that invariant is what keeps the
    # highlighting aligned — it just never becomes a matchable RefAyah.
    ayahs = db.execute(
        select(Ayah).where(Ayah.surah_id == surah_id, Ayah.number >= start_ayah).order_by(Ayah.number)
    ).scalars().all()
    out = []
    idx = 0
    for a in ayahs:
        word_refs = []
        for w in a.words:
            word_refs.append(
                {"surah": surah_id, "ayah": a.number, "position": w.position, "word_id": w.id, "idx": idx}
            )
            idx += 1
        variants = [list(r.ids) for r in a.phoneme_refs if r.ids]
        canonical = list(a.phoneme_ids) if a.phoneme_ids else (variants[0] if variants else None)
        if canonical is None:
            continue  # no reference at all; idx already advanced so highlights don't drift
        out.append(RefAyah(ayah_id=a.id, surah=surah_id, number=a.number,
                           ids=canonical, word_refs=word_refs,
                           variants=variants or [canonical]))
    return out


def surah_list(db: DBSession) -> list[dict]:
    return [
        {"id": s.id, "name_arabic": s.name_arabic, "name_english": s.name_english, "ayah_count": s.ayah_count}
        for s in db.execute(select(Surah).order_by(Surah.id)).scalars()
    ]


def ayah_display(db: DBSession, surah_id: int, start_ayah: int = 1) -> list[dict]:
    """Display payload for the SPA MushafView: per-ayah Uthmani words keyed by idx."""
    ayahs = db.execute(
        select(Ayah).where(Ayah.surah_id == surah_id, Ayah.number >= start_ayah).order_by(Ayah.number)
    ).scalars().all()
    out = []
    for a in ayahs:
        out.append(
            {
                "ayah": a.number,
                "verse_key": a.verse_key,
                "words": [
                    {"word_id": w.id, "position": w.position, "text": w.text_uthmani} for w in a.words
                ],
            }
        )
    return out
