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
