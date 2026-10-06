"""Liable-person determination for a declaration (R1-036): load facts and rules, call the pure
rule, save the decision, ask a person when it cannot decide. Never decides scope, tax point,
quarter or threshold.

The legal date used to pick the rule rows is the declaration's acceptance date AS REPORTED. That
is a stand-in until the tax point exists (Phase 4); it is recorded on every decision as
`as_of_basis = acceptance_date_provisional` so the choice can be revisited (LEGAL-DEC-026).
"""

from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.audit import record
from app.core.decisions import (
    StoredDecision,
    current_decision,
    decision_history,
    save_decision,
)
from app.core.errors import RuleBlockedError, TenantMismatchError
from app.modules.liability import rules
from app.modules.liability.schemas import LiablePersonHistory, LiablePersonOut
from app.modules.refdata import service as refdata
from app.modules.tasks import service as tasks
from app.modules.tasks.service import Actor as TaskActor

DATASET = "liable_person_rules"
SUBJECT = "declaration"
TASK_TYPE = "liable_person.review"
AS_OF_BASIS = "acceptance_date_provisional"
_OPEN_TASK = ("open", "in_progress", "blocked")


def _load(session: Session, tenant_id: UUID, declaration_id: UUID) -> Any:
    row = session.execute(
        text(
            "select d.id, d.acceptance_date, d.representation_type, d.eori_context,"
            " d.content_sha256, d.importer_eori_source, d.importer_party_id, d.declarant_party_id,"
            " d.representative_party_id, i.eori as importer_eori, c.eori as declarant_eori,"
            " r.eori as representative_eori,"
            " not exists (select 1 from cbam.declarations n"
            "   where n.tenant_id = d.tenant_id and n.supersedes_id = d.id) as is_current"
            " from cbam.declarations d"
            " left join cbam.parties i on i.tenant_id = d.tenant_id and i.id = d.importer_party_id"
            " left join cbam.parties c on c.tenant_id = d.tenant_id and c.id = d.declarant_party_id"
            " left join cbam.parties r"
            "   on r.tenant_id = d.tenant_id and r.id = d.representative_party_id"
            " where d.tenant_id = :t and d.id = :i"
        ),
        {"t": tenant_id, "i": declaration_id},
    ).one_or_none()
    if row is None:
        raise TenantMismatchError()
    return row


def _open_review_task(session: Session, tenant_id: UUID, declaration_id: UUID) -> UUID | None:
    found = session.execute(
        text(
            "select id from cbam.tasks where tenant_id = :t and type = :ty"
            " and subject_type = :st and subject_id = :s and status = any(:open)"
            " order by id limit 1"
        ),
        {
            "t": tenant_id,
            "ty": TASK_TYPE,
            "st": SUBJECT,
            "s": declaration_id,
            "open": list(_OPEN_TASK),
        },
    ).scalar_one_or_none()
    return found


def _out(
    row: Any,
    stored: StoredDecision,
    *,
    created: bool,
    review_task_id: UUID | None,
) -> LiablePersonOut:
    details = stored.details or {}
    party = details.get("liable_party")
    party_id = (
        {
            "importer": row.importer_party_id,
            "declarant": row.declarant_party_id,
            "representative": row.representative_party_id,
        }.get(party)
        if party
        else None
    )
    return LiablePersonOut(
        declaration_id=row.id,
        decision_id=stored.id,
        outcome=stored.outcome,
        reason=stored.reason,
        code=details.get("code"),
        liable_party=party,
        liable_party_id=party_id,
        rule_key=details.get("rule_key"),
        rule_version=stored.rule_version,
        source_ids=list(stored.source_ids),
        dataset_version_ids=list(stored.dataset_version_ids),
        as_of=stored.as_of,
        as_of_basis=str(details.get("as_of_basis", AS_OF_BASIS)),
        created=created,
        review_task_id=review_task_id,
        created_at=stored.created_at,
    )


