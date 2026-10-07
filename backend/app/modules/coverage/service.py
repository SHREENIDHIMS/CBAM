"""Customs-data coverage (R1-054): record the days each completed report covers, build the
per-EORI calendar, keep the register of EORIs to cover and ask a person to close gaps.

Nothing here decides scope, tax point, quarter or threshold. Tasks are created, never closed:
a person closes them, and a gap that is still there is raised again by the next scan. A gap that
is later partly filled splits in two: the new second part gets its own task and the first task
stays open until a person closes it (a deliberate choice, noted in DATA-DEC-028).
"""

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.audit import record
from app.core.errors import (
    InvalidRequestError,
    RuleBlockedError,
    StaleVersionError,
    TenantMismatchError,
)
from app.core.ids import uuid7
from app.core.versioning import update_versioned
from app.modules.coverage import rules
from app.modules.coverage.schemas import (
    CalendarOut,
    EoriIn,
    EoriOut,
    EoriPatch,
    OverlapOut,
    PeriodOut,
    ScanOut,
)
from app.modules.refdata import service as refdata
from app.modules.tasks import service as tasks
from app.modules.tasks.service import Actor

log = structlog.get_logger()

DATASET = "customs_data_service"
LAG_KEY = "unavailable_latest_days"
GAP_TASK = "customs_data.gap"
MONTH_TASK = "customs_data.fetch_month"
SUBJECT = "customs_data_eori"
_OPEN_TASK = ["open", "in_progress", "blocked"]
_REPORT_TYPES = ("import_item", "import_header", "import_tax_lines", "export_item")
_EORI_SELECT = (
    "select id, eori, tracking_from, third_party_access, access_recorded_on, note,"
    " row_version, created_at from cbam.customs_data_eoris where tenant_id = :t"
)


def record_for_batch(session: Session, *, tenant_id: UUID, batch_id: UUID, now: datetime) -> bool:
    """Store the days a COMPLETED batch covers. Only a batch that declared an EORI, a report type
    and a window counts: the days are never guessed from the rows. Called in the transaction
    that completes the batch; a repeat changes nothing. `has_errors` marks a batch that finished
    with rejected rows (its days are loaded but not trustworthy, REG-DEC-023)."""
    batch = session.execute(
        text(
            "select eori, cds_report_type, window_start, window_end, status"
            " from cbam.import_batches where tenant_id = :t and id = :b"
        ),
        {"t": tenant_id, "b": batch_id},
    ).one_or_none()
    if (
        batch is None
        or batch.status not in ("completed", "completed_with_errors")
        or batch.eori is None
        or batch.cds_report_type not in _REPORT_TYPES
        or batch.window_start is None
        or batch.window_end is None
        or batch.window_end < batch.window_start
    ):
        if batch is not None and batch.window_start and batch.window_end:
            if batch.window_end < batch.window_start:
                log.warning("coverage_window_inconsistent", batch_id=str(batch_id))
        return False
    inserted = session.execute(
        text(
            "insert into cbam.customs_data_coverage (id, tenant_id, eori, report_type,"
            " covered_from, covered_to, batch_id, has_errors, created_at)"
            " values (:id, :t, :eori, :rt, :f, :to, :b, :err, :now)"
            " on conflict (tenant_id, batch_id) do nothing"
        ),
        {
            "id": uuid7(),
            "t": tenant_id,
            "eori": batch.eori,
            "rt": batch.cds_report_type,
            "f": batch.window_start,
            "to": batch.window_end,
            "b": batch_id,
            "err": batch.status == "completed_with_errors",
            "now": now,
        },
    )
    return bool(inserted.rowcount)  # type: ignore[attr-defined]


# --- the register of EORIs -----------------------------------------------------------------------


def _eori_out(row: Any) -> EoriOut:
    return EoriOut(
        id=row.id,
        eori=row.eori,
        tracking_from=row.tracking_from,
        third_party_access=row.third_party_access,
        access_recorded_on=row.access_recorded_on,
        note=row.note,
        row_version=row.row_version,
        created_at=row.created_at,
    )


def _get_eori(session: Session, tenant_id: UUID, eori_id: UUID) -> EoriOut:
    row = session.execute(
        text(_EORI_SELECT + " and id = :i"), {"t": tenant_id, "i": eori_id}
    ).one_or_none()
    if row is None:
        raise TenantMismatchError()
    return _eori_out(row)


def list_eoris(session: Session, tenant_id: UUID) -> list[EoriOut]:
    rows = session.execute(text(_EORI_SELECT + " order by eori"), {"t": tenant_id})
    return [_eori_out(r) for r in rows]


