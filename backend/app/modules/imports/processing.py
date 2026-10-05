"""Processing one import batch: raw rows, row validation, exception report (R1-025, R1-003).

The stored file is read as a stream. Each chunk of rows (500 by default) is one tenant
transaction that inserts the raw rows and their exceptions, recounts the batch counters from
the tables and writes one audit event of counts, so a crash loses at most the open chunk and
a retry resumes after the last committed row. Every insert is `on conflict do nothing`; the
counters are recounted, never incremented: running the same work twice changes nothing.

Only format and presence are checked while reading. Rows without an error exception are then
normalised into declarations and lines (`normalisation.py`, Phase 3 step 4) in the `normalising`
state, also in resumable chunks. Nothing is decided about scope, tax point or the threshold.
Neither a cell value nor a filename is ever written to an audit event, a log line, an
exception message or a failure reason.

The job holds a lease: a token (`lease_owner`) and an expiry. Only the holder renews or releases
it. A job that finds another token (it was taken over) stops without touching the batch. The
row-size limit (`IMPORT_MAX_ROW_CHARS`) applies to the raw CSV record as read, before any trimming.
"""

import csv
import io
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import Engine, and_, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.audit import record
from app.core.clock import Clock
from app.core.config import Settings, get_settings
from app.core.dates import uk_date
from app.core.db import tenant_session
from app.core.errors import StorageError, TenantMismatchError
from app.core.ids import uuid7
from app.core.storage import ObjectStore
from app.core.versioning import update_versioned
from app.modules.imports import normalisation, rules
from app.modules.imports.models import (
    document_versions,
    import_batches,
    import_line_sources,
    import_lines,
    row_exceptions,
    source_rows,
)
from app.modules.imports.service import Actor, advance_batch
from app.modules.refdata import service as refdata

CHUNK_ROWS = 500
JOB = Actor("job", None)
LAYOUT_DATASET = "cds_report_layouts"

log = structlog.get_logger()


class LeaseLostError(RuntimeError):
    """Another worker took the batch over: this job must stop and leave the batch alone."""


@dataclass
class _Lease:
    """This run's claim on the batch. `taken` is true once the takeover was written; the token
    is what the database row must still hold for the claim to be ours."""

    token: UUID = field(default_factory=uuid7)
    taken: bool = False
    last_renewed: datetime | None = None


class ImportJobError(RuntimeError):
    """Any failure of the job, reduced to the class name of the cause. The original message
    can carry SQL parameters (cell values), so it is dropped before it can reach a log, a
    Celery result or Sentry. `permanent` means retrying cannot help (the batch is marked
    failed straight away and the task does not back off and retry)."""

    def __init__(self, cause: str, *, permanent: bool = False) -> None:
        super().__init__(cause)
        self.permanent = permanent


def limits_from_settings(settings: Settings | None = None) -> rules.ImportLimits:
    cfg = settings or get_settings()
    return rules.ImportLimits(
        max_columns=cfg.import_max_columns,
        max_heading_chars=cfg.import_max_heading_chars,
        max_cell_chars=cfg.import_max_cell_chars,
        max_row_chars=cfg.import_max_row_chars,
        chunk_max_chars=cfg.import_chunk_max_bytes,
        max_attempts=cfg.import_max_attempts,
        lease_seconds=cfg.import_lease_seconds,
    )


@contextmanager
def _field_limit(size: int) -> Iterator[None]:
    """Set the csv module's (process-wide) cell cap for the job and restore it afterwards."""
    previous = csv.field_size_limit(size)
    try:
        yield
    finally:
        csv.field_size_limit(previous)


def _bounded_lines(text_io: io.TextIOBase, limits: rules.ImportLimits) -> Iterator[str]:
    """Lines for the csv reader with every limit enforced BEFORE the csv module can buffer
    more: no physical line over the row cap, no NUL, and no record (which may span many lines
    through quoted newlines) over the row or column caps. A broken limit raises, and the
    messages are never used (csv.Error means unreadable; RecordLimitError carries a code)."""
    guard = rules.RecordGuard(max_record_chars=limits.max_row_chars, max_columns=limits.max_columns)
    while line := text_io.readline(limits.max_row_chars + 1):
        if len(line) > limits.max_row_chars and not line.endswith(("\n", "\r")):
            raise csv.Error("line too long")
        if "\x00" in line:
            raise csv.Error("NUL")
        guard.feed(line)
        yield line


