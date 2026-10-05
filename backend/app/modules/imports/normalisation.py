"""Normalise validated source rows into parties, declarations and import lines (R1-005, R1-006,
R1-010), keeping the lineage back to the raw row (CLAUDE.md rule 4).

One chunk of rows is one tenant transaction. Rows are grouped per declaration reference (MRN)
and each group is serialised by an advisory lock on (tenant, MRN), taken in a fixed order, so two
files that overlap cannot both create the same declaration or line. For every row the pure rule
`rules.reconcile` compares the incoming facts with the CURRENT version of that line:

- new: a version 1 line, plus a `primary` source link;
- same: nothing new, only a `duplicate_seen` source link (the overlap stays as evidence);
- changed: a new version that supersedes the old one (the old one is kept), `source_changed`;
- conflict (two different versions of one key inside one file): a row exception, no line.

A row is done once it has a source link or an error exception, so a crashed run resumes by
asking for the rows that have neither. The audit event of a chunk holds counts and ids only;
never a cell value, an MRN, an EORI or a name. Nothing here decides scope, tax point, quarter,
threshold or the liable person (Phases 4 to 6): the party roles are stored as reported.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.audit import record
from app.core.ids import uuid7
from app.modules.imports import rules
from app.modules.imports.models import (
    declarations,
    import_line_sources,
    import_lines,
    parties,
)

ExceptionSink = Callable[[Session, list[tuple[int, UUID | None, rules.Issue]]], None]
MAX_IDS_PER_EVENT = 500
NORMALISE_CHUNK_ROWS = 500


@dataclass(frozen=True)
class SourceRow:
    id: UUID
    number: int
    raw: dict[str, Any]


@dataclass(frozen=True)
class _Current:
    id: UUID
    version: int
    content_sha256: str
    batch_id: UUID


@dataclass
class ChunkOutcome:
    rows: int = 0
    lines_created: int = 0
    lines_superseded: int = 0
    duplicates_seen: int = 0
    declarations_created: int = 0
    declarations_superseded: int = 0
    rows_rejected: int = 0
    line_ids: list[UUID] = field(default_factory=list)
    declaration_ids: list[UUID] = field(default_factory=list)
    superseded: list[tuple[UUID, UUID]] = field(default_factory=list)


def pending_rows(session: Session, tenant_id: UUID, batch_id: UUID, limit: int) -> list[SourceRow]:
    """Rows of the batch with no error exception and no source link yet, in row order."""
    rows = session.execute(
        text(
            "select sr.id, sr.row_number, sr.raw from cbam.source_rows sr"
            " where sr.tenant_id = :t and sr.batch_id = :b"
            " and not exists (select 1 from cbam.row_exceptions e"
            "   where e.tenant_id = sr.tenant_id and e.batch_id = sr.batch_id"
            "   and e.row_number = sr.row_number and e.severity = 'error')"
            " and not exists (select 1 from cbam.import_line_sources s"
            "   where s.tenant_id = sr.tenant_id and s.source_row_id = sr.id)"
            " order by sr.row_number limit :n"
        ),
        {"t": tenant_id, "b": batch_id, "n": limit},
    ).all()
    return [SourceRow(r.id, int(r.row_number), dict(r.raw)) for r in rows]


def _lock_mrns(session: Session, tenant_id: UUID, mrns: list[str]) -> None:
    for mrn in sorted(mrns):  # one fixed order, so two jobs cannot deadlock each other
        session.execute(
            text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"imports:mrn:{tenant_id}:{mrn}"},
        )


def _upsert_parties(
    session: Session, tenant_id: UUID, eoris: set[str], now: datetime
) -> dict[str, UUID]:
    if not eoris:
        return {}
    session.execute(
        pg_insert(parties)
        .values(
            [
                {"id": uuid7(), "tenant_id": tenant_id, "eori": e, "name": None, "created_at": now}
                for e in sorted(eoris)
            ]
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", "eori"], index_where=parties.c.eori.is_not(None)
        )
    )
    found = session.execute(
        select(parties.c.eori, parties.c.id).where(
            parties.c.tenant_id == tenant_id, parties.c.eori.in_(sorted(eoris))
        )
    ).all()
    return {r.eori: r.id for r in found}


def _current_declarations(
    session: Session, tenant_id: UUID, mrns: list[str]
) -> dict[str, _Current]:
    rows = session.execute(
        text(
            "select d.id, d.mrn, d.version, d.content_sha256, d.batch_id from cbam.declarations d"
            " where d.tenant_id = :t and d.mrn = any(:m)"
            " and not exists (select 1 from cbam.declarations n"
            "   where n.tenant_id = d.tenant_id and n.supersedes_id = d.id)"
        ),
        {"t": tenant_id, "m": mrns},
    ).all()
    return {r.mrn: _Current(r.id, r.version, r.content_sha256, r.batch_id) for r in rows}


def _current_lines(
    session: Session, tenant_id: UUID, mrns: list[str]
) -> dict[tuple[str, int], _Current]:
    rows = session.execute(
        text(
            "select l.id, l.item_no, l.version, l.content_sha256, l.batch_id, d.mrn"
            " from cbam.import_lines l join cbam.declarations d"
            "   on d.tenant_id = l.tenant_id and d.id = l.declaration_id"
            " where l.tenant_id = :t and d.mrn = any(:m)"
            " and not exists (select 1 from cbam.import_lines n"
            "   where n.tenant_id = l.tenant_id and n.supersedes_id = l.id)"
        ),
        {"t": tenant_id, "m": mrns},
    ).all()
    return {
        (r.mrn, int(r.item_no)): _Current(r.id, r.version, r.content_sha256, r.batch_id)
        for r in rows
    }


def normalise_chunk(
    session: Session,
    *,
    tenant_id: UUID,
    batch_id: UUID,
    report_type: str,
    rows: list[SourceRow],
    match: rules.LayoutMatch,
    ctx: rules.NormalisationContext,
    now: datetime,
    add_exceptions: ExceptionSink,
) -> ChunkOutcome:
    """Normalise one chunk inside the caller's transaction and write its audit event."""
    out = ChunkOutcome(rows=len(rows))
    rejected: list[tuple[int, UUID | None, rules.Issue]] = []
    groups: dict[str, list[tuple[SourceRow, rules.NormalisedLine]]] = {}
    for src in rows:
        result = rules.normalise_row(rules.map_row(src.raw, match), ctx)
        if result.line is None:
            rejected.extend((src.number, src.id, issue) for issue in result.issues)
        else:
            groups.setdefault(result.line.declaration.mrn, []).append((src, result.line))
    mrns = sorted(groups)
    _lock_mrns(session, tenant_id, mrns)
    current_decl = _current_declarations(session, tenant_id, mrns)
    current_line = _current_lines(session, tenant_id, mrns)
    party_ids = _upsert_parties(
        session,
        tenant_id,
        {
            e
            for items in groups.values()
            for _, line in items
            for e in (
                line.declaration.importer_eori,
                line.declaration.declarant_eori,
                line.declaration.representative_eori,
            )
            if e
        },
        now,
    )

    decl_rows: list[dict[str, Any]] = []
    line_rows: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    for mrn in mrns:
        for src, line in groups[mrn]:
            decl = line.declaration
            existing = current_decl.get(mrn)
            action = rules.reconcile(
                existing.content_sha256 if existing else None,
                decl.content_sha256,
                same_batch=existing is not None and existing.batch_id == batch_id,
            )
            if action == "conflict":
                rejected.append(
                    (
                        src.number,
                        src.id,
                        rules.Issue("DECLARATION_FACTS_CONFLICT", "declaration.mrn"),
                    )
                )
                continue
            if action in ("new", "changed"):
                decl_id = uuid7()
                decl_rows.append(
                    {
                        "id": decl_id,
                        "tenant_id": tenant_id,
                        "mrn": mrn,
                        "version": 1 if existing is None else existing.version + 1,
                        "supersedes_id": None if existing is None else existing.id,
                        "acceptance_date": decl.acceptance_date,
                        "importer_party_id": party_ids.get(decl.importer_eori or ""),
                        "declarant_party_id": party_ids.get(decl.declarant_eori or ""),
                        "representative_party_id": party_ids.get(decl.representative_eori or ""),
                        "representation_type": decl.representation_type,
                        "eori_context": decl.eori_context,
                        "entry_method": ctx.entry_method,
                        "batch_id": batch_id,
                        "content_sha256": decl.content_sha256,
                        "created_at": now,
                    }
                )
                out.declaration_ids.append(decl_id)
                if existing is None:
                    out.declarations_created += 1
                else:
                    out.declarations_superseded += 1
                existing = _Current(
                    decl_id,
                    1 if existing is None else existing.version + 1,
                    decl.content_sha256,
                    batch_id,
                )
                current_decl[mrn] = existing
            if existing is None:  # unreachable: 'new' and 'changed' both set it
                continue
            key = (mrn, line.item_no)
            previous = current_line.get(key)
            line_action = rules.reconcile(
                previous.content_sha256 if previous else None,
                line.content_sha256,
                same_batch=previous is not None and previous.batch_id == batch_id,
            )
            if line_action == "conflict":
                rejected.append(
                    (src.number, src.id, rules.Issue("LINE_CONFLICT_IN_FILE", "line.item_no"))
                )
                continue
            if line_action == "same" and previous is not None:
                out.duplicates_seen += 1
                source_rows.append(
                    _source(tenant_id, previous.id, src.id, report_type, "duplicate_seen", now)
                )
                continue
            line_id = uuid7()
            version = 1 if previous is None else previous.version + 1
            line_rows.append(
                {
                    "id": line_id,
                    "tenant_id": tenant_id,
                    "declaration_id": existing.id,
                    "item_no": line.item_no,
                    "version": version,
                    "supersedes_id": None if previous is None else previous.id,
                    "commodity_code": line.commodity_code,
                    "description": line.description,
                    "net_mass_kg": line.net_mass_kg,
                    "customs_value_source": line.customs_value_source,
                    "customs_value_currency": line.customs_value_currency,
                    "customs_value_gbp": line.customs_value_gbp,
                    "customs_value_gbp_note": line.customs_value_gbp_note,
                    "valuation_basis": line.valuation_basis,
                    "value_source": line.value_source,
                    "country_of_origin_declared": line.country_of_origin_declared,
                    "cpc": line.cpc,
                    "batch_id": batch_id,
                    "source_row_id": src.id,
                    "entry_method": ctx.entry_method,
                    "change_reason": None if previous is None else rules.REASON_SOURCE_CHANGED,
                    "content_sha256": line.content_sha256,
                    "created_at": now,
                }
            )
            source_rows.append(_source(tenant_id, line_id, src.id, report_type, "primary", now))
            out.line_ids.append(line_id)
            if previous is None:
                out.lines_created += 1
            else:
                out.lines_superseded += 1
                out.superseded.append((previous.id, line_id))
            current_line[key] = _Current(line_id, version, line.content_sha256, batch_id)

    if decl_rows:
        session.execute(insert(declarations), decl_rows)
    if line_rows:
        session.execute(insert(import_lines), line_rows)
    if source_rows:
        session.execute(insert(import_line_sources), source_rows)
    if rejected:
        add_exceptions(session, rejected)
    out.rows_rejected = len({n for n, _, _ in rejected})
    _audit(session, tenant_id, batch_id, rows, out, now)
    return out


