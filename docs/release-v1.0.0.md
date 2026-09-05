# ReciteIQ v1.0.0 — production release status

**Tagged:** `v1.0.0` · **Commit:** `3ca2faa` · **Live:** `reciteiq.wiserhelpdesk.com`

This is the baseline. The architecture below is **frozen** — changes to the
recognition or tracking path need a real production issue behind them, not a
better idea.

## Architecture (frozen)

```
Browser AudioWorklet (16 kHz mono PCM)
  → WebSocket
  → silero VAD, 25 s windows / 0.5 s silence cut / 1.5 s overlap
  → NeMo FastConformer (mohammed/fastconformer-quran-ar), in-process, serialised
  → Imlaei normalisation
  → windowed fuzzy aligner (rapidfuzz, 12 forward / 8 back, accept ≥ 78)
  → RecitationTracker state machine
  → events over WebSocket → React Mushaf + summary
```

One FastAPI process. PostgreSQL for the Qur'an tables, sessions, events and
summaries. No separate AI service; the recogniser is a library call, which is
what keeps a 25 s window inside a ~3 s inference budget.

## Verified metrics

Measured on this commit, against the live deployment unless stated otherwise.

| Metric | Value |
|---|---|
| Test suite | **144 passing** (`.venv/bin/python -m pytest tests`) |
| Release regression, public URL | **7/7 pass** |
| Concurrent sessions admitted | **3/3** (global cap 6, per-client 3) |
| Memory, 1 / 2 / 3 sessions | **1.677 / 1.678 / 1.679 GiB** of 2.5 GiB |
| Inference, warm | ~3 s per 25 s window (RTF ≈ 0.12) |
| Whole Qur'an, perfect input | 77,429 / 77,429 words, all 114 surahs, zero false events |
| Skipped word detection | **100%** across 104 surahs |
| Substituted word detection | **100%** across 104 surahs |
| **Skipped ayah detection** | **58.7%** (61/104) — named-event metric |
| Repeated ayah detection | 86.5% (90/104) |
| Jump events, 104 single-skip sweep | **34** (was 380) |
| Accuracy shown for a skipped-ayah session | **93%** — the same case previously displayed 100% |

### Two numbers that are easy to confuse

They measure different things and are both quoted above deliberately:

- **58.7%** is the *skipped-ayah detection rate*: of 104 surahs with one ayah
  deliberately removed, 61 produced a correctly-named `MISSED_AYAH`. This is the
  headline capability figure.
- **93%** is the *accuracy percentage displayed to the reciter* in one specific
  regression case — Al-Fatihah with ayah 3 skipped, 27 of 29 expected words
  credited. It is evidence that the accuracy denominator is now correct (that
  same case used to display 100%), not a detection rate.

An earlier figure of **84.6%** for skipped-ayah detection should not be quoted.
It came from a metric that counted *any* mutashabeh jump as a successful catch;
requiring the event to name the right ayah accounts for the entire difference,
and of 380 jump events in that sweep not one pointed at the correct place.

## Known limitation

**Long-distance skipped-ayah recovery is not universal across all 114 surahs.**
The aligner searches 12 words ahead of the pointer, and only **42 of 114**
surahs have every ayah inside that window — Al-Baqarah's longest ayah is 128
words. When a reciter skips an ayah longer than the window, the word they resume
on is beyond the aligner's reach, while the relocation index declines to
intervene because the destination is one ayah away and therefore not a
mutashabeh jump. The skip falls between the two mechanisms.

Consequence: ayah-level recovery is 58.7% overall, concentrated in the long
surahs. **Word-level detection is unaffected at 100%**, and every surah in the
curated set is inside the safe 42.

Two remedies were implemented and both withdrawn after measurement — a
far-forward search made detection *worse* (84.6% → 82.7% on the metric of the
day), and a local repositioning rule traded total detection for better event
naming. Recorded in `docs/scope-whole-quran.md` so the next attempt starts from
evidence.

A second, smaller limitation: an ayah repeated *within a single 25 s window* is
collapsed by the RNN-T decoder and never reaches the detector. It raises no
false error, and a repetition spanning a window boundary is still caught.

## Release gate

Every change runs, in this order:

```bash
cd backend
.venv/bin/python -m pytest tests -q                       # 144 tests
.venv/bin/python scripts/sweep_all_surahs.py              # whole Qur'an, perfect input
.venv/bin/python scripts/sweep_errors.py                  # injected errors, 104 surahs
.venv/bin/python scripts/release_regression.py <base_url> # 7 cases, live server
```

`release_regression.py` reconnects the way the SPA does, so a dropped socket
resumes rather than failing the gate — which also exercises non-lossy reconnect
on every run.

## Rollback

Two lines in `deploy/.env`:

```
RECITEIQ_ASR_ENGINE=whisper_local
RECITEIQ_TRACKER_MODE=phoneme
```

No rebuild: the production image carries `faster-whisper` alongside NeMo. The
schema only ever gained columns with defaults, so no downgrade is needed. Full
procedure in `docs/runbook-engine-rollback.md`.

## Security posture

- No credential in the repository or its history; `scripts/check-secrets.sh`
  runs as a pre-commit hook and in CI, and CI fails if the scanner does *not*
  refuse a planted key.
- Recitation audio is never persisted — the only disk write is a temp WAV
  removed within the same call.
- Transcribed text is purged after 30 days by an in-app sweeper (the first run
  removed 1,108 rows that an uninstalled cron had left).
- No authentication: the caps are the only protection. Acceptable for an FYP
  demo; a prerequisite for anything wider.
