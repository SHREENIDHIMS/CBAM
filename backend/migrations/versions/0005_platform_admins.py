"""Platform admins are a separate table, never a tenant role (R1-002, R1-001).

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_TENANT_ROLES = (
    "operations",
    "client_admin",
    "reviewer",
    "approver",
    "supplier",
    "tax_agent",
    "domain_owner",
)
_ALL_ROLES = ("platform_admin", *_TENANT_ROLES)


def _check(roles: tuple[str, ...]) -> str:
    listed = ", ".join(f"'{r}'" for r in roles)
    return f"cardinality(roles) > 0 and roles <@ array[{listed}]"


def upgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute(
        """
        create table cbam.platform_admins (
          user_id uuid primary key references cbam.users (id),
          created_at timestamptz not null default now(),
          created_by uuid
        );
        alter table cbam.platform_admins enable row level security;
        alter table cbam.platform_admins force row level security;
        -- A user may check whether they themselves are a platform admin.
        create policy platform_admin_self on cbam.platform_admins for select
          using (user_id = cbam.current_user_id() or cbam.is_platform());
        create policy platform_admin_granted on cbam.platform_admins for insert
          with check (cbam.is_platform());
        create policy platform_admin_revoked on cbam.platform_admins for delete
          using (cbam.is_platform());
        """
    )
    # platform_admin can no longer be put on a tenant membership.
    op.execute("alter table cbam.memberships drop constraint memberships_roles_check")
    op.execute(
        f"alter table cbam.memberships add constraint memberships_roles_check check ({_check(_TENANT_ROLES)})"
    )


def downgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute("alter table cbam.memberships drop constraint memberships_roles_check")
    op.execute(
        f"alter table cbam.memberships add constraint memberships_roles_check check ({_check(_ALL_ROLES)})"
    )
    op.execute("drop table if exists cbam.platform_admins")
