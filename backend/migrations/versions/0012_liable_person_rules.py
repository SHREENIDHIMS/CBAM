"""Reference dataset `liable_person_rules` (R1-036).

Revision ID: 0012
Revises: 0011

Which party is liable for CBAM for a declaration is law (LEGAL-DEC-019 is still open), so the
rules are DATA: effective-dated rows loaded from `backend/refdata/` and read through
`v_active_liable_person_rules`, which applies the source activation rule (a draft or laid source
never drives a decision). Nothing is loaded by this migration. A row says: for a declaration with
this `representation_type`, this relation between declarant and importer (and optionally this EORI
prefix, GB or XI), the liable party is the importer, the declarant or the representative.

Same shape as the tables of 0008 (triggers, forced RLS, read-open, platform-only insert).
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_TABLE = "cbam.ref_liable_person_rules"

_SQL = f"""
create table {_TABLE} (
  id uuid primary key,
  dataset_version_id uuid not null references cbam.ref_dataset_versions (id),
  effective_from date not null,
  effective_to date,
  rule_key text not null check (rule_key ~ '^[a-z][a-z0-9_.]*$'),
  representation_type text not null
    check (representation_type in ('self','direct','indirect','unknown')),
  declarant_relation text not null
    check (declarant_relation in ('same_as_importer','different_from_importer','absent','any')),
  eori_context text check (eori_context in ('GB','XI')),
  liable_party text not null check (liable_party in ('importer','declarant','representative')),
  description text not null,
  check (effective_to is null or effective_to > effective_from),
  constraint ref_liable_person_rules_no_overlap exclude using gist (
    dataset_version_id with =, rule_key with =,
    daterange(effective_from, effective_to) with &&)
);
create index ref_liable_person_rules_version on {_TABLE} (dataset_version_id);
create trigger ref_liable_person_rules_guard before insert or update or delete on {_TABLE}
  for each row execute function cbam.ref_data_guard();
create trigger ref_liable_person_rules_guard_truncate before truncate on {_TABLE}
  for each statement execute function cbam.ref_data_guard();
revoke update, delete, truncate on {_TABLE} from cbam_app;
alter table {_TABLE} enable row level security;
alter table {_TABLE} force row level security;
create policy open_read on {_TABLE} for select using (true);
create policy platform_insert on {_TABLE} for insert with check (cbam.is_platform());

create view cbam.v_active_liable_person_rules as
select t.*,
       v.version as dataset_version,
       s.source_id as source_ref,
       s.status as source_status,
       greatest(t.effective_from, s.commencement_date, s.effective_from) as usable_from,
       least(t.effective_to, s.effective_to) as usable_to
from {_TABLE} t
join cbam.ref_dataset_versions v on v.id = t.dataset_version_id
join cbam.regulatory_sources s on s.id = v.source_id
where v.status = 'active' and s.status in ('in_force','commenced','superseded');
revoke insert, update, delete, truncate on cbam.v_active_liable_person_rules from cbam_app;
"""  # noqa: S608 - the table name is the constant above

_DOWN = """
drop view if exists cbam.v_active_liable_person_rules;
drop table if exists cbam.ref_liable_person_rules;
"""


def upgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute(_SQL)


def downgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute(_DOWN)
