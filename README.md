# ReciteIQ — Smart Quran Recitation Alignment & Correction

A web-based "Sami" (listener) for Hifz practice: it captures recitation through
the browser microphone, transcribes it with a Quran-fine-tuned Whisper model,
aligns it word-by-word against the full Uthmani Quran, and flags **missed
words**, **missed ayahs**, and **Mutashabeh jumps** (drifting into a similar
verse elsewhere) in real time.

Sessions can start two ways: pick a Surah/Ayah manually, or **Just Recite** —
auto-detection locates the Surah and Ayah from the opening words (global
3-gram search with an ambiguity margin: genuinely ambiguous openings like
الحمد لله رب العالمين, which ends 10:10/37:182/39:75/40:65 verbatim, keep
listening until one location uniquely wins; isti'adha/basmalah are consumed
as preamble first).

## Architecture

```
Browser SPA (React/Vite)            backend (FastAPI, one container)
  mic → AudioWorklet → 16k PCM ──ws──► silero VAD (ONNX) → segment (5s cap)
  green/red MushafView ◄──events──     → faster-whisper int8 (Quran-tuned)
                                       → normalize → windowed fuzzy aligner
                                       → detector (miss/repeat/jump state machine)
                                       → 3-gram relocation index (Mutashabeh)
                                    Postgres: dual-script words, sessions, events
```

Key data decision: words are stored **dual-script** — Uthmani for display,
normalized Imlaei for matching — because ASR emits standard orthography while
Uthmani rasm differs (ٱلصَّلَوٰةَ vs الصلاة). Source: quran.com API v4
word-by-word (canonical word IDs).

## Repo layout

- `backend/` — FastAPI app: `app/asr` (engines), `app/audio` (VAD), `app/engine`
  (aligner/detector/events), `app/mutashabeh` (relocation index), `app/ws`
  (session WS: caps, resume), `scripts/` (data loaders, bench, ws test client)
- `frontend/` — Vite + React + TS SPA
- `deploy/` — docker-compose (db + backend + web), TLS nginx config, ops cron
- `docs/` — FYP documentation

## Local development

```bash
cd deploy && docker compose up -d db          # Postgres on 127.0.0.1:19832
cd ../backend && python3 -m venv .venv && .venv/bin/pip install -e ".[asr,dev]"
.venv/bin/python -m scripts.load_quran        # one-time: Quran data (verifies itself)
.venv/bin/python -m scripts.build_mutashabeh  # one-time: twin-pair table
# models: download CT2 whisper into backend/models/ (see scripts/bench_asr.py MODELS)
.venv/bin/uvicorn app.main:app --port 8000
cd ../frontend && npm install && npm run dev  # SPA on :5173, proxies /api + /ws
```

Tests: `cd backend && .venv/bin/python -m pytest` (15 hard-case fixtures: repetition,
basmalah/isti'adha, Ar-Rahman refrain, garbled tokens, jump confirm/revoke, …).

End-to-end without a mic: `python -m scripts.ws_client eval/audio/fatiha_full.wav 1`
streams a WAV through the full WS pipeline at real-time pace.

## Production deploy (this VPS)

```bash
cd deploy && docker compose build && docker compose up -d
# edge: add `reciteiq.wiserhelpdesk.com 127.0.0.1:19843;` to the SNI map in
# /etc/nginx-edge/dev/nginx.conf, then `docker restart vps_dev_nginx_edge`
# (restart, NOT reload — single-file bind mount pins the inode)
cp deploy/reciteiq.cron /etc/cron.d/reciteiq   # nightly backup + event retention
```

Fresh database bootstrap: `docker compose run --rm backend python -m scripts.load_quran`
then `… python -m scripts.build_mutashabeh` (migrations run automatically at boot).

## Operational guarantees

- **Privacy**: audio is processed in memory only, never written to disk; only
  text events persist. Anonymous session events purge after 30 days.
- **Abuse**: 3 concurrent sessions (friendly "busy" beyond), 2/IP, ingest rate
  capped at 1.1× real-time, idle/duration timeouts, Origin allowlist.
- **Resume**: clients reconnect and echo their last confirmed position; the
  tracker rehydrates in place.
- **Resource budget**: backend ≤1.5GB (model warm), Postgres ≤512MB, web ≤128MB;
  ASR threads pinned (2 threads × 2 workers) for the shared 6-core box.

## Measured (Phase gates)

- ASR: tarteel whisper-base CT2 int8 — RTF 0.45 solo, p95 segment latency ~2.7s
  at 3 concurrent sessions; 100% token accuracy on clean qari clips.
- Detection (live WS, qari audio): clean recitation → 0 false events; skipped
  ayah → exactly one MISSED_AYAH; Fatiha→Ikhlas drift → MUTASHABEH_JUMP
  confirmed with correct destination (112:1).
- Auto-detect (live WS): Fatiha from cold start → locked 1:2 after the
  basmalah (score 0.8), then a clean 0-false-event session; auto-detect
  composes with jump detection in the same session.
- Known tuning item: a reciter who *continues* in the jump destination re-alerts
  every ~2 segments — dedup window is a Phase-6 threshold decision.

## v2 roadmap (designed-for, not built)

Auth (user_id columns ready) · progress dashboards · GPU/cloud ASR via the
`ASREngine` interface · Tajweed analysis · amateur-voice eval corpus.
