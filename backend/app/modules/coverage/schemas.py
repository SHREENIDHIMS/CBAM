from datetime import date, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

EORI_PATTERN = r"^(GB|XI)[0-9]{12}$"
ThirdPartyAccess = Literal["unknown", "requested", "granted", "revoked"]
ReportType = Literal["import_item", "import_header", "import_tax_lines", "export_item"]
PeriodState = Literal["loaded", "loaded_with_errors", "gap", "not_yet_available"]


class EoriIn(BaseModel):
    """Register an EORI (GB or XI) whose customs data must be covered from `tracking_from`."""

    model_config = ConfigDict(extra="forbid")

    eori: str = Field(pattern=EORI_PATTERN)
    tracking_from: date
    third_party_access: ThirdPartyAccess = "unknown"
    note: str | None = Field(default=None, max_length=500)


class EoriPatch(BaseModel):
    """Record third-party access or a note. `tracking_from` is not here on purpose: moving the
    first day to cover could hide a gap."""

    model_config = ConfigDict(extra="forbid")

    third_party_access: ThirdPartyAccess | None = None
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _something_to_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("send third_party_access or note")
        if "third_party_access" in self.model_fields_set and self.third_party_access is None:
            raise ValueError("third_party_access cannot be null")
        return self


class EoriOut(BaseModel):
    id: UUID
    eori: str
    tracking_from: date
    third_party_access: ThirdPartyAccess
    access_recorded_on: date | None
    note: str | None
    row_version: int
    created_at: datetime


class PeriodOut(BaseModel):
    covered_from: date
    covered_to: date
    state: PeriodState
    days: int


class OverlapOut(BaseModel):
    covered_from: date
    covered_to: date
    batch_ids: list[str]


class CalendarOut(BaseModel):
    """Coverage of one EORI and report type: day ranges by state, gaps and overlaps."""

    eori: str
    report_type: ReportType
    tracking_from: date
    registered: bool
    third_party_access: ThirdPartyAccess
    range_from: date
    range_to: date
    periods: list[PeriodOut]
    gaps: list[PeriodOut]
    overlaps: list[OverlapOut]
    complete: bool
    unavailable_latest_days: int | None
    dataset_version_ids: list[UUID]


class ScanOut(BaseModel):
    eoris_scanned: int
    gap_tasks_created: int
    month_tasks_created: int
