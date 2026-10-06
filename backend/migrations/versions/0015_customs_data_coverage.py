"""Customs-data coverage tracker (R1-054, Phase 3 step 8b).

Revision ID: 0015
Revises: 0014

Three things:

`ref_customs_data_service` (+ `v_active_customs_data_service`): the facts about HMRC's "Get
customs data" service that the tracker needs as numbers (for example how many of the latest days
are never available). They come from HMRC guidance, so they are DATA with a source (CLAUDE.md
rule 1), loaded `pending` and usable only once the source is in force (rule 2; see GOV-DEC-021).
Nothing is loaded here.

`customs_data_eoris`: the EORIs (GB or XI) a client must have covered, the first day to cover
(`tracking_from`) and whether the client granted us third-party access in the HMRC service
(`unknown`, `requested`, `granted`, `revoked`). Editable only through the API (row version,
audit); `tracking_from` is never edited, so a gap cannot be hidden by moving the start.

`customs_data_coverage`: one row per COMPLETED report batch that declared an EORI and a date
window: the days that report covers, for the calendar, gap and overlap detection. Append-only
(UPDATE, DELETE and TRUNCATE revoked and blocked by trigger). `has_errors` is true when the
batch finished with rejected rows: those days are loaded but not trustworthy (REG-DEC-023).
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

_DATASET = """
create table cbam.ref_customs_data_service (
  id uuid primary key,
  dataset_version_id uuid not null references cbam.ref_dataset_versions (id),
  effective_from date not null,
  effective_to date,
  rule_key text not null check (rule_key ~ '^[a-z][a-z0-9_.]*$'),
  value_int integer not null check (value_int >= 0),
  description text not null,
  check (effective_to is null or effective_to > effective_from),
  constraint ref_customs_data_service_no_overlap exclude using gist (
    dataset_version_id with =, rule_key with =,
    daterange(effective_from, effective_to) with &&)
);
create index ref_customs_data_service_version on cbam.ref_customs_data_service
  (dataset_version_id);
create trigger ref_customs_data_service_guard before insert or update or delete
  on cbam.ref_customs_data_service for each row execute function cbam.ref_data_guard();
create trigger ref_customs_data_service_guard_truncate before truncate
  on cbam.ref_customs_data_service for each statement execute function cbam.ref_data_guard();
revoke update, delete, truncate on cbam.ref_customs_data_service from cbam_app;
alter table cbam.ref_customs_data_service enable row level security;
alter table cbam.ref_customs_data_service force row level security;
create policy open_read on cbam.ref_customs_data_service for select using (true);
create policy platform_insert on cbam.ref_customs_data_service for insert
  with check (cbam.is_platform());

create view cbam.v_active_customs_data_service as
select t.*,
       v.version as dataset_version,
       s.source_id as source_ref,
       s.status as source_status,
       greatest(t.effective_from, s.commencement_date, s.effective_from) as usable_from,
       least(t.effective_to, s.effective_to) as usable_to
from cbam.ref_customs_data_service t
join cbam.ref_dataset_versions v on v.id = t.dataset_version_id
join cbam.regulatory_sources s on s.id = v.source_id
where v.status = 'active' and s.status in ('in_force','commenced','superseded');
revoke insert, update, delete, truncate on cbam.v_active_customs_data_service from cbam_app;
"""

_TABLES = """
create table cbam.customs_data_eoris (
  id uuid primary key,
  tenant_id uuid not null references cbam.tenants (id),
  eori text not null check (eori ~ '^(GB|XI)[0-9]{12}$'),
  tracking_from date not null,
  third_party_access text not null default 'unknown'
    check (third_party_access in ('unknown','requested','granted','revoked')),
  access_recorded_on date,
  note text check (length(note) <= 500),
  created_at timestamptz not null default now(),
  created_by uuid,
  updated_at timestamptz,
  row_version integer not null default 1,
  unique (tenant_id, id),
  unique (tenant_id, eori)
);

create table cbam.customs_data_coverage (
  id uuid primary key,
  tenant_id uuid not null references cbam.tenants (id),
  eori text not null check (eori ~ '^(GB|XI)[0-9]{12}$'),
  report_type text not null
    check (report_type in ('import_item','import_header','import_tax_lines','export_item')),
  covered_from date not null,
  covered_to date not null,
  batch_id uuid not null,
  has_errors boolean not null default false,
  created_at timestamptz not null default now(),
  check (covered_to >= covered_from),
  unique (tenant_id, batch_id),
  foreign key (tenant_id, batch_id) references cbam.import_batches (tenant_id, id)
);
create index customs_data_coverage_lookup
  on cbam.customs_data_coverage (tenant_id, eori, report_type, covered_from);

create trigger customs_data_coverage_immutable before update or delete
  on cbam.customs_data_coverage for each row execute function cbam.import_facts_block_change();
create trigger customs_data_coverage_no_truncate before truncate
  on cbam.customs_data_coverage for each statement execute function cbam.import_facts_block_change();
"""

_RLS = (
    "\n".join(
        f"""
alter table cbam.{t} enable row level security;
alter table cbam.{t} force row level security;
create policy tenant_isolation on cbam.{t}
  using (tenant_id = cbam.current_tenant()) with check (tenant_id = cbam.current_tenant());
"""
        for t in ("customs_data_eoris", "customs_data_coverage")
    )
    + "\nrevoke update, delete, truncate on cbam.customs_data_coverage from cbam_app;\n"
)

_DOWN = """
drop table if exists cbam.customs_data_coverage;
drop table if exists cbam.customs_data_eoris;
drop view if exists cbam.v_active_customs_data_service;
drop table if exists cbam.ref_customs_data_service;
"""


def upgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute(_DATASET)
    op.execute(_TABLES)
    op.execute(_RLS)


def downgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute(_DOWN)
