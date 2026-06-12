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
