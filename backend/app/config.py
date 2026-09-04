"""Central configuration. Everything operational is env-tunable (RECITEIQ_* vars)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RECITEIQ_", env_file=".env", extra="ignore")

    # --- Database ---
    database_url: str = "postgresql+psycopg://reciteiq:reciteiq@127.0.0.1:19832/reciteiq"

    # --- ASR (decision 9: strict thread budget on 6 shared cores) ---
    asr_engine: str = "whisper_local"          # whisper_local | cloud (Groq + local fallback)
    groq_api_key: str = ""                     # https://console.groq.com (free: 2000 req/day)
    groq_model: str = "whisper-large-v3-turbo"
    cloud_timeout_sec: float = 8.0
    # Phoneme/encoder-CTC recognizer (v1 ID-space tracker)
    phoneme_model_path: str = "models/quran-phoneme-ctc-small-v2.pt"
    tracker_mode: str = "whisper"              # "whisper" (current) | "phoneme" (v1 ID tracker)
    # P1-9: run the encoder over only the frames that carry audio, instead of
    # padding every window to 30s (which cost a flat ~4s regardless of length).
    # Not a pure optimisation in principle — the encoder is bidirectional, so
    # dropping the padding changes what each frame attends over — but measured
    # on real recitation the output is IDENTICAL at 3s and 5s (CER 0.000) and
    # diverges by only 0.018 at 10-22s, far below match_cer_max. Latency:
    # 3s window 4117ms -> 449ms (9.2x), 5s 4041ms -> 741ms (5.5x).
    # Set false to fall back to the padded path (e.g. to A/B a reference rebuild).
    phoneme_variable_length: bool = True
    phoneme_segment_max_sec: float = 25.0      # ≤30s bounded windows (no stitcher in v1)
    phoneme_silence_cut_sec: float = 0.5       # cut at natural pauses (ayah boundaries)
    phoneme_detect_min_ids: int = 6            # min query IDs before auto-detect votes
    phoneme_detect_score_min: float = 0.45     # location lock score floor
    phoneme_detect_margin: float = 0.18        # top-1 vs top-2 margin to lock
    phoneme_detect_consensus: int = 2          # consecutive agreeing windows to lock

    # --- P0-4: uncertainty rather than false verdicts ---
    # Live-measured on an amateur take: 10/12 windows returned no_match with the
    # model CONFIDENT (c_ctc 0.68-0.93) and healthy input, so a failure to match
    # is not evidence the reciter skipped anything.
    phoneme_uncertain_after: int = 2           # consecutive no-match windows before flagging
    phoneme_conf_floor: float = 0.35           # c_ctc below this: never claim a miss

    # --- P0-1: multi-reciter references ---
    # How to reduce K per-reciter CERs to one score. Deliberately NOT decided in
    # advance — the corpus picks the winner (plan §P0-1):
    #   single    legacy: the canonical (Husary) reference only
    #   min       score against whichever reciter is closest (most permissive)
    #   second    2nd-smallest: needs two independent references to agree
    #   median    middle of the K references
    # `min` raises False Ayah Acceptance Rate as K grows, so MATCH_CER_MAX must be
    # recalibrated per rule and per K. Never ship a new rule without measuring FAAR.
    phoneme_ref_rule: str = "single"
    phoneme_ref_max: int = 6                   # cap references considered per ayah

    # --- Segmentation / partial-ayah handling (docs/experiment-segmentation.md) ---
    # Measured: on identical audio, credited ayahs fall 7/7 -> 6/7 -> 4/7 -> 3/7 as
    # windows shrink from 31s to 4.0s, 2.5s and 1.5s, because a window shorter than
    # an ayah cannot match a whole-ayah reference. All DEFAULT OFF so production is
    # unchanged until A/B'd against a real fragmented browser take.
    #
    # carry_forward: an unmatched window's IDs are prepended to the next window's,
    # so consecutive fragments are matched together. Fixes fragmentation at zero
    # cost on clean audio (7/7 -> 7/7 natural, 4/7 -> 7/7 at 2.5s) and adds no
    # inference, since it reuses IDs already computed.
    phoneme_carry_forward: bool = False
    phoneme_carry_max_ids: int = 400           # safety cap on the carry buffer
    # revoke_late_miss: withdraw a MISSED_AYAH when a later window proves the ayah
    # WAS recited. The Whisper path already does this (detector.py, commit be3264c);
    # the phoneme tracker emitted misses with no late-match withdrawal at all.
    # ENABLED 2026-09-04: two of six live takes showed a MISSED_AYAH standing on
    # an ayah that a LATER window then credited (Al-Fatihah 1:2, after the first
    # window anchored on 1:3). A verdict contradicted by later evidence must be
    # withdrawn, so this is on by default; the flag remains for rollback.
    phoneme_revoke_late_miss: bool = True
    # NOTE: raising `phoneme_silence_cut_sec` 0.5 -> 0.7 is the third measured
    # improvement. It needs no new flag (already RECITEIQ_PHONEME_SILENCE_CUT_SEC)
    # and the default stays 0.5. Do NOT go to 0.9+: the sweep shows that loses a
    # correctly recited ayah on clean audio.
    asr_model_path: str = "models/whisper-base-ar-quran-ct2"
    asr_compute_type: str = "int8"
    asr_cpu_threads: int = 2                   # per-inference threads
    asr_num_workers: int = 2                   # concurrent inferences on the shared model
    asr_queue_max: int = 8                     # bounded global transcription queue

    # --- Hallucination gate (D5) ---
    asr_no_speech_prob_max: float = 0.6
    asr_avg_logprob_min: float = -1.0
    asr_compression_ratio_max: float = 2.4
    asr_min_segment_sec: float = 0.4

    # --- VAD / segmentation (D4: hard cap kills the long-segment latency cliff) ---
    vad_threshold: float = 0.5
    segment_max_sec: float = 5.0
    segment_overlap_sec: float = 0.5
    silence_cut_sec: float = 0.7               # trailing silence that closes a natural segment

    # --- Alignment / detection tunables (tuned in Phase 6 against the eval harness) ---
    match_score_min: int = 78                  # rapidfuzz ratio (0-100) to accept a word match
    confirm_window_k: int = 3                  # matches needed to confirm a MISSED_WORD
    align_window_fwd: int = 12                 # words ahead of pointer considered
    align_window_back: int = 8                 # words behind pointer (repetition, D2)
    pause_grace_sec: float = 4.0               # "wait and listen" before MISSED_AYAH can confirm
    jump_confirm_segments: int = 2             # consecutive segments before MUTASHABEH_JUMP (D5)
    relocation_score_min: float = 0.6          # n-gram containment to consider a relocation

    # --- Auto-detect (start session without choosing Surah/Ayah) ---
    detect_min_tokens: int = 4                 # don't even search before this many tokens
    detect_max_tokens: int = 16                # search window cap (longer dilutes diagonals)
    detect_score_min: float = 0.65             # single-window instant-lock threshold
    detect_margin: float = 0.2                 # ...and must beat other locations by this
    detect_consensus_floor: float = 0.4        # consensus: per-window floor to count as a vote
    detect_consensus: int = 3                  # ...leader needs this many votes in the window
    detect_vote_window: int = 6                # ...counted over the last N qualifying segments

    # --- WS abuse controls (D3) ---
    max_concurrent_sessions: int = 3
    max_sessions_per_ip: int = 2
    max_session_minutes: int = 90
    idle_timeout_sec: int = 120
    ingest_rate_factor: float = 1.1            # x real-time; mic audio can't legitimately exceed this
    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # --- Retention (D11) ---
    anonymous_events_retention_days: int = 30

    # --- Audio format contract with the SPA ---
    sample_rate: int = 16000                   # 16 kHz mono s16le PCM


settings = Settings()
