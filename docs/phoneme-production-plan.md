# ReciteIQ — Production Plan for the Phoneme (encoder-CTC) Tracker

**Production path: `RECITEIQ_TRACKER_MODE=phoneme`** (set in `deploy/.env`).

Every change below targets the modules that path actually executes:
`app/ws/phoneme_session.py`, `app/engine/phoneme_tracker.py`,
`app/engine/phoneme_index.py`, `app/asr/phoneme_ctc.py`, `app/db/repo.py`,
`scripts/build_phoneme_refs.py`, `frontend/src/audio/recorder.ts`, and the SPA
word-state layer.

The Whisper path (`app/ws/session.py`, `engine/aligner.py`, `engine/detector.py`,
`nlp/normalize.py`, `asr/base.py`, `asr/cloud.py`, `mutashabeh/index.py`) is
**out of scope**. It is not in the request path when `tracker_mode=phoneme`, so
work there ships no user-visible change. It stays in the tree as a fallback.

Pilot scope: **Surahs 1, 109, 111, 112, 113** (+ **67** optional).
Stress-test-only: **55** (see §6.3).

---

## 1. Do not redo this — already fixed or already correct

Verified against the code on 2026-09-04. Spending effort here is waste.

| Item | Status |
|---|---|
| **One-ayah-per-window false MISSED_AYAH** | **FIXED** (commit `41f6b85`). `PhonemeTracker.feed()` now runs an anchored best-chain search (`_chain` + `_best_span`) and credits every ayah a window covers. Measured on the live socket: `fatiha_full.wav` went 20/29 words + 3 false MISSED_AYAH → **29/29 words, 0 false events**; `fatiha_skip3.wav` still reports exactly one MISSED_AYAH at ayah 3. Do not re-architect windowing to "fix" this. |
| **Canonical normalization preserving ص/س, ط/ت, ظ/ذ, ق/ك, ح/ه** | **ALREADY CORRECT.** `nlp/normalize.py` only strips diacritics/tatweel and harmonizes alef, ya, waw-hamza and ta-marbuta variants. Those consonant pairs were never merged. (Also: normalize.py is not even in the phoneme path — the phoneme tracker compares integer IDs, not text.) |
| **Removing the "upcoming ayah" ASR prompt** | **ALREADY DONE.** `asr/cloud.py:25` documents that a Quranic-context prompt was tried and removed because whisper-large-v3 echoes it back on short/quiet segments. |
| **Provisional → confirmed → revoked lifecycle** | **ALREADY EXISTS.** `EventState` has `PROVISIONAL`/`CONFIRMED`/`REVOKED`, and `MUTASHABEH_JUMP` already flows through all three (`_check_jump`/`_clear_jump`). **Do not add a `MUTASHABEH_PROVISIONAL` event type** — reuse the state. |
| **Groq as primary ASR** | **REJECTED — evidence says no.** Commit `d66b391` is "keep local Quran-tuned model as default after A/B testing Groq"; `deploy/.env` records that Groq "drifts on Quranic spelling and hallucinates on short openings". Groq is also irrelevant here: the phoneme path uses `phoneme_ctc.py` and never calls an ASR engine. Local CTC stays primary. |
| **8s overlapping windows replacing VAD smart cuts** | **REJECTED pending evidence.** Commit `be3264c` deliberately introduced smart cuts at quiet points to stop mid-word slicing. Overlap would reinstate that and add a dedup layer to clean up after it. Task **P1-7** instruments the current segmenter so this can be decided on data. |

**Correction to a stated premise:** there is **no existing `UNCERTAIN` event**. `EventType`
is `WORD_OK, MISSED_WORD, MISSED_AYAH, MUTASHABEH_JUMP, REPEAT, PREAMBLE, POSITION`,
and the SPA's `WordStatus` is `pending | ok | missed-provisional | missed`.
`UNCERTAIN` must be **added** on both ends — see **P0-4**.

---

## 2. Measured baseline (2026-09-04)

Numbers this plan is built on. All measured on this box against the live stack.

**Representation quality is good on professional audio.** Per-ayah best-span CER,
`fatiha_full.wav` vs stored references:

| Ayah | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| CER | 0.037 | 0.107 | 0.125 | 0.125 | 0.065 | 0.208 | 0.698 |

All of 1–6 are far below the `MATCH_CER_MAX = 0.45` gate. **Ayah 7's 0.698 is an
artifact, not a model failure**: `PhonemeCTC.ids()` hard-truncates at 30s and the
clip is 46.1s, so ayah 7 was never seen (see **P1-6**).

**Reference corpus health:**

| Bucket | Count |
|---|---|
| `phoneme_confidence >= 0.75` (stable, trackable) | 5331 |
| `0 < c < 0.75` (genuine cross-reciter disagreement) | 885 |
| `c == 0.0` (a reciter download failed → auto-flagged unstable) | 20 |

**Ayah 1 is measurably damaged by basmalah stripping:**

| Group | n | mean confidence | unstable | % unstable |
|---|---|---|---|---|
| Ayah 1 (basmalah-stripped) | 114 | 0.806 | 29 | **25.4%** |
| Ayah > 1 | 6122 | 0.883 | 876 | 14.3% |

Ayah 1 fails at **1.8× the rate** of other ayahs — precisely where reciters start
and where auto-detect must lock.

**Pilot surahs are clean.** Unstable-ayah counts: Surah 1 → 0, 109 → 0, 111 → 0,
112 → 0, 113 → 0, 67 → 0. (Rejected: 108 → 1, 110 → 1, 114 → 1, 55 → 1; for the
3-ayah surahs 108/110 that is 33% of the surah permanently untrackable.)

**Ambiguity:** Al-Kafirun 109:3 and 109:5 are **byte-identical**. Ar-Rahman's
refrain فبأي آلاء ربكما تكذبان occurs **31 times** (30 duplicate ayahs).

**Reference points from the Whisper path** (for comparison only): same clip
27/29 words, 0 false events, ASR latency median 1952 ms / p95 4028 ms.

**Runtime:** backend 874 MB of a 2560 MB limit; model `model.pt` 352 MB
(whisper-small encoder + CTC head, vocab 39, blank id 0).

