"""Import batch rules (R1-003). Pure functions: no database, clock or network.

Nothing here is law. The batch status machine and the file checks are product rules; the
database enforces the same status order with a trigger (migration 0009, CLAUDE.md rule 17).
"""

import codecs
import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
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


def window_is_valid(window_start: date | None, window_end: date | None, as_of: date) -> bool:
    """The report window cannot end (or start) after the day the file is received (UK date from
    the injected clock). The acquired date and the window end are the recency inputs that decide
    which of two different reports is newer, so neither may point at the future."""
    return all(d is None or d <= as_of for d in (window_start, window_end))


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
        "declaration.declarant_eori",
        "declaration.representative_eori",
        "declaration.representation_type",
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
    "SUPPLIER_MISSING": (
        "warning",
        "No supplier is named on this row, so it cannot be linked to a supplier. "
        "This does not stop the row being used.",
    ),
    "EORI_MISSING": ("error", "The EORI is empty. Fill it in and re-upload."),
    "VALUATION_BASIS_MISSING": (
        "error",
        "The valuation method is empty. Fill it in and re-upload.",
    ),
    "CPC_MISSING": ("error", "The customs procedure code is empty. Fill it in and re-upload."),
    "DESCRIPTION_MISSING": ("error", "The goods description is empty. Fill it in and re-upload."),
    "EORI_INVALID": (
        "error",
        "The EORI must be GB or XI followed by 12 digits, with no spaces.",
    ),
    "REPRESENTATION_TYPE_MISSING": (
        "error",
        "The representation type is empty. Fill it in and re-upload.",
    ),
    "REPRESENTATION_TYPE_INVALID": (
        "error",
        "The representation type must be one of: self, direct, indirect.",
    ),
    "FIELD_TOO_LONG": (
        "error",
        "A value is longer than the platform stores for that field. Shorten it at source "
        "and re-upload.",
    ),
    "DECLARATION_FACTS_CONFLICT": (
        "error",
        "Another row in this file gives the same declaration reference with different "
        "declaration details. Correct the file and re-upload.",
    ),
    "LINE_CONFLICT_IN_FILE": (
        "error",
        "Another row in this file has the same declaration reference and item number with "
        "different details. Correct the file and re-upload.",
    ),
    "SOURCE_CONFLICTS_WITH_CORRECTION": (
        "error",
        "This row differs from a value that was corrected or entered by hand. It was not "
        "applied; a reviewer must decide which value stands.",
    ),
    "MANUAL_ENTRY_OVER_FILE": (
        "error",
        "This declaration or line came from a customs file. A manual entry cannot change it: "
        "use a correction instead.",
    ),
    "OLDER_EXTRACT_CONFLICT": (
        "error",
        "This row differs from facts taken from a more recent report. It was not applied; "
        "a reviewer must decide which value stands.",
    ),
    "VALUE_PRECISION": (
        "error",
        "The customs value has more than 8 decimal places. It is not rounded for you: "
        "correct it at source and re-upload.",
    ),
    "ROW_TOO_LARGE": (
        "error",
        "A row is larger than the allowed size. Split the file or shorten the cells "
        "and upload it again.",
    ),
    "HEADER_TOO_MANY_COLUMNS": (
        "error",
        "The header row has more columns than are allowed. Remove unused columns and "
        "upload the file again.",
    ),
    "HEADER_TOO_LONG": (
        "error",
        "A heading in the header row is longer than allowed. Check that the first row "
        "is the real header row and upload again.",
    ),
    "LAYOUT_INVALID": (
        "error",
        "The active column layout is incomplete or ambiguous, so the file cannot be read. "
        "Ask the domain owner to fix the layout, then upload the file again.",
    ),
    "FILE_INFECTED": (
        "error",
        "The file was flagged by the malware scan and was not read. Do not open it; "
        "get a clean copy and upload it again.",
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
        "HEADER_TOO_MANY_COLUMNS",
        "HEADER_TOO_LONG",
        "ROW_TOO_LARGE",
        "LAYOUT_INVALID",
        "FILE_INFECTED",
    }
)

