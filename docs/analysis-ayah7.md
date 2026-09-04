# Why Al-Fatihah ayah 7 never matched (2026-09-04)

Ayah 7 failed to match in **all six** live browser takes (closest CER 0.583–0.774)
across both devices and both audio modes. Cause identified.

## Not the model, not the reference

Fed the **whole recitation as one stream** (no windowing), every ayah matches —
including ayah 7:

| ayah | ref len | CER on the full stream | ≤ 0.45 |
|---|---|---|---|
| 1 | 27 | 0.259 | yes |
| 2 | 28 | 0.143 | yes |
| 3 | 16 | 0.125 | yes |
| 4 | 16 | 0.188 | yes |
| 5 | 31 | 0.258 | yes |
| 6 | 24 | 0.417 | yes |
| **7** | **63** | **0.208** | **yes** |

So the hypotheses can be closed off:

- **CTC decoding** — ruled out. The IDs are good enough to score 0.208.
- **Reference mismatch** — ruled out. Ayah 7's cross-reciter agreement is 0.868,
  its six variants span 63–66 ids (tight), and it is not flagged unstable. Its
  7.00 ids/word is right at the surah median.
- **Long-ayah / model-length behaviour** — ruled out. The model handles it fine
  when it sees it whole.
- **Segmentation / window length** — **this is it.**

## The mechanism: a hard length gate in `_best_span`

`_best_span` only tries candidate span lengths of 0.75 L … 1.35 L. If the window
is shorter than **0.75 × ref_len**, *no candidate exists at all* and it returns
CER 1.0 — regardless of how perfectly the reciter pronounced it.

Measured on the real recording, scoring ayah 7 against windows of increasing size:

| window (ids) | CER |
|---|---|
| 20 | **1.000** — below 0.75 × 63 = 47, no candidate span exists |
| 26 | **1.000** |
| 32 | **1.000** |
| 40 | **1.000** |
| 47 | 0.524 — a span exists, but still above the 0.45 gate |
| 55 | 0.524 |
| **63** | **0.317** — matches |
| 70 | 0.317 |

**Ayah 7 needs ~63 ids in a single window**, which at ~6 ids/sec is about **10
seconds of continuous recitation with no 0.5s pause**. The observed median live
window is **4.26s / ~26 ids**. Ayah 7 is therefore structurally unmatchable in
normal use — and it is the only ayah in the surah large enough for this to bite:

| ayah | ref ids | min window to match | ≈ seconds |
|---|---|---|---|
| 1 | 27 | 20 | 3.3s |
| 2 | 28 | 21 | 3.5s |
| 3 | 16 | 12 | 2.0s |
| 4 | 16 | 12 | 2.0s |
| 5 | 31 | 23 | 3.8s |
| 6 | 24 | 18 | 3.0s |
| **7** | **63** | **47** | **7.8s** |

A 26-id window can only reach ayahs with ref_len ≤ 34. Ayah 7 (63) is the sole
ayah above that line — which is exactly why it, and only it, never matched.

## Consequence

**Carry-forward is the fix for ayah 7.** It accumulates unmatched fragments until
they reach the length the reference needs, which is precisely this failure. The
segmentation work was not the fix for the earlier browser failures (those windows
were already ayah-sized) but it *is* the fix here.

This also predicts the same failure for every long ayah elsewhere — Al-Baqarah
2:255 (Ayat al-Kursi) and similar — so it is not a Fatihah quirk. Any ayah whose
reference exceeds ~34 ids is unreachable from a typical window today.

**The CER threshold was not touched**, per instruction. Note that raising it
would not help anyway: below 47 ids the score is 1.0 by construction, not a
near-miss. The length gate has to be addressed, not the threshold.
