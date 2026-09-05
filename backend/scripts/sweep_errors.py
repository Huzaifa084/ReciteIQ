"""Inject each error type into every surah and check the right event fires.

The perfect-input sweep proves the tracker does not INVENT errors. This proves
it still catches real ones at the same scale — the two failure modes trade off
against each other, so neither number means much alone.

Synthetic, so it isolates the detector: no ASR noise, no segmentation artifacts.
Errors are injected at a mid-surah ayah to avoid start/end special cases.
"""
import sys
sys.path.insert(0, "/opt/apps/ReciteIQ/backend")
import os; os.chdir("/opt/apps/ReciteIQ/backend")
from collections import Counter

from app.db.repo import load_reference
from app.db.session import SessionLocal
from app.engine.detector import RecitationTracker
from app.mutashabeh.index import get_relocation_index
from app.engine.events import EventState, EventType

W = 30
print('building relocation index...', flush=True)
RELOC = get_relocation_index()


def run(ref, toks):
    tr = RecitationTracker(ref, preamble=False, relocation=RELOC)
    ev = []
    for i in range(0, len(toks), W):
        ev += tr.feed_segment(toks[i:i + W])
    return ev


def confirmed(ev, t):
    return [e for e in ev if e.type == t and e.state == EventState.CONFIRMED]


db = SessionLocal()
res = Counter()
misses = {"skip_word": [], "skip_ayah": [], "repeat": [], "substitute": []}

for surah in range(1, 115):
    ref = load_reference(db, surah)
    by_ayah = {}
    for w in ref:
        by_ayah.setdefault(w.ayah, []).append(w)
    ayahs = sorted(by_ayah)
    if len(ayahs) < 5:
        continue
    mid = ayahs[len(ayahs) // 2]
    idxs = [w.idx for w in by_ayah[mid]]
    if len(idxs) < 3:
        continue
    base = [w.norm for w in ref]

    # 1. skipped word — drop the 2nd word of a mid ayah
    drop = idxs[1]
    ev = run(ref, [t for i, t in enumerate(base) if i != drop])
    hit = any(e.payload.get("idx") == drop for e in confirmed(ev, EventType.MISSED_WORD))
    res["skip_word_ok" if hit else "skip_word_miss"] += 1
    if not hit:
        misses["skip_word"].append(surah)

    # 2. skipped ayah — drop a whole mid ayah
    ev = run(ref, [t for i, t in enumerate(base) if i not in set(idxs)])
    named = any(e.payload.get("ayah") == mid for e in confirmed(ev, EventType.MISSED_AYAH))
    jumped = bool(confirmed(ev, EventType.MUTASHABEH_JUMP))
    res["skip_ayah_ok" if (named or jumped) else "skip_ayah_miss"] += 1
    res["skip_ayah_named"] += 1 if named else 0
    res["skip_ayah_only_jump"] += 1 if (jumped and not named) else 0
    res["skip_ayah_jump_noise"] += len(confirmed(ev, EventType.MUTASHABEH_JUMP))
    if not (named or jumped):
        misses["skip_ayah"].append(surah)

    # 3. repeated ayah
    ev = run(ref, base[:idxs[-1] + 1] + [base[i] for i in idxs] + base[idxs[-1] + 1:])
    hit = bool(confirmed(ev, EventType.REPEAT))
    clean = not confirmed(ev, EventType.MISSED_AYAH) and not confirmed(ev, EventType.MISSED_WORD)
    res["repeat_ok" if hit else "repeat_miss"] += 1
    res["repeat_false_error"] += 0 if clean else 1
    if not hit:
        misses["repeat"].append(surah)

    # 4. substituted word — replace a mid word with a non-Quranic token
    sub = list(base); sub[idxs[1]] = "زقزقزق"
    ev = run(ref, sub)
    hit = any(e.payload.get("idx") == idxs[1] for e in confirmed(ev, EventType.MISSED_WORD))
    res["substitute_ok" if hit else "substitute_miss"] += 1
    if not hit:
        misses["substitute"].append(surah)

db.close()
for k in ("skip_word", "skip_ayah", "repeat", "substitute"):
    ok, miss = res[f"{k}_ok"], res[f"{k}_miss"]
    print(f"{k:11s} caught {ok:3d}/{ok+miss:3d} ({100*ok/(ok+miss):5.1f}%)"
          f"   missed in surahs: {misses[k][:12]}")
print(f"  of skip_ayah: named as MISSED_AYAH {res['skip_ayah_named']}, "
      f"only a JUMP {res['skip_ayah_only_jump']}, "
      f"total jump events {res['skip_ayah_jump_noise']}")
print(f"repeat clips that also raised a false error: {res['repeat_false_error']}")
