from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env",),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # App
    APP_NAME: str = "LeadForge"
    APP_ENV: Literal["dev", "prod"] = "dev"
    SECRET_KEY: str = Field(default="change-me-in-prod", min_length=16)
    BASE_URL: str = "http://127.0.0.1:8000"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    SENTRY_DSN: str | None = None

    # Database
    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/leadforge"
    DB_POOL_SIZE: int = 5

    # LLM
    LLM_PROVIDER: Literal["openai", "ollama", "none"] = "none"
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_STRONG_MODEL: str = "gpt-4o"
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "qwen2.5:7b"
    LLM_TIMEOUT: int = 60
    LLM_MAX_RETRIES: int = 3

    # Sources
    APOLLO_API_KEY: str | None = None
    APOLLO_BASE_URL: str = "https://api.apollo.io"
    HUNTER_API_KEY: str | None = None
    HUNTER_BASE_URL: str = "https://api.hunter.io/v2"
    SKRAPP_API_KEY: str | None = None
    SKRAPP_BASE_URL: str = "https://api.skrapp.io"
    TAVILY_API_KEY: str | None = None
    SERPER_API_KEY: str | None = None
    GOOGLE_PLACES_API_KEY: str | None = None

    # Email (SMTP)
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str = "noreply@leadforge.local"
    SMTP_TLS: bool = True

    # Billing (Razorpay)
    RAZORPAY_KEY_ID: str | None = None
    RAZORPAY_KEY_SECRET: str | None = None
    RAZORPAY_WEBHOOK_SECRET: str | None = None
    RAZORPAY_MODE: Literal["test", "live"] = "test"

    # Key mode
    KEY_MODE: Literal["platform", "byo"] = "platform"

    # LeadOps integration
    LEADOPS_URL: str | None = None
    LEADOPS_TOKEN: str | None = None

    # Webhook
    WEBHOOK_TIMEOUT: int = 10

    # Credits / trial
    TRIAL_CREDITS: int = 10
    TRIAL_DAYS: int = 7

    # Admin seed
    ADMIN_EMAIL: str | None = None
    ADMIN_PASSWORD: str | None = None
    ADMIN_NAME: str = "Admin"

    # Rate limiting
    RATE_LIMIT_JOBS_PER_HOUR: int = 20

    @property
    def is_prod(self) -> bool:
        return self.APP_ENV == "prod"

    @property
    def cookie_secure(self) -> bool:
        return self.is_prod


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
