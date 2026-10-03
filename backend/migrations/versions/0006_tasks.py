"""Tasks and their immutable event history (R1-022).

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_SQL = """
create table cbam.tasks (
  id uuid primary key,
  tenant_id uuid not null references cbam.tenants (id),
  type text not null check (type ~ '^[a-z][a-z0-9_.]*$'),
  subject_type text,
  subject_id uuid,
  title text not null check (length(btrim(title)) > 0),
  due_date date,                       -- a legal or product date; due_rule says which
  due_rule text,                       -- the rule that produced due_date, or 'manual'
  owner_id uuid references cbam.users (id),
  status text not null default 'open'
    check (status in ('open','in_progress','blocked','done','cancelled')),
  escalation_level integer not null default 0 check (escalation_level >= 0),
  created_at timestamptz not null default now(),
  created_by uuid,
  updated_at timestamptz,
  row_version integer not null default 1
);
create index tasks_status_due on cbam.tasks (tenant_id, status, due_date);
create index tasks_owner on cbam.tasks (tenant_id, owner_id);

create table cbam.task_events (
  id uuid primary key,
  tenant_id uuid not null references cbam.tenants (id),
  task_id uuid not null references cbam.tasks (id),
  event_type text not null
    check (event_type in ('created','assigned','status_changed','due_date_changed','escalated')),
  from_value text,
  to_value text,
  reason text,
  actor_type text not null check (actor_type in ('user','supplier','system','job')),
  actor_id uuid,
  occurred_at timestamptz not null default now()
);
create index task_events_task on cbam.task_events (tenant_id, task_id, occurred_at);

create function cbam.task_events_block_change() returns trigger language plpgsql as $$
begin
  raise exception 'task_events is append-only';
end $$;
create trigger task_events_immutable before update or delete on cbam.task_events
  for each row execute function cbam.task_events_block_change();

alter table cbam.tasks enable row level security;
alter table cbam.tasks force row level security;
create policy tenant_isolation on cbam.tasks
  using (tenant_id = cbam.current_tenant()) with check (tenant_id = cbam.current_tenant());
alter table cbam.task_events enable row level security;
alter table cbam.task_events force row level security;
create policy tenant_isolation on cbam.task_events
  using (tenant_id = cbam.current_tenant()) with check (tenant_id = cbam.current_tenant());

revoke update, delete, truncate on cbam.task_events from cbam_app;
revoke delete, truncate on cbam.tasks from cbam_app;
"""


def upgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute(_SQL)


def downgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute("drop table if exists cbam.task_events")
    op.execute("drop table if exists cbam.tasks")
    op.execute("drop function if exists cbam.task_events_block_change()")
