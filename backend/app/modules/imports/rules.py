"""Import batch rules (R1-003). Pure functions: no database, clock or network.

Nothing here is law. The batch status machine and the file checks are product rules; the
database enforces the same status order with a trigger (migration 0009, CLAUDE.md rule 17).
"""

import codecs
import hashlib
import json
from collections.abc import Mapping
from datetime import date

from app.core.decisions import Decision

RULE_TRANSITION = "R1-003.batch_transition"
RULE_VERSION = "1"

# Order of the working states. A batch only moves to a later one.
PROGRESS_STATES: tuple[str, ...] = (
    "received",
    "queued",
    "parsing",
    "validating",
    "normalising",
)
TERMINAL_STATES: frozenset[str] = frozenset(
    {"completed", "completed_with_errors", "failed", "rejected"}
)
STATUSES: tuple[str, ...] = (*PROGRESS_STATES, *sorted(TERMINAL_STATES))

# Methods that bring a file. `manual_entry` has no file and `feed` is for a future HMRC/CDS
# feed (the platform must not assume one exists, R1-003), so neither is an upload.
UPLOAD_METHODS: tuple[str, ...] = (
    "get_customs_data",
    "cds_export",
    "data_request",
    "manual_upload",
)

_DELIMITERS = (b",", b";", b"\t", b"|")
_BOM = codecs.BOM_UTF8


def _decision(outcome: str, reason: str) -> Decision:
    return Decision(
        rule_id=RULE_TRANSITION,
        rule_version=RULE_VERSION,
        source_ids=(),
        outcome=outcome,
        reason=reason,
    )


def _rank(status: str) -> int:
    if status in TERMINAL_STATES:
        return len(PROGRESS_STATES)
    return PROGRESS_STATES.index(status)


def batch_transition(current: str, target: str) -> Decision:
    """ALLOWED or BLOCKED. Forward only; a terminal batch is locked."""
    if current not in STATUSES or target not in STATUSES:
        return _decision("BLOCKED", f"unknown status in {current!r} -> {target!r}")
    if current in TERMINAL_STATES:
        return _decision("BLOCKED", f"{current} is final; the batch is locked")
    if _rank(target) <= _rank(current):
        return _decision("BLOCKED", f"{current} -> {target} does not move forward")
    return _decision("ALLOWED", f"{current} -> {target}")


class Utf8Checker:
    """Feed a file chunk by chunk; says whether it is UTF-8 text (optional BOM, no NUL bytes).

    Binary formats (spreadsheets, archives, images, PDFs) fail on a NUL byte or on invalid
    UTF-8, so they are refused before anything is stored.
    """

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")()
        self._ok = True
        self._seen = 0
        self._head = b""

    @property
    def ok(self) -> bool:
        return self._ok

    def feed(self, chunk: bytes) -> bool:
        if not self._ok:
            return False
        self._seen += len(chunk)
        if len(self._head) < 4096:
            self._head += chunk[: 4096 - len(self._head)]
        if b"\x00" in chunk:
            self._ok = False
            return False
        try:
            self._decoder.decode(chunk, final=False)
        except UnicodeDecodeError:
            self._ok = False
        return self._ok

    def finish(self) -> bool:
        """True if the whole file was valid UTF-8 text and not empty."""
        if self._ok:
            try:
                self._decoder.decode(b"", final=True)  # a cut-off multi-byte character
            except UnicodeDecodeError:
                self._ok = False
        return self._ok and self._seen > 0

    def first_line_has_delimiter(self) -> bool:
        return looks_delimited(self._head)


def looks_delimited(head: bytes) -> bool:
    """True if the first line has a CSV-style delimiter (CDS reports have a header row)."""
    body = head[len(_BOM) :] if head.startswith(_BOM) else head
    first_line = body.split(b"\n", 1)[0]
    return any(d in first_line for d in _DELIMITERS)


def is_probably_csv_utf8(sample: bytes) -> bool:
    """Quick check of a leading sample: UTF-8 text without NUL bytes and a delimited header."""
    checker = Utf8Checker()
    checker.feed(sample)
    # A sample may stop inside a multi-byte character, so only the NUL/invalid-byte checks count.
    return checker.ok and len(sample) > 0 and looks_delimited(sample)


def safe_filename(name: str | None) -> str:
    """A display-only filename: no directories, no control characters, at most 255 characters.

    It is never used to build a storage key or a path.
    """
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(ch for ch in base if ch.isprintable()).strip()
    return cleaned[:255] or "upload.csv"


def request_fingerprint(declared: Mapping[str, str | None]) -> bytes:
    """SHA-256 of the declared metadata, order-independent. Same file + same fingerprint is a
    replay; same file + different fingerprint is a conflict."""
    canonical = json.dumps(dict(declared), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).digest()


def acquired_on_is_valid(acquired_on: date | None, as_of: date) -> bool:
    """The acquisition date cannot be in the future (UK date from the injected clock)."""
    return acquired_on is None or acquired_on <= as_of
