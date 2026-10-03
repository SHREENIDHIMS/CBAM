from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TaskOut(BaseModel):
    id: UUID
    type: str
    subject_type: str | None
    subject_id: UUID | None
    title: str
    due_date: date | None
    due_rule: str | None
    owner_id: UUID | None
    status: str
    escalation_level: int
    row_version: int


class TaskPage(BaseModel):
    items: list[TaskOut]
    next_cursor: str | None


class TaskPatch(BaseModel):
    """Only the fields that are sent are changed; `owner_id: null` unassigns."""

    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    owner_id: UUID | None = None
    due_date: date | None = None
    reason: str | None = None


class TaskEventOut(BaseModel):
    event_type: str
    from_value: str | None
    to_value: str | None
    reason: str | None
    actor_type: str
    actor_id: UUID | None