@dataclass(frozen=True)
class _Start:
    status: str
    storage_key: str
    report_type: str | None
    layout_version_id: UUID | None
    resume_from: int
    layout_date: date
    scan_state: str
    attempts: int
    lease_expires_at: datetime | None
    lease_owner: UUID | None


def process_batch(
    engine: Engine,
    store: ObjectStore,
    clock: Clock,
    tenant_id: UUID,
    batch_id: UUID,
    *,
    chunk_rows: int = CHUNK_ROWS,
    final_attempt: bool = False,
    after_chunk: Callable[[int], None] | None = None,
    after_normalise_chunk: Callable[[int], None] | None = None,
    limits: rules.ImportLimits | None = None,
    release_delay_seconds: int = 0,
) -> str:
    """Process (or resume) a batch; returns its status. A finished batch is a no-op.

    Failures raise ImportJobError so the caller can retry with backoff. With
    `final_attempt=True` the batch is also marked `failed` with a short code first.
    `after_chunk(rows_in_chunk)` runs after each committed read chunk and
    `after_normalise_chunk(rows)` after each committed normalising chunk (tests use them to
    crash). After a handled failure the lease is released to expire `release_delay_seconds`
    from now (the caller's retry back-off), so the sweeper and the retry do not both take over.
    """
    lease = _Lease()
    try:
        return _run(
            engine,
            store,
            clock,
            tenant_id,
            batch_id,
            chunk_rows,
            after_chunk,
            after_normalise_chunk,
            limits or limits_from_settings(),
            lease,
        )
    except LeaseLostError:
        # Someone else owns the batch now: leave it (and its lease) alone.
        return _status(engine, tenant_id, batch_id)
    except Exception as exc:
        if lease.taken:  # only release a lease this run actually took
            _release_lease(engine, clock, tenant_id, batch_id, lease, release_delay_seconds)
        permanent = isinstance(exc, TenantMismatchError)
        if final_attempt or permanent:
            code = "storage_unavailable" if isinstance(exc, StorageError) else "processing_error"
            _mark_failed(engine, clock, tenant_id, batch_id, code)
        raise ImportJobError(type(exc).__name__, permanent=permanent) from None


def _status(engine: Engine, tenant_id: UUID, batch_id: UUID) -> str:
    with tenant_session(engine, tenant_id=tenant_id) as s:
        return str(_batch(s, tenant_id, batch_id).status)


def _lock(session: Session, tenant_id: UUID, batch_id: UUID) -> None:
    session.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"imports:process:{tenant_id}:{batch_id}"},
    )


def _batch(session: Session, tenant_id: UUID, batch_id: UUID) -> Any:
    row = session.execute(
        select(import_batches).where(
            import_batches.c.tenant_id == tenant_id, import_batches.c.id == batch_id
        )
    ).one_or_none()
    if row is None:
        raise TenantMismatchError()
    return row


def _advance(
    session: Session,
    clock: Clock,
    tenant_id: UUID,
    batch_id: UUID,
    target: str,
    **kwargs: Any,
) -> None:
    """Move forward to `target`; does nothing if the batch is already at or past it."""
    current = _batch(session, tenant_id, batch_id)
    if current.status in rules.TERMINAL_STATES:
        return
    if target not in rules.TERMINAL_STATES and (
        rules.PROGRESS_STATES.index(current.status) >= rules.PROGRESS_STATES.index(target)
    ):
        return
    advance_batch(
        session,
        tenant_id=tenant_id,
        batch_id=batch_id,
        target=target,
        expected_version=current.row_version,
        actor=JOB,
        now=clock.now(),
        **kwargs,
    )


def _release_lease(
    engine: Engine, clock: Clock, tenant_id: UUID, batch_id: UUID, lease: _Lease, delay_seconds: int
) -> None:
    """Hand the lease back after a handled failure: no owner, expiring after the retry
    back-off. A clean release is not a lost worker, so the next start does not count an attempt.
    Does nothing unless the batch still carries THIS run's token."""
    try:
        with tenant_session(engine, tenant_id=tenant_id) as s:
            _lock(s, tenant_id, batch_id)
            current = _batch(s, tenant_id, batch_id)
            if current.status not in rules.TERMINAL_STATES and current.lease_owner == lease.token:
                update_versioned(
                    s,
                    "import_batches",
                    row_id=batch_id,
                    expected_version=current.row_version,
                    values={
                        "lease_expires_at": clock.now() + timedelta(seconds=delay_seconds),
                        "lease_owner": None,
                    },
                )
    except Exception as exc:  # best effort: the lease then simply expires on its own
        log.error("import_release_lease_error", batch_id=str(batch_id), error=type(exc).__name__)