**Latency — measured after P1-7 landed (2026-09-04):** p50 **4081 ms**, p95 4318 ms,
max 4318 ms over 4 windows on `fatiha_full.wav`, and **constant with respect to
window length** (5.09s → 3927 ms; 21.95s → 4081 ms). See §5.3 — this invalidated the
plan's original `RTF × window_sec` model and produced task **P1-9**.

**Amateur voice — measured 2026-09-04** (first real data, full table in
`docs/baseline-m0-amateur-first.md`). Input quality is *healthy*: `rms_dbfs` p50
−27.7, `ids_per_sec` p50 5.14 (above the ~4.5 qari reference), `c_ctc` 0.68–0.93.
The failure is representational, not acoustic:

| | CER against the Husary reference |
|---|---|
| qari | 0.037 – 0.208 |
| **amateur** | **0.312 – 1.000, clustering 0.45 – 0.50** |

`MATCH_CER_MAX = 0.45` therefore sits *on top of* the amateur distribution — only
2/12 windows matched, with near-misses at 0.452, 0.464, 0.500. Relaxing the gate
**saturates at 5/12**, so it is not a fix on its own: half the windows are genuinely
far away and need a closer reference (P0-1), not a looser threshold. **Do not touch
`MATCH_CER_MAX` before the intentional-error corpus can bound FAAR.**

---

## 3. P0 — root causes, in impact order

### P0-1 · Multi-reciter phoneme references

**File:** `scripts/build_phoneme_refs.py`, `app/db/models.py`, new Alembic migration, `app/db/repo.py`

**Current behavior.** `RECITERS = ["Husary_128kbps", "Abdul_Basit_Murattal_192kbps"]`,
but the builder stores `canonical = seqs[0]` — **Husary alone**. Abdul Basit is used
only to compute `agreement = 1 - normalized_distance(seqs[0], seqs[1])`, which becomes
`phoneme_confidence`, and then discarded. So every user is matched by edit distance
against one professional reciter's exact CTC output, with `MATCH_CER_MAX = 0.45`
tuned qari-vs-qari.

Two further defects in the same function:
- If either download fails, `agreement = 0.0` → the ayah is flagged unstable and
  becomes permanently untrackable even when the Husary sequence is perfectly good
  (20 ayahs today).
- The basmalah strip template is fetched **once** from `RECITERS[0]` (`bas_audio =
  fetch_audio(client, RECITERS[0], "001001")`) and then applied to **every**
  reciter's ayah 1. Abdul Basit's ayah 1 is stripped using Husary's basmalah IDs.

**Proposed behavior.**
1. New table `ayah_phoneme_refs(ayah_id, reciter, ids jsonb, PRIMARY KEY(ayah_id, reciter))`.
   Keep `ayahs.phoneme_ids` untouched as the rollback path.
2. Extend `RECITERS` to 5–6 stylistically diverse everyayah.com voices (e.g. Husary,
   Abdul Basit Murattal, Minshawi, Alafasy, Shatri) — murattal and mujawwad, fast and
   slow, so the reference set spans tempo and elongation rather than one style.
3. Store **one sequence per reciter**. Confidence becomes the **mean pairwise
   agreement** over all successfully fetched references, and is recorded alongside
   the count of references. A fetch failure reduces `n_refs`; it never fabricates
   `agreement = 0.0`.