LAYOUT_STATUSES: tuple[str, ...] = (
    "matched",
    "not_active",
    "columns_missing",
    "unreadable",
    "invalid",
)
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


def layout_is_invalid(columns: Sequence[LayoutColumn]) -> bool:
    """A layout we must not guess about: a date column without its declared format, or two
    columns mapped to the same canonical field (one would silently overwrite the other)."""
    seen: set[str] = set()
    for col in columns:
        if col.maps_to not in CANONICAL_FIELDS:
            continue
        if col.maps_to in seen:
            return True
        seen.add(col.maps_to)
        if col.maps_to == "declaration.acceptance_date" and not col.date_format:
            return True
    return False


@dataclass(frozen=True)
class ImportLimits:
    """Operational limits for reading one file (settings, not law)."""

    max_columns: int
    max_heading_chars: int
    max_cell_chars: int
    max_row_chars: int
    chunk_max_chars: int
    max_attempts: int
    lease_seconds: int
    # Added to the retry back-off when a failed run hands its lease back, so a retry that fires a
    # moment early still finds the lease expired and does not stop on it.
    retry_margin_seconds: int = 5


def header_problem(cells: Sequence[str], limits: ImportLimits) -> str | None:
    """A file-level code if the header row breaks a limit, else None."""
    if len(cells) > limits.max_columns:
        return "HEADER_TOO_MANY_COLUMNS"
    if any(len(c) > limits.max_heading_chars for c in cells):
        return "HEADER_TOO_LONG"
    return None


def row_chars(cells: Sequence[str]) -> int:
    """Size of a row for the row and chunk budgets (characters in all cells)."""
    return sum(len(c) for c in cells) + len(cells)


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
EORI_SHAPE = re.compile(r"^(GB|XI)[0-9]{12}$")
# The product's own words for who acts for the importer. Which code of a real report means
# which is an open decision (DATA-DEC-025): nothing is inferred and liability is not decided here.
REPRESENTATION_TYPES: tuple[str, ...] = ("self", "direct", "indirect")
# Storage limits of the normalised columns (migration 0011), not regulatory values.
_MAX_LENGTH: dict[str, int] = {
    "declaration.mrn": 100,
    "line.cpc": 20,
    "line.valuation_basis": 200,
    "line.description": 4096,
}
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


def _check_item_no(value: str) -> str | None:
    return None if _ITEM_NO.match(value) and int(value) >= 1 else "ITEM_NO_INVALID"


def _check_commodity(value: str) -> str | None:
    # PROVISIONAL structural check (R1-005, R1-052; docs/OPEN_DECISIONS.md): 8 to 10 digits.
    # The exact code is preserved and nothing checks that it exists in the tariff.
    return None if _COMMODITY.match(value) else "COMMODITY_CODE_INVALID"


def _check_mass(value: str) -> str | None:
    number, precise = parse_plain_decimal(value, int_digits=_MASS_INT_DIGITS, scale=_MASS_SCALE)
    if precise:
        return "NET_MASS_PRECISION"
    return None if number is not None else "NET_MASS_INVALID"


def _check_value(value: str) -> str | None:
    number, precise = parse_plain_decimal(value, int_digits=_VALUE_INT_DIGITS, scale=_VALUE_SCALE)
    if precise:
        return "VALUE_PRECISION"
    return None if number is not None else "VALUE_INVALID"


def _check_currency(value: str) -> str | None:
    return None if _CURRENCY.match(value) else "CURRENCY_INVALID"


def _check_origin(value: str) -> str | None:
    return None if _COUNTRY.match(value) else "ORIGIN_INVALID"


def _check_eori(value: str) -> str | None:
    return None if EORI_SHAPE.match(value) else "EORI_INVALID"


def _check_representation(value: str) -> str | None:
    return None if value.casefold() in REPRESENTATION_TYPES else "REPRESENTATION_TYPE_INVALID"


