"""UUIDv7 primary keys generated in the app (docs/DATABASE.md section 1)."""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """Time-ordered UUID (RFC 9562 v7): 48-bit unix ms, version 7, random tail."""
    millis = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (millis & 0xFFFFFFFFFFFF) << 80
    value |= 0x7 << 76
    value |= ((rand >> 62) & 0xFFF) << 64
    value |= 0b10 << 62
    value |= rand & 0x3FFFFFFFFFFFFFFF
    return uuid.UUID(int=value)