def _source(
    tenant_id: UUID, line_id: UUID, source_row_id: UUID, report_type: str, role: str, now: datetime
) -> dict[str, Any]:
    return {
        "id": uuid7(),
        "tenant_id": tenant_id,
        "import_line_id": line_id,
        "source_row_id": source_row_id,
        "report_type": report_type,
        "role": role,
        "created_at": now,
    }


def _audit(
    session: Session,
    tenant_id: UUID,
    batch_id: UUID,
    rows: list[SourceRow],
    out: ChunkOutcome,
    now: datetime,
) -> None:
    """One event per chunk: counts and ids (at most 500 of each kind, a chunk is at most that
    many rows). No cell value, MRN, EORI or name ever goes in."""
    record(
        session,
        tenant_id=tenant_id,
        actor_type="job",
        actor_id=None,
        action="import_batch.lines_normalised",
        object_type="import_batch",
        object_id=batch_id,
        occurred_at=now,
        after={
            "rows": out.rows,
            "first_row": min(r.number for r in rows),
            "last_row": max(r.number for r in rows),
            "lines_created": out.lines_created,
            "lines_superseded": out.lines_superseded,
            "duplicates_seen": out.duplicates_seen,
            "declarations_created": out.declarations_created,
            "declarations_superseded": out.declarations_superseded,
            "rows_rejected": out.rows_rejected,
            "line_ids": [str(i) for i in out.line_ids[:MAX_IDS_PER_EVENT]],
            "declaration_ids": [str(i) for i in out.declaration_ids[:MAX_IDS_PER_EVENT]],
            "superseded": [
                {"old": str(o), "new": str(n)} for o, n in out.superseded[:MAX_IDS_PER_EVENT]
            ],
        },
    )