def register_eori(
    session: Session,
    *,
    tenant_id: UUID,
    actor: Actor,
    now: datetime,
    today: date,
    body: EoriIn,
) -> EoriOut:
    new_id = uuid7()
    inserted = session.execute(
        text(
            "insert into cbam.customs_data_eoris (id, tenant_id, eori, tracking_from,"
            " third_party_access, access_recorded_on, note, created_at, created_by, row_version)"
            " values (:id, :t, :e, :from, :acc, :rec, :note, :now, :by, 1)"
            " on conflict (tenant_id, eori) do nothing returning id"
        ),
        {
            "id": new_id,
            "t": tenant_id,
            "e": body.eori,
            "from": body.tracking_from,
            "acc": body.third_party_access,
            "rec": today if body.third_party_access != "unknown" else None,
            "note": body.note,
            "now": now,
            "by": actor.actor_id,
        },
    ).scalar_one_or_none()
    if inserted is None:  # also the answer to two simultaneous requests: the database decides
        raise RuleBlockedError("This EORI is already registered", rule_id="R1-054")
    record(
        session,
        tenant_id=tenant_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        action="customs_data.eori_registered",
        object_type=SUBJECT,
        object_id=new_id,
        occurred_at=now,
        after={
            "eori": body.eori,
            "tracking_from": body.tracking_from.isoformat(),
            "third_party_access": body.third_party_access,
        },
    )
    return _get_eori(session, tenant_id, new_id)


def update_eori(
    session: Session,
    *,
    tenant_id: UUID,
    eori_id: UUID,
    expected_version: int,
    actor: Actor,
    now: datetime,
    today: date,
    body: EoriPatch,
) -> EoriOut:
    before = _get_eori(session, tenant_id, eori_id)
    values: dict[str, Any] = {}
    if (
        "third_party_access" in body.model_fields_set
        and body.third_party_access != before.third_party_access
    ):
        values["third_party_access"] = body.third_party_access
        values["access_recorded_on"] = today if body.third_party_access != "unknown" else None
    if "note" in body.model_fields_set and body.note != before.note:
        values["note"] = body.note
    if (
        not values
    ):  # nothing changes: no new version and no audit noise (a stale version still 409s)
        if before.row_version != expected_version:
            raise StaleVersionError("This record changed since you loaded it; reload and try again")
        return before
    update_versioned(
        session,
        "customs_data_eoris",
        row_id=eori_id,
        expected_version=expected_version,
        values=values,
    )
    after = _get_eori(session, tenant_id, eori_id)
    record(
        session,
        tenant_id=tenant_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        action="customs_data.eori_updated",
        object_type=SUBJECT,
        object_id=eori_id,
        occurred_at=now,
        # The note is free text, so only the fact that it changed is recorded.
        before={
            "third_party_access": before.third_party_access,
            "access_recorded_on": None
            if before.access_recorded_on is None
            else before.access_recorded_on.isoformat(),
        },
        after={
            "third_party_access": after.third_party_access,
            "access_recorded_on": None
            if after.access_recorded_on is None
            else after.access_recorded_on.isoformat(),
            "note_changed": before.note != after.note,
        },
    )
    return after


# --- the calendar --------------------------------------------------------------------------------


def _lag(session: Session, today: date) -> tuple[int | None, list[UUID]]:
    """The "latest days not yet available" rule on `today`, with the dataset version it came
    from. None when no active rule exists: then no day is ever hidden."""
    row = refdata.get(session, DATASET, {"rule_key": LAG_KEY}, on=today)
    if row is None:
        return None, []
    return int(row["value_int"]), [row["dataset_version_id"]]


def _windows(session: Session, tenant_id: UUID, eori: str, report_type: str) -> list[rules.Window]:
    rows = session.execute(
        text(
            "select batch_id, covered_from, covered_to, has_errors from cbam.customs_data_coverage"
            " where tenant_id = :t and eori = :e and report_type = :r"
            " order by covered_from, batch_id"
        ),
        {"t": tenant_id, "e": eori, "r": report_type},
    )
    return [rules.Window(str(r.batch_id), r.covered_from, r.covered_to, r.has_errors) for r in rows]


def _calendar(
    windows: list[rules.Window],
    *,
    tracking_from: date,
    range_from: date,
    range_to: date,
    today: date,
    lag: int | None,
) -> rules.Calendar:
    try:
        return rules.build_calendar(
            windows,
            tracking_from=tracking_from,
            range_from=range_from,
            range_to=range_to,
            today=today,
            unavailable_latest_days=lag,
        )
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc


def _period_out(p: rules.Period) -> PeriodOut:
    return PeriodOut(
        covered_from=p.covered_from,
        covered_to=p.covered_to,
        state=p.state,
        days=p.days,
    )


