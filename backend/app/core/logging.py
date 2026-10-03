"""Structured JSON logs with request/tenant/user IDs and no personal data.

CLAUDE.md section 9: log IDs, never names, emails or phone numbers.
"""

import logging
import re
import sys
from contextvars import ContextVar
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


# FastAPI runs sync dependencies in a thread pool with a *copy* of the context, so anything
# they bind with contextvars never reaches the route. A per-request dict is shared by
# reference instead: the middleware creates it, dependencies update it in place.
_request_scope: ContextVar[dict[str, Any] | None] = ContextVar("request_scope", default=None)


def start_request_scope() -> None:
    _request_scope.set({})


def bind_context(**ids: Any) -> None:
    """Bind request_id / tenant_id / user_id / job_id to every following log line."""
    scope = _request_scope.get()
    if scope is not None:
        scope.update(ids)
    else:
        bind_contextvars(**ids)


def clear_context() -> None:
    clear_contextvars()
    _request_scope.set(None)


def current_context() -> dict[str, Any]:
    """The IDs bound so far (for tests and diagnostics)."""
    merged: dict[str, Any] = dict(structlog.contextvars.get_contextvars())
    merged.update(_request_scope.get() or {})
    return merged


def merge_request_scope(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    for key, value in (_request_scope.get() or {}).items():
        event_dict.setdefault(key, value)
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper(), force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            merge_request_scope,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            scrub_pii,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        # Resolve sys.stdout when a logger is created, not when logging is configured.
        logger_factory=lambda *_args: structlog.PrintLogger(file=sys.stdout),
        cache_logger_on_first_use=False,
    )
