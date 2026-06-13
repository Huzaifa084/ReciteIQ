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
