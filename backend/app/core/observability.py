"""Sentry setup with PII and secret scrubbing; disabled when no DSN is set."""

import re
from typing import Any

import sentry_sdk
from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber
from sentry_sdk.transport import Transport

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# Keys whose values are never sent, at any depth (on top of Sentry's own list). The Supabase
# service-role key must not reach an event even if it ends up in a header or an argument.
SECRET_KEYS: tuple[str, ...] = (
    "service_key",
    "service_role_key",
    "key",
    "headers",
    "apikey",
    "authorization",
)


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


def init_sentry(dsn: str, environment: str, *, transport: Transport | None = None) -> bool:
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        send_default_pii=False,
        # Local variables and arguments can hold secrets or personal data: never attach them.
        include_local_variables=False,
        event_scrubber=EventScrubber(recursive=True, denylist=[*DEFAULT_DENYLIST, *SECRET_KEYS]),
        before_send=scrub_event,
        transport=transport,
    )
    return True
