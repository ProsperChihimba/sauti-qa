"""All runtime configuration, read from environment variables (and .env).

Every variable is documented in .env.example at the repository root. Values that
admins may tune at runtime (routing thresholds, retention, channel mapping) are
only defaults here: the effective value lives in the app_settings table.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # General
    env: Literal["dev", "test", "prod"] = "dev"
    app_name: str = "Sauti QA"
    secret_key: str = "change-me-in-production-please-32+chars"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    public_base_url: str = "http://localhost:3000"

    # Database / queue
    database_url: str = "postgresql+psycopg://sauti:sauti@localhost:5432/sauti"
    redis_url: str = "redis://localhost:6379/0"
    celery_eager: bool = False  # run tasks inline (tests / tiny installs)

    # Auth
    jwt_expire_minutes: int = 60 * 12
    cookie_secure: bool = False
    cookie_name: str = "sauti_session"

    # Storage
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_root: Path = Path("./data/storage")
    s3_endpoint_url: str | None = None  # e.g. http://minio:9000
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str = "sauti-audio"
    s3_region: str = "us-east-1"

    # Ingestion
    max_upload_mb: int = 200
    inbox_dir: Path = Path("./data/inbox")
    inbox_poll_seconds: float = 5.0
    inbox_stable_seconds: float = 3.0  # file must stop growing for this long
    allowed_audio_ext: list[str] = Field(
        default_factory=lambda: [".wav", ".mp3", ".ogg", ".opus", ".flac", ".m4a", ".amr", ".gsm", ".webm"]
    )

    # Audio
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    target_sample_rate: int = 16000
    vad_backend: Literal["silero", "energy", "none"] = "silero"
    mute_redacted_audio: bool = False  # silence spoken PII in the playback copy (needs word timestamps)

    # ASR
    asr_provider: Literal["mock", "openchs", "buzzasr", "faster_whisper", "hf_whisper", "openai"] = "mock"
    asr_model: str | None = None  # override model id / path for the chosen provider
    asr_device: str = "cuda"
    asr_compute_type: str = "float16"
    asr_language: str = "sw"
    asr_batch_size: int = 8
    asr_openai_base_url: str | None = None
    asr_openai_api_key: str | None = None
    hf_cache_dir: Path | None = None  # point at pre-downloaded models for offline use

    # Diarization
    diarization_backend: Literal["pyannote", "none"] = "pyannote"
    pyannote_model: str = "pyannote/speaker-diarization-3.1"
    hf_token: str | None = None  # only needed to download gated pyannote weights once

    # LLM
    llm_provider: Literal["mock", "anthropic", "openai"] = "mock"
    llm_model: str | None = None
    anthropic_api_key: str | None = None
    llm_openai_base_url: str | None = None  # e.g. http://vllm:8000/v1 or http://ollama:11434/v1
    llm_openai_api_key: str | None = "not-needed"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 8000
    llm_timeout_seconds: float = 180.0
    llm_speaker_identification: bool = True

    # Review routing defaults (overridable in app_settings)
    review_score_threshold: float = 80.0
    review_confidence_threshold: float = 0.6
    review_on_flags: bool = True
    review_on_auto_fail: bool = True

    # Stereo channel mapping default (overridable in app_settings)
    stereo_agent_channel: Literal["left", "right"] = "left"

    # Retention
    audio_retention_days: int = 90  # 0 = keep forever

    # Jobs
    job_stuck_minutes: int = 30
    job_max_attempts: int = 3

    # Bootstrap admin (created on first start if no users exist)
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    @property
    def is_test(self) -> bool:
        return self.env == "test"


@lru_cache
def get_settings() -> Settings:
    return Settings()
