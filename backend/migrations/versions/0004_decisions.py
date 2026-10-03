"""Decisions: every derived outcome with rule, versions and input fingerprint.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_SQL = """
create table cbam.decisions (
  id uuid primary key,
  tenant_id uuid not null references cbam.tenants (id),
  subject_type text not null,
  subject_id uuid not null,
  rule_id text not null,
  rule_version text not null,
  source_ids text[] not null default '{}',
  dataset_version_ids uuid[] not null default '{}',
  input_fingerprint bytea not null check (octet_length(input_fingerprint) = 32),
  outcome text not null,
  reason text not null,
  details jsonb,
  as_of date not null,
  supersedes_id uuid references cbam.decisions (id),
  created_at timestamptz not null default now(),
  created_by uuid
);
create index decisions_subject on cbam.decisions (tenant_id, subject_type, subject_id);
-- A decision can be superseded once: the history is a straight line.
create unique index decisions_one_successor on cbam.decisions (supersedes_id)
  where supersedes_id is not null;

-- Decisions are immutable; a correction is a new row that supersedes the old one.
create function cbam.decisions_block_change() returns trigger language plpgsql as $$
begin
  raise exception 'decisions are immutable; save a superseding decision instead';
end $$;
create trigger decisions_immutable before update or delete on cbam.decisions
  for each row execute function cbam.decisions_block_change();

alter table cbam.decisions enable row level security;
alter table cbam.decisions force row level security;
create policy tenant_isolation on cbam.decisions
  using (tenant_id = cbam.current_tenant())
  with check (tenant_id = cbam.current_tenant());
revoke update, delete, truncate on cbam.decisions from cbam_app;
"""


def upgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute(_SQL)


def downgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute("drop table if exists cbam.decisions")
    op.execute("drop function if exists cbam.decisions_block_change()")
