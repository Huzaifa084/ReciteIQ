# ReciteIQ — As-Built Audit

**Read-only audit. Nothing was modified.**
Verified against the repository, the running production container, and the live database — not against previous plans.

| | |
|---|---|
| HEAD | `15e7840` |
| Branch | `main` — **55 commits unpushed** |
| Tests | 115 passing (`.venv/bin/python -m pytest tests` from `backend/`) |
| Backend | 3,710 LOC |
| Frontend | 2,047 LOC |

**Verdict at a glance**

| Critical blockers | Important issues | Production path | Concurrent users | Tests on frozen path |
|---|---|---|---|---|
| **5** (2 affect learner feedback) | **9** | Live — `fastconformer` + text tracker | **2** (global, not per-user) | **41 of 115** (36%) |

---

## 1. Architecture as built

One FastAPI process holds the API, the WebSocket session layer, and the recogniser in-process. There is no separate AI service and no Node.js layer — the FYP document still describes both.

### Runtime flow — microphone to UI

| Stage | Where | What happens |
|---|---|---|
| 1 | Browser (SPA) | **AudioWorklet capture** — `recorder.ts`, device rate → linear resample to 16 kHz mono s16le. WebRTC processing **on** by default; `?rawaudio=1` disables it (undocumented debug flag, live in production). |
| 2 | Transport | **WebSocket, binary frames** — `/ws/session/{id}` via nginx (`proxy_read_timeout 180s`). No authentication. Origin allowlist only, and it passes when the Origin header is absent. |
| 3 | Backend — admit | **Admission control** — `SessionRegistry.try_admit`: global cap 3, per-IP cap 2, ingest rate ≤ 1.1× real time, idle 120 s, max 90 min. |
| 4 | Backend — VAD | **Silero VAD segmentation** — `vad.py StreamSegmenter`. Closes on 0.5 s silence or a 25 s cap. A capped cut prefers a quiet point within 3 s (`max_smart`); otherwise a hard cut (`max_hard`) replaying 1.5 s overlap. Between closes, a `buffering` frame goes out at most once a second. |
| 5 | Backend — ASR | **NeMo FastConformer** — `asr/fastconformer.py`. Segment written to a temp WAV inside `TemporaryDirectory`, deleted on exit. Serialised behind an `asyncio.Lock`; a `Semaphore(8)` sheds when full. ~3 s per 25 s window warm. |
| 6 | Backend — match | **Normalise → align** — `nlp/normalize.py` strips diacritics to Imlaei; `aligner.find_match` does a rapidfuzz window search: 12 words forward, 8 back, accept at ratio ≥ 78. |
| 7 | Backend — detect | **RecitationTracker state machine** — `engine/detector.py` (579 LOC): segment pre-pass, multi-word unit merge, gap attribution, rewind/repeat guard, 3-gram relocation for jumps. Emits WORD_OK / MISSED_WORD / MISSED_AYAH / REPEAT / MUTASHABEH_JUMP / UNCERTAIN / POSITION. |
| 8 | Backend — persist | **Events → Postgres, summary on end** — `session_events` (POSITION excluded), then `session_summaries` written by the live finaliser. Audio never reaches the database or disk outside the temp file. |
| 9 | Browser — render | **Reducer → Mushaf colouring** — `state/reducer.ts` applies the provisional/confirmed/revoked lifecycle per word idx; `MushafView` paints ok / uncertain / missed-provisional / missed / current. |

### Engines present, and which one runs

| Engine | File | Status | Notes |
|---|---|---|---|
| **fastconformer** | `asr/fastconformer.py` | **production** | NeMo RNN-T/CTC hybrid, Quran-fine-tuned. Verified live. |
| whisper_local | `asr/whisper_local.py` | rollback | faster-whisper CT2. Present in the same image — rollback needs no rebuild. |
| cloud | `asr/cloud.py` | unused | Groq. Key is injected into production even though the engine is not selected. |
| phoneme CTC | `asr/phoneme_ctc.py` | frozen | Reached only when `tracker_mode=phoneme`. 1,020 LOC across four modules. |

### Database, as it actually stands

