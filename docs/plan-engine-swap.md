# Engine-swap design: FastConformer + the existing text pipeline

**Status: design only. Nothing here is implemented and no production default has
changed.** Gated on `docs/gate-deliberate-errors.md` (passed, one gap) and
`docs/experiment-fastconformer-six-surahs.md` (96.7% of words across six surahs).

## The core insight

FastConformer emits **text**. ReciteIQ already has a complete text pipeline — the
Whisper path — with word-level tracking, `MISSED_WORD`, mutashabeh relocation and
the provisional/confirmed/revoked lifecycle. It was abandoned because
whisper-base was fragile on amateur mics. **That premise is now retired.**

So this is an **ASR engine swap under existing code**, not a rewrite. The phoneme
architecture existed to work around a weak recogniser; with a strong one, the
detour is no longer needed.

## Component inventory: reuse vs retire

### Reuse unchanged (the text pipeline already fits)

| component | lines | role |
|---|---|---|
| `engine/aligner.py` | 97 | windowed fuzzy word alignment |
| `engine/detector.py` | 390 | miss/repeat/jump state machine, event lifecycle |
| `engine/locate.py` | 110 | auto-detect over the relocation index |
| `mutashabeh/index.py` | 139 | word-3-gram relocation index |
| `nlp/normalize.py` | 52 | Arabic normalization (already correct — §1 of the comparison doc) |
| `engine/events.py` | 52 | event types and states |
| `audio/vad.py` | 160 | segmenter — **shared, already used by both paths** |
| `db/repo.py::load_reference` | — | dual-script word reference |
| whole SPA | — | MushafView, reducer, WS client, summary |
| `ws/session.py` | 374 | the text session handler |

**~1400 lines of tracker, detector and index survive untouched.**

### Reuse with modification

| component | change |
|---|---|
| `asr/base.py` | `Transcript` already carries `text` + gate fields. FastConformer has no `avg_logprob`/`no_speech_prob`; either map its confidence or make those optional. |
| `asr/__init__.py::get_engine` | add `fastconformer` alongside `whisper_local` / `cloud`. |
| `ws/session.py` | port the four fixes proven on the phoneme path: session-start anchor rule, late-`MISSED_AYAH` revocation, `UNCERTAIN` + `no_match`, and the P1-7 per-window diagnostics. **Do not lose these.** |
| `config.py` | `asr_engine` gains `fastconformer`; phoneme flags become dormant. |

### New

| component | note |
|---|---|
| `asr/fastconformer.py` | NeMo `ASRModel.restore_from`, lazy + lock-guarded like the existing engines. ~85 lines, mirroring `whisper_local.py`. |
| dual orthographic projection | index each ayah under dagger-alef-dropped **and** expanded (from quran-recitation-finder). Optional but cheap and removes a class of silent mismatch. |

### Retire (only after the swap is proven live)

| component | lines | why |
|---|---|---|
| `ws/phoneme_session.py` | 376 | superseded by `ws/session.py` |
| `engine/phoneme_tracker.py` | 400 | superseded by `aligner` + `detector` |
| `engine/phoneme_index.py` | 81 | superseded by `mutashabeh/index.py` |
| `asr/phoneme_ctc.py` | 162 | superseded by `asr/fastconformer.py` |
| `scripts/build_phoneme_refs.py` | 179 | no phoneme references needed |
| `models/quran-phoneme-ctc-small-v2.pt` | 352 MB | — |
| DB: `ayahs.phoneme_ids`, `phoneme_confidence`, `phoneme_unstable`, table `ayah_phoneme_refs` | — | keep the columns until the swap is proven, then drop in one migration |

**~1200 lines and 352 MB retire**, against ~85 lines added.

### Carry forward as ideas, not code

The phoneme work produced findings that apply to the text path too:
- **absence of a match is not evidence of a skip** (P0-4) — the detector must
  keep this discipline.
- **session-start anchor rule** — a leading gap before any anchor is uncertain.
- **late-match revocation** — a verdict contradicted by later evidence is withdrawn.
- **asymmetric coverage** — partial matches hold position rather than scoring 1.0.
- **per-window diagnostics** — the instrumentation that made every diagnosis above
  possible. Port it first.

## Risks

| risk | mitigation |
|---|---|
| **NeMo dependency**: ~2.2 GB venv, 460 MB checkpoint, Python ≤3.12 | build a separate image; measure the container size before committing. Current backend is 1.65 GB. |
| **Memory**: model ≈ 935 MB resident vs the phoneme model's ~500 MB. Backend limit is 2560 MB. | raise the limit or measure headroom under concurrency first. |
| **Concurrency unmeasured** — RNN-T decoding is a step loop | benchmark 2–3 concurrent sessions before switching the default. |
| `aligner`/`detector` were tuned against whisper-base output | FastConformer output is *cleaner*, so thresholds are likely conservative, but they must be re-measured, not assumed. |
| **Streaming** — the checkpoint is cache-aware/streaming-capable but we would use it in windows initially | keep the existing VAD segmenter; revisit streaming later. |
| Substitution behaviour untested | close the gate gap before the default flips. |

## Sequencing

1. **Close the gate gap** — one deliberately-wrong-word recording.
2. **Port the diagnostics** (P1-7 equivalent) into `ws/session.py`, so the text
   path is measurable from day one.
3. **Add `asr/fastconformer.py`** behind `RECITEIQ_ASR_ENGINE=fastconformer`,
   default off. Build the image; measure size, memory, concurrency.
4. **Port the four phoneme-path fixes** into the detector.
5. **A/B on the recorded corpus** — text path + FastConformer vs the live phoneme
   path, on the same audio, using the same metrics.
6. **Flip the default** only if the A/B wins.
7. **Retire** the phoneme components in a separate commit, after a stable period.

Do not retire anything before step 6. The phoneme path is the rollback.
