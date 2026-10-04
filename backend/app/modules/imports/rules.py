"""Import batch rules (R1-003). Pure functions: no database, clock or network.

Nothing here is law. The batch status machine and the file checks are product rules; the
database enforces the same status order with a trigger (migration 0009, CLAUDE.md rule 17).
"""

import codecs
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

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
# Finished without a usable result: kept as history, never blocks sending the same bytes again.
HISTORY_STATES: tuple[str, ...] = ("failed", "rejected")
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


_FAILURE_CODE = re.compile(r"^[a-z0-9_]{1,64}$")


def is_failure_code(value: str) -> bool:
    """A failure reason is a short code such as `unreadable_header`, never free text: parser
    messages can quote cell values, which may be personal data, and the reason is audited."""
    return _FAILURE_CODE.match(value) is not None


# --- Row validation (R1-025) -------------------------------------------------------------
#
# Format and presence checks only. No scope, no tax point, no threshold decision is made here:
# the acceptance date is kept as the customs report gave it and is NOT a tax point (CLAUDE.md
# rule 3). The commodity code is not looked up in the scope list (that is Phase 4). The column
# names a report really uses come from the `cds_report_layouts` reference dataset (DATA-DEC-002,
# provisional); nothing about HMRC's real headings is written here.

RULE_ROW_VALIDATION = "R1-025.row_validation"

# The product's own vocabulary for "what a column means". A layout row maps a file column to
# one of these; a column with any other (or no) target is kept in the raw row and ignored.
CANONICAL_FIELDS: frozenset[str] = frozenset(
    {
        "declaration.mrn",
        "declaration.acceptance_date",
        "declaration.eori",
        "line.item_no",
        "line.commodity_code",
        "line.net_mass_kg",
        "line.customs_value",
        "line.customs_value_currency",
        "line.origin_country",
        "line.valuation_basis",
        "line.cpc",
        "line.supplier_ref",
        "line.description",
    }
)

# Shapes of the stored numbers (docs/TECHNICAL_SPEC.md section 5): net mass NUMERIC(20,6),
# source money NUMERIC(24,8). These are storage limits, not regulatory values.
_MASS_INT_DIGITS, _MASS_SCALE = 14, 6
_VALUE_INT_DIGITS, _VALUE_SCALE = 16, 8
DEFAULT_DATE_FORMAT = "%Y-%m-%d"  # when a layout row declares none