_SHAPE_CHECKS: dict[str, Callable[[str], str | None]] = {
    "declaration.eori": _check_eori,
    "declaration.declarant_eori": _check_eori,
    "declaration.representative_eori": _check_eori,
    "declaration.representation_type": _check_representation,
    "line.item_no": _check_item_no,
    "line.commodity_code": _check_commodity,
    "line.net_mass_kg": _check_mass,
    "line.customs_value": _check_value,
    "line.customs_value_currency": _check_currency,
    "line.origin_country": _check_origin,
}

_MISSING: dict[str, str] = {
    "declaration.mrn": "MRN_MISSING",
    "declaration.acceptance_date": "ACCEPTANCE_DATE_MISSING",
    "declaration.eori": "EORI_MISSING",
    "declaration.declarant_eori": "EORI_MISSING",
    "declaration.representative_eori": "EORI_MISSING",
    "declaration.representation_type": "REPRESENTATION_TYPE_MISSING",
    "line.item_no": "ITEM_NO_MISSING",
    "line.commodity_code": "COMMODITY_CODE_MISSING",
    "line.net_mass_kg": "NET_MASS_MISSING",
    "line.customs_value": "VALUE_MISSING",
    "line.customs_value_currency": "CURRENCY_MISSING",
    "line.origin_country": "ORIGIN_MISSING",
    "line.valuation_basis": "VALUATION_BASIS_MISSING",
    "line.cpc": "CPC_MISSING",
    "line.supplier_ref": "SUPPLIER_MISSING",
    "line.description": "DESCRIPTION_MISSING",
}


def validate_row(row: MappedRow) -> tuple[Issue, ...]:
    """Format and presence problems for the fields the layout maps. Never raises, whatever the
    cell text. An empty cell is an error wherever the layout marks the column required; an empty
    supplier is always only a warning (supplier matching arrives with the register, Phase 6)."""
    issues: list[Issue] = []
    for field in sorted(row.mapped):
        value = row.values.get(field, "").strip()
        if value == "":
            if field == "line.supplier_ref" or field in row.required:
                issues.append(Issue(_MISSING[field], field))
            continue
        if len(value) > _MAX_LENGTH.get(field, 10**9):
            issues.append(Issue("FIELD_TOO_LONG", field))
            continue
        if field == "declaration.acceptance_date":
            date_format = row.date_formats.get(field)
            if date_format is None or parse_date(value, date_format) is None:
                issues.append(Issue("ACCEPTANCE_DATE_INVALID", field))
            continue
        check = _SHAPE_CHECKS.get(field)
        code = check(value) if check else None
        if code:
            issues.append(Issue(code, field))
    return tuple(issues)


def row_is_valid(issues: Sequence[Issue]) -> bool:
    """A row with any error is rejected; a row with only warnings continues."""
    return all(issue_severity(i.code) != "error" for i in issues)


_CSV_FORMULA_START = (
    "=",
    "+",
    "-",
    "@",
    ";",
    "|",
    "\t",
    "\r",
    "\n",
    "\uff1d",  # fullwidth = + - @
    "\uff0b",
    "\uff0d",
    "\uff20",
)
_CSV_QUOTES = "'\""


def csv_safe(value: str) -> str:
    """Stop spreadsheet formula injection: a cell that starts (after any spaces or quotes) with
    = + - @ ; | their fullwidth forms, or starts with tab, CR or LF, gets a leading apostrophe
    (docs/SECURITY.md files checklist). Applied to every exported cell."""
    start = 0
    while start < len(value) and (value[start].isspace() or value[start] in _CSV_QUOTES):
        start += 1
    if value.startswith(("\t", "\r", "\n")) or value[start:].startswith(_CSV_FORMULA_START):
        return "'" + value
    return value