| Table | Rows | Read at runtime? | Notes |
|---|---:|---|---|
| `words` | 77,429 | yes | Dual-script. Source for reference + relocation index. |
| `ayahs` | 6,236 | yes | All 114 surahs loaded. |
| `surahs` | 114 | yes | |
| `session_events` | 3,138 | yes | Retention job is **not installed** — see S-3. |
| `session_summaries` | 129 | yes | |
| `sessions` | 168 | yes | |
| `mutashabeh_pairs` | 16,844 | **never** | **Dead data.** Zero reads in `app/`. Jumps use the in-memory 3-gram index instead. |
| `ayah_phoneme_refs` | 162 | frozen path | Phoneme rollback only. |

Alembic head `c3f9a2e64d17` matches the live database. No pending migrations.

---

## 2. Feature inventory

"Implemented" means the full path is wired from UI to backend and back, and I saw it work. Where I could not confirm the end-to-end path, it says so.

| Capability | Status | Evidence | Tests | Prod verified |
|---|---|---|---|---|
| Just Recite / auto-detect | partial | `locate.py`, `Home.tsx:70`, `session.py:299` | test_locate (8, synthetic) | **not verified** |
| Guided surah selection | yes | `Home.tsx`, `/api/surahs` | — | yes |
| Surah/ayah positioning | yes | `load_reference(start_ayah)` | indirect | yes |
| Live word tracking | yes | `detector.py`, `MushafView.tsx` | 19 + 9 | yes |
| Correct-word detection | yes | `_advance` → WORD_OK | sweep: 77,429/77,429 | yes |
| Missed-word detection | yes | `_emit_gap`, `_unattributed` | sweep: 104/104 surahs | yes |
| Missed-ayah detection | partial | `_emit_gap` whole-ayah branch | sweep: **61/104 (58.7%)** | yes |
| Repeat / restart | partial | `_rewind` + overlap guard | sweep: 90/104 (86.5%) | yes |
| Mutashabeh jump | partial | `_check_relocation` + ngram index | fires, but noisy (B-9) | **not verified** |
| Uncertain / no-match | yes | UNCERTAIN event, `no_match` frame | 1 test | yes |
| Provisional/confirmed/revoked | yes | `_PendingMiss`, `reducer.ts` | several | yes |
| Session summary | **wrong math** | `Summary.tsx:61` — see B-2 | 5 (counts only) | **defect** |
| Accuracy / statistics | **unsound** | `pct = ok/(ok+missed)` | none | **defect** |
| Quran search | **not implemented** | No endpoint. Home has a client-side surah-name filter only. | — | — |
| All-surah support | yes | `sweep_all_surahs.py` | 1 whole-Quran test | clean recitation only |
| Browser audio handling | yes | `recorder.ts` AudioWorklet | none | yes |
| Reconnect / resume | **lossy** | `client.ts:79` — see B-4 | none | **defect** |
| Concurrent sessions | **capped at 2** | `ws.client.host` — see B-3 | script only | **defect** |
| Error recovery | **absent** | only `WebSocketDisconnect` handled | none | not verified |
| Accounts / progress | **not implemented** | No auth, no user table use. | — | — |

---

## 3. Bugs and technical risks

> **My error — introduced during the production flip.**
> B-1 below is a live API key that I committed while backing up the environment file. It has not been pushed. Please treat it as the first thing to fix.

### B-1 — Live Groq API key committed to git history · **CRITICAL**

- **Evidence** — `deploy/.env.bak-preflip` is tracked, added in commit `96a2559`. `.gitignore` excludes `.env` but not `.env.bak-*`. Remote is a **public GitHub repo**; `origin/main` is at `f3b1793`, so the commit is **local only — 55 commits unpushed**.
- **Impact** — A single `git push` publishes a working key. Not yet exposed.
- **Fix** — Rotate the key at Groq regardless. Remove the file, extend `.gitignore` to `.env*`, rewrite the commit before any push.
- **Complexity** — Low, but must precede the next push.
- **Tests** — Pre-commit secret scan, or CI grep for `gsk_`.

### B-2 — Summary reports 100% accuracy when whole ayahs were skipped · **CRITICAL**

- **Evidence** — `Summary.tsx:61`: `attempted = words_ok + words_missed`. Words inside a skipped ayah are aggregated into `MISSED_AYAH` and never counted in `words_missed`, so they leave the denominator entirely. Confirmed against the live database:

  ```
  surah  words_ok  words_missed  ayahs_missed   UI shows
      1         9             0             3       100%
  ```

