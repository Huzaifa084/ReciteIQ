# Segmentation experiment (2026-09-04)

Controlled comparison of segmentation strategies. **Reference strategy held fixed
throughout** (`phoneme_ref_rule='single'`, Husary canonical) so segmentation is the
only variable. **No production default was changed.**

## Why

The same voice reciting the same surah scored 7/7 ayahs from a recording that
produced 3 useful windows, and 2/12 from a browser session fragmented into
sub-ayah windows (0.58s, 0.64s, 1.15s among 12). A window shorter than an ayah
cannot match a whole-ayah reference, because the tracker's unit is the ayah.

## Fixtures

The clean recording does not fragment on its own, so fragmentation is induced
deterministically: insert 0.7s of silence (above the 0.5s cut threshold) after
every N seconds of speech, for N ∈ {1.5, 2.5, 4.0}. That gives a **dose-response
curve** rather than a single anecdote, from the same source audio.

Two false-match controls run under every condition:
- **real skip** — `fatiha_skip3.wav`: ayah 3 must still be reported missed.
- **wrong surah** — the fragmented Fatihah tracked against Al-Ikhlas (112):
  nothing may be credited.

## Conditions

| name | change |
|---|---|
| `baseline` | current behaviour — every window recognised and matched alone |
| `carry` | (1) an unmatched window's IDs are prepended to the next window's IDs (capped at 400) |
| `silence12` | (2) `phoneme_silence_cut_sec` 0.5 → 1.2 |
| `mindur` | (3) segments under `MIN_SEC` are held and their **audio** concatenated with the next before recognition |
| `mindur+sil` | (2) + (3) |

`MIN_SEC=2.0` was tried first and **never fired**: a segment carries its trailing
silence up to the cut point, so 1.5s of speech arrives as ~2.0s. Re-run at 3.5s.

## Results

All rows: 0 false `MISSED_AYAH` unless stated. `uncert` is the P0-4 UNCERTAIN count.

**natural (31.0s, 3 windows)**

| condition | wins | no_match | credited | missed | meanCER | infer_ms |
|---|---|---|---|---|---|---|
| baseline | 3 | 1 | **7/7** | 0 | 0.212 | 4575 |
| carry | 3 | 1 | **7/7** | 0 | 0.212 | 4358 |
| silence12 | 2 | 1 | 6/7 | 0 | 0.230 | 4183 |
| mindur | 3 | 1 | **7/7** | 0 | 0.212 | 4343 |
| mindur+sil | 2 | 1 | 6/7 | 0 | 0.230 | 4803 |

**frag 4.0s (36.6s)**

| condition | wins | no_match | credited | missed | meanCER | infer_ms |
|---|---|---|---|---|---|---|
| baseline | 11 | 5 | 6/7 | **1 (false)** | 0.267 | 6401 |
| carry | 11 | 4 | **7/7** | **1 (false)** | 0.267 | 6404 |
| silence12 | 4 | 2 | 6/7 | 0 | 0.181 | 5899 |
| mindur | 8 | 3 | 6/7 | 0 | 0.253 | 5707 |
| mindur+sil | 4 | 2 | 6/7 | 0 | 0.181 | 5420 |

**frag 2.5s (40.1s)**

| condition | wins | no_match | credited | missed | meanCER | infer_ms |
|---|---|---|---|---|---|---|
| baseline | 14 | 10 | 4/7 | 0 | 0.157 | 6856 |
| carry | 14 | 7 | **7/7** | 0 | 0.192 | 7463 |
| silence12 | 3 | 1 | **7/7** | 0 | 0.226 | 11092 |
| mindur | **1 (39.87s!)** | 0 | 6/7 | 0 | 0.172 | 7086 |
| mindur+sil | 3 | 1 | **7/7** | 0 | 0.226 | 7483 |

**frag 1.5s (45.7s)** — heaviest fragmentation

| condition | wins | no_match | credited | missed | meanCER | infer_ms |
|---|---|---|---|---|---|---|
| baseline | 21 | 16 | 3/7 | 0 | 0.326 | 8102 |
| carry | 21 | 15 | 5/7 | 0 | 0.306 | 8158 |
| silence12 | 4 | 2 | 5/7 | 0 | 0.241 | 6021 |
| mindur | 21 | 16 | 3/7 | 0 | 0.326 | 7495 |
| mindur+sil | 4 | 2 | 5/7 | 0 | 0.241 | 5691 |

### Controls — no condition creates a false match

| control | every condition |
|---|---|
| real skip (skip3) | **1 MISSED_AYAH reported** (ayah 3) — detector never blinded |
| wrong surah (Fatihah vs 112) | **0/4 credited** — no false matches |

## Findings

**1. Fragmentation is confirmed as the cause.** Baseline degrades monotonically
with window size: **7/7 → 6/7 → 4/7 → 3/7** as chunks shrink 31s → 4.0s → 2.5s →
1.5s, on identical audio. Nothing but segmentation changed.

