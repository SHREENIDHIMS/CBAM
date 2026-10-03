"""Append-only audit table with a per-tenant hash chain (R1-023, CLAUDE.md rule 8).

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_SQL = """
create table cbam.audit_events (
  id uuid primary key,
  tenant_id uuid references cbam.tenants (id),   -- null for platform events
  chain_seq bigint not null default 0,           -- set by trigger, 1.. per tenant chain
  occurred_at timestamptz not null default now(),
  actor_type text not null check (actor_type in ('user','supplier','system','job')),
  actor_id uuid,
  action text not null,
  object_type text not null,
  object_id uuid not null,
  before jsonb,
  after jsonb,
  reason text,
  request_id text,
  prev_hash bytea,
  hash bytea not null default ''::bytea
);
create unique index audit_chain_position
  on cbam.audit_events ((coalesce(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid)), chain_seq);
create index audit_object on cbam.audit_events (tenant_id, object_type, object_id);

-- One canonical form, used both to insert and to verify:
-- hash = sha256(prev_hash || canonical jsonb text of the row without its hash).
create function cbam.audit_compute_hash(prev bytea, r cbam.audit_events) returns bytea
language sql immutable as $$
  select sha256(
    coalesce(prev, ''::bytea) || convert_to(
      jsonb_build_object(
        'id', r.id, 'tenant_id', r.tenant_id, 'chain_seq', r.chain_seq,
        'occurred_at', to_char(r.occurred_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
        'actor_type', r.actor_type, 'actor_id', r.actor_id, 'action', r.action,
        'object_type', r.object_type, 'object_id', r.object_id,
        'before', r.before, 'after', r.after, 'reason', r.reason, 'request_id', r.request_id
      )::text, 'UTF8')
  )
$$;

create function cbam.audit_chain() returns trigger language plpgsql as $$
declare
  last_seq bigint;
  last_hash bytea;
begin
  -- Serialise writers per chain so two concurrent inserts cannot fork it.
  perform pg_advisory_xact_lock(hashtextextended(coalesce(new.tenant_id::text, 'platform'), 0));
  select a.chain_seq, a.hash into last_seq, last_hash
    from cbam.audit_events a
    where coalesce(a.tenant_id, '00000000-0000-0000-0000-000000000000'::uuid)
        = coalesce(new.tenant_id, '00000000-0000-0000-0000-000000000000'::uuid)
    order by a.chain_seq desc limit 1;
  new.chain_seq := coalesce(last_seq, 0) + 1;
  new.prev_hash := last_hash;
  new.hash := cbam.audit_compute_hash(last_hash, new);
  return new;
end $$;
create trigger audit_chain before insert on cbam.audit_events
  for each row execute function cbam.audit_chain();

create function cbam.audit_block_change() returns trigger language plpgsql as $$
begin
  raise exception 'audit_events is append-only';
end $$;
create trigger audit_no_update before update or delete on cbam.audit_events
  for each row execute function cbam.audit_block_change();
create trigger audit_no_truncate before truncate on cbam.audit_events
  for each statement execute function cbam.audit_block_change();

-- Returns the chain position of the first broken row, or no rows when the chain is intact.
create function cbam.audit_verify_chain(p_tenant uuid) returns table (bad_chain_seq bigint)
language sql stable as $$
  select a.chain_seq
  from (
    select e.chain_seq, e.prev_hash, e.hash,
           lag(e.hash) over (order by e.chain_seq) as expected_prev,
           cbam.audit_compute_hash(e.prev_hash, e) as computed
    from cbam.audit_events e
    where coalesce(e.tenant_id, '00000000-0000-0000-0000-000000000000'::uuid) = coalesce(p_tenant, '00000000-0000-0000-0000-000000000000'::uuid)
  ) a
  where a.prev_hash is distinct from a.expected_prev
     or a.hash <> a.computed
  order by a.chain_seq
  limit 1
$$;

alter table cbam.audit_events enable row level security;
alter table cbam.audit_events force row level security;
create policy audit_read on cbam.audit_events for select
  using (tenant_id = cbam.current_tenant() or (tenant_id is null and cbam.is_platform()));
create policy audit_append on cbam.audit_events for insert
  with check (tenant_id = cbam.current_tenant() or (tenant_id is null and cbam.is_platform()));

revoke update, delete, truncate on cbam.audit_events from cbam_app;
"""


def upgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute(_SQL)


def downgrade() -> None:
    op.execute("set local role cbam_owner")
    # CASCADE also drops the functions that take the table's row type.
    op.execute("drop table if exists cbam.audit_events cascade")
    op.execute("drop function if exists cbam.audit_verify_chain(uuid)")
    op.execute("drop function if exists cbam.audit_block_change()")
    op.execute("drop function if exists cbam.audit_chain()")
