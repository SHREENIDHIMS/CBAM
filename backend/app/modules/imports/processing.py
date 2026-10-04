"""Processing one import batch: raw rows, row validation, exception report (R1-025, R1-003).

The stored file is read as a stream. Each chunk of rows (500 by default) is one tenant
transaction that inserts the raw rows and their exceptions, recounts the batch counters from
the tables and writes one audit event of counts, so a crash loses at most the open chunk and
a retry resumes after the last committed row. Every insert is `on conflict do nothing`; the
counters are recounted, never incremented: running the same work twice changes nothing.

Only format and presence are checked here. Nothing is decided about scope, tax point or the
threshold, and nothing is normalised into declarations or lines yet (Phase 3 step 4).
Neither a cell value nor a filename is ever written to an audit event, a log line, an
exception message or a failure reason.
"""

import csv
import io
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import Engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.audit import record
from app.core.clock import Clock
from app.core.db import tenant_session
from app.core.errors import StorageError, TenantMismatchError
from app.core.ids import uuid7
from app.core.storage import ObjectStore
from app.core.versioning import update_versioned
from app.modules.imports import rules
from app.modules.imports.models import (
    document_versions,
    import_batches,
    row_exceptions,
    source_rows,
)
from app.modules.imports.service import Actor, advance_batch
from app.modules.refdata import service as refdata

CHUNK_ROWS = 500
JOB = Actor("job", None)
LAYOUT_DATASET = "cds_report_layouts"

log = structlog.get_logger()


class ImportJobError(RuntimeError):
    """Any failure of the job, reduced to the class name of the cause. The original message
    can carry SQL parameters (cell values), so it is dropped before it can reach a log, a
    Celery result or Sentry."""


@dataclass(frozen=True)
class _Start:
    status: str
    storage_key: str
    report_type: str | None
    layout_version_id: UUID | None
    resume_from: int


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
) -> str:
    """Process (or resume) a batch; returns its status. A finished batch is a no-op.

    Failures raise ImportJobError so the caller can retry with backoff. With
    `final_attempt=True` the batch is also marked `failed` with a short code first.
    `after_chunk(rows_in_chunk)` runs after each committed chunk (tests use it to crash).
    """
    try:
        return _run(engine, store, clock, tenant_id, batch_id, chunk_rows, after_chunk)
    except Exception as exc:
        if final_attempt:
            code = "storage_unavailable" if isinstance(exc, StorageError) else "processing_error"
            _mark_failed(engine, clock, tenant_id, batch_id, code)
        raise ImportJobError(type(exc).__name__) from None


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


def _mark_failed(engine: Engine, clock: Clock, tenant_id: UUID, batch_id: UUID, code: str) -> None:
    try:
        with tenant_session(engine, tenant_id=tenant_id) as s:
            _lock(s, tenant_id, batch_id)
            _advance(s, clock, tenant_id, batch_id, "failed", failure_reason=code)
    except Exception as exc:  # the original failure is the one that matters
        log.error("import_mark_failed_error", batch_id=str(batch_id), error=type(exc).__name__)


def _load_start(session: Session, tenant_id: UUID, batch_id: UUID) -> _Start:
    row = _batch(session, tenant_id, batch_id)
    key = session.execute(
        select(document_versions.c.storage_key).where(
            document_versions.c.tenant_id == tenant_id,
            document_versions.c.id == row.document_version_id,
        )
    ).scalar_one_or_none()
    if key is None:
        raise TenantMismatchError()
    resume = session.execute(
        select(func.coalesce(func.max(source_rows.c.row_number), 0)).where(
            source_rows.c.tenant_id == tenant_id, source_rows.c.batch_id == batch_id
        )
    ).scalar_one()
    return _Start(row.status, key, row.cds_report_type, row.report_layout_version_id, int(resume))


