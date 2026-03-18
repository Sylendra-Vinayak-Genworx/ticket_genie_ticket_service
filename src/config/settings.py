from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
    )

    # ── App ───────────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO")
    environment: str = Field(default="development")

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str

    secret_key: str = Field(default="change-me-at-least-32-chars-long-here")
    algorithm: str = Field(default="HS256")

    auth_service_url: str = Field(default="http://localhost:8001")

    # ── Celery ────────────────────────────────────────────────────────────────
    CELERY_BROKER_URL: str = Field(default="redis://localhost:6379/0")
    CELERY_RESULT_BACKEND: str = Field(default="redis://localhost:6379/1")
    DEFAULT_RESPONSE_TIME_MINUTES: int = 480
    DEFAULT_RESOLUTION_TIME_MINUTES: int = 2880
    DEFAULT_ESCALATION_AFTER_MINUTES: int = 120
    LEAD_TIMEOUT_MINUTES: int = Field(default=15)
    AUTO_CLOSE_AFTER_HOURS: int = Field(default=4320)

    groq_api_key: str = Field(default="")

    # ── Similarity routing ────────────────────────────────────────────────────
    SIMILARITY_THRESHOLD: float = Field(default=0.60)
    MAX_OPEN_TICKETS: int = Field(default=10)
    HF_TOKEN: str = Field(default="")
    FRONTEND_URL: str = Field(default="http://localhost:5173")

    # ── IMAP (inbound email) ──────────────────────────────────────────────────
    # Leave IMAP_HOST blank to disable email polling entirely.
    IMAP_HOST: str = Field(default="")
    IMAP_PORT: int = Field(default=993)
    IMAP_USER: str = Field(default="")
    IMAP_PASSWORD: str = Field(default="")
    IMAP_MAILBOX: str = Field(default="INBOX")

    SMTP_HOST: str = Field(default="smtp.gmail.com")
    SMTP_PORT: int = Field(default=587)
    SMTP_USER: str = Field(default="")
    SMTP_PASSWORD: str = Field(default="")
    SMTP_FROM_NAME: str = Field(default="Support Team")

    # ── Google Cloud Storage ──────────────────────────────────────────────────
    GCS_ENABLED: bool = Field(default=True)
    GCS_PROJECT_ID: str = Field(default="gwx-internship-01")
    GCS_BUCKET_NAME: str = Field(default="gwx-stg-intern-01")
    GCS_BUCKET_PREFIX: str = Field(default="ticketing-genie")
    GCS_TARGET_SERVICE_ACCOUNT: str = Field(
        default="gwx-cloudrun-sa-01@gwx-internship-01.iam.gserviceaccount.com"
    )

    ASSIGNING_LOCK_TIMEOUT_MINUTES: int = Field(default=10)
@lru_cache
def get_settings() -> Settings:
    return Settings()