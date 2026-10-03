from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TenantOut(BaseModel):
    id: UUID
    name: str
    status: str
    row_version: int
    created_at: datetime


class TenantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)


class TenantPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    reason: str | None = None


class MemberOut(BaseModel):
    membership_id: UUID
    user_id: UUID
    email: str
    display_name: str | None
    roles: list[str]
    row_version: int


class InviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    roles: list[str]
    display_name: str | None = Field(default=None, max_length=200)


class RolesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roles: list[str]
