"""Raw source rows, row exceptions and the layout link of a batch (R1-025, R1-003).

Revision ID: 0010
Revises: 0009

`source_rows` holds each data row of an uploaded file exactly as read (header -> cell text),
with its SHA-256. Rows never change and cannot be deleted (trigger, and no UPDATE/DELETE/TRUNCATE
for the app role): CLAUDE.md rule 4. `row_exceptions` is the exception report: one row per
(batch, row number, field, code), so a retried job cannot insert a problem twice. Only the
resolution columns can change, and only from `open` forward. Codes are short upper-case codes and
the message is fixed text per code: never a cell value (the report is exported).

`import_batches` gains the reference-data layout version it was read with and a short
`layout_status`. `ref_cds_report_layouts` gains an optional `date_format` (the format a layout
declares for a date column); its `v_active_` view is rebuilt to expose it.
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_SQL = """
alter table cbam.import_batches add constraint import_batches_tenant_id_key unique (tenant_id, id);
alter table cbam.import_batches
  add column report_layout_version_id uuid references cbam.ref_dataset_versions (id),
  add column layout_status text
    check (layout_status in ('matched','not_active','columns_missing','unreadable'));

create or replace function cbam.import_batches_guard() returns trigger language plpgsql as $$
declare
  old_rank integer;
  new_rank integer;
begin
  old_rank := case old.status
    when 'received' then 0 when 'queued' then 1 when 'parsing' then 2
    when 'validating' then 3 when 'normalising' then 4 else 5 end;
  new_rank := case new.status
    when 'received' then 0 when 'queued' then 1 when 'parsing' then 2
    when 'validating' then 3 when 'normalising' then 4 else 5 end;
  if old_rank = 5 then
    raise exception 'import batch % is in a terminal state (%) and is locked', old.id, old.status;
  end if;
  if new.status <> old.status and new_rank <= old_rank then
    raise exception 'import batch status cannot move from % to %', old.status, new.status;
  end if;
  if old.report_layout_version_id is not null
     and new.report_layout_version_id is distinct from old.report_layout_version_id then
    raise exception 'import batch layout version is immutable once set';
  end if;
  if (new.id, new.tenant_id, new.file_sha256, new.document_version_id, new.filename,
      new.acquisition_method, new.cds_report_type, new.eori, new.window_start, new.window_end,
      new.source_owner, new.acquired_on, new.idempotency_key, new.request_fingerprint,
      new.created_at, new.created_by)
     is distinct from
     (old.id, old.tenant_id, old.file_sha256, old.document_version_id, old.filename,
      old.acquisition_method, old.cds_report_type, old.eori, old.window_start, old.window_end,
      old.source_owner, old.acquired_on, old.idempotency_key, old.request_fingerprint,
      old.created_at, old.created_by) then
    raise exception 'import batch source facts are immutable';
  end if;
  return new;
end $$;

