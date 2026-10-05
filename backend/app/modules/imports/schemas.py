from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

UploadMethod = Literal["get_customs_data", "cds_export", "data_request", "manual_upload"]
CdsReportType = Literal["import_item", "import_header", "import_tax_lines", "export_item"]
BatchStatus = Literal[
    "received",
    "queued",
    "parsing",
    "validating",
    "normalising",
    "completed",
    "completed_with_errors",
    "failed",
    "rejected",
]


class ImportBatchMetadata(BaseModel):
    """What the uploader declares about a file. Built from the multipart form fields."""

    model_config = ConfigDict(extra="forbid")

    acquisition_method: UploadMethod
    cds_report_type: CdsReportType | None = None
    # A UK (GB) or Northern Ireland (XI) EORI: two letters and twelve digits.
    eori: str | None = Field(default=None, pattern=r"^(GB|XI)[0-9]{12}$")
    window_start: date | None = None
    window_end: date | None = None
    source_owner: str | None = Field(default=None, max_length=200)
    acquired_on: date | None = None

    @model_validator(mode="after")
    def _window(self) -> Self:
        if self.window_end is not None and self.window_start is None:
            raise ValueError("window_start is needed with window_end")
        if (
            self.window_start is not None
            and self.window_end is not None
            and self.window_end < self.window_start
        ):
            raise ValueError("window_end cannot be before window_start")
        return self

    def declared(self) -> dict[str, str | None]:
        """Canonical text form, used for the replay fingerprint."""
        return {
            "acquisition_method": self.acquisition_method,
            "cds_report_type": self.cds_report_type,
            "eori": self.eori,
            "window_start": self.window_start.isoformat() if self.window_start else None,
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "source_owner": self.source_owner,
            "acquired_on": self.acquired_on.isoformat() if self.acquired_on else None,
        }


class ImportBatchOut(BaseModel):
    id: UUID
    status: BatchStatus
    file_sha256: str | None
    document_version_id: UUID | None
    filename: str | None
    acquisition_method: str
    cds_report_type: str | None
    eori: str | None
    window_start: date | None
    window_end: date | None
    source_owner: str | None
    acquired_on: date | None
    rows_total: int
    rows_processed: int
    rows_valid: int
    rows_rejected: int
    lines_created: int
    lines_unchanged: int
    failure_reason: str | None
    report_layout_version_id: UUID | None
    layout_status: str | None
    created_at: datetime | None
    created_by: UUID | None
    row_version: int


class ImportBatchCreated(ImportBatchOut):
    """The create response: `replayed` is true when the same file was already received."""

    replayed: bool


class ImportBatchPage(BaseModel):
    items: list[ImportBatchOut]
    next_cursor: str | None


class RowExceptionOut(BaseModel):
    """One problem found in an uploaded file. `message` is fixed text per `code`; it never
    contains a cell value."""

    id: UUID
    row_number: int
    field: str
    code: str
    severity: Literal["error", "warning"]
    message: str
    status: Literal["open", "resolved", "waived"]
    row_version: int


class RowExceptionPage(BaseModel):
    items: list[RowExceptionOut]
    next_cursor: str | None


EntryMethod = Literal["cds", "gcd", "manual", "correction"]
SourceRole = Literal["primary", "header", "tax_line", "duplicate_seen"]


class ImportLineOut(BaseModel):
    """One normalised customs line. Amounts and masses are decimal strings. There is no tax
    point, scope, quarter or threshold field: those are decided later and stored elsewhere
    (CLAUDE.md rule 3). `acceptance_date` is the date the report gave, NOT a tax point."""

    id: UUID
    declaration_id: UUID  # the version the line was created under
    mrn: str
    current_declaration_id: UUID
    declaration_superseded: bool  # true when `declaration_id` is no longer the current version
    acceptance_date: date  # of the CURRENT declaration version, as reported (not a tax point)
    item_no: int
    version: int
    supersedes_id: UUID | None
    is_current: bool
    commodity_code: str
    description: str | None
    net_mass_kg: Decimal
    customs_value_source: Decimal
    customs_value_currency: str
    customs_value_gbp: Decimal | None
    customs_value_gbp_note: str | None
    valuation_basis: str | None
    value_source: str
    value_override_reason: str | None
    country_of_origin_declared: str
    cpc: str | None
    batch_id: UUID
    source_row_id: UUID
    entry_method: EntryMethod
    change_reason: str | None
    created_at: datetime | None
    open_exceptions: int


class ImportLinePage(BaseModel):
    items: list[ImportLineOut]
    next_cursor: str | None


class PartyOut(BaseModel):
    id: UUID
    eori: str | None
    name: str | None


class DeclarationOut(BaseModel):
    id: UUID
    mrn: str
    version: int
    supersedes_id: UUID | None
    is_current: bool
    acceptance_date: date
    acceptance_at: datetime | None
    procedure_code: str | None
    additional_procedure_codes: list[str] | None
    importer: PartyOut | None
    declarant: PartyOut | None
    representative: PartyOut | None
    representation_type: Literal["self", "direct", "indirect", "unknown"]
    eori_context: Literal["GB", "XI"] | None
    entry_method: EntryMethod
    batch_id: UUID
    created_at: datetime | None


class SourceRowOut(BaseModel):
    """The raw row exactly as read from the file (header -> cell text)."""

    source_row_id: UUID
    role: SourceRole
    report_type: str | None
    batch_id: UUID
    row_number: int
    raw: dict[str, Any]
    row_sha256: str


class StoredFileOut(BaseModel):
    """What was stored for the batch's file. Not a download."""

    document_version_id: UUID | None
    filename: str | None
    sha256: str | None
    size_bytes: int | None


class LineBatchOut(BaseModel):
    id: UUID
    status: str
    acquisition_method: str
    cds_report_type: str | None
    eori_context: Literal["GB", "XI"] | None
    acquired_on: date | None
    window_start: date | None
    window_end: date | None


class LineVersionOut(BaseModel):
    id: UUID
    version: int
    supersedes_id: UUID | None
    is_current: bool
    change_reason: str | None
    batch_id: UUID
    created_at: datetime | None


class ImportLineDetail(BaseModel):
    line: ImportLineOut
    declaration: DeclarationOut
    sources: list[SourceRowOut]
    batch: LineBatchOut
    file: StoredFileOut
    versions: list[LineVersionOut]
    open_exceptions: list[RowExceptionOut]