def determine(
    session: Session,
    *,
    tenant_id: UUID,
    declaration_id: UUID,
    actor: TaskActor,
    now: datetime,
) -> LiablePersonOut:
    """Work out (or re-confirm) the liable party of the CURRENT version of a declaration.

    Same facts, same rule version and same reference data give the same decision and write
    nothing. A different outcome supersedes the old decision (it is kept). An undetermined
    outcome opens one review task per declaration; a task a person already works on is not
    duplicated."""
    row = _load(session, tenant_id, declaration_id)
    if not row.is_current:
        raise RuleBlockedError(
            "This declaration version has been superseded: determine the current version",
            rule_id=rules.RULE_ID,
        )
    snapshot = refdata.snapshot(session, [DATASET], on=row.acceptance_date)
    facts = rules.DeclarationParties(
        importer_eori=row.importer_eori,
        declarant_eori=row.declarant_eori,
        representative_eori=row.representative_eori,
        representation_type=row.representation_type,
        eori_context=row.eori_context,
        importer_eori_source=row.importer_eori_source,
    )
    decision = rules.determine(facts, snapshot.rows[DATASET])
    decision = replace(decision, details={**decision.details, "as_of_basis": AS_OF_BASIS})
    saved = save_decision(
        session,
        tenant_id=tenant_id,
        subject_type=SUBJECT,
        subject_id=declaration_id,
        decision=decision,
        dataset_version_ids=snapshot.version_ids,
        inputs={"declaration_sha256": row.content_sha256, "as_of_basis": AS_OF_BASIS},
        as_of=row.acceptance_date,
        created_by=actor.actor_id,
    )
    task_id = _open_review_task(session, tenant_id, declaration_id)
    if saved.created:
        record(
            session,
            tenant_id=tenant_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            action="liable_person.determined",
            object_type="declaration",
            object_id=declaration_id,
            occurred_at=now,
            after={
                "decision_id": str(saved.id),
                "outcome": decision.outcome,
                "code": decision.details.get("code"),
                "rule_key": decision.details.get("rule_key"),
                "liable_party": decision.details.get("liable_party"),
                "dataset_version_ids": [str(v) for v in snapshot.version_ids],
            },
        )
        if decision.outcome == rules.UNDETERMINED and task_id is None:
            task_id = tasks.create_task(
                session,
                tenant_id=tenant_id,
                task_type=TASK_TYPE,
                title="Decide who is liable for CBAM on a declaration",
                actor=actor,
                now=now,
                subject_type=SUBJECT,
                subject_id=declaration_id,
            )
    stored = current_decision(session, tenant_id, SUBJECT, declaration_id, rules.RULE_ID)
    if stored is None:  # unreachable: save_decision always leaves a current decision
        raise RuleBlockedError("The decision could not be read back", rule_id=rules.RULE_ID)
    return _out(row, stored, created=saved.created, review_task_id=task_id)


def get_current(session: Session, tenant_id: UUID, declaration_id: UUID) -> LiablePersonHistory:
    """The current decision and the history (oldest first), or no decision yet."""
    row = _load(session, tenant_id, declaration_id)
    history = decision_history(session, tenant_id, SUBJECT, declaration_id, rules.RULE_ID)
    current = (
        _out(
            row,
            history[-1],
            created=False,
            review_task_id=_open_review_task(session, tenant_id, declaration_id),
        )
        if history
        else None
    )
    return LiablePersonHistory(
        current=current,
        history=[
            {
                "decision_id": str(d.id),
                "outcome": d.outcome,
                "reason": d.reason,
                "rule_version": d.rule_version,
                "dataset_version_ids": [str(v) for v in d.dataset_version_ids],
                "supersedes_id": None if d.supersedes_id is None else str(d.supersedes_id),
                "created_at": d.created_at.isoformat(),
            }
            for d in history
        ],
    )
