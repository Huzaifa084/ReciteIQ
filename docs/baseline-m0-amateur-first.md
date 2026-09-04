# First amateur-voice measurement (2026-09-04)

A live browser take of Al-Fatihah, captured with the P0-3 / P1-7 instrumentation.
**This is the first real amateur data the project has**, and it overturns the
working hypothesis.

```
 win_s     closed     ms  ids  id/s  rms_dB  peak_dB  blank  c_ctc chain meanCER  closest      outcome  matched
  3.55    silence   1570    4  1.13   -30.1    -11.7  0.966  0.930     0       -    1.000     no_match  []
  3.78    silence    623   24  6.36   -27.7    -11.1  0.778  0.799     0       -    0.464     no_match  []
  0.64    silence    212   14 21.88   -40.4    -21.4  0.312  0.850     0       -    0.812     no_match  []
  4.61    silence    745   13  2.82   -27.1     -7.7  0.918  0.881     0       -    0.500     no_match  []
  3.65    silence    639   14  3.84   -25.1     -9.5  0.885  0.907     1   0.312    0.312      chained  [4]
  6.34    silence    881   24  3.79   -27.4     -8.8  0.886  0.918     0       -    0.452     no_match  []
  1.15    silence    239   14 12.15   -37.3    -18.7  0.690  0.792     0       -    0.750     no_match  []
  5.25    silence    599   22  4.19   -26.0     -7.7  0.882  0.835     1   0.417    0.417      chained  [6]
  5.25    silence   1240   27  5.14   -29.1     -9.9  0.859  0.898     0       -    0.774     no_match  []
  5.25    silence    774   27  5.14   -24.4     -7.8  0.859  0.846     0       -    0.778     no_match  []
  2.75    silence    386    5  1.82   -29.8    -12.7  0.927  0.678     0       -    1.000     no_match  []
  2.21    silence    389   13  5.89   -32.5    -13.9  0.856  0.781     0       -    0.812     no_match  []

outcomes {'no_match': 10, 'chained': 2}   ayahs credited: [4, 6]
ids_per_sec p50=5.14 (qari ~4.5)   rms_dbfs p50=-27.7 (min -40.4, max -24.4)
infer_ms p50=639 p95=1570
```

## The input hypothesis is falsified

Every measure of input quality is **healthy**:

| Signal | Value | Verdict |
|---|---|---|
| `rms_dbfs` p50 | **−27.7** (−40.4 … −24.4) | inside the healthy −30…−18 band |
| `ids_per_sec` p50 | **5.14** | **above** the qari reference of ~4.5 |
| `c_ctc` | **0.68 – 0.93**, mostly ~0.85+ | the model is *confident* |
| windows below 2.0 ids/s | 2 of 12 | not starvation |

So this is **not** mic level, not `noiseSuppression`, not token starvation, and not
the resampler. The model is producing plenty of tokens and is confident about them.
The tokens simply **do not match the stored references**.

(The earlier 0.6 ids/sec reading came from a session with much longer windows; with
`window_sec` p50 now 3.78s the rate is healthy. That earlier signal was misleading.)

## The real problem, in one number

| | CER against the Husary reference |
|---|---|
| qari (Alafasy clip) | **0.037 – 0.208** |
| **this amateur take** | **0.312 – 1.000**, clustering **0.45 – 0.50** |

`MATCH_CER_MAX = 0.45` was calibrated on qari-vs-qari agreement. Amateur-vs-Husary
lands **right on top of the gate**, so matching becomes a coin flip:

| MATCH_CER_MAX | windows matched |
|---|---|
| **0.45 (current)** | **2/12 (17%)** |
| 0.47 | 4/12 (33%) |
| 0.50 | 5/12 (42%) |
| 0.60 | 5/12 (42%) |

Three windows are near-misses at **0.452, 0.464, 0.500** — a hair above the gate.
This is direct evidence for **P0-1**: a single professional reference is the wrong
target for an amateur voice, and the threshold is calibrated for the wrong
population.

Note that relaxing the gate saturates at 5/12 — it is *not* a fix on its own. Half
the windows are genuinely far away (0.75 – 1.00) and need a closer reference, not a
looser gate.

## A second, independent bug: absence of a match is treated as a skip

Credited ayahs were `[4, 6]`, and the UI turned ayahs 1, 2, 3 and 5 **red**. But the
reciter did recite them — their windows just failed to match.

