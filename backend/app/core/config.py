"""Settings read from environment variables only (see .env.example)."""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PRODUCTION_SECONDS_PER_DAY = 86400


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"
    database_url: str = ""
    redis_url: str = "redis://127.0.0.1:6379/0"
    sentry_dsn: str = ""
    sentry_environment: str = "local"
    # R1-053: seconds that count as one "day" in the outreach schedule.
    outreach_time_scale_seconds_per_day: int = PRODUCTION_SECONDS_PER_DAY

    @model_validator(mode="after")
    def _production_time_scale(self) -> "Settings":
        if (
            self.app_env == "production"
            and self.outreach_time_scale_seconds_per_day != PRODUCTION_SECONDS_PER_DAY
        ):
            raise ValueError("OUTREACH_TIME_SCALE_SECONDS_PER_DAY must be 86400 in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
