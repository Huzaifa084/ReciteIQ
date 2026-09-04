# FastConformer: memory, latency and concurrency (2026-09-04)

Measured on this box, isolated venv, serialised access (see below).
Production default unchanged — the engine is behind
`RECITEIQ_ASR_ENGINE=fastconformer`.

## NeMo's `transcribe()` is NOT thread-safe

Calling it from two threads on a shared model raises:

```
ValueError: Cannot unfreeze partially without first freezing the module with `freeze()`
```

So concurrent sessions **must queue behind one model**. `app/asr/fastconformer.py`
holds an `asyncio.Lock` for exactly this. Every number below reflects that
serialisation, which is the deployed behaviour.

## Memory

| | RSS |
|---|---|
| baseline process | 678 MB |
| after model load | **1613 MB** (model ≈ 935 MB, cold load 10.3 s) |
| under load, 1–3 sessions | 1735 – 1909 MB |

**The backend container limit is 2560 MB.** These figures come from a *bare*
process — no FastAPI, DB pool, VAD model or SPA serving. The current backend runs
at ~874 MB with the phoneme model. Headroom is thin and must be verified in the
real container before any default change.

## Latency — whole-surah clips (22–33 s)

| sessions | wall | audio | p50 queue | p50 infer | p50 total | max total | RSS |
|---|---|---|---|---|---|---|---|
| 1 | 4.03s | 32.6s | 0.00s | 4.03s | 4.03s | 4.03s | 1793 MB |
| 2 | 8.84s | 63.5s | 2.24s | 4.42s | 6.66s | 8.83s | 1870 MB |
| 3 | 10.11s | 86.3s | 4.10s | 3.32s | 7.41s | 10.09s | 1909 MB |

Aggregate RTF stays ≈ 0.12–0.14 as sessions scale — throughput holds — but
**queueing dominates individual latency**: max total goes 4.03 → 8.83 → 10.09 s.

## Latency — realistic 4 s windows (what the VAD emits) — THE PROBLEM

| sessions | wall | p50 queue | p50 infer | p50 total | max total |
|---|---|---|---|---|---|
| 1 | 2.71s | 0.00s | **2.70s** | 2.70s | 2.70s |
| 2 | 4.66s | 1.04s | 2.29s | 3.33s | 4.55s |
| 3 | 5.79s | 1.63s | 1.94s | 3.84s | **5.78s** |

**A 4 s window costs 2.70 s — RTF 0.675, versus 0.124 for a 33 s clip.** The cost
is not proportional to audio: NeMo's `transcribe()` builds a manifest and spins a
dataloader **per call**, so a fixed overhead of roughly 2.5 s dominates short
windows.

For comparison, the current phoneme path after P1-9 does a 5.95 s window in
**682 ms**. On typical live windows FastConformer is therefore about **4× slower**,
despite being far more accurate.

This is the same shape of problem P1-9 solved for the phoneme model: a fixed
per-call cost that short windows pay in full.

### Three ways out, in order of preference

1. **Bypass `transcribe()`** — preprocess to features and call the model's
   forward/decode directly, skipping the manifest and dataloader. This is the
   direct analogue of P1-9 and should remove most of the 2.5 s. **Do this first**;
   it likely settles the question on its own.
2. **Longer windows** — fewer calls amortise the overhead, at the cost of
   feedback latency. The measured aggregate RTF (0.12) says long windows are
   cheap; the accuracy work says they are also *better* for long ayahs.
3. **Accept it** — only if the product tolerates ~3 s per-window feedback.

## Implications for the swap

- The **accuracy case is settled** (six surahs, 96.7% of words; every deliberate
  error preserved).
- The **operational case is not yet**. Per-window latency regresses ~4× against
  the current path, and container memory headroom is thin.
- **Do not flip the default** until (1) is attempted and re-measured, and memory
  is verified inside the real container.

Nothing here argues against the swap — it argues for finishing the engineering
before switching, exactly as the phoneme path needed P1-9 before its latency was
acceptable.


---

# CORRECTION: the per-window latency problem was a measurement artifact (2026-09-04)

The "4 s window costs 2.70 s" figure above is **wrong**. It was measured with an
unpinned torch thread budget on a contended box. Re-measured warm, with
`torch.set_num_threads(2)` (matching `settings.asr_cpu_threads`), on an otherwise
idle machine:

| window | inference | RTF |
|---|---|---|
| 4 s | **667 ms** | 0.167 |
| 10 s | 1364 ms | 0.136 |
| 20 s | 1701 ms | 0.085 |
| 30 s | 3072 ms | 0.102 |

For comparison the current phoneme path does a 5.95 s window in 682 ms. **The two
are comparable — there is no 4× regression.**

## The direct-inference optimisation was implemented, benchmarked, and REJECTED

A `preprocess -> encoder -> RNN-T decode` path bypassing `transcribe()`'s
per-call manifest and dataloader was built and measured against it, warm, at four
window sizes:

| window | `transcribe()` | direct | speedup | text identical? | WER vs `transcribe()` |
|---|---|---|---|---|---|
| 4 s | 584 ms | 829 ms | **0.71×** | no | 0.2500 |
| 10 s | 1032 ms | 1359 ms | **0.76×** | no | 0.0000 |
| 20 s | 2127 ms | 2172 ms | **0.98×** | no | 0.3846 |
| 30 s | 5071 ms | 5071 ms | **1.00×** | no | 0.1081 |

It is **never faster** and it **changes the recognised text**, failing the stated
equivalence criterion. The overhead it was meant to remove did not exist once the
thread budget was pinned.

Kept instead: `transcribe()`, with `torch.set_num_threads(settings.asr_cpu_threads)`
and `dither = 0` / `pad_to = 0` set once at load. The rejection is documented in
`app/asr/fastconformer.py` so it is not blindly retried.

## Corrected concurrency (4 s windows, serialised behind one model)

| sessions | wall | per session | RSS |
|---|---|---|---|
| 1 | 0.70 s | 0.70 s | 1668 MB |
| 2 | 1.41 s | 0.71 s | 1682 MB |
| 3 | **2.34 s** | 0.78 s | 1690 MB |

Near-linear: throughput holds and the slowest of three sessions waits 2.34 s.

## Lock robustness

| check | result |
|---|---|
| lock released after a failed inference | **True** |
| engine usable after a failure (recovery) | **True**, 0.58 s |
| 6 interleaved calls, 3 forced to fail | 3 succeeded, 3 raised, **lock free, semaphore free** |

`async with` releases on the exception path, so a failed inference cannot strand
the lock or the bounded semaphore, and a session is never left stuck.

## Corrected memory

| | RSS |
|---|---|
| baseline | 678 MB |
| after model load | 1613 MB (cold load **9.7 s**) |
| peak across 1–3 sessions | **1706 MB** |

Still a bare process — the real container adds FastAPI, the DB pool and the VAD
model against a 2560 MB limit, so this must be confirmed in the container before
any default change. But the headroom is better than the earlier figures implied.

## Where this leaves the swap

Accuracy: settled. Latency: **comparable to the current path, not a regression**.
Concurrency: near-linear to 3 sessions. Lock: correct under failure.

The remaining gate is the **live A/B on the validation corpus** and a
**container-level memory check**. No default has been changed.
