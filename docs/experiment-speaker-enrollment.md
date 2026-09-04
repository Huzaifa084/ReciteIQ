# Speaker-enrollment A/B (2026-09-04)

Isolated experiment on a real amateur Al-Fatihah recitation
(`/root/temp/fatiha.ogg`, 30.95s, 48 kHz mono Opus, RMS −17.1 dBFS, peak −0.4,
no clipping). Production defaults unchanged: `phoneme_ref_rule` stays `single`
and the personal reference was written to a scratchpad JSON, **never** to
`ayah_phoneme_refs` (verified: the table holds only the 6 professional reciters).

## ⚠ The headline A/B could not be run

**Only one recording was provided.** The brief asked for enrollment on one take
and evaluation on a *separate* take. Building the reference from the same
utterance we then score against is pure leakage — CER goes to ~0 by
construction and says nothing about whether enrollment generalises. A second
recording of the same surah is required and everything below is reported with
that limitation stated explicitly.

## 1. Leakage-free: this take vs the professional references

Whole-take query (207 IDs from the VAD windows), best span per ayah.

| ayah | husary | AbdulBasit | AbuBakr | Alafasy | Menshawi | Minshawy | min6 | 2nd6 |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.185 | 0.185 | 0.259 | 0.185 | 0.250 | 0.185 | 0.185 | 0.185 |
| 2 | 0.250 | 0.250 | 0.303 | 0.250 | 0.250 | 0.281 | 0.250 | 0.250 |
| 3 | 0.222 | 0.222 | 0.200 | 0.222 | 0.267 | 0.200 | 0.200 | 0.200 |
| 4 | 0.111 | 0.111 | 0.167 | 0.211 | 0.118 | 0.333 | 0.111 | 0.111 |
| 5 | 0.355 | 0.355 | 0.355 | 0.355 | 0.375 | 0.312 | 0.312 | 0.355 |
| 6 | 0.407 | 0.407 | 0.407 | 0.407 | 0.458 | 0.400 | 0.400 | 0.407 |
| 7 | 0.306 | 0.297 | 0.303 | 0.308 | 0.328 | 0.369 | 0.297 | 0.303 |

| strategy | mean CER | min | ayahs ≤ 0.45 |
|---|---|---|---|
| Husary only | 0.262 | 0.111 | **7/7** |
| professional min(6) | 0.251 | 0.111 | **7/7** |
| professional 2nd(6) | 0.259 | 0.111 | **7/7** |

**This take matches the professional references comfortably — every ayah is under
the 0.45 gate**, and multi-reference again adds almost nothing (0.262 → 0.251),
consistent with the earlier finding that the six professionals cluster tightly.

Token behaviour is healthy throughout: **6.69–7.17 IDs/s** (qari reference ~4.5),
`c_ctc` **0.897–0.972**, `blank_frac` 0.75–0.92.

*Measurement sensitivity:* the same audio chunked into fixed 25s blocks instead of
VAD windows gives Husary 0.228 rather than 0.262. Chunking moves per-ayah CER by
~0.03, which is worth remembering when comparing runs.

## 2. Same-utterance four-way — MECHANISM CHECK ONLY, NOT EVIDENCE

Scored against the recording the reference was built from. **Leaked by
construction.** Reported only to prove the enrollment path works end to end, and
as an upper bound.

| ayah | husary | prof_min | personal | combined_min |
|---|---|---|---|---|
| 1 | 0.259 | 0.259 | 0.000 | 0.000 |
| 2 | 0.143 | 0.138 | 0.000 | 0.000 |
| 3 | 0.125 | 0.125 | 0.154 | 0.125 |
| 4 | 0.188 | 0.167 | 0.125 | 0.125 |
| 5 | 0.258 | 0.258 | 0.000 | 0.000 |
| 6 | 0.417 | 0.417 | 0.083 | 0.083 |
| 7 | 0.208 | 0.208 | 0.106 | 0.106 |

