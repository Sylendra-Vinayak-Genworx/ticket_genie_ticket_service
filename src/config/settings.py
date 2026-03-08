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

    # App
    log_level: str = Field(default="INFO")
    environment: str = Field(default="development")

    # Database
    DATABASE_URL: str

    secret_key: str = Field(default="change-me-at-least-32-chars-long-here")
    algorithm: str = Field(default="HS256")

    auth_service_url: str = Field(default="http://localhost:8001")
    
    # SendGrid
    SENDGRID_API_KEY: str = Field(default="")
    FROM_EMAIL: str = Field(default="noreply@ticketinggenie.com")

    # Celery
    CELERY_BROKER_URL: str = Field(default="redis://localhost:6379/0")
    CELERY_RESULT_BACKEND: str = Field(default="redis://localhost:6379/1")
    DEFAULT_RESPONSE_TIME_MINUTES: int = 480       # 8 h
    DEFAULT_RESOLUTION_TIME_MINUTES: int = 2880    # 48 h
    DEFAULT_ESCALATION_AFTER_MINUTES: int = 120    # 2 h
    LEAD_TIMEOUT_MINUTES: int = Field(default=15)

    groq_api_key: str = Field(default="")

    AUTO_CLOSE_AFTER_HOURS: int = Field(default=72*60)

    # Similarity routing
    SIMILARITY_THRESHOLD: float = Field(default=0.60)

    MAX_OPEN_TICKETS: int = Field(default=10)
    HF_TOKEN: str = Field(default="")
    FRONTEND_URL:str=Field("http://localhost:5173")


@lru_cache
def get_settings() -> Settings:
    return Settings()