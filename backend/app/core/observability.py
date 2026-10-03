"""Sentry setup with PII scrubbing; disabled when no DSN is set."""

import re
from typing import Any

import sentry_sdk

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return _EMAIL.sub("[email]", value)
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def scrub_event(event: Any, _hint: Any) -> Any:
    return _scrub(event)


def init_sentry(dsn: str, environment: str) -> bool:
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        send_default_pii=False,
        before_send=scrub_event,
    )
    return True
