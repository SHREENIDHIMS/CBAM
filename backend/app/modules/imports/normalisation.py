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

Stale or hand-made data never replaces newer facts: a row that equals ANY earlier version is
only a sighting, a current version that was corrected or keyed by hand is never superseded by a
file, and a report older than the one the current version came from is left for a human
(`rules.reconcile_version`). Before the chunks, a pre-pass finds rows of one file that give the
same key with different facts and rejects ALL of them (no first-wins).

A row is done once it has a source link or an error exception, so a crashed run resumes by
asking for the rows that have neither. The audit event of a chunk holds counts and ids only;
never a cell value, an MRN, an EORI or a name. Nothing here decides scope, tax point, quarter,
threshold or the liable person (Phases 4 to 6): the party roles are stored as reported.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
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
class _Version:
    id: UUID
    version: int
    content_sha256: str
    batch_id: UUID
    entry_method: str
    value_source: str
    recency: date


@dataclass
class _Chain:
    """Every version of one key, oldest first; the last is the current one."""

    versions: list[_Version]

    @property
    def current(self) -> _Version:
        return self.versions[-1]

    def by_hash(self) -> dict[str, UUID]:
        return {v.content_sha256: v.id for v in self.versions}


# The recency of a version is the date of the report that produced it: the date it was acquired,
# else the end of its window, else the date it was received (UK date).
_RECENCY = (
    "coalesce(b.acquired_on, b.window_end, (b.created_at at time zone 'Europe/London')::date)"
)


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


_FILE_CONFLICT_CODES = "('LINE_CONFLICT_IN_FILE','DECLARATION_FACTS_CONFLICT')"


def pending_rows(
    session: Session,
    tenant_id: UUID,
    batch_id: UUID,
    limit: int,
    *,
    after: int = 0,
    for_conflict_scan: bool = False,
) -> list[SourceRow]:
    """Rows of the batch with no source link yet, in row order. Normally also without an error
    exception; the conflict scan keeps rows whose only errors are file conflicts, so a rerun
    finds the same conflicts."""
    codes = f" and e.code not in {_FILE_CONFLICT_CODES}" if for_conflict_scan else ""
    rows = session.execute(
        text(
            "select sr.id, sr.row_number, sr.raw from cbam.source_rows sr"  # noqa: S608
            " where sr.tenant_id = :t and sr.batch_id = :b and sr.row_number > :after"
            " and not exists (select 1 from cbam.row_exceptions e"
            "   where e.tenant_id = sr.tenant_id and e.batch_id = sr.batch_id"
            f"   and e.row_number = sr.row_number and e.severity = 'error'{codes})"
            " and not exists (select 1 from cbam.import_line_sources s"
            "   where s.tenant_id = sr.tenant_id and s.source_row_id = sr.id)"
            " order by sr.row_number limit :n"
        ),
        {"t": tenant_id, "b": batch_id, "n": limit, "after": after},
    ).all()
    return [SourceRow(r.id, int(r.row_number), dict(r.raw)) for r in rows]


def find_file_conflicts(
    session: Session,
    tenant_id: UUID,
    batch_id: UUID,
    match: rules.LayoutMatch,
    ctx: rules.NormalisationContext,
    *,
    page: int = 500,
) -> list[tuple[int, UUID | None, rules.Issue]]:
    """Rows of ONE file that give the same line key with different facts, or the same MRN with
    different declaration facts. Every row involved is rejected (a data error in the file: there
    is no way to know which row is right), never first-wins."""
    rows: list[tuple[int, UUID, str, int, str, str]] = []
    after = 0
    while True:
        batch = pending_rows(
            session, tenant_id, batch_id, page, after=after, for_conflict_scan=True
        )
        if not batch:
            break
        after = batch[-1].number
        for src in batch:
            line = rules.normalise_row(rules.map_row(src.raw, match), ctx).line
            if line is not None:
                decl = line.declaration
                rows.append(
                    (
                        src.number,
                        src.id,
                        decl.mrn,
                        line.item_no,
                        line.content_sha256,
                        decl.content_sha256,
                    )
                )
    decl_hashes: dict[str, set[str]] = {}
    line_hashes: dict[tuple[str, int], set[str]] = {}
    for _, _, mrn, item, line_hash, decl_hash in rows:
        decl_hashes.setdefault(mrn, set()).add(decl_hash)
        line_hashes.setdefault((mrn, item), set()).add(line_hash)
    found: list[tuple[int, UUID | None, rules.Issue]] = []
    for number, source_id, mrn, item, _, _ in rows:
        if len(decl_hashes[mrn]) > 1:
            found.append(
                (number, source_id, rules.Issue("DECLARATION_FACTS_CONFLICT", "declaration.mrn"))
            )
        elif len(line_hashes[(mrn, item)]) > 1:
            found.append((number, source_id, rules.Issue("LINE_CONFLICT_IN_FILE", "line.item_no")))
    return found


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


