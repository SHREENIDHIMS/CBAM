"""Task service: loads facts, applies the pure rules, writes task + event + audit together."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Row, and_, func, insert, literal, or_, select, text
from sqlalchemy.orm import Session

from app.core.audit import ActorType, record
from app.core.errors import (
    InvalidRequestError,
    ReasonRequiredError,
    RuleBlockedError,
    StaleVersionError,
    TenantMismatchError,
)
from app.core.ids import uuid7
from app.core.pagination import clamp_limit, decode_cursor, encode_cursor
from app.core.versioning import update_versioned
from app.modules.tasks import rules
from app.modules.tasks.models import task_events, tasks
from app.modules.tasks.schemas import TaskEventOut, TaskOut, TaskPage


class _Unset:
    """Marks a PATCH field that was not sent (distinct from an explicit null)."""

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


@dataclass(frozen=True)
class Actor:
    actor_type: ActorType
    actor_id: UUID | None


def _out(row: Row[Any]) -> TaskOut:
    return TaskOut(
        id=row.id,
        type=row.type,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        title=row.title,
        due_date=row.due_date,
        due_rule=row.due_rule,
        owner_id=row.owner_id,
        status=row.status,
        escalation_level=row.escalation_level,
        row_version=row.row_version,
    )


def _event(
    session: Session,
    *,
    tenant_id: UUID,
    task_id: UUID,
    event_type: str,
    from_value: str | None,
    to_value: str | None,
    reason: str | None,
    actor: Actor,
    now: datetime,
) -> None:
    session.execute(
        insert(task_events).values(
            id=uuid7(),
            tenant_id=tenant_id,
            task_id=task_id,
            event_type=event_type,
            from_value=from_value,
            to_value=to_value,
            reason=reason,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            occurred_at=now,
        )
    )


def _audit(
    session: Session,
    *,
    tenant_id: UUID,
    task_id: UUID,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any],
    reason: str | None,
    actor: Actor,
    now: datetime,
) -> None:
    record(
        session,
        tenant_id=tenant_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        action=action,
        object_type="task",
        object_id=task_id,
        occurred_at=now,
        before=before,
        after=after,
        reason=reason,
    )


def _snapshot(row: Row[Any]) -> dict[str, Any]:
    return {
        "status": row.status,
        "owner_id": str(row.owner_id) if row.owner_id else None,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "due_rule": row.due_rule,
        "escalation_level": row.escalation_level,
    }


def create_task(
    session: Session,
    *,
    tenant_id: UUID,
    task_type: str,
    title: str,
    actor: Actor,
    now: datetime,
    subject_type: str | None = None,
    subject_id: UUID | None = None,
    due_date: date | None = None,
    due_rule: str | None = None,
    owner_id: UUID | None = None,
) -> UUID:
    """Create a task (called by rule engines: threshold, outreach, readiness, evidence)."""
    task_id = uuid7()
    session.execute(
        insert(tasks).values(
            id=task_id,
            tenant_id=tenant_id,
            type=task_type,
            subject_type=subject_type,
            subject_id=subject_id,
            title=title,
            due_date=due_date,
            due_rule=due_rule,
            owner_id=owner_id,
            status="open",
            escalation_level=0,
            created_at=now,
            created_by=actor.actor_id,
            row_version=1,
        )
    )
    _event(
        session,
        tenant_id=tenant_id,
        task_id=task_id,
        event_type="created",
        from_value=None,
        to_value="open",
        reason=None,
        actor=actor,
        now=now,
    )
    _audit(
        session,
        tenant_id=tenant_id,
        task_id=task_id,
        action="task.created",
        before=None,
        after={
            "type": task_type,
            "due_date": due_date.isoformat() if due_date else None,
            "due_rule": due_rule,
            "owner_id": str(owner_id) if owner_id else None,
        },
        reason=None,
        actor=actor,
        now=now,
    )
    return task_id


def get_task(session: Session, task_id: UUID) -> TaskOut:
    row = session.execute(select(tasks).where(tasks.c.id == task_id)).one_or_none()
    if row is None:
        raise TenantMismatchError()
    return _out(row)


def task_history(session: Session, task_id: UUID) -> list[TaskEventOut]:
    rows = session.execute(
        select(task_events)
        .where(task_events.c.task_id == task_id)
        .order_by(task_events.c.occurred_at, task_events.c.id)
    ).all()
    return [
        TaskEventOut(
            event_type=r.event_type,
            from_value=r.from_value,
            to_value=r.to_value,
            reason=r.reason,
            actor_type=r.actor_type,
            actor_id=r.actor_id,
        )
        for r in rows
    ]


Sort = Literal["due_date", "-due_date"]


def list_tasks(
    session: Session,
    *,
    status: str | None = None,
    owner_id: UUID | None = None,
    due_before: date | None = None,
    sort: Sort = "due_date",
    limit: int | None = None,
    cursor: str | None = None,
) -> TaskPage:
    """Tasks for the session's tenant, keyset-paginated by (due date, id).

    Tasks with no due date sort last in both directions.
    """
    page = clamp_limit(limit)
    descending = sort == "-due_date"
    far = literal(date.min if descending else date.max)
    sort_key = func.coalesce(tasks.c.due_date, far)
    query = select(tasks, sort_key.label("sort_key"))
    if status:
        query = query.where(tasks.c.status == status)
    if owner_id:
        query = query.where(tasks.c.owner_id == owner_id)
    if due_before:
        query = query.where(tasks.c.due_date < due_before)
    if cursor:
        c = decode_cursor(cursor)
        try:
            after_key = date.fromisoformat(str(c["k"]))
            after_id = UUID(str(c["i"]))
        except (KeyError, ValueError) as exc:
            raise InvalidRequestError("The cursor is not valid") from exc
        if descending:
            query = query.where(
                or_(
                    sort_key < after_key,
                    and_(sort_key == after_key, tasks.c.id < after_id),
                )
            )
        else:
            query = query.where(
                or_(
                    sort_key > after_key,
                    and_(sort_key == after_key, tasks.c.id > after_id),
                )
            )
    order = (
        (sort_key.desc(), tasks.c.id.desc()) if descending else (sort_key.asc(), tasks.c.id.asc())
    )
    rows = session.execute(query.order_by(*order).limit(page + 1)).all()
    items = rows[:page]
    next_cursor = None
    if len(rows) > page:
        last = items[-1]
        next_cursor = encode_cursor({"k": last.sort_key.isoformat(), "i": str(last.id)})
    return TaskPage(items=[_out(r) for r in items], next_cursor=next_cursor)


def _require_member(session: Session, tenant_id: UUID, user_id: UUID) -> None:
    found = session.execute(
        text("select 1 from cbam.memberships where tenant_id = :t and user_id = :u"),
        {"t": tenant_id, "u": user_id},
    ).scalar_one_or_none()
    if found is None:
        raise InvalidRequestError("The owner must be a member of this client account")


def update_task(
    session: Session,
    *,
    tenant_id: UUID,
    task_id: UUID,
    expected_version: int,
    actor: Actor,
    now: datetime,
    status: str | None = None,
    owner_id: UUID | _Unset | None = UNSET,
    due_date: date | _Unset | None = UNSET,
    reason: str | None = None,
) -> TaskOut:
    """Assign, change status or move the due date, in one transaction with history + audit."""
    current = session.execute(select(tasks).where(tasks.c.id == task_id)).one_or_none()
    if current is None:
        raise TenantMismatchError()
    if current.row_version != expected_version:
        raise StaleVersionError("This task changed since you loaded it; reload and try again")

    values: dict[str, Any] = {}
    events: list[tuple[str, str | None, str | None]] = []

    if status is not None:
        decision = rules.transition_decision(current.status, status, reason=reason)
        if decision.outcome == "BLOCKED":
            raise RuleBlockedError(decision.reason, rule_id=decision.rule_id)
        if decision.outcome == "REASON_REQUIRED":
            raise ReasonRequiredError(decision.reason, rule_id=decision.rule_id)
        values["status"] = status
        events.append(("status_changed", current.status, status))

    if not isinstance(owner_id, _Unset) and owner_id != current.owner_id:
        if owner_id is not None:
            _require_member(session, tenant_id, owner_id)
        values["owner_id"] = owner_id
        events.append(
            (
                "assigned",
                str(current.owner_id) if current.owner_id else None,
                str(owner_id) if owner_id else None,
            )
        )

    if not isinstance(due_date, _Unset) and due_date != current.due_date:
        if not (reason and reason.strip()):
            raise ReasonRequiredError(
                "Moving a due date needs a reason", rule_id=rules.RULE_TRANSITION
            )
        values["due_date"] = due_date
        values["due_rule"] = "manual"
        events.append(
            (
                "due_date_changed",
                current.due_date.isoformat() if current.due_date else None,
                due_date.isoformat() if due_date else None,
            )
        )

    if not values:
        raise InvalidRequestError("Nothing to change")

    before = _snapshot(current)
    update_versioned(
        session, "tasks", row_id=task_id, expected_version=expected_version, values=values
    )
    for event_type, from_value, to_value in events:
        _event(
            session,
            tenant_id=tenant_id,
            task_id=task_id,
            event_type=event_type,
            from_value=from_value,
            to_value=to_value,
            reason=reason,
            actor=actor,
            now=now,
        )
    updated = session.execute(select(tasks).where(tasks.c.id == task_id)).one()
    _audit(
        session,
        tenant_id=tenant_id,
        task_id=task_id,
        action="task.updated",
        before=before,
        after=_snapshot(updated),
        reason=reason,
        actor=actor,
        now=now,
    )
    return _out(updated)


def escalate_overdue(
    session: Session,
    *,
    tenant_id: UUID,
    as_of: date,
    thresholds_days: Sequence[int],
    now: datetime,
) -> int:
    """Raise the escalation level of overdue open tasks. Returns how many were escalated.

    Idempotent: running again on the same day changes nothing. Escalation only flags
    and records; it never closes or edits the task's facts (CLAUDE.md rule 13).
    """
    if not thresholds_days:
        return 0
    actor = Actor("job", None)
    rows = session.execute(
        select(tasks).where(
            and_(
                tasks.c.due_date.is_not(None),
                tasks.c.status.in_(["open", "in_progress", "blocked"]),
            )
        )
    ).all()
    escalated = 0
    for row in rows:
        new_level = rules.next_escalation_level(
            row.due_date, as_of, row.escalation_level, thresholds_days
        )
        if new_level <= row.escalation_level:
            continue
        before = _snapshot(row)
        update_versioned(
            session,
            "tasks",
            row_id=row.id,
            expected_version=row.row_version,
            values={"escalation_level": new_level},
        )
        _event(
            session,
            tenant_id=tenant_id,
            task_id=row.id,
            event_type="escalated",
            from_value=str(row.escalation_level),
            to_value=str(new_level),
            reason=f"{(as_of - row.due_date).days} days overdue",
            actor=actor,
            now=now,
        )
        _audit(
            session,
            tenant_id=tenant_id,
            task_id=row.id,
            action="task.escalated",
            before=before,
            after={**before, "escalation_level": new_level},
            reason=f"{(as_of - row.due_date).days} days overdue",
            actor=actor,
            now=now,
        )
        escalated += 1
    return escalated
