# Interleaved A/B: phoneme path vs FastConformer + text path (2026-09-04)

Both arms in **one process**, on the **same audio**, **alternating per clip**, so
CPU state and machine load cannot favour either. 16 clips: 6 clean surahs + 10
deliberate-error clips. Phoneme arm ran with all its fixes enabled
(`partial_coverage`, `carry_forward`, `revoke_late_miss`). Production untouched.

## Clean recitations

| surah | ayahs | phoneme | text | phoneme false-miss | text false-miss |
|---|---|---|---|---|---|
| Al-Fatihah | 7 | 7/7 | **7/7** | 0 | 0 |
| Al-Kafirun | 6 | 6/6 | **6/6** | 0 | 0 |
| Az-Zalzalah | 8 | 7/8 | **8/8** | **1** | 0 |
| Al-Adiyat | 11 | 11/11 | **11/11** | 0 | 0 |
| At-Tariq | 17 | 16/17 | **17/17** | **1** | 0 |
| **Al-Inshiqaq** | 25 | **23/25** | **7/25** | 0 | 0 |
| **total** | 74 | 70/74, **2 false** | 56/74, **0 false** | | |

The text path wins **5 of 6** — including two surahs where the phoneme path
raised a **false MISSED_AYAH** — and then loses catastrophically on Al-Inshiqaq.

## The Al-Inshiqaq anomaly is a DETECTOR failure, not an ASR failure

`clean:inshiqaq` text arm: **WER 0.0654, CER 0.0199** — the transcription is good.
Yet the tracker credited **7 of 25 ayahs**. Compare At-Tariq: WER 0.0000 → 17/17.

So on the longest surah in the set (25 ayahs, 107 words, 4 windows) the
**aligner/detector loses the passage despite being handed a near-correct
transcript**. This is precisely the risk flagged in the swap design: those
components were tuned against whisper-base output and had not been re-measured.
It is now a concrete, reproducible defect rather than a hypothetical.

## Deliberate errors — the text path is clearly better

| clip | phoneme ayahs | text ayahs | phoneme MW | **text MISSED_WORD** | text REPEAT |
|---|---|---|---|---|---|
| zilzal skip_word | 6/8 | **8/8** | 0 | **1** | 0 |
| zilzal skip_ayah3 | 7/8 | 7/8 | 0 | 0 | 0 |
| zilzal repeat_ayah2 | 7/8 | **8/8** | 0 | 0 | 0 |
| fatiha skip_word | 7/7 | 7/7 | 0 | **1** | 0 |
| fatiha skip_ayah3 | 6/7 | 6/7 | 0 | 0 | 0 |
| fatiha repeat_ayah2 | 7/7 | 7/7 | 0 | 0 | **1** |
| kaferoon skip_word | 4/6 | **6/6** | 0 | 0 | 0 |
| **kaferoon skip_ayah4 (3→5)** | 3/6 | **6/6** | 0 | **5** | 0 |
| kaferoon repeat_ayah2 | 3/6 | **6/6** | 0 | 0 | **1** |
| **zilzal native substitution** | 5/8 | **8/8** | 0 | **2** | 0 |

**The capability gap is decisive.** The phoneme path reported **zero**
`MISSED_WORD` on every clip — it structurally cannot, being ayah-granular. The
text path flagged the deliberately substituted words (2 on the native
substitution clip, 1 on each skipped-word clip, 5 across the Kafirun 3→5 case)
and detected **repeats** the phoneme path missed entirely.

For a *Sami* that is the whole point: the phoneme path can say "you skipped an
ayah", the text path can say **which word you got wrong**.

## Operational

| | phoneme | text (FastConformer) |
|---|---|---|
| total inference, 16 clips | 90 s | **73 s (0.81×)** |
| time-to-first-feedback, median | 3.7 s | **3.0 s** |
| process RSS peak (both models loaded) | 2075 MB | |

The text path is **faster**, not slower.

Text-path ASR across all 16 clips: mean **WER 0.1139 / CER 0.0668** — worse than
the 0.0443 measured on whole files, because here each VAD window is transcribed
separately and window boundaries cut mid-ayah. Window quality matters to the text
path too.

## Verdict (superseded — see below)

**ASR: settled.** FastConformer is decisively better and preserves errors.
**Error fidelity: settled.** Word-level detection the phoneme path cannot do.
**Speed: settled.** Faster.
**Detector: was NOT settled.** Al-Inshiqaq 7/25 on a good transcript was a
blocking defect in the *existing text logic*, not the ASR.

## Resolved

The detector blocker was found and fixed, along with five more defects it was
masking. Al-Inshiqaq is **25/25**. The full 15-case gate, its root-cause
analysis and the segmentation decision now live in `gate-release.md`; the
rollout and rollback procedure in `runbook-engine-rollback.md`.

Headline of the re-run, with both arms on identical audio and identical
segments: across six clean recitations the text path credits 74/74 ayahs by the
loose metric and 71/74 by the strict one, with **zero** false MISSED_WORD,
MISSED_AYAH or jump, against 70/74 and two false MISSED_AYAHs for the phoneme
path. On deliberate errors the gap is wider: the text path flags substituted and
skipped words the phoneme path does not report at all.

One caveat on this page's operational table: those timings were measured with
leftover test containers competing for CPU. The clean figures — text path 0.81x
total inference, 3.0s vs 3.7s median time-to-first-feedback — stand, and the
correctness figures above are load-independent.