| strategy | mean CER | max | ayahs ≤ 0.45 |
|---|---|---|---|
| husary | 0.228 | 0.417 | 7/7 |
| prof_min | 0.225 | 0.417 | 7/7 |
| personal | 0.067 | 0.154 | 7/7 |
| combined_min | 0.063 | 0.125 | 7/7 |

Three ayahs land at exactly 0.000 — the signature of leakage. **Draw no
conclusion about enrollment from this table.** It confirms the enrollment
mechanism (ID-space forced alignment against professional references, monotonic
spans of 24/26/13/14/31/24/66 IDs) produces usable references, nothing more.

## 3. Browser capture path, re-tested on amateur audio

The open question from `baseline-m0-pre-serverside.md` was whether the
`recorder.ts` resampler matters for an amateur voice, whose HF content differs
from a studio qari recording. Now answered on the real thing:

| path | ids | id/s | c_ctc | husary | prof_min | ≤0.45 |
|---|---|---|---|---|---|---|
| original (ffmpeg 16k) | 210 | 6.78 | 0.907 | 0.228 | 0.225 | 7/7 |
| browser CURRENT (buggy) | 208 | 6.83 | 0.901 | **0.214** | 0.214 | 7/7 |
| browser FIXED (FIR) | 210 | 6.78 | 0.910 | 0.237 | 0.232 | 7/7 |

**No meaningful difference** — the buggy path is marginally *best*, which is
noise. Note this recording carries only **1.0%** of its energy above 8 kHz (vs
15.8% for the qari mp3), because Opus low-passes it, so aliasing has little to
fold. **P1-8 stays downgraded and this question is now closed for amateur audio
too.**

## 4. The same recording through the live pipeline

`ws_client` against production (which still runs pre-P0-1 code, i.e.
**Husary-only** references):

```
 win_s     closed     ms  ids  id/s  rms_dB  blank  c_ctc chain  meanCER      outcome  matched
  3.62    silence   1995   25  6.91   -16.7  0.746  0.972     1    0.185      chained  [1]
 24.26  max_smart   3911  174  7.17   -17.1  0.769  0.939     6    0.240      chained  [2,3,4,5,6,7]
  3.07      flush    426    8      -   -18.3  0.922  0.897     0        -     no_match  []
```

**29/29 words, zero errors, all 7 ayahs credited.** The 24.26s window chaining
**six ayahs at once** is the one-ayah-per-window fix doing exactly its job, and
the trailing no-match window correctly produced no false miss (P0-4).

## 5. What this reframes

Your browser session and this file are the same voice reciting the same surah,
yet one scored 2/12 windows and the other is perfect. The difference is **not**
the references (Husary alone suffices here), **not** the capture path (§3), and
**not** input level or token rate (both healthy in each).

The difference is **segmentation**:

| | windows | shortest | outcome |
|---|---|---|---|
| browser session | 12 over 44.4s | 0.58s, 0.64s, 1.15s | 10 no_match |
| this recording | 3 over 31.0s | 3.07s | all 7 ayahs credited |

The browser take was **fragmented into sub-ayah pieces** by pauses, and a window
shorter than an ayah cannot match a whole-ayah reference — the tracker's unit is
the ayah. Continuous recitation produces ayah-or-longer windows and works.

**This makes sub-ayah fragmentation the leading remaining failure mode**, ahead of
reference quality. Candidate fixes, all cheap relative to the reference work:
- carry unmatched short windows forward and re-try them **concatenated** with the
  next window, instead of scoring each fragment alone;
- raise `phoneme_silence_cut_sec` (0.5s) so ordinary breath pauses stop cutting
  windows mid-ayah;
- require a minimum window duration before attempting a match at all.

None of these touch the references or the threshold. They should be measured
before any further reference-set expansion.

## What is still needed

1. **A second recording of Al-Fatihah** to run the actual enrollment A/B.
2. A take recorded **through the browser** with the current build, to confirm P0-4
   removes the false reds and to capture the fragmentation pattern with the new
   diagnostics.
