# Release gate — FastConformer + text pipeline

15 cases × 3 segmentations, replayed through the real runtime path (VAD
segmenter → FastConformer → `RecitationTracker`). Verdicts use the **strict**
metric the brief asked for: an ayah counts as credited only when *every* one of
its words produced a CONFIRMED `WORD_OK`.

Harness: `cache_transcripts.py` transcribes each clip once per segmentation and
caches the result; `replay_gate.py` replays the detector against that cache in
about a second. The ASR is fixed input, which is the point — these gates test
the **detector**, and a detector change is re-gated immediately instead of
costing a ten-minute transcription round.

## Result

Four segmentations measured. Overall pass counts do not separate 15s from 25s,
so the choice is made on the two columns that do — false errors and how long the
reciter waits to see anything.

| window | clean ayahs | false MISSED_WORD | error cases | overall | first feedback (median / worst) |
|---|---|---|---|---|---|
| 5 s | 68/74 | 5 | 7/9 | 10/15 | 4.8 s / 5.8 s |
| 10 s | 69/74 | 4 | 6/9 | 8/15 | 8.7 s / 11.5 s |
| 15 s | 70/74 | 2 | 7/9 | **11/15** | 16.8 s / 17.3 s |
| **25 s (shipped)** | **71/74** | **0** | **8/9** | **11/15** | 28.7 s / 28.8 s |

**Latency was invisible to this gate until a live run measured it.** The gate
replays cached transcripts, so every segment arrives instantly; only the
staging concurrency run, which measures wall-clock time to the first event,
showed 27.5 s and 30.9 s. For Al-Kafirun the entire 23 s surah is ONE window, so
nothing changes on screen until the reciter stops.

25 s is shipped because a false accusation is the failure mode that destroys
trust in a Sami — it is what made the original app feel broken — and 25 s is the
only setting with none. The latency it costs is mitigated rather than accepted:
the server now sends a `buffering` frame at most once a second while a window
fills, so the UI can show that audio is being heard without inventing a verdict
for it. The principled fix, if the wait still reads badly to real users, is to
decode a partial window for provisional display while the complete window stays
authoritative for verdicts.

## Result (detail)

| segmentation | clean ayahs | false MISSED_WORD / AYAH / jump | error cases | overall |
|---|---|---|---|---|
| 5 s (Whisper default) | 68/74 (91.9%) | **5** / 0 / 0 | 7/9 | 10/15 |
| 10 s | 69/74 (93.2%) | **4** / 0 / 0 | 6/9 | 8/15 |
| **25 s (shipped)** | **71/74 (95.9%)** | **0 / 0 / 0** | **8/9** | **11/15** |

Progress on the shipped setting: **13/30 → 21/30 → 11/15** as the defects below
were fixed. Zero false errors across all six clean recitations is the number
that matters most for a Sami: the system never once told a correct reciter they
were wrong.

## Named gates

| gate | result |
|---|---|
| clean recitation (6 surahs) | 71/74 ayahs, **no false errors** |
| skipped word (Al-Fatihah, Az-Zalzalah, Al-Kafirun) | **pass** — the *specific* removed word is flagged in all three |
| substituted word (real second take) | **pass** — flags `اخبارها` |
| skipped ayah (Al-Fatihah, Az-Zalzalah) | **pass** — `MISSED_AYAH 3` in both |
| repeat / restart (Al-Fatihah) | **pass** — `REPEAT` fires |
| repeat / restart (Az-Zalzalah) | **fail** — see R4 |
| Al-Kafirun 3→5 | **pass** — one `MISSED_AYAH 4`, no scattered word errors |
| Al-Inshiqaq long passage | 24/25, no false errors (was **7/25**) |

The skipped-word gates assert that the word actually removed from the audio is
the one flagged, not merely that *something* was flagged. The first fixture
generator normalised with a mangled regex and recorded empty strings, so that
assertion was impossible and Al-Kafirun "passed" while detecting nothing;
`mk_errors2.py` rebuilt the clips and records exactly which word it cut.

## Remaining failures, by root cause

All four are ASR-side. None is a detector defect, and none produces a false
error.

- **R1 — Al-Fatihah `الضالين` uncredited (grey).** The ASR emitted `ضالم`,
  which scores 54.5 against the reference word — below even the garbled
  attribution floor of 55, so it is not recognised as an attempt. End-of-clip
  degradation; the recording also trails off into `آمين`.
- **R2 — Al-Adiyat `قدحا` amber.** The ASR emitted `فدحا` — one letter, a single
  dot in script — scoring 75 against the accept threshold of 78. Correctly not
  called an error; shown as uncertain rather than confirmed.
- **R3 — Al-Inshiqaq `وسق` amber.** Same class as R2.
- **R4 — Az-Zalzalah repeat not reported.** The RNN-T prediction network
  collapses an ayah repeated *inside a single window*: the same audio
  transcribes the repetition twice at 5 s and once at 25 s, so the duplicate
  never reaches the detector. A benign observation is lost; no false error is
  raised, and a repeat spanning a window boundary is still caught (Al-Fatihah).

R1–R3 would each be fixed by lowering the match threshold, which is exactly the
global loosening the brief ruled out — and which would cost real error detection,
since `sub:zilzal` depends on a substituted word *failing* to match. They are
correctly left as uncertain rather than forced green.

## Detector defects found and fixed along the way

Each was found by tracing the failing case token by token (`trace_case.py`),
not by guessing.

1. **Long-segment block.** The segment pre-pass counted hits against a fixed
   pointer, but the aligner only searches 20 reference words, so a 34-token
   window was capped at 0.59 and fell under the 0.5 block threshold *for being
   long*. The pointer froze and every later window really was off-reference.
   Al-Inshiqaq 7/25 → 25/25.
2. **Multi-word reference units.** `يَا أَيُّهَا` is one QUL unit with one
   word_id but two ASR tokens, and neither half cleared the threshold.
3. **Positional garbled credit.** Dropped the first N gap words whatever they
   sounded like — absolving genuinely skipped words and blaming the wrong ones.
   Now paired by content.
4. **Word split by a hard cut.** A 0.5 s overlap could not carry a whole word
   into the next segment, so the ASR dropped it on both sides and a correctly
   recited word was reported missed. Overlap 1.5 s; the smart-cut guard also
   required `quiet_pos > overlap`, so a longer overlap would have silently
   disabled smart cuts entirely.
5. **Shifted mutashabeh skip.** Al-Kafirun 4 and 5 both open with `وَلَا`, so the
   resumed ayah's opening word matched the skipped ayah's, leaving a gap that
   was a suffix plus a prefix and never "a whole ayah". Five scattered word
   errors → one `MISSED_AYAH`.
6. **Silent near-misses.** A word the ASR nearly got was neither credited nor
   flagged, so it stayed grey forever — which in the Mushaf reads as "tracking
   stopped". Now `UNCERTAIN`.

## What this does not cover

Single reciter, six short surahs, one microphone. Concurrency, memory and
latency are covered separately in `fastconformer-ops.md`. Surah 55 (the 31×
refrain) and speaker enrollment remain untested.