**2. `mindur` alone is unsafe.** At frag 2.5s it merged everything into a single
**39.87s** window — past the model's 30s cap, so the tail was silently truncated
(and it still only reached 6/7). Any minimum-duration gate needs a maximum-merge
cap. It also adds nothing on top of a longer `silence_cut`: `mindur+sil` and
`silence12` are identical at every level. **Rejected.**

**3. `carry` gives the best ayah recovery and costs nothing on clean audio:**
7/7 → 7/7 natural (no regression), 6/7 → 7/7 at 4.0s, 4/7 → 7/7 at 2.5s,
3/7 → 5/7 at 1.5s. But it does **not** remove the false `MISSED_AYAH` at frag
4.0s, and it needs new code in the session loop.

**4. `silence12` removes the false `MISSED_AYAH`** (1 → 0 at frag 4.0s), cuts
no_match hard (16 → 2 at 1.5s), gives the lowest CER, and is usually the fastest
because it runs far fewer inferences. It is also the **smallest possible change** —
one config value, no code. **But it regresses clean audio: 7/7 → 6/7**, and the
skip control from 6/7 → 5/7 credited. Merging windows loses an ayah somewhere,
which needs explaining before adopting it.

**5. The two fixes are complementary**, addressing different failures: `carry`
recovers ayahs, `silence12` prevents the false miss.

## Threshold sweep — where the clean-audio regression starts

| condition | natural credited | frag 4.0 credited | frag 4.0 false missed | frag 4.0 CER |
|---|---|---|---|---|
| baseline (0.5s) | **7/7** | 6/7 | 1 | 0.267 |
| carry | **7/7** | **7/7** | 1 | 0.267 |
| sil **0.7** | **7/7** | 6/7 | 1 | 0.223 |
| sil **0.9** | 6/7 ✗ | 6/7 | **0** | 0.175 |
| sil 0.7 + carry | **7/7** | **7/7** | 1 | 0.223 |
| sil 0.9 + carry | 6/7 ✗ | 6/7 | **0** | 0.175 |

The clean-audio regression appears at **0.9s, not 0.7s**. So 0.7s is free — it keeps
7/7 on natural audio and lowers CER on fragmented audio (0.267 → 0.223) — but it
does not by itself fix the false miss.

## Root cause of the residual false MISSED_AYAH

`carry` reaches 7/7 at frag 4.0s *and still reports one missed ayah*. That is not a
contradiction: an ayah is flagged missed, and a later window then credits it. **The
phoneme tracker never revokes a `MISSED_AYAH`.** It emits one at a single site and
there is no late-match withdrawal — whereas the Whisper path has exactly that
(`detector.py` keeps `confirmed_missed_ayahs` and emits `REVOKED` on a late match,
from commit `be3264c`).

So `silence12`'s apparent advantage is incidental: it avoids the false miss only by
merging windows so the miss is never emitted, and it pays an ayah on clean audio to
do it. The targeted fix is **late-match revocation of `MISSED_AYAH`**, porting
behaviour the other tracker already has.

## Recommendation — smallest change that fixes fragmentation

**Adopt `carry` (carry-forward concatenation of unmatched windows).**

- It is the only condition that fixes fragmentation with **zero cost on clean
  audio**: 7/7 → 7/7 natural, 6/7 → **7/7** at 4.0s, 4/7 → **7/7** at 2.5s,
  3/7 → 5/7 at 1.5s.
- Both controls stay clean: the real skip is still reported, the wrong surah still
  credits 0/4.
- Latency is unchanged (it reuses the inference already performed — no extra model
  calls, unlike `mindur`).
- Scope: a few lines in `phoneme_session.py`, with a cap already validated at 400
  IDs. The tracker is untouched.

**Bundle two cheap companions:**
1. `phoneme_silence_cut_sec` **0.5 → 0.7** — free, lowers CER on fragmented audio,
   no regression. Do **not** go to 0.9+.
2. **Late-match revocation of `MISSED_AYAH`** — removes the residual false miss at
   its source rather than by merging windows.

**Rejected:** `mindur` (unsafe 39.87s merges past the 30s model cap; adds nothing
over a longer `silence_cut`), and `silence_cut` ≥ 0.9 (costs a correctly recited
ayah on clean audio).

## Caveats

- One speaker, one surah, synthetic gap insertion. The dose-response is consistent
  and the controls are clean, but this is not a corpus. Re-confirm on the recorded
  corpus (plan §5.1) and on a real fragmented browser take before treating the
  numbers as final.
- Silence was inserted at fixed intervals, so cuts land mid-word. Real pauses fall
  at word boundaries, which is *easier* than this fixture — so these figures are
  likely a lower bound on the fixes' benefit.
- `infer_ms` is CPU-contended across runs; treat latency comparisons as indicative.
- **No production default was changed.** `phoneme_ref_rule` remains `single` and
  `phoneme_silence_cut_sec` remains 0.5.

---

# Implementation + A/B (2026-09-04)

Implemented behind flags, **all default OFF** (`test_flags_are_off_by_default`
guards this). Enable per-session with:

