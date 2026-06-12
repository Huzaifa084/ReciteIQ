"""Phase 1 ASR bench-off: accuracy (normalized token match vs DB reference) and
CPU latency on THIS box, per model. Uses EveryAyah qari clips as ground truth.

Usage: python -m scripts.bench_asr
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

import httpx  # noqa: E402
from rapidfuzz import fuzz  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.repo import load_reference  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.nlp.normalize import tokenize  # noqa: E402

AUDIO_DIR = Path("eval/audio")
# (surah, ayah) test set: short+long, incl. الصلاة-family orthography (2:3)
CLIPS = [(1, a) for a in range(1, 8)] + [(2, 3), (112, 1), (112, 2), (112, 3), (112, 4)]
RECITER = "Alafasy_128kbps"
MODELS = {
    "tarteel-base-ct2": "models/whisper-base-ar-quran-ct2",
    "tarteel-tiny-ct2": "models/whisper-tiny-ar-quran-ct2",
}


def fetch_clips() -> list[tuple[int, int, Path]]:
    out = []
    with httpx.Client() as client:
        for s, a in CLIPS:
            mp3 = AUDIO_DIR / f"{s:03d}{a:03d}.mp3"
            wav = AUDIO_DIR / f"{s:03d}{a:03d}.wav"
            if not wav.exists():
                if not mp3.exists():
                    url = f"https://everyayah.com/data/{RECITER}/{s:03d}{a:03d}.mp3"
                    r = client.get(url, timeout=60)
                    r.raise_for_status()
                    mp3.write_bytes(r.content)
                import subprocess

                subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ar", "16000", "-ac", "1", str(wav)],
                    check=True,
                )
            out.append((s, a, wav))
    return out


def token_accuracy(hyp_tokens: list[str], ref_tokens: list[str]) -> float:
    """Greedy in-order fuzzy token match rate against the reference ayah."""
    if not ref_tokens:
        return 0.0
    hits, j = 0, 0
    for rt in ref_tokens:
        for k in range(j, len(hyp_tokens)):
            if fuzz.ratio(hyp_tokens[k], rt) >= settings.match_score_min:
                hits += 1
                j = k + 1
                break
    return hits / len(ref_tokens)


def main() -> None:
    from faster_whisper import WhisperModel

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    clips = fetch_clips()
    db = SessionLocal()
    refs = {}
    for s, a, _ in clips:
        if s not in refs:
            refs[s] = load_reference(db, s)

    print(f"{'model':18s} {'clip':8s} {'dur(s)':>6s} {'asr(s)':>7s} {'RTF':>5s} {'acc':>5s}")
    for name, path in MODELS.items():
        model = WhisperModel(path, device="cpu", compute_type="int8", cpu_threads=settings.asr_cpu_threads)
        total_dur = total_time = 0.0
        accs = []
        for s, a, wav in clips:
            t0 = time.perf_counter()
            segments, info = model.transcribe(
                str(wav), language="ar", beam_size=1, condition_on_previous_text=False, vad_filter=False
            )
            text = " ".join(seg.text for seg in segments)
            dt = time.perf_counter() - t0
            ref_tokens = [w.norm for w in refs[s] if w.ayah == a]
            acc = token_accuracy(tokenize(text), ref_tokens)
            accs.append(acc)
            total_dur += info.duration
            total_time += dt
            print(f"{name:18s} {f'{s}:{a}':8s} {info.duration:6.1f} {dt:7.2f} {dt / info.duration:5.2f} {acc:5.0%}")
        print(
            f"{name:18s} {'TOTAL':8s} {total_dur:6.1f} {total_time:7.2f} "
            f"{total_time / total_dur:5.2f} {sum(accs) / len(accs):5.0%}\n"
        )
        del model
    db.close()


if __name__ == "__main__":
    main()
