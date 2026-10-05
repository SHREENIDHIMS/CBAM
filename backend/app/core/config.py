"""Settings read from environment variables only (see .env.example)."""

from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PRODUCTION_SECONDS_PER_DAY = 86400


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"
    frontend_base_url: str = "http://localhost:5173"
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
    # SECRET. Backend only (inviting users); never in the frontend, logs or errors.
    supabase_service_role_key: SecretStr = SecretStr("")
    # How recent a login must be for sensitive actions (decided 3 Oct 2026: 15 minutes).
    recent_auth_minutes: int = 15
    # Product workflow, not law (CLAUDE.md rule 13): days overdue at which a task escalates.
    task_escalation_overdue_days: tuple[int, ...] = (7, 14, 28)
    # Supabase Storage (private buckets; the backend signs URLs, the frontend never lists).
    supabase_storage_bucket_imports: str = "customs-imports"
    # docs/SECURITY.md: signed URLs live at most 5 minutes.
    signed_url_ttl_seconds: int = Field(default=300, ge=1, le=300)
    # Operational limit for one uploaded customs file (bytes). Not law: tune per environment.
    import_max_file_bytes: int = 52_428_800
    # Uploads one client may have in flight at once in this process (429 above it).
    import_max_concurrent_uploads_per_tenant: int = Field(default=3, ge=1)
    # Operational limits for reading one customs file (product config, not law). A file that
    # breaks one is rejected with a file-level code and no content in the message.
    import_max_columns: int = Field(default=200, ge=1)
    import_max_heading_chars: int = Field(default=200, ge=1)
    import_max_cell_chars: int = Field(default=4096, ge=1)
    import_max_row_chars: int = Field(default=1_048_576, ge=1)
    # A chunk is saved when it reaches 500 rows or this many characters, whichever is first.
    import_chunk_max_bytes: int = Field(default=8_388_608, ge=1)
    # A batch that has been started this many times is a crash loop: it is marked failed.
    import_max_attempts: int = Field(default=8, ge=1)
    # A running job holds a lease this long and renews it after every chunk; an expired
    # lease means the worker died and the sweeper may take the batch over.
    import_lease_seconds: int = Field(default=300, ge=30)
    import_retry_margin_seconds: int = Field(default=5, ge=0)
    # Batches still received/queued after this long are re-queued by the sweeper.
    import_stale_batch_minutes: int = Field(default=10, ge=1)
    # Celery recycles a worker process above this much memory (KiB); 0 = off.
    celery_worker_max_memory_per_child_kb: int = Field(default=524_288, ge=0)
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