`PhonemeTracker.feed()` reports every unmatched ayah inside a chained span as
`MISSED_AYAH`. When the window that covered ayah 1 returns `no_match` and a later
window chains to ayah 4, ayahs 1–3 are declared skipped. **Absence of evidence is
being reported as evidence of a skip**, which is the exact opposite of the
conservative behaviour the module docstring promises.

This is a logic flaw independent of the reference quality, and it is what makes the
screen fill with red. The fix is squarely **P0-4**: when `no_match` windows sit
between two chained windows, the intervening ayahs are `UNCERTAIN` (amber), never
`MISSED_AYAH`. A miss may only be claimed when the ayah was *skipped over inside a
window that otherwise matched well* — i.e. when there is positive evidence the
reciter moved on.

## Consequences for the plan

1. **P0-4 rises to the top.** It is no longer only about UI feedback — it stops the
   tracker from manufacturing false errors. Cheap, self-contained, and it removes
   the worst user-visible symptom.
2. **P0-1 is confirmed as the accuracy lever**, with a number: amateur CER 0.45–0.50
   vs qari 0.04–0.21 against the same references.
3. **Threshold recalibration must wait for FAAR.** Raising the gate to ~0.50 would
   roughly double matches, but this take has no deliberate errors in it, so it
   cannot bound the false-acceptance cost. Do not touch `MATCH_CER_MAX` until the
   intentional-error corpus exists (plan §5.1).
4. **P1-8 stays downgraded.** Input quality is measurably fine.

---

# P0-1 — multi-reciter references, and a negative result (2026-09-04)

Storage, builder and the pluggable rule all landed, and the pilot references are
built: **surahs 1, 109, 111, 112, 113 — 27 ayahs × 6 reciters, 0 failures.**
Per-reciter basmalah templates now come out at 27–28 IDs each, replacing the
single Husary template that was being applied to every voice.

## The reference reduction rule does NOT yet earn its keep

Leave-one-out on the qari clip (holding out whichever reciter matched best, so a
voice is never scored against its own reference):

| ayah | husary | min (all 6) | min (LOO) | 2nd (LOO) | per-reciter spread |
|---|---|---|---|---|---|
| 1 | 0.074 | 0.074 | 0.074 | 0.074 | 0.07 0.07 0.07 0.07 0.15 0.18 |
| 2 | 0.107 | 0.107 | 0.107 | 0.107 | 0.11 0.11 0.11 0.11 0.14 0.17 |
| 3 | 0.125 | 0.125 | 0.125 | 0.188 | 0.12 0.12 0.19 0.20 0.27 0.33 |
| 4 | 0.000 | 0.000 | 0.000 | 0.062 | 0.00 0.00 0.06 0.12 0.12 0.22 |

| rule | mean CER | ayahs ≤ 0.45 |
|---|---|---|
| single | 0.341 | 4/7 |
| min (all 6) | **0.334** | 4/7 |
| min (LOO) | 0.340 | 4/7 |
| second (LOO) | 0.359 | 4/7 |

(Ayahs 5–7 sit at ~0.68–0.72 for *every* reciter because they fall outside the
22s query window — truncation, not a matching failure. They are why the means
look high.)

**Multi-reference buys essentially nothing here: 0.341 → 0.334.** And the reason
is visible in the spread: the six professional reciters produce **highly
correlated ID sequences** (0.07–0.18 within an ayah). They cluster, so taking the
minimum over them barely moves the score.

## What this does and does not settle

**Does not settle the amateur case.** The query is a professional whose CER
against Husary is already 0.07–0.12 — there is no headroom for a better reference
to recover. The 0.45–0.50 amateur gap can only be tested on amateur audio, which
is exactly why the rule choice was left to the corpus. `phoneme_ref_rule` stays
at **`single`**, so production behaviour is unchanged until there is data.

**Does raise a real doubt about the P0-1 hypothesis.** If six professionals
cluster within 0.11 CER of each other, the amateur's 0.45–0.50 distance is
probably not "wrong reciter style" — it is more likely that the model represents
an amateur voice differently from *any* professional. Adding a seventh
professional would then not help either.

That shifts weight onto **P2-2 speaker enrollment**: the reciter's own voice is
the only reference guaranteed to match their acoustics, it drops straight into the
`variants` list with no new matching machinery, and for five short surahs it is a
few minutes of recording. On this evidence it should be promoted ahead of further
reference-set expansion — pending the corpus, which remains the arbiter.