def calendar_for(
    session: Session,
    *,
    tenant_id: UUID,
    today: date,
    eori: str,
    report_type: str,
    range_from: date | None,
    range_to: date | None,
) -> CalendarOut:
    """The coverage calendar of one EORI. The first day to cover is the registered one, or the
    earliest loaded day for an EORI that was loaded but never registered; an EORI that is neither
    is 404."""
    registered = session.execute(
        text(
            "select tracking_from, third_party_access from cbam.customs_data_eoris"
            " where tenant_id = :t and eori = :e"
        ),
        {"t": tenant_id, "e": eori},
    ).one_or_none()
    windows = _windows(session, tenant_id, eori, report_type)
    if registered is not None:
        tracking_from, access = registered.tracking_from, registered.third_party_access
    elif windows:
        tracking_from, access = min(w.covered_from for w in windows), "unknown"
    else:
        raise TenantMismatchError()
    start = range_from or tracking_from
    end = range_to or today
    lag, version_ids = _lag(session, today)
    built = _calendar(
        windows, tracking_from=tracking_from, range_from=start, range_to=end, today=today, lag=lag
    )
    return CalendarOut(
        eori=eori,
        report_type=report_type,
        tracking_from=tracking_from,
        registered=registered is not None,
        third_party_access=access,
        range_from=start,
        range_to=end,
        periods=[_period_out(p) for p in built.periods],
        gaps=[_period_out(p) for p in built.gaps],
        overlaps=[
            OverlapOut(
                covered_from=o.covered_from, covered_to=o.covered_to, batch_ids=list(o.batch_ids)
            )
            for o in built.overlaps
        ],
        complete=built.complete,
        unavailable_latest_days=lag,
        dataset_version_ids=version_ids,
    )


# --- tasks ---------------------------------------------------------------------------------------


def _has_task(
    session: Session,
    tenant_id: UUID,
    task_type: str,
    subject_id: UUID,
    due_rule: str,
    *,
    open_only: bool,
) -> bool:
    found = session.execute(
        text(
            "select 1 from cbam.tasks where tenant_id = :t and type = :ty and subject_type = :st"
            " and subject_id = :s and due_rule = :r"
            " and (not :open_only or status = any(:open)) limit 1"
        ),
        {
            "t": tenant_id,
            "ty": task_type,
            "st": SUBJECT,
            "s": subject_id,
            "r": due_rule,
            "open_only": open_only,
            "open": _OPEN_TASK,
        },
    ).scalar_one_or_none()
    return found is not None


def scan(session: Session, *, tenant_id: UUID, actor: Actor, now: datetime, today: date) -> ScanOut:
    """Create the tasks the calendars call for. Safe to repeat: one open task per gap START (a
    gap that grows keeps its task; a closed task for a gap that is still there is raised again),
    and one fetch task per EORI per month, whatever its status."""
    session.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"coverage_scan:{tenant_id}"},
    )
    lag, _ = _lag(session, today)
    eoris = session.execute(
        text(
            "select id, eori, tracking_from, third_party_access from cbam.customs_data_eoris"
            " where tenant_id = :t order by eori"
        ),
        {"t": tenant_id},
    ).all()
    gap_tasks = month_tasks = 0
    month_first, month_last = rules.previous_month(today)
    for row in eoris:
        # Chunks start at the fixed first day to cover, so a gap keeps the same start date (and
        # the same task key) from one scan to the next however long the client is tracked.
        windows = _windows(session, tenant_id, row.eori, "import_item")
        gaps: list[rules.Period] = []
        chunk_start = row.tracking_from
        while chunk_start <= today:
            chunk_end = min(chunk_start + timedelta(days=rules.MAX_RANGE_DAYS - 1), today)
            gaps.extend(
                _calendar(
                    windows,
                    tracking_from=row.tracking_from,
                    range_from=chunk_start,
                    range_to=chunk_end,
                    today=today,
                    lag=lag,
                ).gaps
            )
            chunk_start = chunk_end + timedelta(days=1)
        for gap in gaps:
            key = rules.gap_key(gap.covered_from)
            if _has_task(session, tenant_id, GAP_TASK, row.id, key, open_only=True):
                continue
            tasks.create_task(
                session,
                tenant_id=tenant_id,
                task_type=GAP_TASK,
                title=(
                    f"Customs data gap: load reports for {gap.covered_from.isoformat()}"
                    f" to {gap.covered_to.isoformat()}"
                ),
                actor=actor,
                now=now,
                subject_type=SUBJECT,
                subject_id=row.id,
                due_date=today,
                due_rule=key,
            )
            gap_tasks += 1
        key = rules.month_task_key(month_first)
        if month_last < row.tracking_from or _has_task(
            session, tenant_id, MONTH_TASK, row.id, key, open_only=False
        ):
            continue
        label = rules.month_label(month_first)
        if row.third_party_access == "granted":
            title = f"Request customs data for {label}"
        else:
            title = (
                f"Ask the client to grant third-party access, then request customs data for {label}"
            )
        tasks.create_task(
            session,
            tenant_id=tenant_id,
            task_type=MONTH_TASK,
            title=title,
            actor=actor,
            now=now,
            subject_type=SUBJECT,
            subject_id=row.id,
            due_date=rules.fetch_due_date(month_last, lag),
            due_rule=key,
        )
        month_tasks += 1
    return ScanOut(
        eoris_scanned=len(eoris), gap_tasks_created=gap_tasks, month_tasks_created=month_tasks
    )
