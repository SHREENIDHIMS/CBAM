from sqlalchemy import Engine, text

from app.core.auth import AuthenticatedUser
from app.core.db import tenant_session
from app.core.permissions import mfa_required, permissions_for
from app.modules.identity.schemas import MembershipOut, MeOut, MfaState


def describe_user(engine: Engine, user: AuthenticatedUser) -> MeOut:
    """The signed-in user's tenants, roles and permissions (GET /me)."""
    with tenant_session(engine, tenant_id=None, user_id=user.user_id) as s:
        rows = s.execute(
            text("select tenant_id, roles from cbam.memberships order by created_at")
        ).all()
        is_admin = s.execute(
            text("select 1 from cbam.platform_admins where user_id = :u"), {"u": user.user_id}
        ).scalar_one_or_none()
        is_domain_owner = s.execute(
            text("select 1 from cbam.platform_domain_owners where user_id = :u"),
            {"u": user.user_id},
        ).scalar_one_or_none()
    memberships: list[MembershipOut] = []
    for row in rows:
        with tenant_session(engine, tenant_id=row.tenant_id, user_id=user.user_id) as s:
            name = s.execute(text("select name from cbam.tenants")).scalar_one()
        roles = list(row.roles)
        memberships.append(
            MembershipOut(
                tenant_id=row.tenant_id,
                tenant_name=name,
                roles=roles,
                permissions=sorted(permissions_for(roles)),
                mfa_required=mfa_required(roles),
            )
        )
    needs_mfa = (
        is_admin is not None
        or is_domain_owner is not None
        or any(m.mfa_required for m in memberships)
    )
    return MeOut(
        user_id=user.user_id,
        platform_admin=is_admin is not None,
        domain_owner=is_domain_owner is not None,
        memberships=memberships,
        mfa=MfaState(required=needs_mfa, passed=user.aal == "aal2"),
    )