- **Impact** — A learner who skipped three ayahs of Al-Fatihah is told they were **100% accurate**. This is the false-"correct" class ranked highest — it actively teaches the wrong thing.
- **Fix** — Denominator should be reference words covered (`words_ok + words_missed + Σ words of missed ayahs`), computed backend-side and returned in the summary rather than derived in the UI.
- **Complexity** — Low. One backend field, one UI line.
- **Tests** — Assert accuracy < 100% for the skipped-ayah fixture; a summary-math unit test with a skipped ayah.

### B-3 — Per-IP limit collapses to the nginx container; the site serves 2 users total · **CRITICAL**

- **Evidence** — `session.py:232` uses `ws.client.host`. uvicorn runs without `--proxy-headers`, and nginx does not rewrite the peer address for WebSocket. Every connection in the production log arrives as `172.24.0.4`, which is `reciteiq-web-1`:

  ```
  INFO: 172.24.0.4:54406 - "WebSocket /ws/session/993de95b…" [accepted]
  INFO: 172.24.0.4:52956 - "WebSocket /ws/session/1d52a537…" [accepted]
  ```

  So `max_sessions_per_ip = 2` is a **global** cap and `max_concurrent_sessions = 3` can never bind.
- **Impact** — The third visitor anywhere in the world is rejected, with the misleading message "too many sessions from this address". Fatal for a demo or viva.
- **Fix** — Trust `X-Forwarded-For` from the known proxy (uvicorn `--proxy-headers --forwarded-allow-ips`, or read the header explicitly in the WS handler), and re-tune the two caps against measured memory.
- **Complexity** — Low to implement; needs a concurrency re-measure afterwards.
- **Tests** — Two sessions from distinct `X-Forwarded-For` values must both be admitted.

### B-4 — Reconnect silently discards everything counted before the drop · **HIGH**

- **Evidence** — On disconnect, `finally: registry.release(...)` runs but `_finalize` does not (`finalize` is False). On reconnect a **new** `LiveSession` is constructed — fresh `counts`, fresh `_ok_idx`, fresh `matched`. The `resume` control only moves the pointer.
- **Impact** — Any dropped connection — and one was observed in production — makes the final summary count only the words recited after the reconnect. The learner sees a worse result than they earned, with no sign anything happened.
- **Fix** — Keep the `LiveSession` in the registry for a grace period keyed by session id and re-attach on reconnect, or rehydrate counts from persisted `session_events`.
- **Complexity** — Medium — session lifecycle change.
- **Tests** — E2E: stream, force-close mid-session, reconnect, finish; assert the summary covers both halves.

### B-5 — Any unexpected exception kills the session with no summary · **HIGH**

- **Evidence** — The WS loop handles only `asyncio.TimeoutError` and `WebSocketDisconnect`. An ASR failure, a DB error, or `json.loads` on a malformed control message propagates out; the `finally` releases the slot but `finalize` stays False, so the row is left `active` and no summary is written.
- **Impact** — Recitation is lost with no explanation, and the session row leaks in an `active` state.
- **Fix** — Wrap per-window processing in `try/except Exception`: log, notify the client, keep the session alive if possible, and always finalise on exit.
- **Complexity** — Low.
- **Tests** — Inject a raising engine; assert the session ends cleanly with a summary.

### B-6 — Gated windows are dropped silently and can surface as false misses · **MEDIUM**

- **Evidence** — `session.py`: `if tr.gated: continue`. FastConformer sets `gated` when the segment is shorter than `asr_min_segment_sec` or the queue is full. The audio is never transcribed and the tracker never learns those words were spoken.
- **Impact** — A dropped window becomes a gap the next window has to explain, which can confirm a `MISSED_WORD` the reciter never made. Shedding is currently unreachable in practice (queue 8 vs 3 sessions), so today only the very-short-segment path fires — but the mechanism is a false-"missed" source under load.
- **Fix** — Treat a gated window as an explicit uncertainty signal, not silence: emit `UNCERTAIN` for the span or suppress miss confirmation across it. Also align `asr_queue_max` with the real session cap.
- **Complexity** — Medium — touches the confirmation rule.
- **Tests** — Force a gated window mid-recitation; assert no `MISSED_WORD` is confirmed.