# code -> (severity, fixed message). Messages never contain a cell value: a cell can be
# personal or commercial data, and the report is exported (docs/SECURITY.md).
ISSUES: dict[str, tuple[str, str]] = {
    "MRN_MISSING": ("error", "The declaration reference (MRN) is empty. Fill it in and re-upload."),
    "ITEM_NO_MISSING": ("error", "The item number is empty. Fill it in and re-upload."),
    "ITEM_NO_INVALID": (
        "error",
        "The item number must be a whole number of 1 or more, up to 5 digits.",
    ),
    "COMMODITY_CODE_MISSING": (
        "error",
        "The commodity code is empty. Enter the 8 to 10 digit code from the declaration.",
    ),
    "COMMODITY_CODE_INVALID": (
        "error",
        "The commodity code must be 8 to 10 digits with no spaces or letters.",
    ),
    "NET_MASS_MISSING": ("error", "The net mass is empty. Enter the net mass in kilograms."),
    "NET_MASS_INVALID": (
        "error",
        "The net mass must be a plain number of kilograms, zero or more, with no units "
        "or thousands separators.",
    ),
    "NET_MASS_PRECISION": (
        "error",
        "The net mass has more than 6 decimal places. It is not rounded for you: "
        "correct it at source and re-upload.",
    ),
    "ACCEPTANCE_DATE_MISSING": ("error", "The acceptance date is empty. Fill it in and re-upload."),
    "ACCEPTANCE_DATE_INVALID": (
        "error",
        "The acceptance date is not a valid date in the format this report uses.",
    ),
    "ORIGIN_MISSING": ("error", "The country of origin is empty. Enter the 2-letter country code."),
    "ORIGIN_INVALID": (
        "error",
        "The country of origin must be a 2-letter code in capitals, such as DE.",
    ),
    "VALUE_MISSING": ("error", "The customs value is empty. Enter the value as declared."),
    "VALUE_INVALID": (
        "error",
        "The customs value must be a plain number, zero or more, with no currency symbol "
        "or thousands separators.",
    ),
    "CURRENCY_MISSING": ("error", "The currency is empty. Enter the 3-letter currency code."),
    "CURRENCY_INVALID": (
        "error",
        "The currency must be a 3-letter code in capitals, such as EUR.",
    ),
    "SUPPLIER_UNMAPPED": (
        "warning",
        "No supplier is named on this row, so it cannot be linked to a supplier yet. "
        "This does not stop the row being used.",
    ),
    "ROW_TOO_LONG": (
        "error",
        "The row has more cells than the header row. Check for an unquoted comma and re-upload.",
    ),
    "ROW_TOO_SHORT": (
        "error",
        "The row has fewer cells than the header row. Check for a missing cell and re-upload.",
    ),
    # file-level problems (row number 0)
    "COLUMN_MISSING": (
        "error",
        "A required column is missing from the file. Add the column named in the Field "
        "column and upload the file again.",
    ),
    "HEADER_MISSING": (
        "error",
        "The header row is empty. Upload a file that starts with headings.",
    ),
    "HEADER_DUPLICATE": (
        "error",
        "Two columns in the header row have the same heading. Rename one and upload again.",
    ),
    "REPORT_TYPE_MISSING": (
        "error",
        "The report type was not declared at upload, so the layout cannot be chosen. "
        "Upload the file again and choose the report type.",
    ),
    "LAYOUT_NOT_ACTIVE": (
        "error",
        "No active column layout exists for this report type, so the file cannot be read yet. "
        "Ask the domain owner to activate the layout, then upload the file again.",
    ),
    "FILE_UNREADABLE": (
        "error",
        "The file could not be read as CSV. Check for a very long cell or a broken quote "
        "and upload it again.",
    ),
}
FILE_LEVEL_CODES: frozenset[str] = frozenset(
    {
        "COLUMN_MISSING",
        "HEADER_MISSING",
        "HEADER_DUPLICATE",
        "REPORT_TYPE_MISSING",
        "LAYOUT_NOT_ACTIVE",
        "FILE_UNREADABLE",
    }
)

LAYOUT_STATUSES: tuple[str, ...] = ("matched", "not_active", "columns_missing", "unreadable")
EXTRA_CELLS_KEY = "__extra_cells__"


def issue_severity(code: str) -> str:
    return ISSUES[code][0]


def issue_message(code: str) -> str:
    return ISSUES[code][1]


@dataclass(frozen=True)
class Issue:
    code: str
    field: str  # a canonical field name, or "" for a whole-row problem


@dataclass(frozen=True)
class LayoutColumn:
    name: str  # the heading in the file
    maps_to: str | None
    required: bool
    date_format: str | None = None


def layout_columns(rows: Sequence[Mapping[str, Any]], report_type: str) -> tuple[LayoutColumn, ...]:
    """The columns of one report type from the active `cds_report_layouts` rows."""
    return tuple(
        LayoutColumn(
            name=str(r["column_name"]),
            maps_to=r.get("maps_to") or None,
            required=bool(r["required"]),
            date_format=r.get("date_format") or None,
        )
        for r in rows
        if r["report_type"] == report_type
    )


def _norm(heading: str) -> str:
    return heading.replace("﻿", "").strip().casefold()


@dataclass(frozen=True)
class LayoutMatch:
    headers: tuple[str, ...]  # exactly as read
    duplicate_headers: bool
    missing_required: tuple[str, ...]  # layout column names, in layout order
    by_header: Mapping[str, LayoutColumn]  # file heading -> layout column (mapped ones only)

    @property
    def ok(self) -> bool:
        return not self.duplicate_headers and not self.missing_required


