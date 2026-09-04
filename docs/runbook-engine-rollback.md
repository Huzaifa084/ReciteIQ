# Runbook — FastConformer rollout and rollback

## Current state

| | engine | tracker | segmentation | where |
|---|---|---|---|---|
| **production** | `whisper_local` | `phoneme` | 5 s / 0.7 s | `reciteiq.wiserhelpdesk.com` → `reciteiq-web-1` → `reciteiq-backend-1` |
| **staging candidate** | `fastconformer` | `whisper` (text) | 25 s / 0.5 s | `127.0.0.1:19844`, loopback only |

Production is unchanged and is not routed through the staging container. The
phoneme implementation is fully intact and is the rollback target.

## Start / stop staging

```
cd /opt/apps/ReciteIQ/deploy
docker compose -f docker-compose.staging.yml up -d
docker compose -f docker-compose.staging.yml logs -f backend-staging
docker compose -f docker-compose.staging.yml down
```

The 1.2 GB checkpoint lives in the `reciteiq_hf` volume, so only the first start
downloads it. Cold start is ~60 s after that; the healthcheck allows 240 s.

## Promoting the candidate to production

One file, two lines — `deploy/.env` (gitignored):

```
RECITEIQ_ASR_ENGINE=fastconformer
RECITEIQ_TRACKER_MODE=whisper
```

then rebuild the production backend against `Dockerfile.fastconformer` (the
default `Dockerfile` has no NeMo) and `docker compose up -d backend`.

**Do not set `RECITEIQ_SEGMENT_MAX_SEC` or `RECITEIQ_SILENCE_CUT_SEC`.** The
engine selects 25 s / 0.5 s, which is what the release gate measured; an
explicit value silently overrides it and costs the result in
`gate-release.md` (five false missed words across six clean recitations at 5 s
versus none at 25 s). This override path is deliberately kept — it is the knob
below — and is covered by `tests/test_engine_segmentation.py`.

## Rollback

```
# deploy/.env
RECITEIQ_ASR_ENGINE=whisper_local
RECITEIQ_TRACKER_MODE=phoneme
```

`docker compose up -d backend`. Nothing else has to change:

- Both paths share the same schema. The `c3f9a2e64d17` migration only ADDS
  `repeats` / `uncertain` columns with defaults, so the old code runs unmodified
  against the new schema — the rollback does not need a downgrade.
- `POST /sessions/{id}/end` dispatches on `tracker_mode`, so a phoneme session
  is finalised by the phoneme finaliser and its summary is not clobbered.
- The SPA is shared and reads only the event stream, which both paths emit.

Rolling back mid-session ends the in-flight WebSocket sessions; nothing is
corrupted, and clients reconnect.

## What to watch after a flip

| signal | expected | where |
|---|---|---|
| memory | ~1.7 GiB steady, 1.83 GiB at 3 concurrent sessions, limit 2560 m | `docker stats` |
| cold start | ~60 s to healthy | healthcheck |
| inference | ~0.15 RTF warm; a 25 s window ≈ 3.5 s | `asr window` log lines, `scripts/window_report.py` |
| concurrency | serialised — one inference at a time by design | `max_inflight` in the engine lock |
| false errors | should stay at zero on clean recitation | user reports |

`max_concurrent_sessions` is 3 and inference is serialised behind an
`asyncio.Lock`, so the fourth session is shed rather than queued. A failed
inference releases both the lock and the queue slot
(`tests/test_fastconformer_contract.py`).

## Known limitation to communicate

An ayah repeated *inside one 25 s window* is collapsed by the RNN-T decoder and
is not reported as a REPEAT. It raises no false error, and a repeat that spans a
window boundary is still caught. See R4 in `gate-release.md`.