class RecordLimitError(Exception):
    """A CSV record broke a size limit. `code` is a file-level issue code, never content."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RecordGuard:
    """Feeds physical lines and enforces limits on the CSV RECORD being built, so a record
    cannot grow without bound by hiding newlines inside quotes (the csv module holds the whole
    record in memory before returning it). Tracks quote state like the csv module does (a quote
    only opens a quoted field at the start of a field; a doubled quote inside one is a literal
    quote), the characters of the current record and the separators outside quotes.

    The first non-blank record is the header: its limits give HEADER_TOO_LONG and
    HEADER_TOO_MANY_COLUMNS; for data rows both give ROW_TOO_LARGE.
    """

    def __init__(self, *, max_record_chars: int, max_columns: int) -> None:
        self._max_chars = max_record_chars
        self._max_columns = max_columns
        self._in_quote = False
        self._at_start = True
        self._after_quote = False
        self._chars = 0
        self._separators = 0
        self._header_done = False
        self._nonblank = False

    def _fail(self, kind: str) -> RecordLimitError:
        if self._header_done:
            return RecordLimitError("ROW_TOO_LARGE")
        return RecordLimitError("HEADER_TOO_LONG" if kind == "chars" else "HEADER_TOO_MANY_COLUMNS")

    def feed(self, line: str) -> None:
        """Account for one physical line; raises RecordLimitError past a limit."""
        self._chars += len(line)
        if self._chars > self._max_chars:
            raise self._fail("chars")
        if line.strip("\r\n"):
            self._nonblank = True
        if '"' in line:
            self._scan(line)
        elif not self._in_quote:
            self._separators += line.count(",")
        if self._separators >= self._max_columns:
            raise self._fail("columns")
        if not self._in_quote and line.endswith(("\n", "\r")):
            self._header_done = self._header_done or self._nonblank
            self._nonblank = False
            self._chars = 0
            self._separators = 0
            self._at_start = True
            self._after_quote = False

    def _scan(self, line: str) -> None:
        in_quote, at_start, after_quote = self._in_quote, self._at_start, self._after_quote
        for ch in line:
            if in_quote:
                if ch == '"':
                    in_quote, after_quote = False, True
                continue
            if ch == '"' and (at_start or after_quote):
                in_quote, at_start, after_quote = True, False, False
            elif ch == ",":
                self._separators += 1
                at_start, after_quote = True, False
            else:
                at_start, after_quote = False, False
        self._in_quote, self._at_start, self._after_quote = in_quote, at_start, after_quote


# --- Normalisation (R1-005, R1-006, R1-010) -----------------------------------------------
#
# A validated row becomes facts about a declaration and one of its lines. Nothing is decided:
# no scope, tax point, quarter, threshold or liable person (Phase 4 and later). The commodity
# code, origin and valuation basis are kept as declared, the net mass at its stored scale, and
# the customs value in its own currency. There is no FX here (R1-035 is Phase 10), so the GBP
# value is only filled when the declared currency already is GBP and needs no rounding.

RULE_NORMALISE = "R1-005.normalise"
VALUE_SOURCES: tuple[str, ...] = ("declared", "manual", "correction")
# Reasons stored with a version that replaces another (short codes, never free text in audit).
REASON_SOURCE_CHANGED = "source_changed"
GBP_NOTE_FX_NEEDED = "non_gbp_no_fx"
GBP_NOTE_PRECISION = "gbp_more_than_2dp"
_GBP_SCALE = Decimal("0.01")

_ENTRY_METHODS: dict[str, str] = {
    "get_customs_data": "gcd",
    "cds_export": "cds",
    "data_request": "cds",
    # `manual` is reserved for human-keyed entry (R1-004). An uploaded file is `cds` whoever
    # prepared it; the mapping of data_request and manual_upload is provisional (DATA-DEC-025).
    "manual_upload": "cds",
    "manual_entry": "manual",
    "feed": "cds",
}


def entry_method_for(acquisition_method: str) -> str:
    """How the data entered the platform, from the batch's acquisition method."""
    return _ENTRY_METHODS[acquisition_method]


def parse_eori_context(eori: str | None) -> str | None:
    """`GB` or `XI` from a well-formed EORI, else None. A fact about the number, not about
    where goods moved (geography rules are Phase 4)."""
    if eori is None or EORI_SHAPE.match(eori) is None:
        return None
    return eori[:2]


def _canonical(value: object) -> object:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")  # 1.50 and 1.5 are the same fact
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool | int):
        return str(value)
    raise TypeError(f"cannot hash {type(value).__name__}")