def _run(
    engine: Engine,
    store: ObjectStore,
    clock: Clock,
    tenant_id: UUID,
    batch_id: UUID,
    chunk_rows: int,
    after_chunk: Callable[[int], None] | None,
) -> str:
    with tenant_session(engine, tenant_id=tenant_id) as s:
        _lock(s, tenant_id, batch_id)
        start = _load_start(s, tenant_id, batch_id)
        if start.status in rules.TERMINAL_STATES:
            return str(start.status)
        _advance(s, clock, tenant_id, batch_id, "queued")
        _advance(s, clock, tenant_id, batch_id, "parsing")

    with store.open(start.storage_key) as binary:
        text_io = io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
        reader = csv.reader(text_io)
        header, unreadable = _read_header(reader)
        if header is None:
            code = "FILE_UNREADABLE" if unreadable else "HEADER_MISSING"
            return _reject(engine, clock, tenant_id, batch_id, [rules.Issue(code, "")], None)
        headers = rules.raw_headers(header)
        match_or_status = _prepare(engine, clock, tenant_id, batch_id, start, headers)
        if isinstance(match_or_status, str):
            return match_or_status
        match = match_or_status
        unreadable = _stream_rows(
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
        )
        text_io.detach()

    if unreadable:
        return _reject(
            engine, clock, tenant_id, batch_id, [rules.Issue("FILE_UNREADABLE", "")], None
        )
    with tenant_session(engine, tenant_id=tenant_id) as s:
        _lock(s, tenant_id, batch_id)
        counters = _recount(s, tenant_id, batch_id)
        target = "completed_with_errors" if counters["rows_rejected"] else "completed"
        _advance(s, clock, tenant_id, batch_id, target, progress=counters)
        status = str(_batch(s, tenant_id, batch_id).status)
    log.info("import_batch_processed", batch_id=str(batch_id), status=status, **counters)
    return status


def _next_row(reader: Iterator[list[str]]) -> tuple[list[str] | None, bool]:
    """(cells, unreadable). Blank lines are skipped; (None, False) is the end of the file."""
    while True:
        try:
            cells = next(reader)
        except StopIteration:
            return None, False
        except (csv.Error, UnicodeDecodeError):
            return None, True
        if cells:
            return cells, False


def _read_header(reader: Iterator[list[str]]) -> tuple[list[str] | None, bool]:
    cells, unreadable = _next_row(reader)
    if cells is None or not any(c.strip() for c in cells):
        return None, unreadable
    return cells, False


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
    as_of = clock.today_uk()
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
    match = rules.match_layout(headers, columns)
    if match.duplicate_headers:
        return _reject(
            engine, clock, tenant_id, batch_id, [rules.Issue("HEADER_DUPLICATE", "")], "unreadable"
        )
    if match.missing_required:
        issues = [rules.Issue("COLUMN_MISSING", name) for name in match.missing_required]
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
) -> bool:
    """Feed the data rows to `_chunk`; returns True if the file stopped being readable."""
    number = 0
    buffer: list[tuple[int, list[str]]] = []
    unreadable = False
    while True:
        cells, unreadable = _next_row(reader)
        if cells is None:
            break
        number += 1
        if number <= resume_from:
            continue
        buffer.append((number, cells))
        if len(buffer) >= chunk_rows:
            written = _chunk(engine, clock, tenant_id, batch_id, headers, match, buffer)
            buffer = []
            if after_chunk is not None:
                after_chunk(written)
    if buffer:
        written = _chunk(engine, clock, tenant_id, batch_id, headers, match, buffer)
        if after_chunk is not None:
            after_chunk(written)
    return unreadable


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
    return {
        "rows_total": int(total),
        "rows_processed": int(total),
        "rows_valid": int(total) - int(rejected),
        "rows_rejected": int(rejected),
    }


def _chunk(
    engine: Engine,
    clock: Clock,
    tenant_id: UUID,
    batch_id: UUID,
    headers: tuple[str, ...],
    match: rules.LayoutMatch,
    buffer: list[tuple[int, list[str]]],
) -> int:
    """One transaction: raw rows, exceptions, counters, one audit event. Returns rows written."""
    now = clock.now()
    with tenant_session(engine, tenant_id=tenant_id) as s:
        _lock(s, tenant_id, batch_id)
        current = _batch(s, tenant_id, batch_id)
        if current.status in rules.TERMINAL_STATES:
            return 0
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
            values=counters,
        )
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