def _renew(
    engine: Engine, clock: Clock, tenant_id: UUID, batch_id: UUID, lease: _Lease, seconds: int
) -> None:
    """Extend the lease if it is still ours; raises LeaseLostError if another job holds it."""
    now = clock.now()
    with tenant_session(engine, tenant_id=tenant_id) as s:
        _lock(s, tenant_id, batch_id)
        current = _batch(s, tenant_id, batch_id)
        if current.status in rules.TERMINAL_STATES:
            return
        if current.lease_owner != lease.token:
            raise LeaseLostError()
        update_versioned(
            s,
            "import_batches",
            row_id=batch_id,
            expected_version=current.row_version,
            values={"lease_expires_at": now + timedelta(seconds=seconds)},
        )
    lease.last_renewed = now


def _renew_if_due(
    engine: Engine, clock: Clock, tenant_id: UUID, batch_id: UUID, lease: _Lease, seconds: int
) -> None:
    """Renew once a third of the lease has passed since the last renewal, so a long read that
    commits nothing (skipping rows already saved, reading the header) cannot outlive it."""
    last = lease.last_renewed
    if last is None or clock.now() - last >= timedelta(seconds=seconds / 3):
        _renew(engine, clock, tenant_id, batch_id, lease, seconds)


def _mark_failed(engine: Engine, clock: Clock, tenant_id: UUID, batch_id: UUID, code: str) -> None:
    try:
        with tenant_session(engine, tenant_id=tenant_id) as s:
            _lock(s, tenant_id, batch_id)
            _advance(s, clock, tenant_id, batch_id, "failed", failure_reason=code)
    except Exception as exc:  # the original failure is the one that matters
        log.error("import_mark_failed_error", batch_id=str(batch_id), error=type(exc).__name__)


def _load_start(session: Session, tenant_id: UUID, batch_id: UUID) -> _Start:
    row = _batch(session, tenant_id, batch_id)
    version = session.execute(
        select(document_versions.c.storage_key, document_versions.c.scan_state).where(
            document_versions.c.tenant_id == tenant_id,
            document_versions.c.id == row.document_version_id,
        )
    ).one_or_none()
    if version is None:
        raise TenantMismatchError()
    resume = session.execute(
        select(func.coalesce(func.max(source_rows.c.row_number), 0)).where(
            source_rows.c.tenant_id == tenant_id, source_rows.c.batch_id == batch_id
        )
    ).scalar_one()
    # The layout is chosen for the date the report was acquired (falling back to the date the
    # batch was received), not the day the job happens to run.
    layout_date = row.acquired_on or uk_date(row.created_at)
    return _Start(
        row.status,
        version.storage_key,
        row.cds_report_type,
        row.report_layout_version_id,
        int(resume),
        layout_date,
        version.scan_state,
        int(row.attempts),
        row.lease_expires_at,
        row.lease_owner,
    )


