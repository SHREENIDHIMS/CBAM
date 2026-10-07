"""Join header and tax-lines report rows to import lines by declaration reference (R1-054).

The reports arrive as separate files in any order. A header or tax-lines row keeps its immutable
`source_rows` row; `report_row_keys` stores the MRN (and a tax line's item number) read from it
with the layout it was loaded under. The join is a source link on every CURRENT line with that
MRN (any declaration version: a line can still sit on an older one; role `header` or `tax_line`),
so the ledger's line detail lists the header and tax rows next to the item row. It runs after a
header or tax-lines chunk and after an item chunk, always under the per-MRN advisory lock the
normaliser takes, so whichever file lands second makes the link and a concurrent pair cannot
miss each other. Re-running changes nothing (the unique link and the unique key absorb it).

Nothing from these rows is copied onto a line: no procedure code, no duty, no tax point. That
reading belongs to the phases that need it.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.ids import uuid7
from app.modules.imports import normalisation, rules
from app.modules.imports.models import report_row_keys

# At most this many MRNs are joined in one statement (the advisory locks are taken per MRN).
JOIN_MRN_BATCH = 500

_JOIN_SQL = text(
    """
    insert into cbam.import_line_sources
      (id, tenant_id, import_line_id, source_row_id, report_type, role, created_at)
    select gen_random_uuid(), k.tenant_id, l.id, k.source_row_id, k.report_type,
           case k.report_type when 'import_header' then 'header' else 'tax_line' end, :now
      from cbam.report_row_keys k
      join cbam.declarations d on d.tenant_id = k.tenant_id and d.mrn = k.mrn
      join cbam.import_lines l
        on l.tenant_id = d.tenant_id and l.declaration_id = d.id
       and (k.item_no is null or l.item_no = k.item_no)
       and not exists (select 1 from cbam.import_lines nl
                        where nl.tenant_id = l.tenant_id and nl.supersedes_id = l.id)
     where k.tenant_id = :t and k.mrn = any(:mrns)
    on conflict (import_line_id, source_row_id, role) do nothing
    """
)


def register_keys(
    session: Session,
    *,
    tenant_id: UUID,
    batch_id: UUID,
    report_type: str,
    rows: Sequence[normalisation.SourceRow],
    match: rules.LayoutMatch,
    now: datetime,
) -> list[str]:
    """Store the join key of every row that has a usable one (the caller already holds the MRN
    locks). Returns the MRNs. A row with no usable key is skipped: its validation issues, already
    recorded, explain it."""
    values: list[dict[str, object]] = []
    mrns: list[str] = []
    for src in rows:
        key = rules.join_key(rules.map_row(src.raw, match), report_type)
        if key is None:
            continue
        mrn, item_no = key
        mrns.append(mrn)
        values.append(
            {
                "id": uuid7(),
                "tenant_id": tenant_id,
                "batch_id": batch_id,
                "source_row_id": src.id,
                "report_type": report_type,
                "mrn": mrn,
                "item_no": item_no,
                "created_at": now,
            }
        )
    if values:
        session.execute(
            pg_insert(report_row_keys)
            .values(values)
            .on_conflict_do_nothing(index_elements=["source_row_id"])
        )
    return sorted(set(mrns))


def keys_for_rows(
    rows: Sequence[normalisation.SourceRow], match: rules.LayoutMatch, report_type: str
) -> list[str]:
    """The MRNs of rows that will get a key: what to lock before registering them."""
    found = {
        key[0]
        for src in rows
        if (key := rules.join_key(rules.map_row(src.raw, match), report_type)) is not None
    }
    return sorted(found)


def lock_mrns(session: Session, tenant_id: UUID, mrns: Sequence[str]) -> None:
    """The per-MRN advisory lock of the normaliser (fixed order, so no deadlock)."""
    normalisation._lock_mrns(session, tenant_id, sorted(set(mrns)))


def join_mrns(session: Session, *, tenant_id: UUID, mrns: Sequence[str], now: datetime) -> int:
    """Link the stored header and tax-lines rows of these declarations to their current lines.
    Returns how many links were created (0 when everything was already linked)."""
    unique = sorted(set(mrns))
    created = 0
    for start in range(0, len(unique), JOIN_MRN_BATCH):
        result = session.execute(
            _JOIN_SQL, {"t": tenant_id, "mrns": unique[start : start + JOIN_MRN_BATCH], "now": now}
        )
        created += int(result.rowcount or 0)  # type: ignore[attr-defined]
    return created


def mrns_of_lines(session: Session, tenant_id: UUID, line_ids: Sequence[UUID]) -> list[str]:
    """The declaration references of lines (to join after an item chunk created them)."""
    if not line_ids:
        return []
    rows = session.execute(
        text(
            "select distinct d.mrn from cbam.import_lines l"
            " join cbam.declarations d on d.tenant_id = l.tenant_id and d.id = l.declaration_id"
            " where l.tenant_id = :t and l.id = any(:ids)"
        ),
        {"t": tenant_id, "ids": list(line_ids)},
    )
    return sorted(r.mrn for r in rows)
