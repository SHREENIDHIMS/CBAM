"""The manifest that sits beside each dataset file (docs/TECHNICAL_SPEC.md section 6)."""

import re
from datetime import date, datetime
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.errors import InvalidRequestError

SourceType = Literal["legislation", "regulation", "notice", "system_boundary", "guidance"]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(min_length=1)
    source_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    source_title: str = Field(min_length=1)
    source_type: SourceType
    source_url: str | None = None
    publication_date: date | None = None
    commencement_date: date | None = None
    retrieved_at: date | datetime
    # What the file claims when it first registers its source. The loader accepts only draft
    # or laid: a domain owner alone sets in_force / commenced in the registry (GOV-DEC-009).
    source_status: Literal["draft", "laid"]
    effective_from: date
    effective_to: date | None = None
    checksum_sha256: str
    fixture: bool = False
    notes: str | None = None

    @field_validator("checksum_sha256")
    @classmethod
    def _checksum(cls, value: str) -> str:
        if not _SHA256.match(value):
            raise ValueError("checksum_sha256 must be 64 lowercase hex characters")
        return value

    @field_validator("version", mode="before")
    @classmethod
    def _version_is_text(cls, value: object) -> object:
        # An unquoted `version: 2027.1` is a YAML number and would lose its meaning.
        if not isinstance(value, str):
            raise ValueError('version must be quoted text, for example "2027.1"')
        return value


def parse_manifest(raw: bytes) -> Manifest:
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise InvalidRequestError(f"manifest.yaml is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise InvalidRequestError("manifest.yaml must be a mapping")
    if data.get("source_status") in ("in_force", "commenced", "superseded"):
        raise InvalidRequestError(
            "A manifest may declare its source only as draft or laid; "
            "a domain owner sets in_force or commenced in the source registry"
        )
    try:
        return Manifest.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise InvalidRequestError(f"manifest.yaml is not valid: {problems}") from exc