```
RECITEIQ_PHONEME_CARRY_FORWARD=true
RECITEIQ_PHONEME_REVOKE_LATE_MISS=true
RECITEIQ_PHONEME_SILENCE_CUT_SEC=0.7      # optional third change
```

`carry` and `revoke` now run the **shipped** code — `eval/segexp.py` drives
`CarryBuffer` / `carry_should_reset` from `phoneme_session.py` and the tracker's
revocation, rather than re-implementing them — so these numbers validate what
would actually ship.

## Results — current (`baseline`) vs new

| fixture | condition | wins | no_match | credited | missed | **revoked** | CER | infer_ms | carryMax |
|---|---|---|---|---|---|---|---|---|---|
| **real recording** (31.0s) | baseline | 3 | 1 | **7/7** | 0 | 0 | 0.212 | 4659 | 0 |
| | carry | 3 | 1 | **7/7** | 0 | 0 | 0.212 | 4523 | 8 |
| | carry+revoke | 3 | 1 | **7/7** | 0 | 0 | 0.212 | 4590 | 8 |
| | sil07+carry+revoke | 3 | 1 | **7/7** | 0 | 0 | 0.210 | 4366 | 8 |
| **frag 4.0s** | baseline | 11 | 5 | 6/7 | **1** | 0 | 0.267 | 8984 | 0 |
| | carry | 11 | 4 | **7/7** | 1 | 0 | 0.267 | 6154 | 42 |
| | carry+revoke | 11 | 4 | **7/7** | 1 | **1** | 0.267 | 5731 | 42 |
| | sil07+carry+revoke | 10 | 3 | **7/7** | 1 | **1** | **0.223** | 5290 | 31 |
| **frag 2.5s** | baseline | 14 | 10 | 4/7 | 0 | 0 | 0.157 | 7054 | 0 |
| | carry | 14 | **7** | **7/7** | 0 | 0 | 0.192 | 6690 | 55 |
| | carry+revoke | 14 | **7** | **7/7** | 0 | 0 | 0.192 | 5841 | 55 |
| | sil07+carry+revoke | 14 | **7** | **7/7** | 0 | 0 | 0.228 | 5867 | 35 |
| **frag 1.5s** | baseline | 21 | 16 | 3/7 | 0 | 0 | 0.326 | 7467 | 0 |
| | carry | 21 | 15 | 5/7 | 0 | 0 | 0.306 | 7429 | 107 |
| | carry+revoke | 21 | 15 | 5/7 | 0 | 0 | 0.306 | 7647 | 107 |
| | sil07+carry+revoke | 18 | 12 | **6/7** | 0 | 0 | 0.324 | 11768* | 70 |

\* CPU-contended; latency figures are indicative only.

### Controls — no false matches under any condition

| control | baseline | carry | carry+revoke | sil07+carry+revoke |
|---|---|---|---|---|
| **real skip** (ayah 3 omitted) | 1 missed, 0 revoked | 1 missed, 0 revoked | **1 missed, 0 revoked** | 1 missed, 0 revoked |
| **wrong surah** (Fatihah vs 112) | **0/4** credited | **0/4** (carryMax 291) | **0/4** (carryMax 291) | **0/4** (carryMax 252) |

Two results matter most here:

- **Revocation never withdraws a genuine miss.** On the real-skip control the miss
  stands with 0 revocations under every condition — it fires only when a later
  window actually credits the ayah.
- **Carry does not manufacture matches.** On the wrong surah it accumulated **291
  IDs** — nothing ever matched, so nothing ever reset it — and still credited
  **0/4**. That is the worst case the 400 cap exists for, and it held.

## Verdict

**`carry` + `revoke` is the pick.**

| | effect |
|---|---|
| fragmentation | 6/7 → **7/7** (4.0s), 4/7 → **7/7** (2.5s), 3/7 → 5/7 (1.5s) |
| clean audio | **unchanged** (7/7, identical CER) |
| standing false misses | frag 4.0s: 1 → **0** (emitted then revoked) |
| no_match | 10 → 7 (2.5s), 5 → 4 (4.0s) |
| latency | unchanged or better — no extra inference |
| carry buffer | peaked at 107 legitimately, 291 worst case, cap 400 |
| controls | real skip still caught; wrong surah still 0/4 |

Adding **`silence_cut=0.7`** helps most at the heaviest fragmentation (5/7 → 6/7)
and lowers CER at 4.0s (0.267 → 0.223), at no cost on clean audio. It is a
reasonable third change but is the least load-bearing of the three.

## Caveat: not yet validated on a browser capture

The "real recording" row is the user's own voice, but it was recorded **outside
the browser** — it is the take that already worked (3 windows, 7/7). The failing
session was browser-captured and fragmented, and **no browser-captured audio has
been available to test**, only its diagnostics. So the fragmented rows remain
synthetic (silence inserted at fixed intervals, cutting mid-word — harsher than
real pauses, so likely a lower bound on the benefit).

**Before flipping any default**, capture a browser take on the current build with
the flags on and compare against the same take with them off.