def _declaration_chains(session: Session, tenant_id: UUID, mrns: list[str]) -> dict[str, _Chain]:
    rows = session.execute(
        text(
            "select d.id, d.mrn, d.version, d.content_sha256, d.batch_id, d.entry_method,"  # noqa: S608
            f" 'declared' as value_source, {_RECENCY} as recency"
            " from cbam.declarations d join cbam.import_batches b"
            "   on b.tenant_id = d.tenant_id and b.id = d.batch_id"
            " where d.tenant_id = :t and d.mrn = any(:m) order by d.mrn, d.version"
        ),
        {"t": tenant_id, "m": mrns},
    ).all()
    chains: dict[str, _Chain] = {}
    for r in rows:
        v = _Version(
            r.id, r.version, r.content_sha256, r.batch_id, r.entry_method, r.value_source, r.recency
        )
        chains.setdefault(r.mrn, _Chain([])).versions.append(v)
    return chains


def _line_chains(
    session: Session, tenant_id: UUID, mrns: list[str]
) -> dict[tuple[str, int], _Chain]:
    rows = session.execute(
        text(
            "select l.id, l.item_no, l.version, l.content_sha256, l.batch_id, l.entry_method,"  # noqa: S608
            f" l.value_source, d.mrn, {_RECENCY} as recency"
            " from cbam.import_lines l join cbam.declarations d"
            "   on d.tenant_id = l.tenant_id and d.id = l.declaration_id"
            " join cbam.import_batches b on b.tenant_id = l.tenant_id and b.id = l.batch_id"
            " where l.tenant_id = :t and d.mrn = any(:m) order by d.mrn, l.item_no, l.version"
        ),
        {"t": tenant_id, "m": mrns},
    ).all()
    chains: dict[tuple[str, int], _Chain] = {}
    for r in rows:
        v = _Version(
            r.id, r.version, r.content_sha256, r.batch_id, r.entry_method, r.value_source, r.recency
        )
        chains.setdefault((r.mrn, int(r.item_no)), _Chain([])).versions.append(v)
    return chains


def _decide(chain: _Chain | None, incoming_hash: str, batch_id: UUID, recency: date) -> str:
    cur = chain.current if chain else None
    return rules.reconcile_version(
        current_hash=cur.content_sha256 if cur else None,
        current_entry_method=cur.entry_method if cur else None,
        current_value_source=cur.value_source if cur else None,
        current_batch_id=cur.batch_id if cur else None,
        current_recency=cur.recency if cur else None,
        earlier_hashes=frozenset(v.content_sha256 for v in chain.versions[:-1])
        if chain
        else frozenset(),
        incoming_hash=incoming_hash,
        incoming_batch_id=batch_id,
        incoming_recency=recency,
    )