def match_layout(headers: Sequence[str], columns: Sequence[LayoutColumn]) -> LayoutMatch:
    """Match a file's headings to a layout by heading text (case and outer spaces ignored).

    Extra columns are fine and stay in the raw row; a missing required column fails the file.
    """
    by_norm: dict[str, str] = {}
    duplicate = False
    for heading in headers:
        key = _norm(heading)
        if key in by_norm:
            duplicate = True
        by_norm[key] = heading
    missing: list[str] = []
    mapped: dict[str, LayoutColumn] = {}
    for col in columns:
        found = by_norm.get(_norm(col.name))
        if found is None:
            if col.required:
                missing.append(col.name)
            continue
        if col.maps_to in CANONICAL_FIELDS:
            mapped[found] = col
    return LayoutMatch(
        headers=tuple(headers),
        duplicate_headers=duplicate,
        missing_required=tuple(missing),
        by_header=mapped,
    )


def raw_headers(cells: Sequence[str]) -> tuple[str, ...]:
    """Raw-row keys: the headings as read (a blank heading is named `column_N`)."""
    out: list[str] = []
    for i, cell in enumerate(cells):
        text = cell.replace("﻿", "", 1) if i == 0 else cell
        out.append(text if text.strip() else f"column_{i + 1}")
    return tuple(out)


def build_raw(headers: Sequence[str], cells: Sequence[str]) -> tuple[dict[str, Any], list[Issue]]:
    """Header -> cell text exactly as read. Extra cells go under one reserved key; a short row
    simply has fewer keys. Neither case drops or alters a cell."""
    raw: dict[str, Any] = dict(zip(headers, cells, strict=False))
    issues: list[Issue] = []
    if len(cells) > len(headers):
        raw[EXTRA_CELLS_KEY] = list(cells[len(headers) :])
        issues.append(Issue("ROW_TOO_LONG", ""))
    elif len(cells) < len(headers):
        issues.append(Issue("ROW_TOO_SHORT", ""))
    return raw, issues