create table cbam.source_rows (
  id uuid primary key,
  tenant_id uuid not null references cbam.tenants (id),
  batch_id uuid not null,
  row_number integer not null check (row_number >= 1),
  raw jsonb not null check (jsonb_typeof(raw) = 'object'),
  row_sha256 char(64) not null check (row_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  unique (batch_id, row_number),
  unique (tenant_id, id),
  foreign key (tenant_id, batch_id) references cbam.import_batches (tenant_id, id)
);

create function cbam.source_rows_block_change() returns trigger language plpgsql as $$
begin
  raise exception 'source rows are immutable: a correction is a new version, not an edit';
end $$;
create trigger source_rows_immutable before update or delete on cbam.source_rows
  for each row execute function cbam.source_rows_block_change();
create trigger source_rows_no_truncate before truncate on cbam.source_rows
  for each statement execute function cbam.source_rows_block_change();

create table cbam.row_exceptions (
  id uuid primary key,
  tenant_id uuid not null references cbam.tenants (id),
  batch_id uuid not null,
  source_row_id uuid,                      -- null = a problem with the whole file
  row_number integer not null check (row_number >= 0),
  field text not null default '' check (length(field) <= 200),
  code text not null check (code ~ '^[A-Z0-9_]{1,64}$'),
  severity text not null check (severity in ('error','warning')),
  message text not null check (length(message) between 1 and 500),
  status text not null default 'open' check (status in ('open','resolved','waived')),
  resolved_by uuid,
  resolved_at timestamptz,
  resolution_reason text check (length(resolution_reason) <= 1000),
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  row_version integer not null default 1,
  unique (batch_id, row_number, field, code),
  unique (tenant_id, id),
  check ((source_row_id is null) = (row_number = 0)),
  check (status = 'open' or resolved_at is not null),
  foreign key (tenant_id, batch_id) references cbam.import_batches (tenant_id, id),
  foreign key (tenant_id, source_row_id) references cbam.source_rows (tenant_id, id)
);
create index row_exceptions_batch on cbam.row_exceptions (tenant_id, batch_id, row_number);

create function cbam.row_exceptions_guard() returns trigger language plpgsql as $$
begin
  if tg_op <> 'UPDATE' then
    raise exception 'row exceptions cannot be deleted';
  end if;
  if (new.id, new.tenant_id, new.batch_id, new.source_row_id, new.row_number, new.field,
      new.code, new.severity, new.message, new.created_at)
     is distinct from
     (old.id, old.tenant_id, old.batch_id, old.source_row_id, old.row_number, old.field,
      old.code, old.severity, old.message, old.created_at) then
    raise exception 'row exception facts are immutable; only the resolution can change';
  end if;
  if old.status <> 'open' and new.status <> old.status then
    raise exception 'a resolved or waived exception cannot change status again';
  end if;
  return new;
end $$;
create trigger row_exceptions_guard before update or delete on cbam.row_exceptions
  for each row execute function cbam.row_exceptions_guard();
create trigger row_exceptions_no_truncate before truncate on cbam.row_exceptions
  for each statement execute function cbam.row_exceptions_guard();

alter table cbam.source_rows enable row level security;
alter table cbam.source_rows force row level security;
create policy tenant_isolation on cbam.source_rows
  using (tenant_id = cbam.current_tenant()) with check (tenant_id = cbam.current_tenant());
alter table cbam.row_exceptions enable row level security;
alter table cbam.row_exceptions force row level security;
create policy tenant_isolation on cbam.row_exceptions
  using (tenant_id = cbam.current_tenant()) with check (tenant_id = cbam.current_tenant());

revoke update, delete, truncate on cbam.source_rows from cbam_app;
revoke update, delete, truncate on cbam.row_exceptions from cbam_app;
grant update (status, resolved_by, resolved_at, resolution_reason, updated_at, row_version)
  on cbam.row_exceptions to cbam_app;

-- A layout may declare how its date column is written (strptime-style pattern).
alter table cbam.ref_cds_report_layouts add column date_format text
  check (date_format is null or length(date_format) <= 40);
drop view cbam.v_active_cds_report_layouts;
create view cbam.v_active_cds_report_layouts as
select t.*,
       v.version as dataset_version,
       s.source_id as source_ref,
       s.status as source_status,
       greatest(t.effective_from, s.commencement_date, s.effective_from) as usable_from,
       least(t.effective_to, s.effective_to) as usable_to
from cbam.ref_cds_report_layouts t
join cbam.ref_dataset_versions v on v.id = t.dataset_version_id
join cbam.regulatory_sources s on s.id = v.source_id
where v.status = 'active' and s.status in ('in_force','commenced','superseded');
revoke insert, update, delete, truncate on cbam.v_active_cds_report_layouts from cbam_app;
"""

_DOWN = """
drop view cbam.v_active_cds_report_layouts;
alter table cbam.ref_cds_report_layouts drop column date_format;
create view cbam.v_active_cds_report_layouts as
select t.*,
       v.version as dataset_version,
       s.source_id as source_ref,
       s.status as source_status,
       greatest(t.effective_from, s.commencement_date, s.effective_from) as usable_from,
       least(t.effective_to, s.effective_to) as usable_to
from cbam.ref_cds_report_layouts t
join cbam.ref_dataset_versions v on v.id = t.dataset_version_id
join cbam.regulatory_sources s on s.id = v.source_id
where v.status = 'active' and s.status in ('in_force','commenced','superseded');
revoke insert, update, delete, truncate on cbam.v_active_cds_report_layouts from cbam_app;

drop table cbam.row_exceptions;
drop table cbam.source_rows;
drop function cbam.row_exceptions_guard();
drop function cbam.source_rows_block_change();

create or replace function cbam.import_batches_guard() returns trigger language plpgsql as $$
declare
  old_rank integer;
  new_rank integer;
begin
  old_rank := case old.status
    when 'received' then 0 when 'queued' then 1 when 'parsing' then 2
    when 'validating' then 3 when 'normalising' then 4 else 5 end;
  new_rank := case new.status
    when 'received' then 0 when 'queued' then 1 when 'parsing' then 2
    when 'validating' then 3 when 'normalising' then 4 else 5 end;
  if old_rank = 5 then
    raise exception 'import batch % is in a terminal state (%) and is locked', old.id, old.status;
  end if;
  if new.status <> old.status and new_rank <= old_rank then
    raise exception 'import batch status cannot move from % to %', old.status, new.status;
  end if;
  if (new.id, new.tenant_id, new.file_sha256, new.document_version_id, new.filename,
      new.acquisition_method, new.cds_report_type, new.eori, new.window_start, new.window_end,
      new.source_owner, new.acquired_on, new.idempotency_key, new.request_fingerprint,
      new.created_at, new.created_by)
     is distinct from
     (old.id, old.tenant_id, old.file_sha256, old.document_version_id, old.filename,
      old.acquisition_method, old.cds_report_type, old.eori, old.window_start, old.window_end,
      old.source_owner, old.acquired_on, old.idempotency_key, old.request_fingerprint,
      old.created_at, old.created_by) then
    raise exception 'import batch source facts are immutable';
  end if;
  return new;
end $$;
alter table cbam.import_batches
  drop column layout_status,
  drop column report_layout_version_id;
alter table cbam.import_batches drop constraint import_batches_tenant_id_key;
"""


def upgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute(_SQL)


def downgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute(_DOWN)
