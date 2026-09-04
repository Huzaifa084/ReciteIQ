"""Controlled segmentation experiment. Reference strategy is held FIXED
(phoneme_ref_rule='single', Husary canonical) so segmentation is the only variable.

Conditions
  baseline   current behaviour: every window recognised and matched on its own
  carry      (1) an unmatched window's IDs are prepended to the next window's IDs
  silence12  (2) phoneme_silence_cut_sec 0.5 -> 1.2, so short pauses stop cutting
  mindur     (3) segments under MIN_SEC are held and their AUDIO concatenated
                 with the next segment before recognition
  mindur+sil combination of (2) and (3)

Mirrors app/ws/phoneme_session.py's loop (segmenter -> recognize -> tracker.feed);
the WS/DB work in the real handler does not affect matching.
"""
import sys, time, wave
import numpy as np

from app.asr.phoneme_ctc import get_phoneme_ctc
from app.audio.vad import StreamSegmenter
from app.config import settings
from app.db.repo import load_phoneme_reference
from app.db.session import SessionLocal
from app.engine.events import EventState, EventType
from app.engine.phoneme_tracker import PhonemeTracker

settings.phoneme_ref_rule = "single"          # hold the reference strategy fixed

import os
# 2.0s proved ineffective: a segment carries its trailing silence up to the cut
# point, so 1.5s of speech lands at ~2.0s and the gate never fired.
MIN_SEC = float(os.environ.get("SEG_MIN_SEC", "3.5"))
CARRY_MAX_IDS = 400                            # (1) cap so carry-forward cannot grow forever

model = get_phoneme_ctc()
_db = SessionLocal()
REF = {s: load_phoneme_reference(_db, s) for s in (1, 112)}
_db.close()


def read(path):
    with wave.open(path) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16)


def run(pcm, surah, cond):
    # condition names encode their own silence_cut, e.g. "sil08" -> 0.8s
    silence_cut = settings.phoneme_silence_cut_sec
    for tok in cond.split("+"):
        if tok.startswith("sil") and tok[3:].isdigit():
            silence_cut = int(tok[3:]) / 10.0
    if cond in ("silence12", "mindur+sil"):
        silence_cut = 1.2
    seg = StreamSegmenter(max_sec=settings.phoneme_segment_max_sec, silence_cut_sec=silence_cut)
    tr = PhonemeTracker(ref=REF[surah])
    raw = pcm.tobytes()

    carry: list[int] = []
    held: np.ndarray | None = None
    stats = {"windows": 0, "no_match": 0, "infer_ms": 0, "n_infer": 0,
             "missed": 0, "cers": [], "durs": []}
    events = []

    def process(audio, duration):
        nonlocal carry
        stats["windows"] += 1
        stats["durs"].append(duration)
        t0 = time.perf_counter()
        res = model.recognize(audio)
        stats["infer_ms"] += int((time.perf_counter() - t0) * 1000)
        stats["n_infer"] += 1
        ids = (carry + res.ids) if "carry" in cond else res.ids
        ev = tr.feed(ids, c_ctc=res.c_ctc)
        events.extend(ev)
        d = tr.last_diag
        if d.get("outcome") == "no_match":
            stats["no_match"] += 1
            if "carry" in cond:
                carry = (carry + res.ids)[-CARRY_MAX_IDS:]
        else:
            carry = []
            if d.get("chain_mean_cer") is not None:
                stats["cers"].append(d["chain_mean_cer"])

    CH = 8000
    segments = []
    for i in range(0, len(raw), CH):
        segments.extend(seg.feed(raw[i:i + CH]))
    if (s := seg.flush()) is not None:
        segments.append(s)

    for s in segments:
        if cond in ("mindur", "mindur+sil") and s.duration < MIN_SEC:
            held = s.audio if held is None else np.concatenate([held, s.audio])
            continue
        audio, dur = s.audio, s.duration
        if held is not None:
            audio = np.concatenate([held, audio])
            dur += len(held) / 16000
            held = None
        process(audio, dur)
    if held is not None and len(held) > 0:
        process(held, len(held) / 16000)

    credited = sorted({e.payload["ayah"] for e in events
                       if e.type == EventType.WORD_OK and e.state == EventState.CONFIRMED})
    stats["missed"] = len({e.payload["ayah"] for e in events
                           if e.type == EventType.MISSED_AYAH and e.state == EventState.CONFIRMED})
    stats["uncertain"] = len({e.payload["ayah"] for e in events
                              if e.type == EventType.UNCERTAIN and e.state == EventState.PROVISIONAL})
    stats["credited"] = credited
    return stats


CONDS = os.environ.get("SEG_CONDS", "baseline,carry,silence12,mindur,mindur+sil").split(",")
# label, path, surah-to-track, expectation
FIXTURES = [(a, b, int(c)) for a, b, c in zip(sys.argv[1::3], sys.argv[2::3], sys.argv[3::3])]

for label, path, surah in FIXTURES:
    pcm = read(path)
    print(f"\n=== {label}  ({len(pcm)/16000:.1f}s, tracking surah {surah}, MIN_SEC={MIN_SEC}) ===")
    print(f"{'condition':<12} {'wins':>5} {'no_match':>9} {'credited':>9} "
          f"{'missed':>7} {'uncert':>7} {'meanCER':>8} {'infer_ms':>9} {'shortest':>9}")
    for cond in CONDS:
        s = run(pcm, surah, cond)
        cer = sum(s["cers"]) / len(s["cers"]) if s["cers"] else float("nan")
        print(f"{cond:<12} {s['windows']:5d} {s['no_match']:9d} "
              f"{len(s['credited']):6d}/{len(REF[surah]):<2d} {s['missed']:7d} {s['uncertain']:7d} "
              f"{cer:8.3f} {s['infer_ms']:9d} {min(s['durs']):9.2f}")
