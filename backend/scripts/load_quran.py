"""One-time loader: quran.com API v4 word-by-word -> Postgres.

Stores dual-script words (decision D1): Uthmani for display, Imlaei-derived
normalized text for matching. Idempotent: truncates and reloads quran tables.

Usage:  python -m scripts.load_quran            (full load, ~130 HTTP requests)
        python -m scripts.load_quran --verify   (only run the verification queries)
"""

import argparse
import sys
import time

import httpx
from sqlalchemy import func, select, text

sys.path.insert(0, ".")  # allow `python -m scripts.load_quran` from backend/

from app.db.models import Ayah, Base, Surah, Word  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.nlp.normalize import normalize  # noqa: E402

API = "https://api.quran.com/api/v4"
WORD_FIELDS = "text_uthmani,text_imlaei,char_type_name"
PER_PAGE = 50
EXPECTED_SURAHS = 114
EXPECTED_AYAHS = 6236


def fetch(client: httpx.Client, url: str, params: dict | None = None, retries: int = 5) -> dict:
    for attempt in range(retries):
        try:
            r = client.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            if attempt == retries - 1:
                raise
            wait = 2**attempt
            print(f"  retry {attempt + 1} after {e!r}, sleeping {wait}s")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def load() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    client = httpx.Client(headers={"User-Agent": "ReciteIQ-loader/0.1"})

    # Idempotent reload of the static Quran tables only
    db.execute(text("TRUNCATE words, ayahs, surahs RESTART IDENTITY CASCADE"))

    chapters = fetch(client, f"{API}/chapters")["chapters"]
    assert len(chapters) == EXPECTED_SURAHS
    for ch in chapters:
        db.add(
            Surah(
                id=ch["id"],
                name_arabic=ch["name_arabic"],
                name_english=ch["name_simple"],
                ayah_count=ch["verses_count"],
            )
        )
    db.flush()

    total_words = 0
    for ch in chapters:
        sid = ch["id"]
        page = 1
        while True:
            data = fetch(
                client,
                f"{API}/verses/by_chapter/{sid}",
                params={
                    "words": "true",
                    "word_fields": WORD_FIELDS,
                    "fields": "text_uthmani",
                    "per_page": PER_PAGE,
                    "page": page,
                },
            )
            for v in data["verses"]:
                db.add(
                    Ayah(
                        id=v["id"],
                        surah_id=sid,
                        number=v["verse_number"],
                        verse_key=v["verse_key"],
                        text_uthmani=v["text_uthmani"],
                    )
                )
                pos = 0
                for w in v["words"]:
                    if w["char_type_name"] != "word":  # skip ayah-number "end" markers
                        continue
                    pos += 1
                    imlaei = w.get("text_imlaei") or w["text_uthmani"]
                    db.add(
                        Word(
                            id=w["id"],
                            ayah_id=v["id"],
                            position=pos,
                            text_uthmani=w["text_uthmani"],
                            text_imlaei=imlaei,
                            text_normalized=normalize(imlaei),
                        )
                    )
                    total_words += 1
            if data["pagination"]["next_page"] is None:
                break
            page += 1
        db.flush()
        print(f"surah {sid:3d} loaded ({ch['name_simple']})")

    db.commit()
    print(f"\nDone: {total_words} words.")
    client.close()
    db.close()


def verify() -> int:
    db = SessionLocal()
    ok = True

    n_surahs = db.scalar(select(func.count(Surah.id)))
    n_ayahs = db.scalar(select(func.count(Ayah.id)))
    n_words = db.scalar(select(func.count(Word.id)))
    print(f"surahs={n_surahs} ayahs={n_ayahs} words={n_words}")
    ok &= n_surahs == EXPECTED_SURAHS
    ok &= n_ayahs == EXPECTED_AYAHS
    ok &= bool(n_words) and n_words > 77000  # ~77.4k word tokens

    # D1 spot-check: Uthmani rasm must diverge from normalized Imlaei on صلاة-family words
    row = db.execute(
        select(Word.text_uthmani, Word.text_imlaei, Word.text_normalized)
        .join(Ayah)
        .where(Ayah.verse_key == "2:3", Word.position == 5)
    ).one()
    print(f"2:3 word 5: uthmani={row.text_uthmani} imlaei={row.text_imlaei} norm={row.text_normalized}")
    ok &= row.text_normalized == "الصلاه"  # normalized: no diacritics, ta-marbuta -> ha
    # D1 property: Uthmani rasm differs from Imlaei on this word (الصلوة vs الصلاة) —
    # normalizing the Uthmani form must NOT equal the Imlaei-derived matching key
    ok &= normalize(row.text_uthmani) != row.text_normalized

    # Ordered word query works for an arbitrary ayah
    words = db.execute(
        select(Word.text_normalized).join(Ayah).where(Ayah.verse_key == "1:2").order_by(Word.position)
    ).scalars().all()
    print(f"1:2 normalized: {' '.join(words)}")
    ok &= words[0] == "الحمد"

    # No empty normalized forms
    empties = db.scalar(select(func.count(Word.id)).where(Word.text_normalized == ""))
    print(f"empty normalized words: {empties}")
    ok &= empties == 0

    db.close()
    print("VERIFY:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    if args.verify:
        raise SystemExit(verify())
    load()
    raise SystemExit(verify())
