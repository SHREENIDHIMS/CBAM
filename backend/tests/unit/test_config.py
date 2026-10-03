import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_refuses_scaled_outreach_days() -> None:
    """R1-053: production must run the outreach schedule at 86400 s/day."""
    with pytest.raises(ValidationError):
        Settings(app_env="production", outreach_time_scale_seconds_per_day=60)
    assert Settings(app_env="staging", outreach_time_scale_seconds_per_day=60)


def test_env_example_values_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    """The formats documented in .env.example must load, including the JSON list."""
    monkeypatch.setenv("TASK_ESCALATION_OVERDUE_DAYS", "[7,14,28]")
    monkeypatch.setenv("RECENT_AUTH_MINUTES", "15")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "")
    s = Settings()
    assert s.task_escalation_overdue_days == (7, 14, 28)
    assert s.recent_auth_minutes == 15
    assert s.supabase_jwt_secret == ""


def test_shared_jwt_secret_is_refused_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production", supabase_jwt_secret="a-local-dev-secret")  # noqa: S106 - dummy
