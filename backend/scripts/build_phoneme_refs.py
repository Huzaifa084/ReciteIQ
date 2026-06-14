"""v1 reference batch: model-derived ayah-level phoneme IDs (Approach A).

For every ayah, run the encoder-CTC recognizer on 2 reciters (Husary +
Abdul Basit), strip prepended basmalah from non-Surah-1 first ayahs, take the
canonical sequence (Husary) and a cross-reciter agreement confidence; flag
unstable (low-agreement) ayahs. Audio is downloaded to a temp file, transcribed,
and discarded — only integer ID sequences are stored.

Resumable: skips ayahs that already have phoneme_ids unless --force.
Usage:  python -m scripts.build_phoneme_refs [--limit N] [--surah S] [--force]
"""

import argparse
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import httpx
import numpy as np
from rapidfuzz.distance import Levenshtein
from sqlalchemy import select

sys.path.insert(0, ".")
from app.asr.phoneme_ctc import get_phoneme_ctc  # noqa: E402
from app.db.models import Ayah  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402

RECITERS = ["Husary_128kbps", "Abdul_Basit_Murattal_192kbps"]
UNSTABLE_AGREEMENT = 0.75  # below this cross-reciter agreement → flag unstable
EVERYAYAH = "https://everyayah.com/data"


def fetch_audio(client: httpx.Client, reciter: str, code: str) -> np.ndarray | None:
    """Download mp3 → 16k mono wav → float32; return None on failure."""
    try:
        r = client.get(f"{EVERYAYAH}/{reciter}/{code}.mp3", timeout=30)
        if r.status_code != 200 or not r.content:
            return None
        with tempfile.TemporaryDirectory() as td:
            mp3, wav = Path(td) / "a.mp3", Path(td) / "a.wav"
            mp3.write_bytes(r.content)
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ar", "16000", "-ac", "1", str(wav)],
                check=True,
            )
            with wave.open(str(wav)) as w:
                return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0
    except Exception:
        return None


def build(limit: int | None, surah: int | None, force: bool) -> None:
    model = get_phoneme_ctc()
    db = SessionLocal()
    client = httpx.Client(headers={"User-Agent": "ReciteIQ-phoneme-refs/1.0"})

    # basmalah ID template = Surah 1 ayah 1 (Husary), built first
    bas_audio = fetch_audio(client, RECITERS[0], "001001")
    basmalah = model.ids(bas_audio) if bas_audio is not None else []
    print(f"basmalah template len={len(basmalah)}")

    q = select(Ayah).order_by(Ayah.id)
    if surah:
        q = q.where(Ayah.surah_id == surah)
    ayahs = db.execute(q).scalars().all()

    done = built = flagged = failed = 0
    for ayah in ayahs:
        if ayah.phoneme_ids is not None and not force:
            continue
        if limit and built >= limit:
            break
        code = f"{ayah.surah_id:03d}{ayah.number:03d}"
        seqs = []
        for reciter in RECITERS:
            audio = fetch_audio(client, reciter, code)
            if audio is None:
                continue
            ids = model.ids(audio)
            if ayah.number == 1 and ayah.surah_id != 1 and basmalah:
                ids = _strip_basmalah(ids, basmalah)
            seqs.append(ids)

        if not seqs:
            failed += 1
            print(f"  {code}: FAILED (no audio)")
            continue
        canonical = seqs[0]
        if len(seqs) == 2 and seqs[0] and seqs[1]:
            agreement = 1 - Levenshtein.normalized_distance(seqs[0], seqs[1])
        else:
            agreement = 0.0
        ayah.phoneme_ids = canonical
        ayah.phoneme_confidence = round(agreement, 4)
        ayah.phoneme_unstable = agreement < UNSTABLE_AGREEMENT
        built += 1
        flagged += ayah.phoneme_unstable
        if built % 50 == 0:
            db.commit()
            print(f"  ...{built} built ({flagged} unstable, {failed} failed)")

    db.commit()
    done = db.execute(select(Ayah).where(Ayah.phoneme_ids.isnot(None))).scalars().all()
    print(f"\nDone: built {built} this run, {len(done)} total have phoneme_ids, "
          f"{flagged} flagged unstable, {failed} failed.")
    client.close()
    db.close()


def _strip_basmalah(ids: list[int], template: list[int], max_cer: float = 0.30) -> list[int]:
    tlen = len(template)
    if len(ids) < tlen - 4:
        return ids
    best_k, best = None, 1.0
    lo, hi = max(2, tlen - 6), min(len(ids) - 2, tlen + 7)
    for k in range(lo, max(lo + 1, hi)):
        c = Levenshtein.normalized_distance(ids[:k], template)
        if c < best:
            best, best_k = c, k
    return ids[best_k:] if (best_k and best <= max_cer) else ids


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--surah", type=int, default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    build(args.limit, args.surah, args.force)