### B-7 — SPA ignores connection state entirely · **MEDIUM**

- **Evidence** — `Recite.tsx:95`: `onStatusChange: () => {}`. The socket reconnects up to five times with backoff and then gives up; none of that reaches the UI, which keeps showing "listening".
- **Impact** — The user recites into a dead socket and only discovers it at the summary. Compounds B-4.
- **Fix** — Surface connecting / reconnecting / lost states in the status pill; stop the recorder and prompt when attempts are exhausted.
- **Complexity** — Low.
- **Tests** — Component test on status→pill mapping.

### B-8 — Clean recitation can display "0 things to review below" · **MEDIUM**

- **Evidence** — `clean` requires `uncertain === 0`, but `issues = words_missed + ayahs_missed + jumps` excludes uncertain. A near-miss ASR word therefore blocks the "flawless" message while leaving the count at zero. Live rows for surah 84 show exactly this state (`uncertain: 1`, all error counts 0).
- **Impact** — Confusing, self-contradicting summary on an otherwise perfect recitation.
- **Fix** — Give uncertain its own sentence ("one word we couldn't confirm") rather than folding it into the flawless test.
- **Complexity** — Low.
- **Tests** — Snapshot with `uncertain=1` and no errors.

### B-9 — Mutashabeh jumps fire in volume on a single skip · **MEDIUM**

- **Evidence** — Measured during this audit: one skipped ayah in Al-Baqarah produced **58 confirmed MUTASHABEH_JUMP events**; across 104 surahs with one injected skip each, 238–381 jump events total. `_check_relocation` proposes but never repositions, so the pointer can stay lost while jumps keep firing.
- **Impact** — The jump banner would flap repeatedly, and the summary error list would fill with jumps the reciter never made — false feedback.
- **Fix** — Rate-limit jump confirmation per session, and require the destination to be corroborated by continued forward recitation before surfacing it.
- **Complexity** — Medium.
- **Tests** — Assert at most one confirmed jump per divergence.

### B-10 — Admission race; global cap can be exceeded · **LOW**

- **Evidence** — `try_admit` checks `len(self.active)` under the lock, but `registry.active[session_id] = live` happens *outside* it. Concurrent connects can all pass the check before any insert lands.
- **Impact** — More concurrent sessions than the memory budget assumes; a duplicate session id also orphans one `LiveSession`.
- **Fix** — Reserve the slot inside the same lock that admits it.
- **Complexity** — Low. **Tests** — Concurrent admit test.

### B-11 — Dead code, dead data, stale contracts · **LOW**

- `mutashabeh_pairs` — 16,844 rows, zero reads in `app/`. The model class exists solely as a definition.
- SPA sends `client_info` on every connect; only `phoneme_session.py` (frozen) handles it.
- `settings.pause_grace_sec` and `settings.anonymous_events_retention_days` — **zero** usages, yet both are documented behaviour.
- 1,020 LOC of frozen phoneme modules plus a 1.6 GB `phoneme_lab/` working directory.
- `session.py` and `phoneme_session.py` duplicate the WS loop (861 LOC combined).

**Impact** — Misleads the next reader about what is live; the two unused settings make documented features look implemented. **Fix** — Delete or clearly quarantine; drop the settings that do nothing.

### B-12 — Structural limit: skipped ayahs longer than the alignment window · **KNOWN**

- **Evidence** — `align_window_fwd = 12`; only **42 of 114** surahs have every ayah inside that window (Al-Baqarah 282 is 128 words). Without the relocation index Surah 2 stops dead at word 2,550 of 6,116.
- **Impact** — Ayah-level recovery ~85% on long surahs. Word-level detection unaffected. All six gate surahs are inside the safe 42.
- **Fix** — Documented, not scheduled. Two attempts were measured and reverted — see `docs/scope-whole-quran.md`.
- **Complexity** — High. **Tests** — `sweep_errors.py` already measures it.

---

## 4. Test audit

The count is real. The suite was run during this audit: **115 passed** in 82 s. Authoritative command, from `backend/`:

```bash
.venv/bin/python -m pytest tests -q     # testpaths=tests, asyncio_mode=auto
```

### Composition

| File | Tests | Type | Exercises |
|---|---:|---|---|
| `test_detector.py` | 19 | unit, synthetic tokens | **production** |
| `test_long_segment.py` | 9 | unit + whole-Quran sweep | **production** |
| `test_segmentation_carry.py` | 12 | unit, synthetic audio | mixed |
| `test_locate.py` | 8 | unit, synthetic | **production** |
| `test_summary_categories.py` | 5 | unit + DB round-trip | **production** |
| `test_fastconformer_contract.py` | 5 | **mocked** — `_FakeModel` | wrapper only |
| `test_engine_segmentation.py` | 4 | config unit | **production** |
| `test_session_finalize.py` | 4 | integration, DB | mixed |
| `test_segmenter_instrumentation.py` | 3 | unit | **production** |
| `test_phoneme_tracker.py` | 17 | unit | frozen |
| `test_fatiha_anchor.py` | 7 | unit | frozen |
| `test_partial_coverage.py` | 7 | unit | frozen |
| `test_phoneme_multi_ref.py` | 6 | unit | frozen |
| `test_phoneme_variable_length.py` | 4 | unit | frozen |

### What has no test at all

- **The production WebSocket loop.** No test imports `session_ws`. Admission control, the ingest rate cap, idle timeout, gated-window handling, the `buffering` and `no_match` frames, reconnect and resume are *entirely untested* — and three of the critical findings live in exactly that file.
- **The summary accuracy math** (B-2). The five summary tests check category counts, never the percentage the learner reads.
- **The real ASR.** `test_fastconformer_contract.py` substitutes a fake model, so NeMo itself is never exercised by `pytest`.
- **The frontend.** Zero tests — no reducer test, no component test, no typecheck in CI.

### Assertions that can pass while the feature is broken

- The clean-recitation gate asserts "no false errors", which stays true when a window is *silently dropped* (B-6) — nothing asserts that all spoken words were seen.
- `sweep_errors.py` counts *any* MUTASHABEH_JUMP as a successful catch, which is why 381 spurious jumps still scored as 91% detection. The metric flatters the noisier behaviour; B-9 was invisible to it.

### Fixture trustworthiness

The deliberate-error clips are now sound — `mk_errors2.py` aligns against reference units split into constituent tokens and records the exact word removed. The *original* generator was not: it normalised with a mangled regex, recorded `removed_words: ['']`, and its Al-Kafirun clip cut an unknown word, so the gate built on it proved nothing. **Any result quoted from before that rebuild should be discarded.**

**Scripts are evidence, not tests.** `sweep_all_surahs.py`, `sweep_errors.py`, `release_regression.py`, `staging_smoke.py` and `staging_concurrency.py` produced most of the numbers in this audit, but none run under `pytest` and none are in CI. They will rot silently.

---

## 5. Production verification

Read from the running container and the live database. Nothing was changed.

| Property | Repository | Live production | |
|---|---|---|---|
| ASR engine | `fastconformer` (default) | `fastconformer` | match |
| Tracker | `whisper` (text) | `whisper` | match |
| Segmentation | engine-selected | 25.0 s / 0.5 s cut / 1.5 s overlap | match |
| Match threshold | 78 | 78 | match |
| Image | `Dockerfile.fastconformer` | `reciteiq-backend`, built 07:16 UTC 05 Sep | match |
| Memory limit | 2560m | 2,684,354,560 B | match |
| Steady memory | — | ~1.6 GiB | ok |
| Concurrency caps | 3 global / 2 per IP | **effective: 2 total** | **B-3** |
| Origins | env-set | `["https://reciteiq.wiserhelpdesk.com"]` | match |
| Groq key | should be absent | **injected, engine unused** | **S-2** |
| Alembic | `c3f9a2e64d17` | `c3f9a2e64d17` | match |
| Healthcheck | `/healthz`, 240 s start | healthy | ok |
| Retention cron | `deploy/reciteiq.cron` | **`/etc/cron.d/reciteiq` absent** | **S-3** |
| Staging | compose file present | stopped | intended |

