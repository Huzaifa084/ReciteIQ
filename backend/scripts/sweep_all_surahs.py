"""Detector sweep over every surah, with perfect ASR.

Feeds each surah's own reference words back through RecitationTracker in
realistic multi-ayah windows. Perfect input isolates the DETECTOR: any error
here is alignment or bookkeeping, never transcription. This is the question
"is the text path really limited to a few curated surahs?" answered directly —
the phoneme path needed a hand-built CTC reference per surah, this one reads
the Quran tables, which hold all 114.

The refrain surahs are the real test: Ar-Rahman repeats one ayah 31 times, and
Al-Mursalat 10 times.
"""
import sys
sys.path.insert(0, "/opt/apps/ReciteIQ/backend")
import os; os.chdir("/opt/apps/ReciteIQ/backend")

from app.db.repo import load_reference
from app.db.session import SessionLocal
from app.engine.detector import RecitationTracker
from app.engine.events import EventState, EventType

WINDOW_WORDS = 30          # ~25s of recitation at the measured 1.2 words/sec

db = SessionLocal()
bad = []
tot_words = tot_ok = 0
for surah in range(1, 115):
    ref = load_reference(db, surah)
    if not ref:
        bad.append((surah, "no reference"))
        continue
    tr = RecitationTracker(ref, preamble=False)
    ev = []
    toks = [w.norm for w in ref]
    for i in range(0, len(toks), WINDOW_WORDS):
        ev += tr.feed_segment(toks[i:i + WINDOW_WORDS])
    ok = {e.payload["idx"] for e in ev
          if e.type == EventType.WORD_OK and e.state == EventState.CONFIRMED}
    mw = sum(1 for e in ev if e.type == EventType.MISSED_WORD
             and e.state == EventState.CONFIRMED)
    ma = sum(1 for e in ev if e.type == EventType.MISSED_AYAH
             and e.state == EventState.CONFIRMED)
    jm = sum(1 for e in ev if e.type == EventType.MUTASHABEH_JUMP
             and e.state == EventState.CONFIRMED)
    rp = sum(1 for e in ev if e.type == EventType.REPEAT)
    tot_words += len(ref); tot_ok += len(ok)
    if len(ok) != len(ref) or mw or ma or jm or rp:
        bad.append((surah, f"{len(ok)}/{len(ref)} words, "
                           f"missed_w={mw} missed_a={ma} jumps={jm} repeats={rp}"))
db.close()

print(f"words credited {tot_ok}/{tot_words} ({100*tot_ok/tot_words:.2f}%)")
print(f"surahs with any defect: {len(bad)}/114")
for s, why in bad[:25]:
    print(f"  surah {s:3d}: {why}")
print("SWEEP " + ("PASS" if not bad else "FAIL"))
