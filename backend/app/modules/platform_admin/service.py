"""Platform admin service: tenants, invitations and roles, with audit in the platform chain.

Runs in a platform-mode session (tenants, users and memberships only). Events go to the
platform audit chain with the tenant in `after`, because a platform session has no tenant.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record
from app.core.errors import (
    InvalidRequestError,
    ReasonRequiredError,
    RuleBlockedError,
    StaleVersionError,
    TenantMismatchError,
)
from app.core.ids import uuid7
from app.core.supabase_admin import AuthAdmin
from app.core.versioning import update_versioned
from app.modules.platform_admin import rules
from app.modules.platform_admin.schemas import MemberOut, TenantOut


@dataclass(frozen=True)
class Admin:
    user_id: UUID


def _tenant(row: Any) -> TenantOut:
    return TenantOut(
        id=row.id,
        name=row.name,
        status=row.status,
        row_version=row.row_version,
        created_at=row.created_at,
    )


def _audit(
    session: Session,
    admin: Admin,
    now: datetime,
    action: str,
    object_type: str,
    object_id: UUID,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> None:
    record(
        session,
        tenant_id=None,
        actor_type="user",
        actor_id=admin.user_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        occurred_at=now,
        before=before,
        after=after,
        reason=reason,
    )


def list_tenants(session: Session) -> list[TenantOut]:
    rows = session.execute(
        text("select id, name, status, row_version, created_at from cbam.tenants order by name, id")
    ).all()
    return [_tenant(r) for r in rows]


def _get_tenant(session: Session, tenant_id: UUID) -> Any:
    row = session.execute(
        text("select id, name, status, row_version, created_at from cbam.tenants where id = :i"),
        {"i": tenant_id},
    ).one_or_none()
    if row is None:
        raise TenantMismatchError()
    return row


def create_tenant(session: Session, admin: Admin, now: datetime, name: str) -> TenantOut:
    cleaned = name.strip()
    if not cleaned:
        raise InvalidRequestError("A client name is required")
    tenant_id = uuid7()
    session.execute(
        text(
            "insert into cbam.tenants (id, name, created_by, created_at) values (:i, :n, :by, :at)"
        ),
        {"i": tenant_id, "n": cleaned, "by": admin.user_id, "at": now},
    )
    _audit(session, admin, now, "tenant.created", "tenant", tenant_id, after={"name": cleaned})
    return _tenant(_get_tenant(session, tenant_id))


def change_tenant_status(
    session: Session,
    admin: Admin,
    now: datetime,
    tenant_id: UUID,
    *,
    expected_version: int,
    status: str,
    reason: str | None,
) -> TenantOut:
    current = _get_tenant(session, tenant_id)
    if current.row_version != expected_version:
        raise StaleVersionError("This client changed since you loaded it; reload and try again")
    decision = rules.tenant_status_decision(current.status, status, reason=reason)
    if decision.outcome == "BLOCKED":
        raise RuleBlockedError(decision.reason, rule_id=decision.rule_id)
    if decision.outcome == "REASON_REQUIRED":
        raise ReasonRequiredError(decision.reason, rule_id=decision.rule_id)
    update_versioned(
        session,
        "tenants",
        row_id=tenant_id,
        expected_version=expected_version,
        values={"status": status},
    )
    _audit(
        session,
        admin,
        now,
        "tenant.status_changed",
        "tenant",
        tenant_id,
        before={"status": current.status},
        after={"status": status},
        reason=reason,
    )
    return _tenant(_get_tenant(session, tenant_id))


def _member(row: Any) -> MemberOut:
    return MemberOut(
        membership_id=row.id,
        user_id=row.user_id,
        email=row.email,
        display_name=row.display_name,
        roles=list(row.roles),
        row_version=row.row_version,
    )


_MEMBER_SQL = (
    "select m.id, m.user_id, u.email, u.display_name, m.roles, m.row_version"
    " from cbam.memberships m join cbam.users u on u.id = m.user_id"
)


def list_members(session: Session, tenant_id: UUID) -> list[MemberOut]:
    _get_tenant(session, tenant_id)
    rows = session.execute(
        text(_MEMBER_SQL + " where m.tenant_id = :t order by lower(u.email)"), {"t": tenant_id}
    ).all()
    return [_member(r) for r in rows]


def _get_member(session: Session, tenant_id: UUID, user_id: UUID) -> Any:
    row = session.execute(
        text(_MEMBER_SQL + " where m.tenant_id = :t and m.user_id = :u"),
        {"t": tenant_id, "u": user_id},
    ).one_or_none()
    if row is None:
        raise TenantMismatchError()
    return row


def invite_member(
    session: Session,
    admin: Admin,
    auth_admin: AuthAdmin,
    now: datetime,
    tenant_id: UUID,
    *,
    email: str,
    roles: list[str],
    display_name: str | None,
    redirect_to: str | None,
) -> MemberOut:
    try:
        clean_email = rules.clean_email(email)
        clean_roles = rules.clean_roles(roles)
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc
    tenant = _get_tenant(session, tenant_id)
    if tenant.status != "active":
        raise RuleBlockedError(
            "People can only be invited to an active client", rule_id=rules.RULE_TENANT_STATUS
        )
    existing = session.execute(
        text("select id from cbam.users where lower(email) = :e"), {"e": clean_email}
    ).scalar_one_or_none()
    # The person is created in Supabase Auth first; if a later step fails they hold no access.
    user_id = existing or auth_admin.invite(clean_email, redirect_to=redirect_to)
    session.execute(
        text(
            "insert into cbam.users (id, email, display_name) values (:i, :e, :d)"
            " on conflict (id) do nothing"
        ),
        {"i": user_id, "e": clean_email, "d": display_name},
    )
    membership_id = uuid7()
    try:
        with session.begin_nested():
            session.execute(
                text(
                    "insert into cbam.memberships (id, user_id, tenant_id, roles, created_by)"
                    " values (:i, :u, :t, cast(:r as text[]), :by)"
                ),
                {
                    "i": membership_id,
                    "u": user_id,
                    "t": tenant_id,
                    "r": list(clean_roles),
                    "by": admin.user_id,
                },
            )
    except IntegrityError as exc:
        raise InvalidRequestError("That person is already a member of this client") from exc
    _audit(
        session,
        admin,
        now,
        "membership.invited",
        "membership",
        membership_id,
        after={"tenant_id": str(tenant_id), "user_id": str(user_id), "roles": list(clean_roles)},
    )
    return _member(_get_member(session, tenant_id, user_id))


def set_member_roles(
    session: Session,
    admin: Admin,
    now: datetime,
    tenant_id: UUID,
    user_id: UUID,
    *,
    expected_version: int,
    roles: list[str],
) -> MemberOut:
    try:
        clean_roles = rules.clean_roles(roles)
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc
    current = _get_member(session, tenant_id, user_id)
    if current.row_version != expected_version:
        raise StaleVersionError("This membership changed since you loaded it; reload and try again")
    if tuple(current.roles) == clean_roles:
        raise InvalidRequestError("Nothing to change")
    update_versioned(
        session,
        "memberships",
        row_id=current.id,
        expected_version=expected_version,
        values={"roles": list(clean_roles)},
    )
    _audit(
        session,
        admin,
        now,
        "membership.roles_changed",
        "membership",
        current.id,
        before={"tenant_id": str(tenant_id), "user_id": str(user_id), "roles": list(current.roles)},
        after={"tenant_id": str(tenant_id), "user_id": str(user_id), "roles": list(clean_roles)},
    )
    return _member(_get_member(session, tenant_id, user_id))


def remove_member(
    session: Session, admin: Admin, now: datetime, tenant_id: UUID, user_id: UUID
) -> None:
    current = _get_member(session, tenant_id, user_id)
    session.execute(text("delete from cbam.memberships where id = :i"), {"i": current.id})
    _audit(
        session,
        admin,
        now,
        "membership.removed",
        "membership",
        current.id,
        before={"tenant_id": str(tenant_id), "user_id": str(user_id), "roles": list(current.roles)},
    )
