"""Application settings, read from environment variables (and an optional .env file)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/featureflags"
    cache_url: str | None = None
    cache_ttl_seconds: int = Field(default=60, ge=1, le=3600)
    api_key: str | None = None
    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        # DigitalOcean provides postgresql:// URLs, but SQLAlchemy needs the driver in the scheme.
        for scheme in ("postgresql://", "postgres://"):
            if url.startswith(scheme):
                return "postgresql+psycopg://" + url.removeprefix(scheme)
        return url

    @field_validator("cache_url", "api_key")
    @classmethod
    def blank_means_unset(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def require_api_key_in_production(self) -> "Settings":
        if self.environment == "production" and not self.api_key:
            raise ValueError("API_KEY must be set when ENVIRONMENT=production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
