import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_refuses_scaled_outreach_days() -> None:
    """R1-053: production must run the outreach schedule at 86400 s/day."""
    with pytest.raises(ValidationError):
        Settings(app_env="production", outreach_time_scale_seconds_per_day=60)
    assert Settings(app_env="staging", outreach_time_scale_seconds_per_day=60)