# Mixed into every content hash and stored with the row. Adding or removing a hashed field must
# raise it AND ship a plan for existing rows, otherwise every stored row would look "changed".
HASH_VERSION = 1


def content_hash(parts: Mapping[str, object]) -> str:
    """SHA-256 of the facts of a declaration or line, stable across runs and key order. Strings,
    Decimals, dates, ints and None only: a float is refused (CLAUDE.md rule 5)."""
    canonical = {k: _canonical(v) for k, v in parts.items()}
    canonical["_hash_version"] = str(HASH_VERSION)
    text = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode()).hexdigest()


IMPORTER_DECLARED = "declared"
IMPORTER_FALLBACK = "batch_fallback"


@dataclass(frozen=True)
class NormalisationContext:
    batch_eori: str | None  # the EORI declared for the batch, used when the row has none
    entry_method: str
    # How the facts were derived (R1-010). A file's rows are `declared`; a hand-keyed entry is
    # `manual` and then MUST carry the reason it was keyed (a database check enforces it).
    value_source: str = "declared"
    override_reason: str | None = None
    change_reason: str = REASON_SOURCE_CHANGED  # recorded when a new version supersedes one


@dataclass(frozen=True)
class DeclarationFacts:
    mrn: str
    acceptance_date: date
    importer_eori: str | None
    declarant_eori: str | None
    representative_eori: str | None
    representation_type: str  # self | direct | indirect | unknown (never inferred)
    eori_context: str | None
    content_sha256: str
    # `declared` (the row named the importer), `batch_fallback` (taken from the batch's EORI, an
    # inference the liable-person engine must not rely on, R1-036) or None (no importer at all).
    importer_eori_source: str | None = None


@dataclass(frozen=True)
class NormalisedLine:
    declaration: DeclarationFacts
    item_no: int
    commodity_code: str
    description: str | None
    net_mass_kg: Decimal
    customs_value_source: Decimal
    customs_value_currency: str
    customs_value_gbp: Decimal | None
    customs_value_gbp_note: str | None
    valuation_basis: str | None
    value_source: str
    country_of_origin_declared: str
    cpc: str | None
    content_sha256: str


@dataclass(frozen=True)
class NormalisationResult:
    line: NormalisedLine | None
    issues: tuple[Issue, ...]


# What an item report must map (and the file must carry) for a line to be built.
LINE_FIELDS: tuple[str, ...] = (
    "declaration.mrn",
    "declaration.acceptance_date",
    "line.item_no",
    "line.commodity_code",
    "line.net_mass_kg",
    "line.customs_value",
    "line.customs_value_currency",
    "line.origin_country",
)


def missing_line_fields(match: LayoutMatch) -> tuple[str, ...]:
    """Canonical fields an item report needs for normalisation that this layout does not map
    to a heading present in the file. Their rows could only fail one by one, so the file is
    refused up front instead."""
    present = {col.maps_to for col in match.by_header.values()}
    return tuple(f for f in LINE_FIELDS if f not in present)


def line_key(row: MappedRow) -> tuple[str, int] | None:
    """(MRN, item number) that identifies a line across files, or None if either is unusable."""
    mrn = row.values.get("declaration.mrn", "").strip()
    item = row.values.get("line.item_no", "").strip()
    if not mrn or _check_item_no(item) is not None:
        return None
    return mrn, int(item)


def _text(row: MappedRow, field: str) -> str | None:
    value = row.values.get(field, "").strip()
    return value or None


def customs_value_gbp(value: Decimal, currency: str) -> tuple[Decimal | None, str | None]:
    """(GBP value, note). Set only for a GBP declaration that needs no rounding; otherwise
    None and a short note saying why. Nothing is converted or rounded here."""
    if currency != "GBP":
        return None, GBP_NOTE_FX_NEEDED
    if value != value.quantize(_GBP_SCALE):
        return None, GBP_NOTE_PRECISION
    return value.quantize(_GBP_SCALE), None


