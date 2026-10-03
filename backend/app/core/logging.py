"""Structured JSON logs with request/tenant/user IDs and no personal data.

CLAUDE.md section 9: log IDs, never names, emails or phone numbers.
"""

import logging
import re
import sys
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars
from structlog.typing import EventDict, WrappedLogger

REDACTED = "[redacted]"
_PII_KEYS = frozenset(
    {
        "email",
        "name",
        "first_name",
        "last_name",
        "full_name",
        "phone",
        "telephone",
        "mobile",
        "address",
        "contact_name",
        "contact_email",
        "contact_phone",
    }
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def scrub_pii(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    for key in list(event_dict):
        if key.lower() in _PII_KEYS:
            event_dict[key] = REDACTED
        elif isinstance(event_dict[key], str):
            event_dict[key] = _EMAIL.sub("[email]", event_dict[key])
    return event_dict


def bind_context(**ids: Any) -> None:
    """Bind request_id / tenant_id / user_id / job_id to every following log line."""
    bind_contextvars(**ids)


def clear_context() -> None:
    clear_contextvars()


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper(), force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            scrub_pii,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )
