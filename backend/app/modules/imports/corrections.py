"""Customs-value correction (R1-010): a person fixes the value of a line, with a reason.

Source facts are never overwritten (CLAUDE.md rule 4). A correction is a NEW version of the line
that supersedes the current one: `entry_method = correction`, `value_source = correction`, the
reason on the row, and a one-row `manual_entry` batch whose source row records what was changed
(old and new value and currency). The old version stays, with its raw file row. Because the new
version is not file data, a later file can never silently put the old value back
(`SOURCE_CONFLICTS_WITH_CORRECTION`), and a file that repeats the original value is only a
sighting of the earlier version.

Only the CURRENT version of a line can be corrected (409 otherwise), under the same advisory lock
the file normaliser takes, so a correction and a file load cannot both extend one chain.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from app.core.audit import record
from app.core.errors import (
    InvalidRequestError,
    NotPermittedError,
    ReasonRequiredError,
    StaleVersionError,
    TenantMismatchError,
)
from app.core.ids import uuid7
from app.modules.imports import normalisation, rules
from app.modules.imports.manual_schemas import ValueCorrectionIn, ValueCorrectionOut
from app.modules.imports.models import (
    import_batches,
    import_line_sources,
    import_lines,
    source_rows,
)
from app.modules.imports.service import Actor, advance_batch, find_keyed_batch

_STORED_VALUE_SCALE = Decimal("0.00000001")  # customs_value_source is NUMERIC(24,8)


def _stored(amount: Decimal) -> str:
    """The value as the database stores it (8 places), so the reply matches the ledger."""
    return format(amount.quantize(_STORED_VALUE_SCALE), "f")


def _problems(issues: tuple[rules.Issue, ...]) -> list[dict[str, str]]:
    return [
        {"field": i.field, "code": i.code, "message": rules.issue_message(i.code)}
        for i in issues
        if rules.issue_severity(i.code) == "error"
    ]


def _current_line(session: Session, tenant_id: UUID, line_id: UUID) -> Any:
    row = session.execute(
        text(
            "select l.*, d.mrn from cbam.import_lines l"
            " join cbam.declarations d on d.tenant_id = l.tenant_id and d.id = l.declaration_id"
            " where l.tenant_id = :t and l.id = :i"
        ),
        {"t": tenant_id, "i": line_id},
    ).one_or_none()
    if row is None:
        raise TenantMismatchError()
    return row


def correct_value(
    session: Session,
    *,
    tenant_id: UUID,
    line_id: UUID,
    actor: Actor,
    permissions: frozenset[str],
    now: datetime,
    today: date,
    body: ValueCorrectionIn,
    expected_version: int,
    idempotency_key: str | None = None,
) -> ValueCorrectionOut:
    """`expected_version` is the line version the user saw (If-Match); a newer one is a 409."""
    decision = rules.check_value_correction(permissions, body.reason)
    if decision.outcome == "BLOCKED":
        error = NotPermittedError if "imports:correct" not in permissions else ReasonRequiredError
        raise error(decision.reason)
    reason = body.reason.strip()
    fingerprint = bytes.fromhex(
        rules.row_hash(
            {
                "line_id": str(line_id),
                "customs_value": body.customs_value.strip(),
                "customs_value_currency": (body.customs_value_currency or "").strip(),
                "reason": reason,
            }
        )
    )
    if idempotency_key:
        earlier = find_keyed_batch(
            session, tenant_id=tenant_id, key=idempotency_key, fingerprint=fingerprint
        )
        if earlier is not None:  # answered already: the old version is no longer current
            return _replay(session, tenant_id, earlier.id)

    start = _current_line(session, tenant_id, line_id)
    normalisation._lock_mrns(session, tenant_id, [start.mrn])
    line = _current_line(session, tenant_id, line_id)  # re-read under the lock
    if int(line.version) != expected_version:
        raise StaleVersionError("This line changed since you loaded it: reload it and try again")
    successor = session.execute(
        text("select 1 from cbam.import_lines where tenant_id = :t and supersedes_id = :i"),
        {"t": tenant_id, "i": line_id},
    ).scalar_one_or_none()
    if successor is not None:
        raise StaleVersionError("This line has a newer version: reload it and correct that one")

    currency = (body.customs_value_currency or line.customs_value_currency).strip()
    amount, issues = rules.parse_corrected_value(body.customs_value, currency)
    if amount is None:
        raise InvalidRequestError(
            "The corrected value is not valid", rule_id=decision.rule_id, errors=_problems(issues)
        )
    if amount == line.customs_value_source and currency == line.customs_value_currency:
        raise InvalidRequestError(
            "The corrected value equals the current value: nothing to change",
            rule_id=decision.rule_id,
        )

    declaration = session.execute(
        text(
            "select d.id, d.content_sha256 from cbam.declarations d"
            " where d.tenant_id = :t and d.mrn = :m"
            " and not exists (select 1 from cbam.declarations n"
            "   where n.tenant_id = d.tenant_id and n.supersedes_id = d.id)"
        ),
        {"t": tenant_id, "m": line.mrn},
    ).one()
    gbp, note = rules.customs_value_gbp(amount, currency)
    new_hash = rules.content_hash(
        {
            "declaration": declaration.content_sha256,
            "item_no": line.item_no,
            "commodity_code": line.commodity_code,
            "description": line.description,
            "net_mass_kg": line.net_mass_kg,
            "customs_value_source": amount,
            "customs_value_currency": currency,
            "valuation_basis": line.valuation_basis,
            "country_of_origin_declared": line.country_of_origin_declared,
            "cpc": line.cpc,
        }
    )

    raw = {
        "line_id": str(line_id),
        "field": "line.customs_value",
        "old_value": format(line.customs_value_source, "f"),
        "old_currency": line.customs_value_currency,
        "new_value": body.customs_value.strip(),
        "new_currency": currency,
        rules.MANUAL_REASON_KEY: reason,
    }
    row_hash = rules.row_hash(raw)
    batch_id, source_row_id, new_id = uuid7(), uuid7(), uuid7()
    session.execute(
        insert(import_batches).values(
            id=batch_id,
            tenant_id=tenant_id,
            acquisition_method="manual_entry",
            acquired_on=today,
            request_fingerprint=fingerprint,
            idempotency_key=idempotency_key or None,
            status="received",
            created_at=now,
            created_by=actor.actor_id,
            row_version=1,
        )
    )
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
    session.execute(
        insert(import_lines).values(
            id=new_id,
            tenant_id=tenant_id,
            declaration_id=declaration.id,
            item_no=line.item_no,
            version=line.version + 1,
            supersedes_id=line_id,
            commodity_code=line.commodity_code,
            description=line.description,
            net_mass_kg=line.net_mass_kg,
            supplementary_qty=line.supplementary_qty,
            supplementary_unit=line.supplementary_unit,
            customs_value_source=amount,
            customs_value_currency=currency,
            customs_value_gbp=gbp,
            customs_value_gbp_note=note,
            valuation_basis=line.valuation_basis,
            value_source="correction",
            value_override_reason=reason,
            country_of_origin_declared=line.country_of_origin_declared,
            cpc=line.cpc,
            batch_id=batch_id,
            source_row_id=source_row_id,
            entry_method="correction",
            change_reason=rules.REASON_VALUE_CORRECTED,
            content_sha256=new_hash,
            hash_version=rules.HASH_VERSION,
            created_at=now,
        )
    )
    session.execute(
        insert(import_line_sources).values(
            id=uuid7(),
            tenant_id=tenant_id,
            import_line_id=new_id,
            source_row_id=source_row_id,
            report_type=None,
            role="primary",
            created_at=now,
        )
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
            "lines_created": 1,
            "lines_unchanged": 0,
        },
    )
    record(
        session,
        tenant_id=tenant_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        action="import_line.value_corrected",
        object_type="import_line",
        object_id=new_id,
        occurred_at=now,
        before={
            "line_id": str(line_id),
            "customs_value_source": format(line.customs_value_source, "f"),
            "customs_value_currency": line.customs_value_currency,
        },
        after={
            "line_id": str(new_id),
            "version": line.version + 1,
            "customs_value_source": _stored(amount),
            "customs_value_currency": currency,
            "batch_id": str(batch_id),
        },
        reason=reason,
    )
    return ValueCorrectionOut(
        batch_id=batch_id,
        declaration_id=declaration.id,
        line_id=new_id,
        superseded_line_id=line_id,
        version=line.version + 1,
        customs_value_source=_stored(amount),
        customs_value_currency=currency,
        customs_value_gbp=None if gbp is None else format(gbp, "f"),
    )


def _replay(session: Session, tenant_id: UUID, batch_id: UUID) -> ValueCorrectionOut:
    row = session.execute(
        text(
            "select id, declaration_id, supersedes_id, version, customs_value_source,"
            " customs_value_currency, customs_value_gbp from cbam.import_lines"
            " where tenant_id = :t and batch_id = :b"
        ),
        {"t": tenant_id, "b": batch_id},
    ).one()
    return ValueCorrectionOut(
        batch_id=batch_id,
        declaration_id=row.declaration_id,
        line_id=row.id,
        superseded_line_id=row.supersedes_id,
        version=int(row.version),
        customs_value_source=_stored(row.customs_value_source),
        customs_value_currency=row.customs_value_currency,
        customs_value_gbp=None
        if row.customs_value_gbp is None
        else format(row.customs_value_gbp, "f"),
        replayed=True,
    )
