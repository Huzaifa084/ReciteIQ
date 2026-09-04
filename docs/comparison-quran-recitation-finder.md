# Comparison: quran-recitation-finder vs ReciteIQ (2026-09-04)

Reviewed from `/opt/apps/quran-recitation-finder.zip`.

## They solve a different, smaller problem

| | quran-recitation-finder | ReciteIQ |
|---|---|---|
| Task | **"which ayah is this?"** — one-shot identification | **continuous tracking** of a known passage |
| Live word-by-word progress | no | yes |
| Missed-word / missed-ayah detection | **none** (no such code exists) | yes |
| Mutashabeh jump detection | no | yes |
| Session summary | no | yes |
| Deployed | local dev | live at reciteiq.wiserhelpdesk.com |

Their headline **17/17 top-1 ayah accuracy** is closest to *our auto-detect
feature*, not to our tracker. Our problem is strictly harder: identification asks
"where is this?" once; tracking asks "is the reciter still where I think, and did
they miss anything?" continuously, and has to be honest when unsure.

So this is not a rival implementation to copy wholesale. It is a well-engineered
solution to one sub-problem, with several parts worth taking.

## The big caveat on their numbers

WER 0.079 / CER 0.030 / 17-of-17 were measured on **17 clips of Mishary Alafasy —
a professional qari**. That is exactly the population where *we* also do well: our
qari clip scores CER 0.037–0.208 and tracks 7/7. Their benchmark says nothing
about amateur voices, which is our actual blocker (amateur CER 0.45–0.50 against
the same references).

Do not read 17/17 as "this would fix our problem". It is evidence about clean
professional audio only — the same trap that made the earlier resampler and
segmentation hypotheses look stronger than they were.

## Worth taking

### 1. Their ASR model — `mohammed/fastconformer-quran-ar`

NVIDIA NeMo FastConformer (`EncDecHybridRNNTCTCBPE`), checkpoint
`phase3_full/phase3_full_wer0.0014.nemo`, ~460 MB, ~0.5 s per short ayah on CPU.
Quran-fine-tuned, emits Imla'i, and is **cache-aware / streaming-capable** — which
our 30 s-window encoder is not.

Verified downloadable (HF returns 200). Their bundled `.venv` is macOS arm64 and
unusable here, so NeMo would need a fresh install.

This is a genuinely stronger ASR than the whisper-base our Whisper path uses. But
adopting it means matching **text**, not phoneme IDs — i.e. reviving the Whisper
path with a much better model, not improving the phoneme tracker. That is a real
architectural fork and should be decided on measurement, not on their benchmark.

They also list `tarteel-ai/whisper-base-ar-quran` (the same model family our CT2
checkpoint comes from) and `MaddoggProduction/whisper-l-v3-turbo-quran-lora-dataset-mix`.

### 2. Asymmetric coverage — directly relevant to our ayah-7 bug

Their level 3 measures **"how much of the query the passage explains"**, not how
similar two strings are, explicitly because *"a partial recitation is a subset of
an ayah, so a symmetric measure would punish exactly the case the app is built
for."*

That is precisely our ayah-7 failure. `_best_span` uses symmetric normalized edit
distance plus a `0.75L` length floor, so a 26-ID window against a 63-ID ayah
scores **1.0 by construction** — the hard cliff documented in
`analysis-ayah7.md`. An asymmetric coverage score would let a partial window match
a long ayah *proportionally* instead of not at all.

**This is the most immediately useful idea in their codebase**, and it is a
better answer to ayah 7 than either carry-forward or a threshold change.

### 3. Dual orthographic projection

They index every ayah **twice** — dagger alef dropped *and* expanded — and score
under both, keeping whichever agrees. We normalise to Imla'i only. Their approach
removes a whole class of silent mismatch, and they reached it from the same
dagger-alef problem we documented.

### 4. IDF-weighted retrieval with a max-IDF penalty for unknown tokens

Our auto-detect uses unweighted n-gram voting. Giving a token absent from the
Qur'an the *maximum* IDF, so a mis-recognised word cannot quietly dilute a score,
is a better design than ours.

### 5. The no-Arabic-literals AST test

A test that walks the AST of the ASR layer proving it contains no Arabic string
literals — so no model can ever emit Qur'anic text that did not come from the
canonical database by reference. For an FYP on a Qur'an app that is a strong
integrity guarantee and cheap to adopt.

## Not worth taking

- Their retrieval/matching pipeline wholesale — it is built for one-shot
  identification over the whole Qur'an, whereas our tracker matches against a
  known short reference list. Their seven-level scorer would be overkill.
- Their engine-swap abstraction — we already have `tracker_mode` and a narrower
  need.

## Recommended next step

Before any architectural move, run the decisive test: **transcribe the user's own
`.ogg` amateur recitation with FastConformer and compare against the reference
text.** If it transcribes an amateur voice near its qari WER, the text path with
this model is likely better than the phoneme path and the fork is worth
considering. If it degrades the way whisper-base did, the phoneme architecture
stands and we take only ideas 2–5.

NeMo must be installed in an isolated environment — not into the production
backend — since it is a heavy dependency and the current stack is working.
