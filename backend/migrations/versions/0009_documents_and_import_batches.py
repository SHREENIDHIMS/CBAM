"""Stored files and customs import batches (R1-003).

Revision ID: 0009
Revises: 0008

`documents` / `document_versions` are the minimal file record: where the bytes live, their
SHA-256 and size, what we detected, who uploaded them. Rows never change (trigger + no UPDATE
for the app role); Phase 7 extends them (scan results, supersession, legal hold).

`import_batches` is one received file (or one manual-entry session). The source facts of a batch
(hash, filename, EORI, window, method, owner, acquisition date, idempotency key, fingerprint)
never change; only status and progress columns do, and only forward. A terminal batch is locked.
The same rules live in `app/modules/imports/rules.py` (CLAUDE.md rule 17: enforce twice).
`source_rows` and the business lines arrive in later steps and are not created here.
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_SQL = """
create table cbam.documents (
  id uuid primary key,
  tenant_id uuid not null references cbam.tenants (id),
  created_at timestamptz not null default now(),
  created_by uuid,
  unique (tenant_id, id)     -- target of the composite tenant foreign keys below
);

create table cbam.document_versions (
  id uuid primary key,
  tenant_id uuid not null references cbam.tenants (id),
  document_id uuid not null,
  version integer not null default 1 check (version >= 1),
  storage_key text not null check (length(btrim(storage_key)) > 0),
  sha256 char(64) not null check (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes bigint not null check (size_bytes >= 0),
  mime_detected text not null,
  original_filename text not null check (length(original_filename) <= 255),
  uploaded_by_type text not null check (uploaded_by_type in ('user','supplier','system','job')),
  uploaded_by_id uuid,
  scan_state text not null default 'not_scanned'
    check (scan_state in ('not_scanned','pending','clean','infected')),
  uploaded_at timestamptz not null default now(),
  unique (document_id, version),
  unique (tenant_id, id),
  foreign key (tenant_id, document_id) references cbam.documents (tenant_id, id)
);
create index document_versions_sha on cbam.document_versions (tenant_id, sha256);

create function cbam.documents_block_change() returns trigger language plpgsql as $$
begin
  raise exception '% is immutable: add a new version instead', tg_table_name;
end $$;
create trigger documents_immutable before update or delete on cbam.documents
  for each row execute function cbam.documents_block_change();
create trigger document_versions_immutable before update or delete on cbam.document_versions
  for each row execute function cbam.documents_block_change();

create table cbam.import_batches (
  id uuid primary key,
  tenant_id uuid not null references cbam.tenants (id),
  file_sha256 char(64) check (file_sha256 ~ '^[0-9a-f]{64}$'),   -- null for manual entry
  document_version_id uuid,
  filename text check (length(filename) <= 255),
  acquisition_method text not null check (acquisition_method in
    ('get_customs_data','cds_export','data_request','manual_upload','manual_entry','feed')),
  cds_report_type text check (cds_report_type in
    ('import_item','import_header','import_tax_lines','export_item')),
  eori text check (eori ~ '^(GB|XI)[0-9]{12}$'),
  window_start date,
  window_end date,
  source_owner text check (length(source_owner) <= 200),
  acquired_on date,
  idempotency_key text check (length(idempotency_key) between 1 and 200),
  request_fingerprint bytea not null check (length(request_fingerprint) = 32),
  status text not null default 'received' check (status in
    ('received','queued','parsing','validating','normalising',
     'completed','completed_with_errors','failed','rejected')),
  rows_total integer not null default 0 check (rows_total >= 0),
  rows_processed integer not null default 0 check (rows_processed >= 0),
  rows_valid integer not null default 0 check (rows_valid >= 0),
  rows_rejected integer not null default 0 check (rows_rejected >= 0),
  lines_created integer not null default 0 check (lines_created >= 0),
  lines_unchanged integer not null default 0 check (lines_unchanged >= 0),
  failure_reason text check (failure_reason ~ '^[a-z0-9_]{1,64}$'),  -- a code, never parser text
  created_at timestamptz not null default now(),
  created_by uuid,
  updated_at timestamptz,
  row_version integer not null default 1,
  check (window_end is null or window_start is not null),
  check (window_end >= window_start),
  check ((file_sha256 is null) = (document_version_id is null)),
  check (acquisition_method <> 'manual_entry' or file_sha256 is null),
  foreign key (tenant_id, document_version_id) references cbam.document_versions (tenant_id, id)
);
-- A failed or rejected batch is history: it does not block sending the same bytes (or key) again.
create unique index import_batches_tenant_sha
  on cbam.import_batches (tenant_id, file_sha256)
  where file_sha256 is not null and status not in ('failed','rejected');
create unique index import_batches_tenant_idem
  on cbam.import_batches (tenant_id, idempotency_key)
  where idempotency_key is not null and status not in ('failed','rejected');
create index import_batches_tenant_created on cbam.import_batches (tenant_id, id desc);

-- Status moves forward only; terminal batches are locked; source facts never change.
create function cbam.import_batches_guard() returns trigger language plpgsql as $$
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
create trigger import_batches_guard before update on cbam.import_batches
  for each row execute function cbam.import_batches_guard();

create function cbam.import_batches_block_delete() returns trigger language plpgsql as $$
begin
  raise exception 'import batches cannot be deleted';
end $$;
create trigger import_batches_no_delete before delete on cbam.import_batches
  for each row execute function cbam.import_batches_block_delete();

alter table cbam.documents enable row level security;
alter table cbam.documents force row level security;
create policy tenant_isolation on cbam.documents
  using (tenant_id = cbam.current_tenant()) with check (tenant_id = cbam.current_tenant());
alter table cbam.document_versions enable row level security;
alter table cbam.document_versions force row level security;
create policy tenant_isolation on cbam.document_versions
  using (tenant_id = cbam.current_tenant()) with check (tenant_id = cbam.current_tenant());
alter table cbam.import_batches enable row level security;
alter table cbam.import_batches force row level security;
create policy tenant_isolation on cbam.import_batches
  using (tenant_id = cbam.current_tenant()) with check (tenant_id = cbam.current_tenant());

revoke update, delete, truncate on cbam.documents from cbam_app;
revoke update, delete, truncate on cbam.document_versions from cbam_app;
revoke delete, truncate on cbam.import_batches from cbam_app;
"""


def upgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute(_SQL)


def downgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute("drop table if exists cbam.import_batches")
    op.execute("drop table if exists cbam.document_versions")
    op.execute("drop table if exists cbam.documents")
    op.execute("drop function if exists cbam.import_batches_guard()")
    op.execute("drop function if exists cbam.import_batches_block_delete()")
    op.execute("drop function if exists cbam.documents_block_change()")
