"""Decisions: every derived outcome stores its rule, versions and an input fingerprint.

CLAUDE.md rule 4: source -> normalised -> derived. A derived number is never overwritten;
a changed outcome creates a new decision that supersedes the old one. Re-running a rule on
the same inputs, rule version and reference data gives the same fingerprint and no new row.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.ids import uuid7
from app.core.money import dumps


@dataclass(frozen=True)
class Decision:
    """What a pure `rules.py` function returns."""

    rule_id: str
    rule_version: str
    source_ids: tuple[str, ...]
    outcome: str
    reason: str
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StoredDecision:
    id: UUID
    tenant_id: UUID
    subject_type: str
    subject_id: UUID
    rule_id: str
    rule_version: str
    source_ids: tuple[str, ...]
    dataset_version_ids: tuple[UUID, ...]
    input_fingerprint: bytes
    outcome: str
    reason: str
    details: dict[str, Any] | None
    as_of: date
    supersedes_id: UUID | None
    created_at: datetime


@dataclass(frozen=True)
class SavedDecision:
    id: UUID
    created: bool  # False when an identical current decision already existed


def _canonical(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, int | str):
        return value
    if isinstance(value, float):
        raise TypeError("float is not allowed in decision inputs; use Decimal or str")
    if isinstance(value, Decimal):
        # 1.50 and 1.5 are the same input; plain notation, never scientific.
        normalised = value.normalize()
        return format(normalised, "f") if normalised != 0 else "0"
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("decision inputs need timezone-aware datetimes")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _canonical(v) for k, v in value.items()}
    if isinstance(value, set | frozenset):
        return sorted(_canonical(v) for v in value)
    if isinstance(value, list | tuple):
        return [_canonical(v) for v in value]
    raise TypeError(f"cannot fingerprint {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Stable JSON: sorted keys, no spaces, Decimals as plain strings, no floats."""
    return json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"))


def fingerprint(inputs: Any) -> bytes:
    """SHA-256 of the canonical JSON of a decision's inputs."""
    return hashlib.sha256(canonical_json(inputs).encode("utf-8")).digest()


_COLUMNS = (
    "id, tenant_id, subject_type, subject_id, rule_id, rule_version, source_ids,"
    " dataset_version_ids, input_fingerprint, outcome, reason, details, as_of,"
    " supersedes_id, created_at"
)


def _stored(row: Any) -> StoredDecision:
    return StoredDecision(
        id=row.id,
        tenant_id=row.tenant_id,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        rule_id=row.rule_id,
        rule_version=row.rule_version,
        source_ids=tuple(row.source_ids),
        dataset_version_ids=tuple(row.dataset_version_ids),
        input_fingerprint=bytes(row.input_fingerprint),
        outcome=row.outcome,
        reason=row.reason,
        details=row.details,
        as_of=row.as_of,
        supersedes_id=row.supersedes_id,
        created_at=row.created_at,
    )


def current_decision(
    session: Session, tenant_id: UUID, subject_type: str, subject_id: UUID, rule_id: str
) -> StoredDecision | None:
    """The decision nothing has superseded yet, or None."""
    row = session.execute(
        text(
            f"select {_COLUMNS} from cbam.decisions d"  # noqa: S608 - constant column list
            " where d.tenant_id = :t and d.subject_type = :st and d.subject_id = :sid"
            " and d.rule_id = :rid"
            " and not exists (select 1 from cbam.decisions s where s.supersedes_id = d.id)"
        ),
        {"t": tenant_id, "st": subject_type, "sid": subject_id, "rid": rule_id},
    ).one_or_none()
    return None if row is None else _stored(row)


def decision_history(
    session: Session, tenant_id: UUID, subject_type: str, subject_id: UUID, rule_id: str
) -> list[StoredDecision]:
    """All decisions for a subject and rule, oldest first, following the supersedes chain."""
    rows = session.execute(
        text(
            f"""
            with recursive chain as (
              select {_COLUMNS}, 1 as depth from cbam.decisions
              where tenant_id = :t and subject_type = :st and subject_id = :sid
                and rule_id = :rid and supersedes_id is null
              union all
              select {", ".join("n." + c.strip() for c in _COLUMNS.split(","))}, c.depth + 1
              from cbam.decisions n join chain c on n.supersedes_id = c.id
            )
            select {_COLUMNS} from chain order by depth
            """  # noqa: S608 - constant column list
        ),
        {"t": tenant_id, "st": subject_type, "sid": subject_id, "rid": rule_id},
    ).all()
    return [_stored(r) for r in rows]


def save_decision(
    session: Session,
    *,
    tenant_id: UUID,
    subject_type: str,
    subject_id: UUID,
    decision: Decision,
    dataset_version_ids: Sequence[UUID],
    inputs: Any,
    as_of: date,
    created_by: UUID | None = None,
) -> SavedDecision:
    """Save a decision in the caller's transaction (the service also writes the audit event).

    Identical to the current decision (same rule version, reference-data versions, input
    fingerprint and outcome) -> nothing is written. Otherwise a new decision supersedes it.
    `as_of` is stored but not compared: re-running on a later day with the same facts and
    reference data is not a new decision.
    """
    key = f"decision:{tenant_id}:{subject_type}:{subject_id}:{decision.rule_id}"
    session.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": key})
    digest = fingerprint(inputs)
    datasets = sorted(dataset_version_ids, key=str)
    current = current_decision(session, tenant_id, subject_type, subject_id, decision.rule_id)
    if (
        current is not None
        and current.rule_version == decision.rule_version
        and sorted(current.dataset_version_ids, key=str) == datasets
        and current.input_fingerprint == digest
        and current.outcome == decision.outcome
    ):
        return SavedDecision(id=current.id, created=False)
    decision_id = uuid7()
    session.execute(
        text(
            """
            insert into cbam.decisions
              (id, tenant_id, subject_type, subject_id, rule_id, rule_version, source_ids,
               dataset_version_ids, input_fingerprint, outcome, reason, details, as_of,
               supersedes_id, created_by)
            values
              (:id, :t, :st, :sid, :rid, :rv, :src, :ds, :fp, :outcome, :reason,
               cast(:details as jsonb), :as_of, :sup, :by)
            """
        ),
        {
            "id": decision_id,
            "t": tenant_id,
            "st": subject_type,
            "sid": subject_id,
            "rid": decision.rule_id,
            "rv": decision.rule_version,
            "src": list(decision.source_ids),
            "ds": datasets,
            "fp": digest,
            "outcome": decision.outcome,
            "reason": decision.reason,
            "details": dumps(dict(decision.details)) if decision.details else None,
            "as_of": as_of,
            "sup": None if current is None else current.id,
            "by": created_by,
        },
    )
    return SavedDecision(id=decision_id, created=True)
