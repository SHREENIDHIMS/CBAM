from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SourceOut(BaseModel):
    id: UUID
    source_id: str
    title: str
    source_type: str
    url: str | None
    publication_date: date | None
    status: str
    commencement_date: date | None
    effective_from: date | None
    effective_to: date | None
    retrieved_at: datetime | None
    notes: str | None
    row_version: int


class SourceStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["laid", "in_force", "commenced", "superseded"]
    reason: str = Field(min_length=1, max_length=2000)
    commencement_date: date | None = None


class DatasetOut(BaseModel):
    id: UUID
    name: str
    active_version: str | None
    pending_versions: int


class VersionOut(BaseModel):
    id: UUID
    dataset: str
    version: str
    source_ref: str
    source_status: str
    checksum_sha256: str
    effective_from: date
    effective_to: date | None
    is_fixture: bool
    row_count: int
    status: str
    loaded_at: datetime
    activated_by: UUID | None
    activated_at: datetime | None
    retired_at: datetime | None
    has_impact_report: bool
    row_version: int
    notes: str | None


class VersionDetailOut(VersionOut):
    impact_report: dict[str, Any] | None