def _run(
    engine: Engine,
    store: ObjectStore,
    clock: Clock,
    tenant_id: UUID,
    batch_id: UUID,
    chunk_rows: int,
    after_chunk: Callable[[int], None] | None,
    after_normalise_chunk: Callable[[int], None] | None,
    limits: rules.ImportLimits,
    lease: _Lease,
) -> str:
    with tenant_session(engine, tenant_id=tenant_id) as s:
        _lock(s, tenant_id, batch_id)
        start = _load_start(s, tenant_id, batch_id)
        if start.status in rules.TERMINAL_STATES:
            return str(start.status)
        now = clock.now()
        if (
            start.status in rules.PROGRESS_STATES[2:]
            and start.lease_expires_at is not None
            and start.lease_expires_at > now
        ):
            # Another worker holds a fresh lease: a duplicate delivery does nothing and is
            # not counted as an attempt.
            return str(start.status)
        # A first start or a takeover of a LOST worker's lease is an attempt. A lease handed
        # back after a handled failure (no owner, but an expiry) is not: that failure is bounded
        # by the task's retry limit. A worker that keeps dying mid-file must not be taken over
        # forever (crash-loop guard).
        released_cleanly = start.lease_owner is None and start.lease_expires_at is not None
        attempts = start.attempts + (0 if released_cleanly else 1)
        current = _batch(s, tenant_id, batch_id)
        update_versioned(
            s,
            "import_batches",
            row_id=batch_id,
            expected_version=current.row_version,
            values={
                "attempts": attempts,
                "lease_expires_at": now + timedelta(seconds=limits.lease_seconds),
                "lease_owner": lease.token,
            },
        )
        lease.taken = True
        lease.last_renewed = now
        if attempts > limits.max_attempts:
            _advance(s, clock, tenant_id, batch_id, "failed", failure_reason="worker_crash_loop")
            log.error("import_crash_loop", batch_id=str(batch_id), attempts=attempts)
            return "failed"
        _advance(s, clock, tenant_id, batch_id, "queued")
        _advance(s, clock, tenant_id, batch_id, "parsing")
    if start.scan_state == "infected":  # 'pending' proceeds until Phase 7 gates on 'clean'
        return _reject(engine, clock, tenant_id, batch_id, [rules.Issue("FILE_INFECTED", "")], None)

    with _field_limit(limits.max_cell_chars), store.open(start.storage_key) as binary:
        text_io = io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
        reader = csv.reader(_bounded_lines(text_io, limits))
        header, problem = _read_header(reader, limits)
        if header is None:
            return _reject(
                engine,
                clock,
                tenant_id,
                batch_id,
                [rules.Issue(problem or "HEADER_MISSING", "")],
                None,
            )
        too_big = rules.header_problem(header, limits)
        if too_big:
            return _reject(
                engine, clock, tenant_id, batch_id, [rules.Issue(too_big, "")], "unreadable"
            )
        headers = rules.raw_headers(header)
        match_or_status = _prepare(engine, clock, tenant_id, batch_id, start, headers)
        if isinstance(match_or_status, str):
            return match_or_status
        match = match_or_status
        _renew(engine, clock, tenant_id, batch_id, lease, limits.lease_seconds)
        stopped = _stream_rows(
            engine,
            clock,
            tenant_id,
            batch_id,
            reader,
            headers,
            match,
            start.resume_from,
            chunk_rows,
            after_chunk,
            limits,
            lease,
        )
        text_io.detach()

    if stopped:
        # Rows saved before the problem stay (raw rows are never deleted) with their counters;
        # the batch is rejected and a corrected file makes a new batch.
        return _reject(engine, clock, tenant_id, batch_id, [rules.Issue(stopped, "")], None)
    if start.report_type == "import_item":  # other reports are joined by the adapter (step 8a)
        _normalise(
            engine,
            clock,
            tenant_id,
            batch_id,
            match,
            chunk_rows,
            after_normalise_chunk,
            limits,
            lease,
        )
    with tenant_session(engine, tenant_id=tenant_id) as s:
        _lock(s, tenant_id, batch_id)
        counters = _recount(s, tenant_id, batch_id)
        target = "completed_with_errors" if counters["rows_rejected"] else "completed"
        _advance(s, clock, tenant_id, batch_id, target, progress=counters)
        status = str(_batch(s, tenant_id, batch_id).status)
    log.info("import_batch_processed", batch_id=str(batch_id), status=status, **counters)
    return status


def _next_row(
    reader: Iterator[list[str]], limits: rules.ImportLimits
) -> tuple[list[str] | None, str | None]:
    """(cells, stop_code). Blank lines are skipped; (None, None) is the end of the file; a stop
    code (`FILE_UNREADABLE` or `ROW_TOO_LARGE`) means the file cannot be read any further."""
    while True:
        try:
            cells = next(reader)
        except StopIteration:
            return None, None
        except rules.RecordLimitError as exc:
            return None, exc.code
        except (csv.Error, UnicodeDecodeError):
            return None, "FILE_UNREADABLE"
        if rules.row_chars(cells) > limits.max_row_chars:
            return None, "ROW_TOO_LARGE"
        if cells:
            return cells, None


def _read_header(
    reader: Iterator[list[str]], limits: rules.ImportLimits
) -> tuple[list[str] | None, str | None]:
    cells, problem = _next_row(reader, limits)
    if cells is None or not any(c.strip() for c in cells):
        return None, problem
    return cells, None