def normalise_row(row: MappedRow, ctx: NormalisationContext) -> NormalisationResult:
    """Facts for one validated row, or the issues that stop it. Pure and total: never raises
    for any cell text (a row that passed `validate_row` always normalises)."""
    issues: list[Issue] = []
    mrn = _text(row, "declaration.mrn")
    accepted_text = _text(row, "declaration.acceptance_date")
    date_format = row.date_formats.get("declaration.acceptance_date")
    accepted = parse_date(accepted_text, date_format) if accepted_text and date_format else None
    item = _text(row, "line.item_no") or ""
    code = _text(row, "line.commodity_code") or ""
    mass, _ = parse_plain_decimal(
        _text(row, "line.net_mass_kg") or "", int_digits=_MASS_INT_DIGITS, scale=_MASS_SCALE
    )
    amount, _ = parse_plain_decimal(
        _text(row, "line.customs_value") or "", int_digits=_VALUE_INT_DIGITS, scale=_VALUE_SCALE
    )
    currency = _text(row, "line.customs_value_currency") or ""
    origin = _text(row, "line.origin_country") or ""
    for field, bad in (
        ("declaration.mrn", mrn is None),
        ("declaration.acceptance_date", accepted is None),
        ("line.item_no", _check_item_no(item) is not None),
        ("line.commodity_code", _check_commodity(code) is not None),
        ("line.net_mass_kg", mass is None),
        ("line.customs_value", amount is None),
        ("line.customs_value_currency", _check_currency(currency) is not None),
        ("line.origin_country", _check_origin(origin) is not None),
    ):
        if bad:
            issues.append(Issue(_normalise_code(field), field))
    given = _text(row, "declaration.representation_type")
    kind = "unknown" if given is None else given.casefold()
    if given is not None and kind not in REPRESENTATION_TYPES:
        issues.append(Issue("REPRESENTATION_TYPE_INVALID", "declaration.representation_type"))
    eoris = {
        field: _text(row, field)
        for field in (
            "declaration.eori",
            "declaration.declarant_eori",
            "declaration.representative_eori",
        )
    }
    importer_declared = eoris["declaration.eori"] is not None
    eoris["declaration.eori"] = eoris["declaration.eori"] or ctx.batch_eori
    issues.extend(
        Issue("EORI_INVALID", field) for field, v in eoris.items() if v and _check_eori(v)
    )
    if issues or mrn is None or accepted is None or mass is None or amount is None or origin == "":
        return NormalisationResult(None, tuple(issues))

    importer = eoris["declaration.eori"]
    importer_source = (
        None if importer is None else IMPORTER_DECLARED if importer_declared else IMPORTER_FALLBACK
    )
    hashed: dict[str, object] = {
        "mrn": mrn,
        "acceptance_date": accepted,
        "importer_eori": importer,
        "declarant_eori": eoris["declaration.declarant_eori"],
        "representative_eori": eoris["declaration.representative_eori"],
        "representation_type": kind,
    }
    if importer_source == IMPORTER_FALLBACK:  # a declared importer keeps its original hash
        hashed["importer_eori_source"] = importer_source
    decl_hash = content_hash(hashed)
    declaration = DeclarationFacts(
        mrn=mrn,
        acceptance_date=accepted,
        importer_eori=importer,
        declarant_eori=eoris["declaration.declarant_eori"],
        representative_eori=eoris["declaration.representative_eori"],
        representation_type=kind,
        eori_context=parse_eori_context(importer),
        content_sha256=decl_hash,
        importer_eori_source=importer_source,
    )
    gbp, note = customs_value_gbp(amount, currency)
    description = _text(row, "line.description")
    basis = _text(row, "line.valuation_basis")
    cpc = _text(row, "line.cpc")
    # The line hash covers its own facts and its declaration's, so a changed declaration
    # makes every line seen in the file a new version under the new declaration.
    line_hash = content_hash(
        {
            "declaration": decl_hash,
            "item_no": int(item),
            "commodity_code": code,
            "description": description,
            "net_mass_kg": mass,
            "customs_value_source": amount,
            "customs_value_currency": currency,
            "valuation_basis": basis,
            "country_of_origin_declared": origin,
            "cpc": cpc,
        }
    )
    line = NormalisedLine(
        declaration=declaration,
        item_no=int(item),
        commodity_code=code,
        description=description,
        net_mass_kg=mass,
        customs_value_source=amount,
        customs_value_currency=currency,
        customs_value_gbp=gbp,
        customs_value_gbp_note=note,
        valuation_basis=basis,
        value_source=ctx.value_source,
        country_of_origin_declared=origin,
        cpc=cpc,
        content_sha256=line_hash,
    )
    return NormalisationResult(line, ())


