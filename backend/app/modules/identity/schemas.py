from uuid import UUID

from pydantic import BaseModel


class MembershipOut(BaseModel):
    tenant_id: UUID
    tenant_name: str
    roles: list[str]
    permissions: list[str]
    mfa_required: bool


class MfaState(BaseModel):
    required: bool  # at least one of the user's roles needs MFA
    passed: bool  # this token is aal2


class MeOut(BaseModel):
    user_id: UUID
    platform_admin: bool
    memberships: list[MembershipOut]
    mfa: MfaState
