"""Where a declaration's importer EORI came from (R1-036).

Revision ID: 0013
Revises: 0012

A report row without an importer EORI falls back to the EORI declared for the batch. That is a
convenience for the ledger, not a fact the customs data stated, so the liable-person engine must
not treat it as the importer (CLAUDE.md rule 15: no invented behaviour). `importer_eori_source`
records `declared` (the row said so) or `batch_fallback`. It is NULL for rows stored before this
migration and where there is no importer; the engine treats NULL with an importer as not declared
(fail closed). Declarations are append-only, so old rows are not rewritten.
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_UP = """
alter table cbam.declarations add column importer_eori_source text
  check (importer_eori_source in ('declared','batch_fallback'));
"""

_DOWN = "alter table cbam.declarations drop column importer_eori_source;"


def upgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute(_UP)


def downgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute(_DOWN)
