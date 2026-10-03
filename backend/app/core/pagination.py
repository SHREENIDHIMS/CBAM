"""Cursor pagination (docs/API_SPEC.md section 1): ?limit=50&cursor=... -> {items, next_cursor}."""

import base64
import json
from typing import Any

from app.core.errors import InvalidRequestError

MAX_LIMIT = 200
DEFAULT_LIMIT = 50


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


def encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidRequestError("The cursor is not valid") from exc
    if not isinstance(payload, dict):
        raise InvalidRequestError("The cursor is not valid")
    return payload