def _normalise_code(field: str) -> str:
    """The validation code for a missing or malformed field (normalising an unchecked row)."""
    return {
        "declaration.mrn": "MRN_MISSING",
        "declaration.acceptance_date": "ACCEPTANCE_DATE_INVALID",
        "line.item_no": "ITEM_NO_INVALID",
        "line.commodity_code": "COMMODITY_CODE_INVALID",
        "line.net_mass_kg": "NET_MASS_INVALID",
        "line.customs_value": "VALUE_INVALID",
        "line.customs_value_currency": "CURRENCY_INVALID",
        "line.origin_country": "ORIGIN_INVALID",
    }[field]


def reconcile(existing_hash: str | None, incoming_hash: str, *, same_batch: bool = False) -> str:
    """`new` (no current version), `same` (identical facts: only the sighting is recorded),
    `changed` (a new version supersedes the old) or `conflict` (two different versions of one
    key inside the SAME file, which is a data error, not a source change)."""
    if existing_hash is None:
        return "new"
    if existing_hash == incoming_hash:
        return "same"
    return "conflict" if same_batch else "changed"


CORRECTED_ENTRY_METHODS: frozenset[str] = frozenset({"correction", "manual"})


def reconcile_version(
    *,
    current_hash: str | None,
    current_entry_method: str | None,
    current_value_source: str | None,
    current_batch_id: object,
    current_recency: date | None,
    earlier_hashes: frozenset[str],
    incoming_hash: str,
    incoming_batch_id: object,
    incoming_recency: date,
    incoming_entry_method: str | None = None,
) -> str:
    """What to do with a row whose key already has versions. Stale or hand-made data must never
    replace newer facts or a human's correction (CLAUDE.md rule 4):

    - `new`: no version yet;
    - `same`: identical to the current version (only a sighting is recorded);
    - `seen_earlier`: identical to an EARLIER version (a stale overlapping file): only a sighting;
    - `blocked_by_correction`: the current version was corrected or keyed by hand: a human decides;
    - `manual_over_file`: a hand-keyed entry differs from a version that came from a file; keying
      never replaces file data (R1-004): the correction route (R1-010, `imports:correct`) does;
    - `older_extract`: the report is older than the one the current version came from: a human
      decides (equal recency lets the later-loaded report win);
    - `conflict`: two different versions inside one file (a data error);
    - `changed`: a newer report with different facts supersedes the current version.

    Recency comes from user-declared batch metadata (acquired date, else window end, else the
    received date), bounded to not-after-receipt. A file with none of them counts as received
    today and so as NEWER than a dated older extract: a known limitation. Nothing is ever
    destroyed by this decision: both versions are kept and a review exception is raised.
    `hash_version` is NOT compared here: a HASH_VERSION bump needs a migration plan for the
    stored hashes first, or every row would look changed.
    """
    if current_hash is None:
        return "new"
    if current_hash == incoming_hash:
        return "same"
    if incoming_hash in earlier_hashes:
        return "seen_earlier"
    corrected = current_entry_method in CORRECTED_ENTRY_METHODS or current_value_source in (
        "correction",
        "manual",
    )
    if incoming_entry_method == "manual" and not corrected:
        return "manual_over_file"
    if corrected:
        return "blocked_by_correction"
    if incoming_batch_id == current_batch_id:
        return "conflict"
    if current_recency is not None and incoming_recency < current_recency:
        return "older_extract"
    return "changed"