**Rollback** is genuine and better than documented: the production image carries `faster-whisper` and NeMo together, so switching to the phoneme path is two lines in `deploy/.env` with no rebuild. Both imports were verified inside the running container. The migration only adds columns with defaults, so no downgrade is needed.

**Logging** is a genuine strength — every window emits a structured record with duration, cut reason, inference ms, token rate, pointer, event types, and audio level. That is what made this audit possible.

---

## 6. Documentation consistency

Listed, not corrected.

| Location | Claim | Reality |
|---|---|---|
| `README.md:63` | "Quran-fine-tuned Whisper (int8 on CPU, ~0.45× realtime)" as the ML layer | Production is FastConformer at ~0.12 RTF. Stale. |
| `README.md:97` | "place a CT2 Whisper model in backend/models/" | Quick-start no longer matches the shipped engine. |
| `README.md:114` | Groq key export in setup instructions | Encourages the pattern that produced B-1. |
| FYP §110, §133 | "Web Speech / browser microphone input" | AudioWorklet + raw PCM over WebSocket. Web Speech is not used anywhere. |
| FYP §516 | Class diagram lists "SessionController, WebSocketGateway, UserService in the Node.js layer" | No Node.js layer exists. Also names `UserService` — there is no auth or user model. |
| FYP §132–134 | Scope = three detections (missed ayah, missed word, jump) | Under-states delivery: repeat and uncertain are also implemented and surfaced. |
| FYP §320 | "Levenstein-style alignment" | rapidfuzz ratio within a bounded pointer window — related but not plain edit distance. |
| `docs/gate-release.md` | Records 7/7 post-flip | Accurate, including the honest 6/7 note over the public URL. |
| Code comment, `_check_relocation` | Design note implies pause-awareness via `pause_grace_sec` | Setting has zero usages. |

---

## 7. Security and privacy

### S-1 — Committed API key · **BLOCKS DEMO**
See B-1. Public remote, unpushed. Rotate and purge before any push.

### S-2 — Unused Groq key injected into the production container · **MEDIUM**
Present in the environment and readable via `docker inspect` though `asr_engine=fastconformer`. Remove it until the cloud engine is actually selected.

### S-3 — Stated 30-day retention is not enforced · **MEDIUM**
`/etc/cron.d/reciteiq` is not installed and `anonymous_events_retention_days` has no code path. Transcribed recitation text in `session_events` accumulates indefinitely — 3,138 rows today. The privacy posture is documented but not implemented.

### S-4 — No authentication anywhere · **MEDIUM**
Anyone can `POST /api/sessions` and open a WebSocket. `_origin_allowed` returns **true when the Origin header is absent**, so non-browser clients bypass it entirely — that is how the audit scripts connect. The only protection is the caps, which B-3 shows are misconfigured. On a public URL this is an unauthenticated CPU-bound compute endpoint.

### S-5 — Debug flag live in production · **LOW**
`?rawaudio=1` changes microphone constraints on the public site. Harmless but undocumented and unbounded.

### Verified good

- **Audio is not persisted.** The only disk write is a temp WAV inside a `TemporaryDirectory` removed on exit; nothing else writes audio. Confirmed by grep across `app/`.
- **Logs carry no audio** — only levels, counts and token statistics.
- FastAPI docs endpoints are disabled (`docs_url=None, redoc_url=None`).
- CORS is restricted to the production origin and does not enable credentials.
- Database credentials are container-internal; Postgres is bound to loopback only.

---

## 8. UX and functional

- **False 100% accuracy** (B-2) — the single most damaging user-visible defect.
- **"0 things to review below"** (B-8) on an otherwise clean recitation.
- **No connection feedback** (B-7) — reconnects and give-up are invisible.
- **Up to 28 s before anything changes on screen.** A consequence of the 25 s window; for Al-Kafirun the whole surah is one window. Mitigated by the `buffering` heartbeat ("hearing you · 12s") but the Mushaf itself stays static.
- **Backend and frontend disagree after a reconnect** — the SPA keeps its accumulated word colours, the backend does not (B-4), so the screen and the summary tell different stories.
- **Revoked events are handled correctly** in the reducer — provisional misses clear on recovery and on REPEAT. This part is sound.
- **Empty-session state is handled** — "No recitation captured" rather than a false flawless.
- **Not verified:** mobile browsers, iOS Safari AudioWorklet behaviour, and the jump-accept flow (`JumpBanner` → reposition).

