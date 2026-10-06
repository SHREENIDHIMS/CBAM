from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


class LiablePersonOut(BaseModel):
    """The current liable-person decision for one declaration (R1-036).

    `outcome` is `determined` or `undetermined`. When it is undetermined, `code` says why and a
    review task (`review_task_id`) asks a person to decide; nothing is guessed.
    """

    declaration_id: UUID
    decision_id: UUID
    outcome: Literal["determined", "undetermined"]
    reason: str
    code: str | None
    liable_party: Literal["importer", "declarant", "representative"] | None
    liable_party_id: UUID | None
    rule_key: str | None
    rule_version: str
    source_ids: list[str]
    dataset_version_ids: list[UUID]
    as_of: date
    as_of_basis: str
    created: bool
    review_task_id: UUID | None
    created_at: datetime | None


class LiablePersonHistory(BaseModel):
    current: LiablePersonOut | None
    history: list[dict[str, Any]]