def normalise_chunk(
    session: Session,
    *,
    tenant_id: UUID,
    batch_id: UUID,
    report_type: str,
    rows: list[SourceRow],
    match: rules.LayoutMatch,
    ctx: rules.NormalisationContext,
    recency: date,
    now: datetime,
    add_exceptions: ExceptionSink,
) -> ChunkOutcome:
    """Normalise one chunk inside the caller's transaction and write its audit event.
    `recency` is the date of this batch's report (see `_RECENCY`)."""
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
    decl_chains = _declaration_chains(session, tenant_id, mrns)
    line_chains = _line_chains(session, tenant_id, mrns)
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
            chain = decl_chains.get(mrn)
            action = _decide(chain, decl.content_sha256, batch_id, recency)
            if action in _DECLARATION_BLOCKED:
                rejected.append((src.number, src.id, _blocked_issue(action, "declaration.mrn")))
                continue
            key = (mrn, line.item_no)
            lchain = line_chains.get(key)
            line_action = _decide(lchain, line.content_sha256, batch_id, recency)
            if line_action in _LINE_BLOCKED:
                rejected.append((src.number, src.id, _blocked_issue(line_action, "line.item_no")))
                continue
            if action in ("new", "changed"):
                previous = chain.current if chain else None
                decl_id = uuid7()
                version = 1 if previous is None else previous.version + 1
                decl_rows.append(
                    {
                        "id": decl_id,
                        "tenant_id": tenant_id,
                        "mrn": mrn,
                        "version": version,
                        "supersedes_id": None if previous is None else previous.id,
                        "acceptance_date": decl.acceptance_date,
                        "importer_party_id": party_ids.get(decl.importer_eori or ""),
                        "declarant_party_id": party_ids.get(decl.declarant_eori or ""),
                        "representative_party_id": party_ids.get(decl.representative_eori or ""),
                        "representation_type": decl.representation_type,
                        "eori_context": decl.eori_context,
                        "entry_method": ctx.entry_method,
                        "batch_id": batch_id,
                        "content_sha256": decl.content_sha256,
                        "hash_version": rules.HASH_VERSION,
                        "created_at": now,
                    }
                )
                out.declaration_ids.append(decl_id)
                if previous is None:
                    out.declarations_created += 1
                else:
                    out.declarations_superseded += 1
                entry = _Version(
                    decl_id,
                    version,
                    decl.content_sha256,
                    batch_id,
                    ctx.entry_method,
                    "declared",
                    recency,
                )
                chain = decl_chains.setdefault(mrn, _Chain([]))
                chain.versions.append(entry)
            if chain is None:  # unreachable: 'new' and 'changed' both create the chain
                continue
            # 'same' and 'seen_earlier' keep the CURRENT declaration; a stale header never
            # replaces a newer one.
            current_decl = chain.current
            if line_action in ("same", "seen_earlier") and lchain is not None:
                target = (
                    lchain.current.id
                    if line_action == "same"
                    else lchain.by_hash()[line.content_sha256]
                )
                out.duplicates_seen += 1
                source_rows.append(
                    _source(tenant_id, target, src.id, report_type, "duplicate_seen", now)
                )
                continue
            previous_line = lchain.current if lchain else None
            line_id = uuid7()
            version = 1 if previous_line is None else previous_line.version + 1
            line_rows.append(
                {
                    "id": line_id,
                    "tenant_id": tenant_id,
                    "declaration_id": current_decl.id,
                    "item_no": line.item_no,
                    "version": version,
                    "supersedes_id": None if previous_line is None else previous_line.id,
                    "commodity_code": line.commodity_code,
                    "description": line.description,
                    "net_mass_kg": line.net_mass_kg,
                    "customs_value_source": line.customs_value_source,
                    "customs_value_currency": line.customs_value_currency,
                    "customs_value_gbp": line.customs_value_gbp,
                    "customs_value_gbp_note": line.customs_value_gbp_note,
                    "valuation_basis": line.valuation_basis,
                    "value_source": line.value_source,
                    "value_override_reason": ctx.override_reason,
                    "country_of_origin_declared": line.country_of_origin_declared,
                    "cpc": line.cpc,
                    "batch_id": batch_id,
                    "source_row_id": src.id,
                    "entry_method": ctx.entry_method,
                    "change_reason": None if previous_line is None else ctx.change_reason,
                    "content_sha256": line.content_sha256,
                    "hash_version": rules.HASH_VERSION,
                    "created_at": now,
                }
            )
            source_rows.append(_source(tenant_id, line_id, src.id, report_type, "primary", now))
            out.line_ids.append(line_id)
            if previous_line is None:
                out.lines_created += 1
            else:
                out.lines_superseded += 1
                out.superseded.append((previous_line.id, line_id))
            line_chains.setdefault(key, _Chain([])).versions.append(
                _Version(
                    line_id,
                    version,
                    line.content_sha256,
                    batch_id,
                    ctx.entry_method,
                    line.value_source,
                    recency,
                )
            )

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


_DECLARATION_BLOCKED = frozenset({"conflict", "blocked_by_correction", "older_extract"})
_LINE_BLOCKED = _DECLARATION_BLOCKED


def _blocked_issue(action: str, field: str) -> rules.Issue:
    if action == "blocked_by_correction":
        return rules.Issue("SOURCE_CONFLICTS_WITH_CORRECTION", field)
    if action == "older_extract":
        return rules.Issue("OLDER_EXTRACT_CONFLICT", field)
    return rules.Issue(
        "DECLARATION_FACTS_CONFLICT" if field == "declaration.mrn" else "LINE_CONFLICT_IN_FILE",
        field,
    )


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
