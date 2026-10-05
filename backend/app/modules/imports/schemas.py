from datetime import date, datetime
from typing import Literal, Self
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