def _insert_exceptions(
    session: Session,
    *,
    tenant_id: UUID,
    batch_id: UUID,
    now: datetime,
    items: list[tuple[int, UUID | None, rules.Issue]],
) -> None:
    values: dict[tuple[int, str, str], dict[str, Any]] = {}
    for number, source_row_id, issue in items:
        values[(number, issue.field, issue.code)] = {
            "id": uuid7(),
            "tenant_id": tenant_id,
            "batch_id": batch_id,
            "source_row_id": source_row_id,
            "row_number": number,
            "field": issue.field,
            "code": issue.code,
            "severity": rules.issue_severity(issue.code),
            "message": rules.issue_message(issue.code),
            "status": "open",
            "row_version": 1,
            "created_at": now,
        }
    if values:
        session.execute(
            pg_insert(row_exceptions)
            .values(list(values.values()))
            .on_conflict_do_nothing(index_elements=["batch_id", "row_number", "field", "code"])
        )


def _reject(
    engine: Engine,
    clock: Clock,
    tenant_id: UUID,
    batch_id: UUID,
    issues: list[rules.Issue],
    layout_status: str | None,
) -> str:
    """Reject the whole file: file-level exceptions (row 0) and the `rejected` status, together."""
    with tenant_session(engine, tenant_id=tenant_id) as s:
        _lock(s, tenant_id, batch_id)
        current = _batch(s, tenant_id, batch_id)
        if current.status in rules.TERMINAL_STATES:
            return str(current.status)  # lost a race: the batch already has its final state
        _insert_exceptions(
            s,
            tenant_id=tenant_id,
            batch_id=batch_id,
            now=clock.now(),
            items=[(0, None, i) for i in issues],
        )
        counters = _recount(s, tenant_id, batch_id)
        _advance(
            s,
            clock,
            tenant_id,
            batch_id,
            "rejected",
            progress=counters,
            failure_reason=issues[0].code.lower(),
            layout={"layout_status": layout_status} if layout_status else None,
        )
        status = str(_batch(s, tenant_id, batch_id).status)
    log.info("import_batch_rejected", batch_id=str(batch_id), reason=issues[0].code)
    return status


def _prepare(
    engine: Engine,
    clock: Clock,
    tenant_id: UUID,
    batch_id: UUID,
    start: _Start,
    headers: tuple[str, ...],
) -> rules.LayoutMatch | str:
    """Choose the layout and check the headings; returns the match or the rejected status.

    A new batch uses the layout version active today. A batch being resumed keeps the version
    it started with, so a layout activated mid-file cannot change how later rows are read.
    """
    as_of = start.layout_date
    with tenant_session(engine, tenant_id=tenant_id) as s:
        if start.layout_version_id is not None:
            rows = refdata.rows_of_version(s, LAYOUT_DATASET, start.layout_version_id)
            version_id: UUID | None = start.layout_version_id
        elif start.report_type is None:
            rows, version_id = [], None
        else:
            snap = refdata.snapshot(s, [LAYOUT_DATASET], on=as_of)
            rows = [
                dict(r) for r in snap.rows[LAYOUT_DATASET] if r["report_type"] == start.report_type
            ]
            version_id = rows[0]["dataset_version_id"] if rows else None
    if start.report_type is None and start.layout_version_id is None:
        return _reject(
            engine, clock, tenant_id, batch_id, [rules.Issue("REPORT_TYPE_MISSING", "")], None
        )
    columns = rules.layout_columns(rows, start.report_type or "")
    if version_id is None or not columns:
        return _reject(
            engine,
            clock,
            tenant_id,
            batch_id,
            [rules.Issue("LAYOUT_NOT_ACTIVE", "")],
            "not_active",
        )
    if rules.layout_is_invalid(columns):
        return _reject(
            engine, clock, tenant_id, batch_id, [rules.Issue("LAYOUT_INVALID", "")], "invalid"
        )
    match = rules.match_layout(headers, columns)
    if match.duplicate_headers:
        return _reject(
            engine, clock, tenant_id, batch_id, [rules.Issue("HEADER_DUPLICATE", "")], "unreadable"
        )
    if match.missing_required:
        issues = [rules.Issue("COLUMN_MISSING", name) for name in match.missing_required]
        return _reject(engine, clock, tenant_id, batch_id, issues, "columns_missing")
    unmapped = rules.missing_line_fields(match) if start.report_type == "import_item" else ()
    if unmapped:
        issues = [rules.Issue("COLUMN_MISSING", name) for name in unmapped]
        return _reject(engine, clock, tenant_id, batch_id, issues, "columns_missing")
    with tenant_session(engine, tenant_id=tenant_id) as s:
        _lock(s, tenant_id, batch_id)
        _advance(
            s,
            clock,
            tenant_id,
            batch_id,
            "validating",
            layout={"report_layout_version_id": version_id, "layout_status": "matched"},
        )
    return match


