# `M0-pre` — server-side baseline (2026-09-04)

First instrumented numbers from the production phoneme path, captured immediately
after **P1-7** landed and **before** P1-8 (resampler) or any accuracy work.

**Scope caveat — read first.** These runs use `scripts.ws_client`, which streams a
16 kHz WAV straight to the WebSocket and **never touches
`frontend/src/audio/recorder.ts`**. They therefore measure the *server* side only
and **cannot** show the resampler effect. The `M0-pre` → post-P1-8 delta still
requires live browser captures (see plan §6.1).

Config: `RECITEIQ_TRACKER_MODE=phoneme`, backend 874 MB / 2560 MB limit,
`phoneme_segment_max_sec=25.0`, `phoneme_silence_cut_sec=0.5`, `MATCH_CER_MAX=0.45`.

## Accuracy — both cases correct

| Clip | Windows | Ayahs matched per window | words_ok | Errors |
|---|---|---|---|---|
| `fatiha_full.wav` (clean, 46.1s) | 4 | `[1]`, `[2,3,4,5]`, `[6]`, `[7]` | **29/29** | **none** |
| `fatiha_skip3.wav` (ayah 3 skipped) | 4 | `[1]`, `[2,4,5]`, … | 27/27 | exactly 1 MISSED_AYAH on ayah 3 |

The `[2,3,4,5]` window is the one-ayah-per-window fix working: four ayahs credited
from a single window. Pre-fix this window credited one ayah and reported the other
three as missed.

## Latency — inference cost is CONSTANT

| window_sec | closed | infer_ms |
|---|---|---|
| 5.09 | silence | 3927 |
| 5.95 | silence | 4017 |
| 11.23 | silence | 4318 |
| 17.15 | silence | 4694 |
| 21.95 | silence | 4081 |

A 4.3× range in window length produces a ~1.2× range in inference time. Cause:
`_WIN_SAMPLES = 30 * _SR` and the feature extractor's `chunk_length=30` pad every
window to 30s, so the encoder always processes 1500 frames; `n_real` trims only the
output, after the forward pass is paid for.

- Single session: **p50 4081 ms, p95 4318 ms**.
- Per-window feedback floor ≈ 0.5s (silence cut) + ~4.1s ≈ **4.6s**.
- Effective RTF is 0.77 at a 5s window, not the 0.1 quoted for a full 30s window.

**Under contention:** the second run overlapped the first and measured **p50 8430 ms,
p95 10337 ms** — roughly 2–2.5× worse with two concurrent sessions, against a
configured `max_concurrent_sessions = 3`. Not a controlled experiment, but it flags
concurrency as a real risk and something to measure properly before any demo.

## What this changes

1. The plan's original `t_infer = RTF × window_sec` model was wrong → replaced
   (§5.3), and the provisional 1.5s / 3.5s targets are withdrawn.
2. New task **P1-9**: slice mel features and encoder positional embeddings to the
   real audio length (~6× less compute on a 5s window).
3. **Short windows are strictly wasteful** — fixed cost means longer windows are
   more efficient, inverting the usual latency intuition. Input to P2-5.
4. Concurrency needs its own measurement before the 3-session cap is trusted.

## Still not measured

Any accuracy figure on amateur voices. The reported ~4–5% is a user observation, it
predates the one-ayah-per-window fix, and it is not comparable to anything here.
That gap closes only with the recorded corpus (plan §5.1).

---

# `M0-pre` — resampler defect, quantified (2026-09-04)

The browser resampler could not be measured with `ws_client` (it bypasses
`recorder.ts`), and a live human take varies between runs. But the defect is
**purely algorithmic and deterministic**, so it was quantified exactly by porting
today's loop faithfully and running genuine device-rate audio through both paths.

Source: `001001–001007.mp3` (Husary, 44.1 kHz stereo originals) concatenated and
decoded to **48 kHz mono**, 46.122s — byte-for-byte the same content as
`fatiha_full.wav` (46.1225s), so results are directly comparable to the runs above.
Simulator: `scratchpad/sim_browser_audio.py` (ported from `recorder.ts`, including
the per-block phase reset and the discarded block tail).

## Signal-level damage: real and severe

| Path | samples | vs ideal | duration | drift |
|---|---|---|---|---|
| ideal | 737958 | — | 46.122s | — |
| **current** | 726390 | **−11568** | 45.399s | **−1.57%** |
| fixed (FIR + continuous phase) | 737958 | 0 | 46.122s | 0.00% |

- **Time drift −1.57%** — 11,568 samples silently dropped. The recitation is
  time-compressed, i.e. played back 1.57% fast. Confirms the predicted 1.56%
  (`floor(128/3) = 42` outputs consume 126 of every 128 input samples).
- **Aliasing is total, not marginal.** A 12 kHz tone (above the 8 kHz Nyquist of
  16 kHz audio) folds down to 4 kHz at **−0.9 dB of in-band energy** — the alias
  *is* the signal. The fixed path removes it completely (0.0).
- The source genuinely has content to fold: **15.8%** of its 0–8 kHz energy sits
  in 8–16 kHz.

## Downstream effect on the tracker: none measurable

| Audio | words_ok | Errors | infer_ms p50 |
|---|---|---|---|
| `fatiha_cur48.wav` (today's buggy resampler) | **29/29** | **none** | 4020 |
| `fatiha_fix48.wav` (anti-aliased, correct phase) | **29/29** | **none** | 3906 |

**Identical.** On clean professional recitation the encoder-CTC model is robust to
both defects: the ayah chain, the credited words and the error count are unchanged.

## Consequence for the plan — P1-8 is downgraded

P1-8 was ordered as **P0-blocking** on the assumption that corrupted input would
invalidate every downstream measurement. That assumption is now **falsified for
clean audio**: the numbers above are trustworthy as they stand, and the reference
work (P0-1) does not need to wait for the resampler.

P1-8 remains worth doing — dropping 1.57% of every recitation and folding full-
amplitude aliases into the speech band is indefensible in a thesis, and it is cheap
— but it moves to **P1, after the accuracy work**.

**One open question keeps it on the list:** amateur mics have quite different
high-frequency content from a studio qari recording — sibilance, mic self-noise,
room tone, fan hum — and that folds differently. This test cannot settle that.
Re-run the same A/B on real amateur takes once the corpus exists (plan §5.1); if
amateur audio *is* sensitive, P1-8 climbs straight back up.