def check_value_correction(permissions: frozenset[str], reason: str | None) -> Decision:
    """R1-010: a customs-value correction needs `imports:correct` and a written reason
    (`POST /import-lines/{id}/corrections` applies it). ALLOWED or BLOCKED."""
    if "imports:correct" not in permissions:
        return Decision(
            rule_id="R1-010.value_correction",
            rule_version=RULE_VERSION,
            source_ids=(),
            outcome="BLOCKED",
            reason="correcting a customs value needs the imports:correct permission",
        )
    if reason is None or not reason.strip() or len(reason.strip()) > 1000:
        return Decision(
            rule_id="R1-010.value_correction",
            rule_version=RULE_VERSION,
            source_ids=(),
            outcome="BLOCKED",
            reason="a customs-value correction needs a reason of 1 to 1000 characters",
        )
    return Decision(
        rule_id="R1-010.value_correction",
        rule_version=RULE_VERSION,
        source_ids=(),
        outcome="ALLOWED",
        reason="permission and reason present",
    )


REASON_VALUE_CORRECTED = "value_corrected"


def parse_corrected_value(value: str, currency: str) -> tuple[Decimal | None, tuple[Issue, ...]]:
    """The corrected customs value as a Decimal with the same shape checks a file row gets
    (plain digits, at most the stored precision, a non-negative amount, a three-letter currency),
    or the issues that stop it. Never rounds."""
    row = MappedRow(
        values={"line.customs_value": value, "line.customs_value_currency": currency},
        required=frozenset({"line.customs_value", "line.customs_value_currency"}),
        date_formats={},
        mapped=frozenset({"line.customs_value", "line.customs_value_currency"}),
    )
    issues = validate_row(row)
    if not row_is_valid(issues):
        return None, issues
    amount, _ = parse_plain_decimal(value.strip(), int_digits=_VALUE_INT_DIGITS, scale=_VALUE_SCALE)
    return amount, issues


# --- manual entry (R1-004) -------------------------------------------------------------------
# A keyed entry goes through the SAME validation and normalisation as a file row. It is read
# through an identity layout (each column is named after the canonical field it fills), so no
# second set of checks exists. This layout is product vocabulary, not a customs report layout and
# not law; the date is always ISO (`2027-01-05`) because a form has no regional format.

RULE_MANUAL_ENTRY = "R1-004.manual_entry"
REASON_MANUAL_ENTRY = "manual_entry"
MANUAL_DATE_FORMAT = "%Y-%m-%d"
MANUAL_REASON_KEY = "entry_reason"
MANUAL_REASON_MAX = 1000


def manual_layout() -> tuple[LayoutColumn, ...]:
    """One column per canonical field; the item fields a line needs are required."""
    return tuple(
        LayoutColumn(
            name=field,
            maps_to=field,
            required=field in LINE_FIELDS,
            date_format=MANUAL_DATE_FORMAT if field == "declaration.acceptance_date" else None,
        )
        for field in sorted(CANONICAL_FIELDS)
    )


def manual_raw(values: Mapping[str, str | None], reason: str) -> dict[str, str]:
    """The raw row of a keyed entry: the canonical field -> text as typed (blank fields left out)
    plus the reason. Stored as the source row, so the keyed facts keep their lineage."""
    raw = {k: v.strip() for k, v in values.items() if v is not None and v.strip()}
    raw[MANUAL_REASON_KEY] = reason.strip()
    return raw


def check_manual_reason(reason: str | None) -> Decision:
    """R1-004: a keyed entry needs a written reason of 1 to 1000 characters. ALLOWED or BLOCKED."""
    if reason is None or not reason.strip() or len(reason.strip()) > MANUAL_REASON_MAX:
        return Decision(
            rule_id=RULE_MANUAL_ENTRY,
            rule_version=RULE_VERSION,
            source_ids=(),
            outcome="BLOCKED",
            reason="a manual entry needs a reason of 1 to 1000 characters",
        )
    return Decision(
        rule_id=RULE_MANUAL_ENTRY,
        rule_version=RULE_VERSION,
        source_ids=(),
        outcome="ALLOWED",
        reason="reason present",
    )
