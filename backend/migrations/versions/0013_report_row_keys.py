"""Join keys of header and tax-lines report rows (R1-054, Phase 3 step 8a).

Revision ID: 0013
Revises: 0012

The HMRC "Get customs data" service gives an import item report (one row per line), an import
header report (one row per declaration) and an import tax-lines report. The three arrive as
separate files, in any order, and are joined by declaration reference (MRN). A header or tax-lines
row is already stored as an immutable `source_rows` row; this table records ONLY the join key read
from it with the layout it was loaded under (the MRN and, for a tax line that names one, the item
number). The join itself is lineage: `import_line_sources` rows with role `header` or `tax_line`
(allowed since 0011). Nothing in the header or tax-lines rows becomes a fact about the line here:
procedure codes and duties are read in the phases that need them (Phase 4 onward).

Append-only like the other import tables: UPDATE, DELETE and TRUNCATE are revoked from `cbam_app`
and blocked by a trigger for every role. One key per source row (a re-run changes nothing).
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_SQL = """
create table cbam.report_row_keys (
  id uuid primary key,
  tenant_id uuid not null references cbam.tenants (id),
  batch_id uuid not null,
  source_row_id uuid not null,
  report_type text not null check (report_type in ('import_header','import_tax_lines')),
  mrn text not null check (length(mrn) between 1 and 100),
  item_no integer check (item_no >= 1),
  created_at timestamptz not null default now(),
  unique (source_row_id),
  foreign key (tenant_id, batch_id) references cbam.import_batches (tenant_id, id),
  foreign key (tenant_id, source_row_id) references cbam.source_rows (tenant_id, id),
  check (report_type = 'import_tax_lines' or item_no is null)
);
create index report_row_keys_tenant_mrn on cbam.report_row_keys (tenant_id, mrn);
create index report_row_keys_batch on cbam.report_row_keys (tenant_id, batch_id);

create trigger report_row_keys_immutable before update or delete on cbam.report_row_keys
  for each row execute function cbam.import_facts_block_change();
create trigger report_row_keys_no_truncate before truncate on cbam.report_row_keys
  for each statement execute function cbam.import_facts_block_change();

alter table cbam.report_row_keys enable row level security;
alter table cbam.report_row_keys force row level security;
create policy tenant_isolation on cbam.report_row_keys
  using (tenant_id = cbam.current_tenant()) with check (tenant_id = cbam.current_tenant());
revoke update, delete, truncate on cbam.report_row_keys from cbam_app;
"""

_DOWN = """
drop table if exists cbam.report_row_keys;
"""


def upgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute(_SQL)


def downgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute(_DOWN)
