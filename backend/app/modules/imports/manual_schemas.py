"""Request and response shapes for manual entry and value corrections (R1-004, R1-010).

Numbers travel as strings (never floats): they are checked by the same rules a file row meets.
"""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EntryProblem(BaseModel):
    field: str
    code: str
    message: str


class ManualEntryIn(BaseModel):
    """One keyed line. The same validation as a file row applies; `reason` is mandatory."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=1000)
    mrn: str = Field(min_length=1, max_length=100)
    acceptance_date: date
    importer_eori: str = Field(min_length=1, max_length=20)
    declarant_eori: str | None = Field(default=None, max_length=20)
    representative_eori: str | None = Field(default=None, max_length=20)
    representation_type: Literal["self", "direct", "indirect"] | None = None
    item_no: int = Field(ge=1, le=99999)
    commodity_code: str = Field(max_length=20)
    net_mass_kg: str = Field(max_length=40)
    customs_value: str = Field(max_length=40)
    customs_value_currency: str = Field(max_length=3)
    origin_country: str = Field(max_length=2)
    valuation_basis: str | None = Field(default=None, max_length=200)
    cpc: str | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=4096)
    supplier_ref: str | None = Field(default=None, max_length=200)


class ManualEntryOut(BaseModel):
    batch_id: UUID
    declaration_id: UUID
    line_id: UUID
    version: int
    # created: a new line; superseded: a new version of a line a file gave; duplicate_seen: the
    # same facts were already there (nothing new, the keyed row is kept as a sighting).
    result: Literal["created", "superseded", "duplicate_seen"]
    warnings: list[EntryProblem]
    replayed: bool = False  # true when an earlier request with the same Idempotency-Key answered


class ValueCorrectionIn(BaseModel):
    """Correct the customs value (and optionally its currency) of the CURRENT version of a line."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=1000)
    customs_value: str = Field(max_length=40)
    customs_value_currency: str | None = Field(default=None, max_length=3)


class ValueCorrectionOut(BaseModel):
    batch_id: UUID
    declaration_id: UUID
    line_id: UUID
    superseded_line_id: UUID
    version: int
    customs_value_source: str
    customs_value_currency: str
    customs_value_gbp: str | None
    replayed: bool = False