def _stream_rows(
    engine: Engine,
    clock: Clock,
    tenant_id: UUID,
    batch_id: UUID,
    reader: Iterator[list[str]],
    headers: tuple[str, ...],
    match: rules.LayoutMatch,
    resume_from: int,
    chunk_rows: int,
    after_chunk: Callable[[int], None] | None,
    limits: rules.ImportLimits,
    lease: _Lease,
) -> str | None:
    """Feed the data rows to `_chunk`, 500 rows or `chunk_max_chars` at a time, whichever
    comes first. Returns a file-level stop code if the file stopped being readable.
    Row numbers count CSV records, not file lines (a quoted newline is one record)."""
    number = 0
    buffer: list[tuple[int, list[str]]] = []
    buffered_chars = 0
    stop: str | None = None

    def flush() -> None:
        written = _chunk(
            engine, clock, tenant_id, batch_id, headers, match, buffer, lease, limits.lease_seconds
        )
        buffer.clear()
        if after_chunk is not None:
            after_chunk(written)

    while True:
        cells, stop = _next_row(reader, limits)
        if cells is None:
            break
        number += 1
        if number <= resume_from:
            # Skipping rows already saved commits nothing, so renew on a time basis.
            _renew_if_due(engine, clock, tenant_id, batch_id, lease, limits.lease_seconds)
            continue
        buffer.append((number, cells))
        buffered_chars += rules.row_chars(cells)
        if len(buffer) >= chunk_rows or buffered_chars >= limits.chunk_max_chars:
            flush()
            buffered_chars = 0
    if buffer:
        flush()
    return stop


def _recount(session: Session, tenant_id: UUID, batch_id: UUID) -> dict[str, int]:
    """Counters recomputed from the tables, so repeating a chunk can never double-count."""
    total = session.execute(
        select(func.count()).where(
            source_rows.c.tenant_id == tenant_id, source_rows.c.batch_id == batch_id
        )
    ).scalar_one()
    rejected = session.execute(
        select(func.count(func.distinct(row_exceptions.c.row_number))).where(
            row_exceptions.c.tenant_id == tenant_id,
            row_exceptions.c.batch_id == batch_id,
            row_exceptions.c.severity == "error",
            row_exceptions.c.row_number > 0,
        )
    ).scalar_one()
    created = session.execute(
        select(func.count()).where(
            import_lines.c.tenant_id == tenant_id, import_lines.c.batch_id == batch_id
        )
    ).scalar_one()
    unchanged = session.execute(
        select(func.count())
        .select_from(
            import_line_sources.join(
                source_rows,
                and_(
                    source_rows.c.tenant_id == import_line_sources.c.tenant_id,
                    source_rows.c.id == import_line_sources.c.source_row_id,
                ),
            )
        )
        .where(
            import_line_sources.c.tenant_id == tenant_id,
            source_rows.c.batch_id == batch_id,
            import_line_sources.c.role == "duplicate_seen",
        )
    ).scalar_one()
    return {
        "rows_total": int(total),
        "rows_processed": int(total),
        "rows_valid": int(total) - int(rejected),
        "rows_rejected": int(rejected),
        "lines_created": int(created),
        "lines_unchanged": int(unchanged),
    }


