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

---

# P1-9 — variable-length encoder pass (2026-09-04)

## The constant is removed

Measured on real recitation (`fatiha_full.wav`, truncated to each duration),
padded path vs sliced path:

| window | padded_ids | sliced_ids | CER | padded | **sliced** | speedup |
|---|---|---|---|---|---|---|
| 3.0s | 25 | 25 | **0.000** | 4117 ms | **449 ms** | **9.2×** |
| 5.0s | 26 | 26 | **0.000** | 4041 ms | **741 ms** | **5.5×** |
| 10.0s | 55 | 54 | 0.018 | 4315 ms | 1281 ms | 3.4× |
| 22.0s | 98 | 99 | 0.010 | 9833 ms* | 5953 ms | 1.7× |

\* inflated by CPU contention; the same window measured 4081 ms in the single-session
run above, so the true 22s speedup is smaller than the table implies.

Inference now **scales with duration** instead of being flat. For the 3–6s windows
that dominate ayah-by-ayah recitation, feedback latency drops from ~4.1s to
**0.45–0.75s**, which moves the per-window floor from ≈4.6s to roughly
**1.0–1.3s** (0.5s silence cut + sub-second inference).

## Bit-identical where it matters — but NOT by construction

**Exact equality is impossible in principle** and the plan's original acceptance
criterion ("bit-identical output") was wrong. The Whisper encoder is
**bidirectional**: with 30s padding, every real frame attends over the padded
region as well, so removing the padding changes the representation by definition.
It is a different function, not an off-by-one.

Empirically it does not matter: **CER 0.000 at 3s and 5s** on real speech, and
0.018 / 0.010 at 10s / 22s — two orders of magnitude below `MATCH_CER_MAX = 0.45`,
and safe against the stored references even though those were built with the
padded path.

**A first attempt at the acceptance test asserted exact equality on synthetic
tone+noise and failed at 3s and 25s.** That test was measuring noise: synthetic
signals yielded only 6–8 tokens, where one differing token is a huge relative CER.
Real recitation is the only valid fixture, and on it the same durations are
identical. The test now asserts a CER budget (0.06) on real audio plus a measured
speedup.

`RECITEIQ_PHONEME_VARIABLE_LENGTH` defaults **true**, with the padded path retained
for A/B against any future reference rebuild.

## Benchmark rerun with P1-9 deployed

Same clips, same harness, live socket:

| Clip | words_ok | Errors | infer_ms p50 | p95 |
|---|---|---|---|---|
| `fatiha_full.wav` | **29/29** | **none** | **1423** (was 4081) | 2955 (was 4318) |
| `fatiha_skip3.wav` | 27/27 | exactly 1 MISSED_AYAH on ayah 3 | **1566** | 2097 |

Per-window on the skip run — every window sub-2.1s, none near the old flat ~4s:

```
 win_s     closed     ms  ids chain  meanCER      outcome  matched
  5.09    silence    995   26     1    0.111      chained  [1]
 17.15    silence   2097   78     3    0.106      chained  [2, 4, 5]
  5.66    silence    699   25     1    0.125      chained  [6]
 11.55    silence   1566   64     1    0.032      chained  [7]
```

Accuracy is unchanged and the §5.3 latency targets (P50 ≤ 1.5s, P95 ≤ 3.5s) are now
met on a single session. **Concurrency remains unvalidated** — two overlapping
sessions previously doubled latency against a configured cap of 3.