def row_hash(raw: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(raw), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class MappedRow:
    values: Mapping[str, str]  # canonical field -> cell text, as read
    required: frozenset[str]
    date_formats: Mapping[str, str]
    mapped: frozenset[str]  # canonical fields this layout maps at all


def map_row(raw: Mapping[str, Any], match: LayoutMatch) -> MappedRow:
    values: dict[str, str] = {}
    required: set[str] = set()
    formats: dict[str, str] = {}
    mapped: set[str] = set()
    for heading, col in match.by_header.items():
        if col.maps_to is None:
            continue
        mapped.add(col.maps_to)
        cell = raw.get(heading)
        if isinstance(cell, str):
            values[col.maps_to] = cell
        if col.required:
            required.add(col.maps_to)
        if col.date_format:
            formats[col.maps_to] = col.date_format
    return MappedRow(values, frozenset(required), formats, frozenset(mapped))


_PLAIN_NUMBER = re.compile(r"^(?P<int>[0-9]+)(?:\.(?P<frac>[0-9]*))?$")
_COMMODITY = re.compile(r"^[0-9]{8,10}$")
_ITEM_NO = re.compile(r"^[0-9]{1,5}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


def parse_plain_decimal(text: str, *, int_digits: int, scale: int) -> tuple[Decimal | None, bool]:
    """(value, too_precise). Plain digits with an optional point only: no sign, exponent,
    separators, NaN or infinity. The value goes from text to Decimal directly, never through a
    binary float. More decimals than `scale` (ignoring trailing zeros) is reported, not rounded."""
    match = _PLAIN_NUMBER.match(text.strip())
    if match is None:
        return None, False
    whole = match.group("int").lstrip("0") or "0"
    frac = (match.group("frac") or "").rstrip("0")
    if len(whole) > int_digits:
        return None, False
    if len(frac) > scale:
        return None, True
    return Decimal(f"{whole}.{frac}" if frac else whole), False


def parse_date(text: str, date_format: str) -> date | None:
    try:
        return datetime.strptime(text.strip(), date_format).date()  # noqa: DTZ007 - date only
    except (ValueError, OverflowError):
        return None


def validate_row(row: MappedRow) -> tuple[Issue, ...]:
    """Format and presence problems for the fields the layout maps. Never raises, whatever the
    cell text. An empty cell is a problem only where the layout marks the column required."""
    issues: list[Issue] = []

    def cell(field: str) -> str | None:
        if field not in row.mapped:
            return None
        value = row.values.get(field, "").strip()
        if value == "":
            if field in row.required:
                issues.append(Issue(_MISSING[field], field))
            return None
        return value

    cell("declaration.mrn")
    if (value := cell("declaration.acceptance_date")) is not None and (
        parse_date(value, row.date_formats.get("declaration.acceptance_date", DEFAULT_DATE_FORMAT))
        is None
    ):
        issues.append(Issue("ACCEPTANCE_DATE_INVALID", "declaration.acceptance_date"))
    if (value := cell("line.item_no")) is not None and (
        _ITEM_NO.match(value) is None or int(value) < 1
    ):
        issues.append(Issue("ITEM_NO_INVALID", "line.item_no"))
    if (value := cell("line.commodity_code")) is not None and _COMMODITY.match(value) is None:
        issues.append(Issue("COMMODITY_CODE_INVALID", "line.commodity_code"))
    if (value := cell("line.net_mass_kg")) is not None:
        number, precise = parse_plain_decimal(value, int_digits=_MASS_INT_DIGITS, scale=_MASS_SCALE)
        if precise:
            issues.append(Issue("NET_MASS_PRECISION", "line.net_mass_kg"))
        elif number is None:
            issues.append(Issue("NET_MASS_INVALID", "line.net_mass_kg"))
    if (value := cell("line.customs_value")) is not None:
        number, precise = parse_plain_decimal(
            value, int_digits=_VALUE_INT_DIGITS, scale=_VALUE_SCALE
        )
        if number is None:
            issues.append(Issue("VALUE_INVALID", "line.customs_value"))
    if (value := cell("line.customs_value_currency")) is not None and (
        _CURRENCY.match(value) is None
    ):
        issues.append(Issue("CURRENCY_INVALID", "line.customs_value_currency"))
    if (value := cell("line.origin_country")) is not None and _COUNTRY.match(value) is None:
        issues.append(Issue("ORIGIN_INVALID", "line.origin_country"))
    # No supplier register exists until Phase 6, so a named supplier cannot be mapped yet and
    # is not flagged. A row that names none at all is a non-blocking warning.
    if "line.supplier_ref" in row.mapped and not row.values.get("line.supplier_ref", "").strip():
        issues.append(Issue("SUPPLIER_UNMAPPED", "line.supplier_ref"))
    return tuple(issues)


_MISSING: dict[str, str] = {
    "declaration.mrn": "MRN_MISSING",
    "declaration.acceptance_date": "ACCEPTANCE_DATE_MISSING",
    "line.item_no": "ITEM_NO_MISSING",
    "line.commodity_code": "COMMODITY_CODE_MISSING",
    "line.net_mass_kg": "NET_MASS_MISSING",
    "line.customs_value": "VALUE_MISSING",
    "line.customs_value_currency": "CURRENCY_MISSING",
    "line.origin_country": "ORIGIN_MISSING",
}


def row_is_valid(issues: Sequence[Issue]) -> bool:
    """A row with any error is rejected; a row with only warnings continues."""
    return all(issue_severity(i.code) != "error" for i in issues)


_CSV_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: str) -> str:
    """Stop spreadsheet formula injection: a cell that starts with = + - @ tab or CR gets a
    leading apostrophe (docs/SECURITY.md files checklist). Applied to every exported cell."""
    return "'" + value if value.startswith(_CSV_FORMULA_START) else value
