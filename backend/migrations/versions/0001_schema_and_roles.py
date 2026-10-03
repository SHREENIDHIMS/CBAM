"""Create schema cbam and roles; lock Supabase API roles out.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Passwords are set outside migrations (secrets are never committed).
_CREATE_ROLES = """
do $$
begin
  if not exists (select from pg_roles where rolname = 'cbam_owner') then
    create role cbam_owner login nobypassrls;
  end if;
  if not exists (select from pg_roles where rolname = 'cbam_app') then
    create role cbam_app login nobypassrls;
  end if;
end $$;
"""


def upgrade() -> None:
    op.execute(_CREATE_ROLES)
    op.execute("create schema if not exists cbam")
    op.execute("alter schema cbam owner to cbam_owner")
    op.execute("grant usage on schema cbam to cbam_app")
    op.execute(
        "alter default privileges for role cbam_owner in schema cbam "
        "grant select, insert, update, delete on tables to cbam_app"
    )
    op.execute(
        "alter default privileges for role cbam_owner in schema cbam "
        "grant usage, select on sequences to cbam_app"
    )
    # CLAUDE.md rule 18: Supabase's auto-generated API must never reach cbam.
    op.execute("revoke all on schema cbam from public")
    for role in ("anon", "authenticated"):
        op.execute(
            f"do $$ begin if exists (select from pg_roles where rolname = '{role}') then "  # noqa: S608
            f"revoke all on schema cbam from {role}; end if; end $$;"
        )


def downgrade() -> None:
    # The schema holds Alembic's own version table and the roles are cluster-level, so
    # neither is dropped here. Downgrade removes what upgrade granted.
    op.execute(
        "alter default privileges for role cbam_owner in schema cbam "
        "revoke select, insert, update, delete on tables from cbam_app"
    )
    op.execute(
        "alter default privileges for role cbam_owner in schema cbam "
        "revoke usage, select on sequences from cbam_app"
    )
    op.execute("revoke usage on schema cbam from cbam_app")
