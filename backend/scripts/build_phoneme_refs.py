"""Reference batch: model-derived ayah-level phoneme IDs (Approach A).

For every ayah, run the encoder-CTC recognizer on EACH reciter in `RECITERS` and
store one reference row per reciter (P0-1), so the matcher can score against
whichever voice is closest instead of against one professional's exact output.
`ayahs.phoneme_ids` is still written with the canonical (Husary) sequence, so the
previous single-reference path stays available as a rollback.

Confidence is the mean PAIRWISE agreement over the references actually obtained;
a failed download reduces the reference count rather than fabricating an
agreement of 0.0. Basmalah stripping for non-Surah-1 first ayahs uses EACH
reciter's own basmalah template.

Audio is fetched to a temp dir, transcribed and discarded — only integer ID
sequences are stored. Verify redistribution terms per reciter before shipping
these assets anywhere public (see the note on RECITERS).

Resumable: skips ayahs that already have per-reciter refs unless --force.
Usage:  python -m scripts.build_phoneme_refs [--limit N] [--surah S ...] [--force]
Pilot:  python -m scripts.build_phoneme_refs --surah 1 109 111 112 113 --force
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
from app.db.models import Ayah, AyahPhonemeRef  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402

# P0-1: stylistically diverse voices — murattal and mujawwad, fast and slow — so
# the reference set spans tempo and elongation instead of one reciter's style.
# Measured motivation: an amateur scores CER 0.45-0.50 against Husary alone where
# a qari scores 0.04-0.21 (docs/baseline-m0-amateur-first.md).
#
# LICENSING: verify redistribution terms per reciter before shipping any of this
# in a public repo, thesis artifact or deployment package. Only derived integer ID
# sequences are stored — the audio is fetched to a temp dir and discarded — which
# is the posture to keep, since derived references may be distributable where the
# source audio is not.
RECITERS = [
    "Husary_128kbps",
    "Abdul_Basit_Murattal_192kbps",
    "Minshawy_Murattal_128kbps",
    "Alafasy_128kbps",
    "Abu_Bakr_Ash-Shaatree_128kbps",
    "Menshawi_16kbps",
]
UNSTABLE_AGREEMENT = 0.75  # below this mean pairwise agreement → flag low-confidence
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

    # PER-RECITER basmalah templates. The old code fetched ONE template from
    # RECITERS[0] and stripped every reciter's ayah 1 with it — Abdul Basit's
    # ayah 1 was being trimmed using Husary's IDs. That cross-reciter strip is
    # why ayah 1 is unstable in 29 surahs (25.4% vs 14.3% elsewhere).
    basmalah: dict[str, list[int]] = {}
    for reciter in RECITERS:
        a = fetch_audio(client, reciter, "001001")
        basmalah[reciter] = model.ids(a) if a is not None else []
        print(f"basmalah template {reciter}: len={len(basmalah[reciter])}")

    q = select(Ayah).order_by(Ayah.id)
    if surah:
        q = q.where(Ayah.surah_id.in_(surah))
    ayahs = db.execute(q).scalars().all()

    done = built = flagged = failed = 0
    for ayah in ayahs:
        if ayah.phoneme_refs and not force:
            continue          # already has per-reciter refs; --force to rebuild
        if limit and built >= limit:
            break
        code = f"{ayah.surah_id:03d}{ayah.number:03d}"
        seqs: dict[str, list[int]] = {}
        for reciter in RECITERS:
            audio = fetch_audio(client, reciter, code)
            if audio is None:
                continue                      # missing audio only reduces n_refs
            ids = model.ids(audio)
            if ayah.number == 1 and ayah.surah_id != 1 and basmalah.get(reciter):
                ids = _strip_basmalah(ids, basmalah[reciter])   # this reciter's own template
            if ids:
                seqs[reciter] = ids

        if not seqs:
            failed += 1
            print(f"  {code}: FAILED (no audio from any reciter)")
            continue

        # Store one row per reciter, replacing any previous rows for this ayah.
        ayah.phoneme_refs.clear()
        for reciter, ids in seqs.items():
            ayah.phoneme_refs.append(AyahPhonemeRef(
                reciter=reciter, ids=ids,
                source_url=f"{EVERYAYAH}/{reciter}/{code}.mp3",
            ))

        # Confidence = MEAN PAIRWISE agreement over the references we actually
        # got. The old code set agreement=0.0 whenever a single download failed,
        # which silently marked good references unstable (20 ayahs).
        vals = list(seqs.values())
        pairs = [1 - Levenshtein.normalized_distance(vals[i], vals[j])
                 for i in range(len(vals)) for j in range(i + 1, len(vals))]
        agreement = sum(pairs) / len(pairs) if pairs else None

        ayah.phoneme_ids = seqs.get(RECITERS[0], vals[0])   # legacy canonical, for rollback
        ayah.phoneme_confidence = round(agreement, 4) if agreement is not None else None
        # A confidence signal now, NOT an exclusion — load_phoneme_reference no
        # longer drops these. Unknown agreement (one reference) is not "unstable".
        ayah.phoneme_unstable = agreement is not None and agreement < UNSTABLE_AGREEMENT
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
    ap.add_argument("--surah", type=int, nargs="+", default=None,
                    help="one or more surah ids, e.g. --surah 1 109 111 112 113")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    build(args.limit, args.surah, args.force)
