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
    # Placeholder until BRAND-DEC-015 fixes the product name and domain.
    error_type_base: str = "https://cbam.example/errors/"
    # Supabase Auth (JWT verification). Keys come from the project JWKS.
    supabase_url: str = ""
    supabase_jwt_audience: str = "authenticated"
    # Local development only (older Supabase CLI signs with a shared secret). Refused in
    # production, where only asymmetric keys from the JWKS are accepted.
    supabase_jwt_secret: str = ""
    # How recent a login must be for sensitive actions (decided 3 Oct 2026: 15 minutes).
    recent_auth_minutes: int = 15
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

    @model_validator(mode="after")
    def _no_shared_secret_in_production(self) -> "Settings":
        if self.app_env == "production" and self.supabase_jwt_secret:
            raise ValueError("SUPABASE_JWT_SECRET must not be set in production; use the JWKS")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
