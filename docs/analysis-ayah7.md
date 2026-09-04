# Why Al-Fatihah ayah 7 never matched (2026-09-04)

Ayah 7 failed to match in **all six** live browser takes (closest CER 0.583–0.774),
across both devices and both audio configurations. Candidate causes were CTC
decoding, reference mismatch, long-ayah/model-length behaviour, segmentation, or
something else.

## It is the length gate in `_best_span`, driven by segmentation

`_best_span` scans candidate span lengths of `0.75L .. 1.35L` for a reference of
length `L`. **If the window is shorter than `0.75L`, no candidate exists at all**
and the score is 1.0 by construction — regardless of how perfectly the reciter
pronounced it. Ayah 7 is 63 IDs, so it needs **≥ 47 IDs in a single window**:

| window (ids) | CER vs ayah 7 |
|---|---|
| 18 | 1.000 |
| 31 | 1.000 |
| 44 | 1.000 |
| **46** | **1.000** |
| **47** | **0.254** |
| 56 | 0.111 |
| 63 | 0.000 |

A hard cliff between 46 and 47 IDs. At the observed ~6 IDs/sec that is **7.8
seconds of continuous recitation with no 0.5s pause** — and the browser takes
produced windows of ~4.3s / ~26 IDs (largest ~30). Ayah 7 was therefore
**unscoreable**, not mis-scored.

## The other candidates are ruled out

**Not the reference.** Ayah 7's cross-reciter confidence is 0.868 and its six
variant lengths span 63–66 — as tight an agreement as any other ayah (ayah 2:
0.977, 28–29).

**Not CTC decoding.** Every take showed healthy token production (4.9–7.2 IDs/sec
against a ~4.5 qari reference) and high posteriors (`c_ctc` 0.74–0.99). The model
was transcribing ayah 7 fine; nothing could score it.

**Not model-length behaviour.** P1-9's variable-length encoder is validated to
CER 0.000 against the padded path at 3s and 5s, and 0.018 at 10s.

**It is segmentation — and the evidence cuts both ways:**
- The `.ogg` take produced one **24.26s / 174-ID** window and chained
  `[2,3,4,5,6,7]` — **ayah 7 matched**.
- The Al-Baqarah take produced windows of 100/87/76/66/66 IDs and matched long
  ayahs without trouble.
- Every browser Al-Fatihah take produced ~26-ID windows and never matched ayah 7.

Same model, same references, same threshold. Only the window size differed.

## Implication

This is the clearest use case yet for **carry-forward**, which is already
implemented and tested but off by default: it accumulates unplaced fragments until
they reach a matchable length, which is exactly what a 63-ID ayah needs from ~26-ID
windows. The synthetic experiment showed carry recovering 4/7 → 7/7 at comparable
fragmentation.

**No threshold change is warranted.** The failure is not that 0.45 is too strict —
ayah 7 scored 1.0, infinitely far from any gate. Raising `MATCH_CER_MAX` would not
have matched a single additional ayah-7 window, and would only increase false
acceptance elsewhere.

Worth considering separately: the `0.75L` floor is itself a design choice, and a
long ayah could instead be matched *partially* (crediting the portion covered).
That is a v2 word-span concern (P2-1), not a threshold tweak.

## Note on evidence handling

The per-window logs for these six sessions were lost when the backend container
was recreated. The analysis above rests on the reference data, the code path, and
figures already transcribed into the experiment docs — but per-session diagnostics
should be persisted outside `docker logs` before the next round of measurement.
