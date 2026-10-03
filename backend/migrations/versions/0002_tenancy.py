"""Tenancy tables with row-level security (R1-001).

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ROLES = (
    "platform_admin",
    "operations",
    "client_admin",
    "reviewer",
    "approver",
    "supplier",
    "tax_agent",
    "domain_owner",
)

_FUNCTIONS = """
create function cbam.current_tenant() returns uuid language sql stable as
$$ select nullif(current_setting('app.tenant_id', true), '')::uuid $$;

create function cbam.current_user_id() returns uuid language sql stable as
$$ select nullif(current_setting('app.user_id', true), '')::uuid $$;

-- Platform mode is set by the app only after verifying platform_admin. It opens
-- tenants/users/memberships only; business tables never reference it.
create function cbam.is_platform() returns boolean language sql stable as
$$ select coalesce(current_setting('app.is_platform', true), '') = 'on' $$;
"""


def _force_rls(table: str) -> None:
    op.execute(f"alter table cbam.{table} enable row level security")
    op.execute(f"alter table cbam.{table} force row level security")


def upgrade() -> None:
    # Objects must belong to cbam_owner so the default grants to cbam_app apply.
    op.execute("set local role cbam_owner")
    op.execute(_FUNCTIONS)

    op.execute(
        """
        create table cbam.tenants (
          id uuid primary key,
          name text not null,
          status text not null default 'active' check (status in ('active','suspended','closed')),
          created_at timestamptz not null default now(),
          created_by uuid,
          updated_at timestamptz,
          row_version integer not null default 1
        )
        """
    )
    op.execute(
        """
        create table cbam.users (
          id uuid primary key,  -- = Supabase auth.users.id; no FK, we never touch auth
          email text not null,
          display_name text,
          status text not null default 'active' check (status in ('active','disabled')),
          created_at timestamptz not null default now(),
          updated_at timestamptz,
          row_version integer not null default 1
        )
        """
    )
    op.execute("create unique index users_email_lower on cbam.users (lower(email))")
    op.execute(
        """
        create table cbam.organisations (
          id uuid primary key,
          tenant_id uuid not null references cbam.tenants (id),
          legal_name text not null,
          business_type text,
          address jsonb,
          gb_eori text,
          xi_eori text,
          vat_number text,
          vat_status text,
          acts_as text not null default 'liable_person'
            check (acts_as in ('liable_person','agent')),
          created_at timestamptz not null default now(),
          created_by uuid,
          updated_at timestamptz,
          row_version integer not null default 1
        )
        """
    )
    op.execute("create index organisations_tenant on cbam.organisations (tenant_id)")
    role_list = ", ".join(f"'{r}'" for r in ROLES)
    op.execute(
        f"""
        create table cbam.memberships (
          id uuid primary key,
          user_id uuid not null references cbam.users (id),
          tenant_id uuid not null references cbam.tenants (id),
          roles text[] not null check (cardinality(roles) > 0 and roles <@ array[{role_list}]),
          created_at timestamptz not null default now(),
          created_by uuid,
          updated_at timestamptz,
          row_version integer not null default 1,
          unique (user_id, tenant_id)
        )
        """
    )
    op.execute("create index memberships_tenant on cbam.memberships (tenant_id)")
    op.execute(
        """
        create table cbam.approval_roles (
          id uuid primary key,
          tenant_id uuid not null references cbam.tenants (id),
          role_name text not null,
          permissions text[] not null default '{}',
          created_at timestamptz not null default now(),
          created_by uuid,
          updated_at timestamptz,
          row_version integer not null default 1,
          unique (tenant_id, role_name)
        )
        """
    )

    for table in ("tenants", "users", "organisations", "memberships", "approval_roles"):
        _force_rls(table)

    op.execute(
        """
        create policy tenant_visible on cbam.tenants for select
          using (id = cbam.current_tenant() or cbam.is_platform());
        create policy platform_creates on cbam.tenants for insert
          with check (cbam.is_platform());
        create policy tenant_updates on cbam.tenants for update
          using (id = cbam.current_tenant() or cbam.is_platform())
          with check (id = cbam.current_tenant() or cbam.is_platform());

        create policy tenant_isolation on cbam.organisations
          using (tenant_id = cbam.current_tenant())
          with check (tenant_id = cbam.current_tenant());
        create policy tenant_isolation on cbam.approval_roles
          using (tenant_id = cbam.current_tenant())
          with check (tenant_id = cbam.current_tenant());

        -- A user sees themself, platform sees all, a tenant sees its own members.
        create policy users_visible on cbam.users for select
          using (
            id = cbam.current_user_id()
            or cbam.is_platform()
            or exists (
              select 1 from cbam.memberships m
              where m.user_id = users.id and m.tenant_id = cbam.current_tenant()
            )
          );
        create policy users_written on cbam.users for insert
          with check (id = cbam.current_user_id() or cbam.is_platform());
        create policy users_updated on cbam.users for update
          using (id = cbam.current_user_id() or cbam.is_platform())
          with check (id = cbam.current_user_id() or cbam.is_platform());

        -- user_id lets the app find a user's tenants *before* a tenant is selected.
        create policy memberships_visible on cbam.memberships for select
          using (
            tenant_id = cbam.current_tenant()
            or user_id = cbam.current_user_id()
            or cbam.is_platform()
          );
        create policy memberships_written on cbam.memberships for insert
          with check (tenant_id = cbam.current_tenant() or cbam.is_platform());
        create policy memberships_updated on cbam.memberships for update
          using (tenant_id = cbam.current_tenant() or cbam.is_platform())
          with check (tenant_id = cbam.current_tenant() or cbam.is_platform());
        create policy memberships_removed on cbam.memberships for delete
          using (tenant_id = cbam.current_tenant() or cbam.is_platform());
        """
    )
    # Records are closed or superseded, never deleted (docs/DATABASE.md section 1).
    op.execute("revoke delete on cbam.tenants, cbam.users, cbam.organisations from cbam_app")


def downgrade() -> None:
    op.execute("set local role cbam_owner")
    # users' policy reads memberships, so users goes first (cascade drops its policy and FKs).
    op.execute("drop table if exists cbam.approval_roles")
    op.execute("drop table if exists cbam.organisations")
    op.execute("drop table if exists cbam.users cascade")
    op.execute("drop table if exists cbam.memberships")
    op.execute("drop table if exists cbam.tenants")
    op.execute("drop function if exists cbam.is_platform()")
    op.execute("drop function if exists cbam.current_user_id()")
    op.execute("drop function if exists cbam.current_tenant()")