4. Build a **per-reciter basmalah template** (each reciter's own `001001`) and strip
   ayah 1 with the matching template.
5. `phoneme_unstable` stops being an exclusion. An ayah is **trackable if it has
   ≥ 1 reference**; agreement becomes a soft input to confidence (P0-3), not a gate.

**Reference-selection strategy — storage first, scoring rule chosen by measurement.**
**Implement multi-reference storage first.** `RefAyah.ids: list[int]` becomes
`RefAyah.variants: list[list[int]]`, and `_best_span(window, variants)` returns
`(cer, start, end, variant_idx)` under a **pluggable** reduction over variants.

Then **evaluate single-reference, min-CER, and 2nd-smallest/consensus strategies on
the calibration/validation data before selecting the production scoring rule.** No
strategy is committed to in advance:

| Candidate rule | Expected trade-off |
|---|---|
| **single-reference** (today) | baseline; highest false MISSED_AYAH on style mismatch |
| **min-CER** | lowest false MISSED_AYAH; highest false-acceptance exposure |
| **2nd-smallest / median (consensus)** | needs two independent references to agree; middle ground |

Rationale for expecting a multi-reference rule to help at all: a reciter's style
resembles *some* professional more than others, so scoring against a closer
reference should reduce false MISSED_AYAH relative to one fixed reference. Whether
the right reduction is `min` or a consensus rule is an **empirical question**, and
`RECITEIQ_PHONEME_REF_RULE` selects it so the comparison is a config change, not a
rewrite.

**Why it fixes a measured problem.** Directly attacks the top suspect for the
4–5% figure. Qari audio already scores CER 0.037–0.208 against a same-style
reference; the gap is style mismatch, and a diverse reference set is the cheapest
way to close it. Also recovers the 20 fetch-failure ayahs and removes the
cross-reciter basmalah-strip bug.

**Dependencies / risk.** **This is the plan's main risk.** Any permissive reduction
over K references (`min` most of all) lowers CER for *wrong* ayahs too, so it raises
the **False Ayah Acceptance Rate** — crediting an ayah that was not correctly
recited. Mitigations, in order:
- Re-calibrate `MATCH_CER_MAX` **as a function of K and of the chosen rule** on the
  calibration split — it must come *down* as K grows. Never keep 0.45 while adding
  references.
- Add a **variant-consistency constraint**: within one chain, prefer the variant
  family that wins most links; penalise chains that hop between variants.
- If FAAR exceeds the §6.2 gate under `min`, select the **2nd-smallest/consensus**
  rule instead — which is why the rule is pluggable rather than hard-coded.
Requires a migration and a re-run of the reference batch (network + ~6× the
inference of the original build; scope to the pilot surahs first — that is ~141
ayahs, not 6236).

**Release requirement — reference-audio licensing.** **Verify
redistribution/licensing terms for all reference reciter audio before including
those assets in any public repository, thesis artifact, or deployment package.**
This applies to every voice added to `RECITERS`, not just the current two. Note
that today's pipeline stores only derived integer ID sequences and discards the
audio (`fetch_audio` writes to a `TemporaryDirectory`), which is the posture to
preserve: **derived references may be distributable where the source audio is
not.** Record the per-reciter licence and source URL alongside each reference set,
and treat an unverified licence as a blocker for public release — not for local
development.

**How it will be tested.**
- `test_multi_variant_reduction_rules`: a synthetic variant set where the query
  matches only variant 3 yields a match under `min`, and does **not** under the
  consensus rule — pinning the semantics of each reduction so the strategy
  comparison is meaningful. Querying an unrelated ayah matches under neither.
- `test_variant_fetch_failure_does_not_flag_unstable`: one failed reciter leaves
  `n_refs = K-1` and the ayah trackable.
- `test_per_reciter_basmalah_strip`: reciter B's ayah 1 is stripped with B's own
  template, and the surviving sequence matches B's ayah-1-without-basmalah.
- Regression: `fatiha_full.wav` must stay at **29/29 words, 0 false events**, and
  `fatiha_skip3.wav` at exactly one MISSED_AYAH on ayah 3.
- **False Ayah Acceptance Rate** on the intentional-error corpus (§5.2) is the
  acceptance gate, not the unit tests. The scoring-rule selection is decided by
  this measurement.

---

### P0-2 · Rebuild pilot references and retire the ayah-1 penalty

**File:** `scripts/build_phoneme_refs.py` (`--surah` already supported), `app/db/repo.py`

**Current behavior.** `load_phoneme_reference()` skips any ayah with
`phoneme_unstable` or null `phoneme_ids`: those ayahs consume their `idx` range (so
UI highlight positions never drift) but can **never** turn green. With ayah 1
unstable in 29 surahs at 25.4%, the very first ayah a reciter says is often
untrackable — which also starves auto-detect of its opening evidence.

**Proposed behavior.** Re-run the P0-1 builder for the pilot surahs only
(`--surah 1 109 111 112 113 67`, `--force`), with per-reciter basmalah templates and
multi-reference storage. Then relax `load_phoneme_reference` to include any ayah with
≥ 1 reference, carrying `n_refs` and mean agreement into `RefAyah` for the confidence
term. Keep the `idx` enumeration over **all** ayahs exactly as it is — that invariant
is what keeps SPA highlighting aligned.

**Why it fixes a measured problem.** Removes the 1.8× ayah-1 failure rate and the
14.5% blanket exclusion, for the surahs we are actually demoing. The pilot surahs
already have 0 unstable ayahs, so this is about *keeping* them clean under the new
multi-reference schema and fixing the strip bug at the source.

**Dependencies / risk.** Depends on P0-1. Low risk — pilot-scoped and reversible
(`ayahs.phoneme_ids` is untouched). Risk of `idx` drift if the enumeration is
touched; it must not be.

**How it will be tested.** `test_idx_enumeration_covers_all_ayahs` (existing
invariant, assert unchanged for a surah containing an untrackable ayah);
`test_ayah1_trackable_after_rebuild` for each pilot surah; a DB assertion that all
pilot ayahs have `n_refs >= 2`.

---

### P0-3 · CTC posterior confidence from the existing logits

**File:** `app/asr/phoneme_ctc.py`, `app/engine/phoneme_tracker.py`, `app/config.py`

**Current behavior.** `ids()` computes `logits`, takes `torch.argmax(...)`, collapses,
and **throws the logits away**. The tracker therefore has no idea whether a window was
crisp speech or mush — every window is treated as equally reliable, and the only gate
is a fixed `MATCH_CER_MAX = 0.45`. Whisper's `avg_logprob` / `no_speech_prob` do not
exist on this path and must not be used.

**Proposed behavior.** Return a result object instead of a bare list:

```
PhonemeResult(ids: list[int], token_conf: list[float], c_ctc: float)
```

- `probs = softmax(logits, dim=-1)` over the real (non-padding) frames only —
  reuse the existing `n_real` trim.
- `token_conf[i]` = mean posterior of the winning class over the consecutive frames
  that collapsed into token `i`.
- `c_ctc` = mean `token_conf` over non-blank tokens for the window, in `[0, 1]`.

Feed it into the tracker two ways:
1. **Evidence gate.** If `c_ctc < phoneme_conf_floor`, the window is low-evidence:
   the tracker emits `UNCERTAIN` (P0-4) and **must not** emit `MISSED_AYAH`. Today a
   mumbled window that fails to chain can produce a confident miss.
2. **Adaptive acceptance.** Replace the fixed threshold with
   `cer_max = base_cer_max + k_conf * (c_ctc - conf_ref)`, clipped to
   `[cer_floor, cer_ceil]` — stricter when the audio is poor, more forgiving when it
   is clean. All five constants land in `config.py` as `RECITEIQ_*` env-tunables.

**This is a confidence *heuristic*, not a calibration.** Nothing is fitted. It is
monotonic in the model's own posterior and nothing more. Calling it "calibrated"
would be wrong. P2-3 optionally fits a real calibrator.

**Why it fixes a measured problem.** Gives the tracker the missing "how much do I
trust this window" signal, which is what currently forces a binary
credit-or-report-a-miss decision. It is also the prerequisite for `UNCERTAIN` being
meaningful rather than just "chain came back empty".

**Dependencies / risk.** Small extra compute (one softmax over ~1500×39 — negligible
against the encoder pass). **API-breaking**: `ids()` is called by
`phoneme_session.py`, `build_phoneme_refs.py` and `phoneme_index` tooling; keep an
`ids()` shim returning `.ids` so callers migrate incrementally. Risk of making
things *worse* if `k_conf` is guessed — it must be fitted on the calibration split,
and until then ship with `k_conf = 0` (pure gate, no adaptive threshold).

**How it will be tested.** `test_c_ctc_bounds` (0 ≤ c_ctc ≤ 1 on silence, speech and
white noise); `test_token_conf_aligns_with_collapse` (one confidence per emitted
token); `test_low_confidence_window_emits_uncertain_not_missed_ayah`;
`test_ids_shim_backwards_compatible`. Baseline regression on the two Fatihah clips.

---

### P0-4 · `no_match` signal + `UNCERTAIN` event

**File:** `app/engine/events.py`, `app/engine/phoneme_tracker.py`, `app/ws/phoneme_session.py`, `frontend/src/types.ts`, `frontend/src/state/reducer.ts`, `frontend/src/components/MushafView.tsx`, `frontend/src/index.css`, `frontend/src/pages/Recite.tsx`

**Current behavior.** When `_chain()` returns empty and no jump confirms,
`tracker.feed()` returns `[]`, `phoneme_session` sends **nothing**, and the SPA has no
handler for that case. The UI sits on "listening" indefinitely. This is exactly the
reported symptom, and it also means we have zero diagnosability in production —
`log.info("phoneme detect miss ...")` exists for auto-detect only, not for tracking.

**Proposed behavior.** Respect the transport/decision split (§7):
- **Decision, in the tracker:** add `EventType.UNCERTAIN`, emitted as
  `EventState.PROVISIONAL`, carrying the pointer's word refs plus
  `{c_ctc, best_cer, top_candidates}`. Emitted when a window yields no chain, or
  when `c_ctc` is below the floor. Revoked (`EventState.REVOKED`) as soon as a later
  window chains through that position — reusing the existing revocation machinery
  that `MISSED_WORD` already uses.
- **Transport, in the session layer:** `phoneme_session.py` additionally emits a
  lightweight `{"type": "no_match", "reason", "c_ctc", "top": [...]}` frame so the UI
  can distinguish "I hear you but can't place you" from "I hear nothing". The tracker
  stays pure and WS-unaware.
- **SPA:** `WordStatus` gains `'uncertain'`; `.word-uncertain` renders amber
  (matching the existing `.word-missed-provisional` treatment); the status line shows
  *"Can't place your recitation — keep going, or pick the Surah manually."* Add a
  debug panel (query-flagged, e.g. `?debug=1`) listing top candidate ayahs with CER
  and `c_ctc`.

**Why it fixes a measured problem.** Turns a silent dead-end into both user feedback
and a tuning instrument. Without it, no threshold in this plan can be tuned against
real sessions, because failures leave no trace.

**Dependencies / risk.** `c_ctc` comes from P0-3 (ship `no_match` without it if
needed, with `c_ctc: null`). Low risk. Watch for **UI noise**: an `UNCERTAIN` per
window during a long unmatched stretch would flicker — debounce so amber appears only
after `uncertain_max_consecutive` windows, and make sure `UNCERTAIN` never counts
toward the session summary's error tally.

**How it will be tested.** `test_uncertain_emitted_on_no_chain`;
`test_uncertain_revoked_when_position_later_matches`;
`test_uncertain_excluded_from_summary_counts`; a `ws_client` run on a noise clip
asserting `no_match` frames arrive and no `MISSED_AYAH` is produced.

---

## 4. P1 and P2 — accuracy, ambiguity, audio quality, and deferred work

### P1-5 · Multi-hypothesis (beam) tracker for identical verses

**File:** `app/engine/phoneme_tracker.py`

**Current behavior.** A single `pointer: int` plus a `_recited: set[int]`. `_chain()`
picks the single best chain and `feed()` commits its events immediately. For
identical verses this is unresolvable in principle: when the reciter says
109:3's text, "at ayah 3" and "at ayah 5" are indistinguishable from that window
alone, but the tracker must commit now.

**Proposed behavior.** Replace the single pointer with a small beam:

```
Hypothesis(pointer, recited: frozenset, score: float, pending: list[Event])
```

Per window: expand every hypothesis with its candidate chains, score each by
accumulated `(1 - mean_cer)` weighted by `c_ctc` plus a mild forward-progress prior,
prune to the top `B`. **Initial beam width `B = 4`; configurable
(`phoneme_beam_width`) and benchmarked. `B = 4` is not a design limit** — it is a
starting point to be swept against accuracy and per-window latency (§P1-7), and
raised or lowered on that evidence.

**Commit rule — deferred commitment.** Events flush to the client only when either
(a) all surviving hypotheses agree on them, or (b) one hypothesis leads by
`phoneme_beam_margin` for `phoneme_beam_settle` consecutive windows. Until then they
are held and mirrored to the UI as `PROVISIONAL`. Pruning a hypothesis emits
`REVOKED` for anything it alone had claimed. **No new event type** — this is exactly
what `PROVISIONAL`/`CONFIRMED`/`REVOKED` are for (§1).

**Al-Kafirun worked example.** Reciter is at 109:3 and says
وَلَا أَنتُمْ عَابِدُونَ مَا أَعْبُدُ:
- Two hypotheses survive with **identical** scores: `H1(pointer→4)` (that was ayah 3)
  and `H2(pointer→6)` (that was ayah 5). Nothing commits; ayahs 3 and 5 both show
  amber "checking".
- Next window says وَلَا أَنَا عَابِدٌ مَّا عَبَدتُّمْ (ayah 4) → only H1 can chain.
  H2 is pruned, H1 commits: ayah 3 CONFIRMED, no error. Correct.
- Or next window says لَكُمْ دِينُكُمْ وَلِيَ دِينِ (ayah 6) → H2 chains cleanly;
  H1 would have to skip both 4 and 5. H2 wins, commits ayah 5 CONFIRMED and
  MISSED_AYAH for 3 and 4 — the reciter did jump. Under H1 the miss set would be
  {4, 5}. Either way ayah 4 is missed; the beam decides *which* of 3/5 was recited,
  which is precisely the information a single pointer cannot recover.

**Why it fixes a measured problem.** 109:3/109:5 are byte-identical (verified), and
Al-Kafirun is in the pilot. A precedence chain over one pointer cannot resolve this
regardless of how the precedence is ordered — the previous plan's own narrative
required waiting for ayah 6 while its pseudocode committed immediately.

**Dependencies / risk.** Highest-complexity item here; do it **after** P0-1..P0-4 so
it is tuned against good references and real confidence. Risks: (i) event ordering
and revocation bugs — mitigate by keeping `pending` per hypothesis and never
mutating already-flushed events; (ii) **cost** is `B` × current chain search, so
measure latency after (P1-7); (iii) UI churn from provisional flicker — reuse the
`missed-provisional` debounce pattern. Ar-Rahman's 31-way refrain will exceed any
sane `B`; that is why 55 is a stress test, not a pilot (§6.3).

**How it will be tested.**
- `test_kafirun_3_then_4_resolves_to_repeat_free_progress` — no error events.
- `test_kafirun_3_then_6_resolves_to_ayah5_reading` — ayah 5 credited, 3+4 missed.
- `test_beam_defers_commit_until_disambiguated` — no CONFIRMED event on the
  ambiguous window itself.
- `test_pruned_hypothesis_revokes_its_events`.
- `test_beam_matches_single_pointer_on_unambiguous_surah` — Surah 112/113 results
  identical to pre-beam, guarding against regression.
- Live: `ws_client` on both Fatihah clips must reproduce 29/29-0 and 1-miss-on-3.

### P1-6 · Guard the 30s CTC truncation

**File:** `app/asr/phoneme_ctc.py`, `app/config.py`

**Current behavior.** `audio = audio[: _WIN_SAMPLES]` silently discards everything
past 30s. Proven live: `fatiha_full.wav` (46.1s) scored CER 0.698 on ayah 7 purely
because ayah 7 was never fed to the model. Production is safe only by luck —
`phoneme_segment_max_sec = 25.0` sits just under the cap.

**Proposed behavior.** Never silently truncate. If a window exceeds the model's 30s
capacity, split it at the best interior quiet point and run both halves, concatenating
the collapsed ID streams; if no quiet point exists, split at 25s with a small overlap.
Log a warning whenever this triggers. Add a startup assertion that
`phoneme_segment_max_sec <= 30`.

**Why it fixes a measured problem.** Removes a silent data-loss path and unblocks
raising the window cap. It is also the honest fix for the one bad number in §2.

**Dependencies / risk.** Low. Real risk is a split landing mid-word and producing
junk IDs at the seam — mitigate by preferring VAD quiet points (the segmenter already
tracks `_quiet_pos`) and by overlapping the split.

**How it will be tested.** `test_long_audio_not_truncated` (a 46s Fatihah yields IDs
covering ayah 7, and its best-span CER drops below 0.45);
`test_config_rejects_window_over_30s`; `test_split_prefers_quiet_point`.

### P1-7 · Instrument the phoneme pipeline (latency + per-window diagnostics)

**File:** `app/ws/phoneme_session.py`, `app/audio/vad.py`, `scripts/ws_client.py`

**Current behavior.** The Whisper session reports `asr_ms` and `ws_client` prints
median/p95 from it; **the phoneme session reports nothing**. We have no measured
latency for the production path and no per-window record of chain outcome. That is
why §2 has a "not yet measured" row and why no accuracy target can honestly be set.

**Proposed behavior.** Emit per window: `window_sec`, `infer_ms`, `n_ids`, `c_ctc`,
`chain_len`, `best_cer`, `matched_ayahs`, and `beam_size` once P1-5 lands. Send
`infer_ms` on the events frame (mirroring `asr_ms`) so `ws_client` can report
p50/p95, and log the rest as structured JSON. Add `segment_closed_reason`
(`silence` | `max_sec`) in the segmenter so the smart-cut-vs-overlap question in §1
can be settled with data rather than opinion.

**Why it fixes a measured problem.** Requirements 14 and 17 depend on it: gates and
latency targets cannot be set before this exists. It also produces the evidence
needed to accept or reject overlapping windows.

**Dependencies / risk.** None — do it **first** (see §7). Risk: log volume; keep
per-window logs at INFO with the existing 10 MB × 3 rotation, and put anything
verbose behind a debug flag.

**How it will be tested.** `test_events_frame_carries_infer_ms`;
`test_segment_closed_reason_reported`; `ws_client` on the eval clips prints
p50/p95 `infer_ms` and a per-window table.

### P1-9 · Variable-length encoder pass (remove the constant 30s cost)

**File:** `app/asr/phoneme_ctc.py`

**Current behavior.** Every window is padded to 30s and the encoder runs over all
1500 frames regardless of how much real audio there is. Measured: 3927 ms for 5.09s
of audio, 4081 ms for 21.95s — a fixed ≈ 4.1s cost. `n_real` discards the padding
frames *after* paying for them.

**Proposed behavior.** Feed the encoder only the frames that contain audio: slice
`input_features` to `ceil(duration × 100)` mel frames and slice
`encoder.embed_positions.weight` to the matching number of output positions
(`n_frames // 2`, since the conv stack halves the time axis). Keep the 30s path as a
fallback behind a config flag so it can be A/B'd, and assert the sliced pass returns
IDs identical to the padded pass on the eval clips.

**Why it fixes a measured problem.** For a 5s window this is ~6× less encoder
compute (250 frames vs 1500), which is the difference between ~4s and well under a
second of feedback latency. It is the single largest latency lever available, and it
costs no accuracy if the positional slice is correct.

**Dependencies / risk.** Independent of the accuracy work; do it after P1-8.
**Risk: positional-embedding slicing must be exact** — an off-by-one on the conv
downsampling shifts every position and would silently degrade IDs. That is why the
acceptance test is bit-identical output against the padded path, not just "looks
reasonable". Also verify the CTC head's `n_real` trimming is removed rather than
double-applied once padding is gone.

**How it will be tested.** `test_variable_length_matches_padded` — for clips of 3s,
10s and 25s, sliced-pass IDs must equal padded-pass IDs exactly;
`test_variable_length_is_faster` — measured `infer_ms` scales with duration instead
of staying flat; live re-run of both Fatihah clips must reproduce 29/29-0 and
one-miss-on-3.

### P1-8 · Correct anti-aliased decimation inside the AudioWorklet

**File:** `frontend/src/audio/recorder.ts`

**Current behavior.** The worklet (`CaptureProcessor.process`) only forwards raw
device-rate frames; **all resampling happens on the main thread** in
`port.onmessage`, as bare linear interpolation with no low-pass. Two defects:
- **No anti-aliasing.** 48 kHz → 16 kHz linear interpolation folds everything above
  8 kHz back into the speech band. Both the CTC model and Whisper use 80-mel features
  capped at 8 kHz, so this is aliased energy landing exactly where the features live.
- **Per-block phase reset and sample loss.** `pos = i * ratio` restarts at 0 for each
  128-frame worklet block, and the tail is clamped by
  `input[Math.min(i0+1, input.length-1)]`. At 48 kHz (`ratio = 3`),
  `outLen = floor(128/3) = 42` consumes 126 samples and **drops 2 every block —
  1.56% of all audio**, with a phase discontinuity at every block boundary.

**Proposed behavior.** Move decimation **into the worklet** (per requirement 11 — no
`OfflineAudioContext`; it is for offline rendering and is the wrong tool for a live
`MediaStream`):
- A windowed-sinc (Kaiser or Blackman-Harris) FIR low-pass at ~7.6 kHz cutoff,
  applied before decimation, with coefficients precomputed for the actual
  `sampleRate / 16000` ratio.
- A **persistent filter-state and fractional-phase accumulator across `process`
  calls**, so no sample is dropped and phase is continuous. Retain the FIR history
  tail between blocks.
- Handle non-integer ratios (44.1 kHz → 16 kHz) via the same fractional accumulator.
- Keep the existing `AudioContext()` at device rate. Do **not** rely on
  `new AudioContext({sampleRate: 16000})` — the file's own comment records that
  browsers "won't reliably honor" it.
- Separately A/B `echoCancellation` / `noiseSuppression` (currently both `true`):
  they are tuned for telephony and may distort sustained *madd* vowels. Treat as a
  measured experiment, not an assumed win.

**Why it fixes a measured problem.** It is upstream of *both* tracker paths, so the
1.56% sample loss, per-block clicks and aliased HF energy degrade every downstream
measurement in this plan. Fixing the input is a precondition for trusting any
accuracy number.

**Dependencies / risk.** Independent of the backend — parallelisable. Risk: FIR cost
in the audio thread (a ~48-tap FIR on 128-frame blocks is comfortably real-time, but
must be verified on a low-end laptop), and group delay must be accounted for if
timestamps are ever used. Regression risk if the ratio maths is wrong — verify
numerically before shipping.

**How it will be tested.** Node/vitest unit test on the worklet DSP: a 12 kHz sine at
48 kHz input must attenuate by > 40 dB after decimation (no alias at 4 kHz); a swept
sine must show **no** discontinuity at block boundaries; total output sample count
must equal `floor(input_count / ratio)` ± 1 over 1000 blocks (proving no 1.56% loss).
End-to-end: re-run the eval clips through the browser path and confirm CER does not
regress.

### P2-1 · Word-level spans via CTC frame alignment

**File:** `app/asr/phoneme_ctc.py`, `app/engine/phoneme_tracker.py`

**Current behavior.** Phoneme mode credits whole ayahs: `_confirm_ayah` bursts
`WORD_OK` for every word of a matched ayah as soft progress, and **`MISSED_WORD` is
never emitted** (a documented v1 invariant, `test_no_missed_word_events_ever`).

**Proposed behavior.** Use the CTC frame indices already available before collapsing
(P0-3 exposes them) to map ID spans back to word boundaries within the matched ayah,
giving per-word spans and restoring `MISSED_WORD`. Unlocks the word-level
false-`WORD_OK` metric (§5.2).

**Why.** Missed-word detection is a headline feature currently absent from the
production path. **Risk:** word boundaries in a 39-symbol ID space are approximate;
must not regress FAAR by converting ayah-level uncertainty into confident word-level
errors. **Test:** word spans on pilot surahs against hand-annotated boundaries; the
v1 invariant test is replaced, not deleted.

### P2-2 · Speaker enrollment (personal references)

Extend P0-1's variant list with the user's **own** recitation of the pilot surahs,
captured once. Natural continuation of multi-reference storage — an enrolled voice
is just another variant, so no new matching machinery. Likely the single largest
accuracy win for a scoped surah set. Requires per-user reference storage and a
consent/privacy path, since this is the first time user audio is used to derive
anything persistent.

### P2-3 · True calibration of `c_ctc`

Fit an isotonic or Platt calibrator mapping `c_ctc` → P(correct match) on the
calibration split. **Only after this is fitted may the word "calibrated" be used**
in the thesis; until then `c_ctc` is a confidence *heuristic* (§P0-3).

### P2-4 · Phonetic similarity as a scoring feature

If phonetic tolerance is added — for near-miss consonants such as ص/س, ط/ت, ظ/ذ,
ق/ك, ح/ه — it enters as a **soft similarity feature inside the scorer only**.

> **Phonetic equivalence mappings must not modify canonical Quran text; they are
> applied only inside the phonetic similarity feature.**

Concretely: `text_uthmani` and the word-level Imlaei text are never rewritten;
`nlp/normalize.py` is not extended to merge these pairs (it already correctly keeps
them distinct — §1); and stored `phoneme_ids` / reference variants are never
folded. A phonetic mapping is a *scoring* concession to accent variation, never a
claim that two Quranic letters are the same letter. Merging them into canonical
text would silently mask genuine pronunciation errors and corrupt the reference
data for every future experiment.

Applies equally to the ID space: if near-confusable CTC symbols are given partial
credit, that partial credit lives in the distance function, not in the stored
sequences.

### P2-5 · Overlap-vs-smart-cut decision

Decide from P1-7's `segment_closed_reason` and per-window CER data whether
overlapping windows beat the existing VAD smart cuts. **Do nothing unless the
measurement shows a clear benefit** (§1).

---

## 5. Evaluation protocol

### 5.1 Corpus (speaker-disjoint)

Pilot surahs **1, 109, 111, 112, 113** (+ **67**). ~141 ayahs for the five core surahs.

| Split | Speakers | Purpose |
|---|---|---|
| **Train / calibration** | 3 (mixed native + non-native) | Fit `MATCH_CER_MAX(K)`, `phoneme_conf_floor`, `k_conf`, beam constants |
| **Validation** | 2 | Iterate design choices; compare reference-scoring rules; watch FAAR while tuning |
| **Held-out** | 3 (≥ 1 native, ≥ 2 non-native) | Touched **once**, for the final thesis numbers |

**Splitting is by speaker, never by clip.** A speaker appearing in two splits
inflates every metric. Environments (studio / laptop built-in / headset with ambient
chatter) must appear in **all** splits so environment is not confounded with split.

Per speaker, per surah: 3 clean takes, plus scripted error takes —
(a) skip one word, (b) skip a whole ayah, (c) substitute a wrong word,
(d) restart/repeat an ayah, (e) an identical-verse jump for 109 (3→6).
Target ≈ 8 speakers × 5 surahs × ~6 takes ≈ 240 clips.

**Ground truth** is word-level: for each take, the ordered list of reference word
IDs actually recited, plus a label per deviation. This annotation is the real cost of
the corpus and must be budgeted; the false-`WORD_OK` metric is impossible without it.

**Honest caveat for the write-up:** 3 held-out speakers gives wide confidence
intervals. Report intervals, not bare point estimates.

### 5.2 Metrics

Ayah-level first, since phoneme v1 credits whole ayahs.

**Naming, deliberately:** through P0 and P1 the tracker has **no word alignment** —
it credits an ayah by bursting `WORD_OK` for all of that ayah's words as soft
progress, which is explicitly *not* a per-word judgement. So the early safety metric
is the **False Ayah Acceptance Rate (FAAR)**, defined at ayah granularity. A true
**word-level false-`WORD_OK` rate** is only meaningful once **P2-1** provides CTC
frame-level word alignment, and is introduced then (§4, P2-1). Do not report a
word-level false-`WORD_OK` figure before P2-1 — with ayah-level crediting the
denominator would be fictional.

| Metric | Definition |
|---|---|
| **Ayah recall (clean)** | credited ayahs ÷ ayahs actually recited |
| **False MISSED_AYAH rate (clean)** | correctly recited ayahs flagged missed ÷ ayahs recited |
| **False Ayah Acceptance Rate (FAAR)** | ayahs containing a deliberate error that were nonetheless credited ÷ ayahs containing a deliberate error. **The critical safety metric** — an app that greenlights wrong recitation is worse than one that says "unsure". Ayah-level crediting is structurally prone to this, so it must be measured, not assumed. |
| **Missed-ayah recall** | deliberately skipped ayahs correctly reported |
| **Identical-verse resolution accuracy** | 109 3-vs-5 decided correctly (P1-5) |
| **Benign repeat accuracy** | restart/repeat takes producing zero error events |
| **Uncertainty usefulness** | share of low-quality windows surfaced as `UNCERTAIN` instead of a false miss |
| **Auto-detect lock rate / time-to-lock** | opening-window detection on pilot surahs |

### 5.3 Latency — defined from the actual architecture

The phoneme path is **not** a streaming word recogniser. A window is closed by the
VAD (0.5s trailing silence, or the 25s cap), then **one** CTC forward pass runs over
the whole window.

**Measured 2026-09-04 (P1-7, `fatiha_full.wav`, 4 windows):**

| window_sec | closed | infer_ms |
|---|---|---|
| 5.09 | silence | 3927 |
| 21.95 | silence | 4081 |
| — | p50 / p95 / max | **4081 / 4318 / 4318** |

**Inference cost is CONSTANT, not proportional to window length.** A 5s window costs
the same as a 22s window, because `_WIN_SAMPLES = 30 * _SR` and the feature
extractor's `chunk_length=30` pad every window to 30s — the encoder always runs over
1500 frames, and `n_real` trims only the *output*, after the full forward pass. So:

```
t_feedback = t_silence_cut (0.5s) + t_infer (~4.1s CONSTANT) + t_net
```

This supersedes the earlier `RTF × window_sec` model, which was wrong. The
"RTF ≈ 0.1" figure holds only for a *full* 30s window; for a 5s window the effective
RTF is **0.77**.

Two consequences worth stating plainly:
- The per-window latency floor on this box is ≈ **4.6s**. A `≤ 600 ms` P50 is
  architecturally impossible, and so are the provisional 1.5s / 3.5s numbers this
  section previously carried.
- **Short windows are strictly wasteful.** Since cost is fixed, the efficient move is
  *longer* windows, not shorter ones — the opposite of a latency-minded design. This
  is a direct input to P2-5 and to any window-size tuning, and it is only knowable
  because P1-7 measured it.

**P1-9 has landed and removed the constant.** Re-measured on the live socket,
same clip, `RECITEIQ_PHONEME_VARIABLE_LENGTH=true`:

| window_sec | infer_ms before | infer_ms after |
|---|---|---|
| 5.09 | 3927 | **1423** |
| 5.95 | 4017 | **682** |
| 21.95 | 4081 | **2955** |
| p50 / p95 | 4081 / 4318 | **1423 / 2955** |

Accuracy unchanged: 29/29 words, 0 errors on the clean clip. Cost now scales with
duration, so the model becomes:

```
t_feedback = t_silence_cut (0.5s) + t_infer (~0.15 x window_sec) + t_net
```

giving ≈ **1.2s** for a typical 5s window and ≈ 3.5s for a 22s one.

Targets, now that the architecture can support them:

- **Per-window processing latency** — window close → UI update.
  **P50 ≤ 1.5s, P95 ≤ 3.5s** (currently p50 1423 ms, p95 2955 ms — both met on a
  single session; must be re-confirmed under concurrency, see below).
- **Time-to-first-feedback** — utterance start → first green. Bounded below by the
  window length; report the distribution, do not reduce it to one number.
- **Concurrency is unvalidated.** Two overlapping sessions previously doubled
  latency (p50 8430 ms pre-P1-9) against a configured cap of 3. Re-measure
  deliberately before any demo.

Fully streaming sub-second feedback would need incremental partial CTC hypotheses —
out of scope for v1, noted as future work.

---

## 6. Milestone gates

### 6.1 M0 — baseline (no targets, just numbers)

**Before P1-8, capture a minimal as-is baseline on the current deployed audio path.
This is diagnostic only and is not used as the formal thesis baseline.** Land
**P1-7** first (instrumentation), then run the pilot clips and a handful of live
amateur takes through the **unmodified** resampler and record per-window `c_ctc`,
`best_cer`, `chain_len` and ayah recall. Re-running the identical set after P1-8
isolates the effect of the 1.56% sample-loss and aliasing bug from every other
change in this plan — otherwise the resampler fix and the reference work land
together and neither effect is separable.

Keep this run small and clearly labelled `M0-pre` in the results: same speakers,
same clips, same surahs, no corpus-wide effort. It is a diagnostic delta, not a
reportable result.

> **`M0-pre` must be captured through the BROWSER, not through `ws_client`.**
> `scripts/ws_client.py` reads a 16 kHz WAV and sends the PCM straight to the
> WebSocket — it never touches `frontend/src/audio/recorder.ts`. So file-fed eval
> clips are **structurally incapable** of showing the resampler effect: the 1.56%
> sample loss and aliasing only occur on live `getUserMedia` capture. The `M0-pre`
> vs post-P1-8 delta therefore requires the **same human reciting the same surahs
> into the live SPA** before and after, with per-window diagnostics read from the
> backend log. File-fed runs remain valuable for the tracker and latency baseline
> (`M0`), and as the invariant regression check — but they measure the server
> side only.

**The formal baseline (`M0`)** is then measured after P1-7 **and** P1-8, on the
recorded corpus: every §5.2 metric on the calibration + validation splits with
today's tracker (including the already-landed one-ayah-per-window fix). **No
accuracy target is set before `M0` exists.** `M0` is the number the thesis improves
on, and it converts the anecdotal "4–5%" into an instrumented figure.

### 6.2 Gates

Each gate is relative to M0 plus an absolute floor on the safety metric.

| Milestone | Content | Gate |
|---|---|---|
| **M1** | P0-1, P0-2, P0-3, P0-4 | Ayah recall ≥ 2× M0 on validation; false MISSED_AYAH below M0; **FAAR ≤ 10%**; zero regression on the two Fatihah clips |
| **M2** | P1-5 (beam), P1-6 | Identical-verse resolution ≥ 90% on 109; **FAAR ≤ 5%**; per-window P95 ≤ 3.5s |
| **M3** | P2 items | Word-level spans on pilot surahs; **FAAR ≤ 3%**, and word-level false-`WORD_OK` reported for the first time (enabled by P2-1) |

Stretch targets (ayah recall ≥ 95%, false alarms ≤ 4%) are stated as **aspirations
until M0 exists**. Committing to ≥ 95% from a 4–5% starting point with nothing in
between is a wish, not a plan.

### 6.3 Ar-Rahman (Surah 55) — stress test only

Deliberately excluded from the pilot. Its refrain repeats **31 times** (30 identical
ayahs, verified), a 31-way ambiguity that exceeds any practical beam width. It is the
right *final* robustness test — the unique ayahs between refrains are what make it
tractable at all — but a terrible starting point. Revisit only after M2, and treat
partial success there as a documented limitation rather than a failure.

---

## 7. Implementation order

**Architectural invariant (requirement 18):** transcript/window assembly stays in
`ws/phoneme_session.py` and `audio/vad.py`; match/state decisions stay in
`engine/phoneme_tracker.py`. The tracker never learns about WebSockets, and the
session layer never decides whether an ayah was recited. `no_match` is a transport
frame; `UNCERTAIN` is a tracker decision.

| Order | Task | Priority | Why here |
|---|---|---|---|
| 1 | **P1-7** instrumentation | **P0-blocking** | Nothing can be tuned or gated without it. Cheap, zero-risk. |
| 2 | **`M0-pre`** minimal as-is audio baseline | **DONE 2026-09-04** | Quantified deterministically by porting `recorder.ts` and running device-rate audio through both paths — see `docs/baseline-m0-pre-serverside.md`. Signal damage is severe (−1.57% drift, full-amplitude aliasing) but **downstream tracker output is identical** on clean audio (29/29 words, 0 errors both ways). |
| 3 | ~~**P1-8** worklet decimation~~ → **moved to P1** | **P1** | **Downgraded on evidence.** Was P0-blocking on the assumption that corrupted input invalidates all measurement; that is falsified for clean audio. Still worth fixing, but it no longer blocks P0-1. Re-test on amateur takes once the corpus exists — their HF content folds differently. |
| 4 | **`M0`** corpus + formal baseline | **P0** | The reference point for every gate. Measured after P1-7 **and** P1-8. |
| 5 | **P0-1** multi-reference storage, then scoring-rule comparison | **IN PROGRESS** | Storage landed: `ayah_phoneme_refs` (migration `a1c4e7f20b91`), 6 stylistically diverse reciters, per-reciter basmalah templates, mean-pairwise confidence, and a pluggable `RECITEIQ_PHONEME_REF_RULE` (`single`/`min`/`second`/`median`) defaulting to `single` so nothing changes until the corpus decides. Pilot references building. |
| 6 | **P0-2** pilot rebuild + drop the unstable exclusion | **P0** | Depends on 5; removes the ayah-1 penalty. |
| 7 | **P0-3** CTC posterior confidence | **P0** | Ship with `k_conf = 0` until fitted. Heuristic, not calibration. |
| 8 | **P0-4** `no_match` + `UNCERTAIN` | **DONE 2026-09-04** | Landed as a **correctness** fix, not just UI: the tracker was reporting every unmatched ayah in a chained span as MISSED_AYAH, so unplaced windows produced false red (live: credited [4,6], marked 1/2/3/5 missed though all were recited). Now only in-window skips are misses; cross-window gaps are UNCERTAIN. `fatiha_skip3` still reports exactly one miss on ayah 3. |
| 9 | **P1-9** variable-length encoder pass | **DONE 2026-09-04** | Landed. p50 4081 → **1423 ms**, a 5.95s window 4017 → **682 ms**, accuracy unchanged (29/29, 0 errors). Note: bit-identical output was an impossible acceptance criterion — the encoder is bidirectional — so it is validated by a CER budget on real audio instead. |
| 9b | **P1-6** 30s truncation guard | **P1** | Independent, small, removes silent data loss. Pairs naturally with P1-9. |
| 10 | **P1-5** beam tracker | **P1** | Most complex; wants good refs + confidence first. Sweep `B` (start 4, not a limit). → **M2** |
| 11 | **P2-1** word-level spans via CTC frame alignment | **P2** | Restores MISSED_WORD; first point at which a word-level false-`WORD_OK` rate is meaningful. |
| 12 | **P2-2** speaker enrollment (personal references) | **P2** | Likely large win; natural extension of P0-1's variant list. |
| 13 | **P2-3** true calibration (isotonic/Platt on `c_ctc`) | **P2** | Only then may the word "calibrated" be used. |
| 14 | **P2-4** phonetic similarity as a scoring feature | **P2** | Scorer-only; never touches canonical text or stored references. |
| 15 | **P2-5** overlap-vs-smart-cut decision | **P2** | Decide from P1-7 data; do nothing unless it wins. |
| 16 | **Surah 55 stress test** | **P2** | Post-M2 robustness only. |

**Not on this list, by design:** anything in the Whisper path, making Groq primary,
adding a `MUTASHABEH_PROVISIONAL` event type, changing `normalize.py`, replacing VAD
smart cuts, or re-fixing one-ayah-per-window. See §1.

**No other architectural change lands without measured evidence.** Anything not
listed above requires a number from P1-7 instrumentation or the evaluation corpus
before it is written.