def _chunk(
    engine: Engine,
    clock: Clock,
    tenant_id: UUID,
    batch_id: UUID,
    headers: tuple[str, ...],
    match: rules.LayoutMatch,
    buffer: list[tuple[int, list[str]]],
    lease: _Lease,
    lease_seconds: int,
) -> int:
    """One transaction: raw rows, exceptions, counters, one audit event. Returns rows written."""
    now = clock.now()
    with tenant_session(engine, tenant_id=tenant_id) as s:
        _lock(s, tenant_id, batch_id)
        current = _batch(s, tenant_id, batch_id)
        if current.status in rules.TERMINAL_STATES:
            return 0
        if current.lease_owner != lease.token:
            raise LeaseLostError()
        planned: dict[int, tuple[UUID, list[rules.Issue]]] = {}
        values: list[dict[str, Any]] = []
        for number, cells in buffer:
            raw, issues = rules.build_raw(headers, cells)
            issues.extend(rules.validate_row(rules.map_row(raw, match)))
            source_id = uuid7()
            planned[number] = (source_id, issues)
            values.append(
                {
                    "id": source_id,
                    "tenant_id": tenant_id,
                    "batch_id": batch_id,
                    "row_number": number,
                    "raw": raw,
                    "row_sha256": rules.row_hash(raw),
                    "created_at": now,
                }
            )
        inserted = set(
            s.execute(
                pg_insert(source_rows)
                .values(values)
                .on_conflict_do_nothing(index_elements=["batch_id", "row_number"])
                .returning(source_rows.c.row_number)
            ).scalars()
        )
        if not inserted:
            return 0  # another attempt already saved these rows
        items: list[tuple[int, UUID | None, rules.Issue]] = [
            (number, planned[number][0], issue)
            for number in sorted(inserted)
            for issue in planned[number][1]
        ]
        _insert_exceptions(s, tenant_id=tenant_id, batch_id=batch_id, now=now, items=items)
        counters = _recount(s, tenant_id, batch_id)
        update_versioned(
            s,
            "import_batches",
            row_id=batch_id,
            expected_version=current.row_version,
            values={**counters, "lease_expires_at": now + timedelta(seconds=lease_seconds)},
        )
        lease.last_renewed = now
        by_code: dict[str, int] = {}
        for _, _, issue in items:
            by_code[issue.code] = by_code.get(issue.code, 0) + 1
        record(
            s,
            tenant_id=tenant_id,
            actor_type="job",
            actor_id=None,
            action="import_batch.rows_processed",
            object_type="import_batch",
            object_id=batch_id,
            occurred_at=now,
            after={
                "rows": len(inserted),
                "first_row": min(inserted),
                "last_row": max(inserted),
                "rows_with_errors": sum(
                    1 for n in inserted if not rules.row_is_valid(planned[n][1])
                ),
                "issues_by_code": dict(sorted(by_code.items())),
                **counters,
            },
        )
        return len(inserted)


def _add_exceptions(
    tenant_id: UUID,
    batch_id: UUID,
    now: datetime,
    session: Session,
    items: list[tuple[int, UUID | None, rules.Issue]],
) -> None:
    _insert_exceptions(session, tenant_id=tenant_id, batch_id=batch_id, now=now, items=items)


def _normalise(
    engine: Engine,
    clock: Clock,
    tenant_id: UUID,
    batch_id: UUID,
    match: rules.LayoutMatch,
    chunk_rows: int,
    after_chunk: Callable[[int], None] | None,
    limits: rules.ImportLimits,
    lease: _Lease,
) -> None:
    """The `normalising` pass: rows with no error exception become declarations and lines, one
    chunk per transaction. Resumable and idempotent: a row is done once it has a source link or
    an error exception, and the counters are recounted from the tables."""
    with tenant_session(engine, tenant_id=tenant_id) as s:
        _lock(s, tenant_id, batch_id)
        _advance(s, clock, tenant_id, batch_id, "normalising")
        batch = _batch(s, tenant_id, batch_id)
        ctx = rules.NormalisationContext(
            batch_eori=batch.eori, entry_method=rules.entry_method_for(batch.acquisition_method)
        )
        report_type = str(batch.cds_report_type)
    size = max(1, min(chunk_rows, normalisation.NORMALISE_CHUNK_ROWS))
    while True:
        now = clock.now()
        with tenant_session(engine, tenant_id=tenant_id) as s:
            _lock(s, tenant_id, batch_id)
            current = _batch(s, tenant_id, batch_id)
            if current.status in rules.TERMINAL_STATES:
                return
            if current.lease_owner != lease.token:
                raise LeaseLostError()
            rows = normalisation.pending_rows(s, tenant_id, batch_id, size)
            if not rows:
                return
            normalisation.normalise_chunk(
                s,
                tenant_id=tenant_id,
                batch_id=batch_id,
                report_type=report_type,
                rows=rows,
                match=match,
                ctx=ctx,
                now=now,
                add_exceptions=partial(_add_exceptions, tenant_id, batch_id, now),
            )
            update_versioned(
                s,
                "import_batches",
                row_id=batch_id,
                expected_version=current.row_version,
                values={
                    **_recount(s, tenant_id, batch_id),
                    "lease_expires_at": now + timedelta(seconds=limits.lease_seconds),
                },
            )
            lease.last_renewed = now
        if after_chunk is not None:
            after_chunk(len(rows))