---

## 9. Component maturity

| Component | Classification | Basis |
|---|---|---|
| ASR (FastConformer) | **production-ready** | WER 0.0443; preserves spoken errors; stable memory and latency in the live container. |
| VAD / segmentation | **production-ready** | Smart-cut and overlap behaviour measured; instrumented per window. |
| Aligner + word detection | **production-ready** | 77,429/77,429 words on perfect input; 100% of injected word errors across 104 surahs. |
| Ayah-level detection | needs hardening | **58.7%** across surahs; structurally bounded by the 12-word window. |
| Mutashabeh detection | prototype | Fires, but 58 events for one skip. Never verified end-to-end in the UI. |
| Session lifecycle / WS | needs hardening | No error recovery, lossy reconnect, admission race, zero tests. |
| Summary & statistics | **broken** | Reports 100% accuracy for a recitation that skipped three ayahs. |
| Frontend tracking UI | needs hardening | Event lifecycle correct; connection state and summary copy are not. |
| Auto-detect | prototype | Implemented and unit-tested; never verified end-to-end on real audio. |
| Deployment / rollback | **production-ready** | Single image both engines, verified; healthcheck, limits, documented runbook. |
| Observability | **production-ready** | Structured per-window diagnostics. |
| Quran search | not implemented | No endpoint exists. |
| Accounts / progress | not implemented | No auth, no user model in use. |
| Phoneme path | frozen | Reachable by config, 1,020 LOC, 41 tests, no longer developed. |

---

## 10. Action plan

### A · Critical blockers — before calling this production or FYP-ready

| # | Problem | Impact | Fix | Effort | Tests needed |
|---|---|---|---|---|---|
| B-1 | Live API key in git history | One push publishes it | Rotate, purge, `.gitignore .env*` | 1 h | CI secret scan |
| B-2 | 100% accuracy despite skipped ayahs | Teaches a learner the wrong thing | Backend-computed denominator incl. missed-ayah words | 2 h | Summary math unit + gate assertion |
| B-3 | Site serves 2 concurrent users total | Third visitor rejected — fails a viva | Trust `X-Forwarded-For`; re-tune caps | 2 h | Two distinct forwarded IPs admitted |
| B-4 | Reconnect discards prior counts | Summary undercounts after any drop | Re-attach LiveSession, or rehydrate from events | 1 d | E2E drop-and-resume |
| B-5 | Any exception kills the session silently | Recitation lost, row stuck active | Per-window try/except; always finalise | 3 h | Raising-engine test |

### B · Important — soon

| # | Problem | Impact | Fix | Effort |
|---|---|---|---|---|
| B-6 | Gated windows dropped silently | False "missed" under load | Emit uncertainty; suppress confirmation across the gap | 4 h |
| B-9 | 58 jump events for one skip | False jump feedback | Rate-limit + corroborate destination | 1 d |
| B-7 | No connection feedback | User recites into a dead socket | Wire `onStatusChange` to the pill | 2 h |
| B-8 | "0 things to review" | Self-contradicting summary | Separate uncertain from the flawless test | 1 h |
| S-3 | Retention not enforced | Documented privacy claim unmet | Install cron, or implement in-app | 1 h |
| S-2 | Unused key in container | Needless exposure | Drop from compose until cloud is used | 15 m |
| T-1 | WS loop has zero tests | Three criticals live there | Integration tests with a fake engine | 1–2 d |
| T-2 | Sweeps/regression outside pytest | Evidence will rot | Wrap as marked slow tests; run in CI | 4 h |
| B-10 | Admission race | Cap can be exceeded | Reserve inside the lock | 1 h |

### C · Product improvements

- **Cut the 28 s feedback wait** — decode a partial window for provisional display while the full window stays authoritative. The single biggest perceived-quality win.
- **Verify auto-detect on real audio** and surface its confidence; it is unproven end-to-end.
- **Word-level missed-word UX** — tap a flagged word to hear the reference and see the ayah in context.
- **Quran search** — currently absent; a text search over `words` is straightforward given the schema.
- **Real accuracy statistics** once B-2 is fixed: per-session and per-surah history.

### D · Nice to have

