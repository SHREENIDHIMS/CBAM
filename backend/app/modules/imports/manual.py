"""Manual import entry (R1-004): a person keys one line, with a reason.

The entry is not a back door. It becomes a one-row batch (`manual_entry`, no file), its keyed
facts are stored as an immutable source row (so lineage and the "raw" view work as for a file),
and it goes through the SAME validation and normalisation as a file row (`rules.validate_row`,
`rules.normalise_row`, `normalisation.normalise_chunk`). The line is stored with `entry_method =
manual`, `value_source = manual` and the reason; everything downstream reads it like any other
line. A manual entry never changes a declaration or line that came from a file (409
`MANUAL_ENTRY_OVER_FILE`: use a correction, R1-010), nor one another entry or a correction
already settled; one that equals what is already there is only recorded as a sighting.

Nothing here decides scope, tax point, quarter, threshold or the liable person.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from app.core.audit import record
from app.core.errors import InvalidRequestError, ReasonRequiredError, RuleBlockedError
from app.core.ids import uuid7
from app.modules.imports import normalisation, rules
from app.modules.imports.manual_schemas import EntryProblem, ManualEntryIn, ManualEntryOut
from app.modules.imports.models import import_batches, source_rows
from app.modules.imports.service import Actor, advance_batch, find_keyed_batch

REPORT_TYPE = "import_item"


def _fields(entry: ManualEntryIn) -> dict[str, str | None]:
    return {
        "declaration.mrn": entry.mrn,
        "declaration.acceptance_date": entry.acceptance_date.isoformat(),
        "declaration.eori": entry.importer_eori,
        "declaration.declarant_eori": entry.declarant_eori,
        "declaration.representative_eori": entry.representative_eori,
        "declaration.representation_type": entry.representation_type,
        "line.item_no": str(entry.item_no),
        "line.commodity_code": entry.commodity_code,
        "line.net_mass_kg": entry.net_mass_kg,
        "line.customs_value": entry.customs_value,
        "line.customs_value_currency": entry.customs_value_currency,
        "line.origin_country": entry.origin_country,
        "line.valuation_basis": entry.valuation_basis,
        "line.cpc": entry.cpc,
        "line.description": entry.description,
        "line.supplier_ref": entry.supplier_ref,
    }


def _problem(issue: rules.Issue) -> EntryProblem:
    return EntryProblem(field=issue.field, code=issue.code, message=rules.issue_message(issue.code))


def _match() -> rules.LayoutMatch:
    headers = [*sorted(rules.CANONICAL_FIELDS), rules.MANUAL_REASON_KEY]
    return rules.match_layout(headers, rules.manual_layout())


def check_entry(entry: ManualEntryIn) -> tuple[dict[str, str], list[EntryProblem]]:
    """Validate a keyed entry with the file rules. Returns the raw row and the warnings, or
    raises 422 listing every error (nothing is stored for an invalid entry)."""
    decision = rules.check_manual_reason(entry.reason)
    if decision.outcome == "BLOCKED":
        raise ReasonRequiredError(decision.reason, rule_id=decision.rule_id)
    raw = rules.manual_raw(_fields(entry), entry.reason)
    mapped = rules.map_row(raw, _match())
    issues = list(rules.validate_row(mapped))
    ctx = rules.NormalisationContext(
        batch_eori=entry.importer_eori, entry_method="manual", value_source="manual"
    )
    if rules.row_is_valid(issues):
        issues.extend(rules.normalise_row(mapped, ctx).issues)
    errors = [i for i in issues if rules.issue_severity(i.code) == "error"]
    if errors:
        raise InvalidRequestError(
            "The entry is not valid",
            rule_id=rules.RULE_MANUAL_ENTRY,
            errors=[_problem(i).model_dump() for i in errors],
        )
    return raw, [_problem(i) for i in issues if rules.issue_severity(i.code) != "error"]


def create_manual_entry(
    session: Session,
    *,
    tenant_id: UUID,
    actor: Actor,
    now: datetime,
    today: date,
    entry: ManualEntryIn,
    idempotency_key: str | None = None,
) -> ManualEntryOut:
    """Store one keyed line in the caller's transaction (all or nothing). The same
    Idempotency-Key with the same entry answers again without storing anything."""
    raw, warnings = check_entry(entry)
    reason = entry.reason.strip()
    batch_id = uuid7()
    row_hash = rules.row_hash(raw)
    if idempotency_key:
        earlier = find_keyed_batch(
            session,
            tenant_id=tenant_id,
            key=idempotency_key,
            fingerprint=bytes.fromhex(row_hash),
        )
        if earlier is not None:
            return _replay(session, tenant_id, earlier.id, warnings)
    session.execute(
        insert(import_batches).values(
            id=batch_id,
            tenant_id=tenant_id,
            acquisition_method="manual_entry",
            cds_report_type=REPORT_TYPE,
            eori=entry.importer_eori,
            acquired_on=today,
            request_fingerprint=bytes.fromhex(row_hash),
            idempotency_key=idempotency_key or None,
            status="received",
            created_at=now,
            created_by=actor.actor_id,
            row_version=1,
        )
    )
    source_row_id = uuid7()
    session.execute(
        insert(source_rows).values(
            id=source_row_id,
            tenant_id=tenant_id,
            batch_id=batch_id,
            row_number=1,
            raw=raw,
            row_sha256=row_hash,
            created_at=now,
        )
    )
    rejected: list[tuple[int, UUID | None, rules.Issue]] = []

    def sink(_: Session, items: list[tuple[int, UUID | None, rules.Issue]]) -> None:
        rejected.extend(items)

    ctx = rules.NormalisationContext(
        batch_eori=entry.importer_eori,
        entry_method=rules.entry_method_for("manual_entry"),
        value_source="manual",
        override_reason=reason,
        change_reason=rules.REASON_MANUAL_ENTRY,
    )
    outcome = normalisation.normalise_chunk(
        session,
        tenant_id=tenant_id,
        batch_id=batch_id,
        report_type=REPORT_TYPE,
        rows=[normalisation.SourceRow(source_row_id, 1, raw)],
        match=_match(),
        ctx=ctx,
        recency=today,
        now=now,
        add_exceptions=sink,
    )
    if rejected:
        # Rolled back with the caller's transaction: a refused entry leaves nothing behind.
        issues = [i for _, _, i in rejected]
        codes = sorted({i.code for i in issues})
        over_file = "MANUAL_ENTRY_OVER_FILE" in codes
        raise RuleBlockedError(
            rules.issue_message("MANUAL_ENTRY_OVER_FILE")
            if over_file
            else "A line or declaration with this reference was already settled by a correction "
            f"or a manual entry, or by a newer report ({', '.join(codes)}): use a correction",
            rule_id=rules.RULE_MANUAL_ENTRY,
            errors=[_problem(i).model_dump() for i in issues],
        )
    line_id, declaration_id, version, result = _resulting_line(
        session, tenant_id, outcome, source_row_id
    )
    batch = advance_batch(
        session,
        tenant_id=tenant_id,
        batch_id=batch_id,
        target="normalising",
        expected_version=1,
        actor=actor,
        now=now,
    )
    advance_batch(
        session,
        tenant_id=tenant_id,
        batch_id=batch_id,
        target="completed",
        expected_version=batch.row_version,
        actor=actor,
        now=now,
        progress={
            "rows_total": 1,
            "rows_processed": 1,
            "rows_valid": 1,
            "rows_rejected": 0,
            "lines_created": outcome.lines_created + outcome.lines_superseded,
            "lines_unchanged": outcome.duplicates_seen,
        },
    )
    record(
        session,
        tenant_id=tenant_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        action="import_line.manual_entry",
        object_type="import_line",
        object_id=line_id,
        occurred_at=now,
        after={
            "batch_id": str(batch_id),
            "declaration_id": str(declaration_id),
            "version": version,
            "result": result,
        },
        reason=reason,
    )
    return ManualEntryOut(
        batch_id=batch_id,
        declaration_id=declaration_id,
        line_id=line_id,
        version=version,
        result=result,
        warnings=warnings,
    )


def _resulting_line(
    session: Session,
    tenant_id: UUID,
    outcome: normalisation.ChunkOutcome,
    source_row_id: UUID,
) -> tuple[UUID, UUID, int, str]:
    if outcome.line_ids:
        line_id = outcome.line_ids[0]
        result = "superseded" if outcome.lines_superseded else "created"
    else:
        found: Any = session.execute(
            text(
                "select import_line_id from cbam.import_line_sources"
                " where tenant_id = :t and source_row_id = :s"
            ),
            {"t": tenant_id, "s": source_row_id},
        ).scalar_one()
        line_id, result = found, "duplicate_seen"
    row = session.execute(
        text(
            "select declaration_id, version from cbam.import_lines where tenant_id = :t and id = :i"
        ),
        {"t": tenant_id, "i": line_id},
    ).one()
    return line_id, row.declaration_id, int(row.version), result


def _replay(
    session: Session, tenant_id: UUID, batch_id: UUID, warnings: list[EntryProblem]
) -> ManualEntryOut:
    found = session.execute(
        text(
            "select l.id, l.declaration_id, l.version, s.role from cbam.import_line_sources s"
            " join cbam.source_rows r on r.tenant_id = s.tenant_id and r.id = s.source_row_id"
            " join cbam.import_lines l on l.tenant_id = s.tenant_id and l.id = s.import_line_id"
            " where s.tenant_id = :t and r.batch_id = :b"
        ),
        {"t": tenant_id, "b": batch_id},
    ).one()
    result = (
        "duplicate_seen"
        if found.role == "duplicate_seen"
        else "superseded"
        if found.version > 1
        else "created"
    )
    return ManualEntryOut(
        batch_id=batch_id,
        declaration_id=found.declaration_id,
        line_id=found.id,
        version=int(found.version),
        result=result,
        warnings=warnings,
        replayed=True,
    )
