# How much of the Qur'an does the text path actually handle?

The phoneme path needed a hand-built CTC reference per surah, so it covered a
handful. The text detector reads the Qur'an tables — all 114 surahs, 6,236
ayahs, 77,429 words — and the relocation index is built over every one of them
with no filter. So the honest question is not "is it curated?" but "where does
it hold up?"

Two sweeps answer that. Both feed reference words directly, so there is no ASR
noise and no segmentation artifact: any failure is the detector's.

## Perfect recitation — all 114 surahs

`scripts/sweep_all_surahs.py`

**77,429 / 77,429 words credited (100.00%), 0 surahs with any defect.**
No false MISSED_WORD, MISSED_AYAH, REPEAT or JUMP anywhere in the Qur'an.
Ar-Rahman — one ayah repeated 31 times, the case the tracker was most feared to
mishandle — passes clean.

Getting there fixed a real bug. The first run scored 77,319/77,429 with 15
defective surahs, all traced to one cause: the multi-word merge consuming words
that stand on their own. In Al-Hijr the two CORRECT words الا + ابليس join to
"الا ابليس", which scores 82.4 against the unit "يا ابليس" nine words later —
clearing both the match threshold and the length guard. Two right words were
fused and matched to the wrong place, costing a false MISSED_AYAH and a false
REPEAT on a flawless recitation.

## Deliberate errors — 104 surahs, four error types

`scripts/sweep_errors.py`, injecting into a mid-surah ayah.

| error | caught |
|---|---|
| skipped word | **104/104 (100%)** |
| substituted word | **104/104 (100%)** |
| skipped ayah | 88/104 (84.6%) |
| repeated ayah | 90/104 (86.5%) |

Word-level detection is perfect. Ayah-level is not, and the failures are
concentrated in long surahs for a structural reason.

## The boundary: `align_window_fwd`

The aligner searches 12 words ahead of the pointer. **Only 42 of 114 surahs have
every ayah inside that window.** Al-Baqarah's longest ayah is 128 words; Surah 4
reaches 88, Surah 24 and Surah 73 reach 78.

When a skipped ayah is longer than the window, the word the reciter resumes on
is out of the aligner's reach. Relocation does not rescue it either, because D8
deliberately refuses to call a JUMP for a destination within ±2 ayahs — that
rule exists so refrains do not fire spurious jumps. So a long skip falls between
the two mechanisms.

Without the relocation index the consequence is severe: Surah 2 stops dead at
word 2550 of 6116 and reports nothing at all. With it, the session recovers, but
noisily — a single skipped ayah in Surah 2 produced 58 confirmed JUMP events.

**All six release-gate surahs (1, 84, 86, 99, 100, 109) are inside the safe 42.**
So this bounds expansion, not the shipped scope.

## Two fixes tried and reverted

Neither earned its place, and both are recorded so they are not re-attempted
blind.

1. **Far-forward resync** — when the pointer is stuck, search much further ahead
   at a higher score bar, requiring two agreeing tokens. Measured *worse*:
   skipped-ayah detection 84.6% → 82.7%, and one more false error.
2. **Local resync** — treat a relocation hit just ahead in the same surah as an
   ordinary skip: reposition and report MISSED_AYAH instead of JUMP. Genuinely
   ambiguous. It named 69 skips correctly against 61, and cut jump noise from
   381 events to 238 — but total detection fell from 91.3% to 84.6% and repeat
   clips raised 21 false errors against 16.

The second is worth revisiting with a metric that can actually judge it. "Caught"
here counts *any* JUMP as a catch, which flatters the noisier arm: 381 jump
events across 104 clips is roughly 3.7 spurious jumps per clip, and a jump
pointing at the wrong ayah still scored as a catch. A metric that requires the
event to name the right ayah would likely reverse the verdict.

## What would actually fix it

A forward resync that does not depend on the relocation index ranking the local
destination first — most directly, extending the aligner's reach to the end of
the current ayah plus a margin, since the failure is always "the skipped ayah
was longer than the window". That is a real piece of work, not a constant
change: the first naive attempt made things worse.