- Retire the phoneme path once FastConformer has real-user runtime — recovers 1,020 LOC, 41 tests and 1.6 GB.
- Drop `mutashabeh_pairs` or start using it to improve jump precision.
- Long-distance skipped-ayah recovery (B-12) — high effort, two failed attempts documented.
- Accounts and progress dashboards; Tajweed feedback; mobile verification.

---

## Current ReciteIQ status

**What is actually built.** A working real-time Quran recitation tracker, live at `reciteiq.wiserhelpdesk.com` on a Quran-fine-tuned FastConformer feeding a text-based alignment and detection engine. Recognition, segmentation and *word-level* detection are genuinely production-grade: every word of all 114 surahs is credited on perfect input with no false events, and 100% of injected skipped and substituted words are caught across 104 surahs. Deployment, rollback and observability are solid.

**What is partially built.** Ayah-level detection works but is structurally capped at ~85% on long surahs. Mutashabeh detection fires but floods. Auto-detect is implemented and unit-tested but never proven on real audio. The session lifecycle — reconnect, error recovery, admission — is the weakest area and has no test coverage at all.

**What is missing.** Quran search, accounts and progress statistics. And the summary, which is the screen a learner actually judges themselves by, currently computes accuracy in a way that reports 100% for a recitation that skipped three ayahs.

**What I recommend next.** Do not start a new feature phase. Spend roughly one focused week on section A: rotate and purge the key, fix the accuracy math, fix the per-IP cap so more than two people can use the site, make reconnect non-lossy, and add error recovery. Those five changes are what separate "an impressive demo that works when one person uses it carefully" from something you can put in front of a panel or a class. Then add the WebSocket integration tests, because three of the five criticals live in the one file nothing tests — and only then return to features.

---

## Addendum — post-remediation (same day)

Every P0 finding above has been fixed and verified; see the commits from `0567d76`
onward. Two figures in the audit itself needed correcting, both because a metric
was too generous:

**Skipped-ayah detection is 58.7%, not 84.6%.** `sweep_errors.py` counted *any*
MUTASHABEH_JUMP as a successful catch. Requiring the event to name the right
ayah removes the difference entirely — of 380 jump events across 104
single-skip clips, **not one** pointed at the correct place. All 61 genuine
catches come from `MISSED_AYAH`; the jump mechanism contributed nothing to local
skips but noise.

**The jump flood is fixed, and it was worse than a duplicate problem.** Deduping
by destination left 380 events because the index proposes a new destination as
the pointer wanders. Allowing only one outstanding jump at a time — matching the
single banner the UI shows — takes it to **34**, with detection rates unchanged.

**B-3 could not be fixed the way the audit proposed.** The public edge is an SNI
*stream* proxy with no PROXY protocol, so the real client address never reaches
this stack; setting `X-Forwarded-For` from `$remote_addr` would only have
collapsed the bucket to a different constant. The global cap is now the binding
control (6, from the measured memory and duty-cycle figures) and per-IP is
looser at 3 so it cannot silently become a global cap again. Restoring true
per-user limiting requires PROXY protocol on the shared edge — outside this
app's blast radius, and left as a documented follow-up.

**S-3 was worse than "not enforced".** The first run of the in-app retention
sweep deleted **1,108** event rows, which is the measure of how long the
uninstalled cron had not been running.

### Post-remediation verification (production, live)

| check | result |
|---|---|
| `pytest tests` | **144 passed** (was 115) |
| `release_regression.py` against the public URL | **7/7 pass** |
| concurrency, 1 / 2 / 3 sessions from one client | **3/3 admitted**, 0 rejected — was 2 then rejected |
| memory, 1 / 2 / 3 sessions | 1.677 / 1.678 / 1.679 GiB of 2.5 GiB |
| accuracy on a skipped-ayah session | **93%** — the same case previously displayed 100% |
| retention sweep, first run | 1,108 rows deleted |
| jump events, 104 single-skip clips | 380 → **34** |
| Groq key in the production container | `''` |
| key in git history | purged; scanner refuses a re-entry |

Still open, and deliberately so: **rotating the Groq key** needs the account
owner, and **true per-user rate limiting** needs PROXY protocol on the shared
edge, which is outside this application's blast radius.
