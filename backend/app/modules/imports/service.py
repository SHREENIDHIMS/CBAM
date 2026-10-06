"""Import batch service: stores the original file, then saves document, version, batch and
audit event in one transaction (R1-003). Replaying the same file creates nothing new."""

import hashlib
import re
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, BinaryIO
from uuid import UUID

from sqlalchemy import Row, and_, func, insert, or_, select, text, tuple_
from sqlalchemy.orm import Session

from app.core.audit import ActorType, record
from app.core.errors import (
    IdempotencyConflictError,
    InvalidRequestError,
    PayloadTooLargeError,
    RuleBlockedError,
    StaleVersionError,
    StorageError,
    TenantMismatchError,
    TooManyRequestsError,
    UnsupportedMediaError,
)
from app.core.ids import uuid7
from app.core.pagination import clamp_limit, decode_cursor, encode_cursor
from app.core.storage import ObjectStore, new_object_key
from app.core.versioning import update_versioned
from app.modules.imports import rules
from app.modules.imports.models import (
    document_versions,
    documents,
    import_batches,
    row_exceptions,
)
from app.modules.imports.schemas import (
    ImportBatchCreated,
    ImportBatchMetadata,
    ImportBatchOut,
    ImportBatchPage,
    RowExceptionOut,
    RowExceptionPage,
)

_CHUNK = 64 * 1024
_PROGRESS_COLUMNS = (
    "rows_total",
    "rows_processed",
    "rows_valid",
    "rows_rejected",
    "lines_created",
    "lines_unchanged",
)


_LAYOUT_COLUMNS = ("report_layout_version_id", "layout_status")


def _audit_value(value: Any) -> Any:
    return str(value) if isinstance(value, UUID) else value


@dataclass(frozen=True)
class Actor:
    actor_type: ActorType
    actor_id: UUID | None


@dataclass(frozen=True)
class ScannedFile:
    sha256: str
    size_bytes: int
    mime_detected: str


def scan_upload(file: BinaryIO, *, max_bytes: int) -> ScannedFile:
    """Read the upload once: SHA-256, size limit and content check, without loading it all.

    Raises 413 above `max_bytes`, 415 for binary or non-UTF-8 content, 422 for an empty file or
    one with no delimited header row. Nothing about the content goes into an error message.
    """
    digest = hashlib.sha256()
    checker = rules.Utf8Checker()
    size = 0
    file.seek(0)
    while chunk := file.read(_CHUNK):
        size += len(chunk)
        if size > max_bytes:
            raise PayloadTooLargeError(f"Files can be at most {max_bytes} bytes")
        digest.update(chunk)
        if not checker.feed(chunk):
            raise UnsupportedMediaError("Only CSV text files (UTF-8) are accepted")
    if size == 0:
        raise InvalidRequestError("The file is empty")
    if not checker.finish():
        raise UnsupportedMediaError("Only CSV text files (UTF-8) are accepted")
    if not checker.first_line_has_delimiter():
        raise InvalidRequestError("The file does not look like a CSV file with a header row")
    file.seek(0)
    return ScannedFile(sha256=digest.hexdigest(), size_bytes=size, mime_detected="text/csv")


def _out(row: Row[Any]) -> ImportBatchOut:
    return ImportBatchOut(
        id=row.id,
        status=row.status,
        file_sha256=row.file_sha256,
        document_version_id=row.document_version_id,
        filename=row.filename,
        acquisition_method=row.acquisition_method,
        cds_report_type=row.cds_report_type,
        eori=row.eori,
        window_start=row.window_start,
        window_end=row.window_end,
        source_owner=row.source_owner,
        acquired_on=row.acquired_on,
        rows_total=row.rows_total,
        rows_processed=row.rows_processed,
        rows_valid=row.rows_valid,
        rows_rejected=row.rows_rejected,
        lines_created=row.lines_created,
        lines_unchanged=row.lines_unchanged,
        failure_reason=row.failure_reason,
        report_layout_version_id=row.report_layout_version_id,
        layout_status=row.layout_status,
        created_at=row.created_at,
        created_by=row.created_by,
        row_version=row.row_version,
    )


def _created(row: Row[Any], *, replayed: bool) -> ImportBatchCreated:
    return ImportBatchCreated(**_out(row).model_dump(), replayed=replayed)


def _lock(session: Session, tenant_id: UUID, kind: str, value: str) -> None:
    """Serialise concurrent requests for the same file (or key) within a tenant. Held only for
    the short insert transaction, never while a file is being streamed to storage."""
    session.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"imports:{kind}:{tenant_id}:{value}"},
    )


def _find_replay(
    session: Session,
    *,
    tenant_id: UUID,
    sha256: str,
    fingerprint: bytes,
    idempotency_key: str | None,
) -> ImportBatchCreated | None:
    """The live batch for these bytes, as a replay, or None if the file is new.

    A failed or rejected batch is history and never counts: the same bytes can be sent again
    and get a new batch. Same bytes with different declared details is a 409. The tenant is
    filtered here as well as by row-level security (CLAUDE.md rule 7). A different
    Idempotency-Key for bytes already received replays and the new key is ignored.
    """
    live = import_batches.c.status.not_in(rules.HISTORY_STATES)
    existing = session.execute(
        select(import_batches).where(
            import_batches.c.tenant_id == tenant_id,
            import_batches.c.file_sha256 == sha256,
            live,
        )
    ).one_or_none()
    if existing is not None:
        if bytes(existing.request_fingerprint) != fingerprint:
            raise IdempotencyConflictError(
                "This file was already received with different details "
                f"(batch {existing.id}); upload a new file or use the existing batch"
            )
        return _created(existing, replayed=True)
    if idempotency_key:
        by_key = session.execute(
            select(import_batches.c.id).where(
                import_batches.c.tenant_id == tenant_id,
                import_batches.c.idempotency_key == idempotency_key,
                live,
            )
        ).first()
        if by_key is not None:
            raise IdempotencyConflictError("This Idempotency-Key was used for a different file")
    return None


_KEY_SHAPE = re.compile(r"^[\x21-\x7e]{1,200}$")


def check_idempotency_key(key: str | None) -> str | None:
    """The key as sent, or None; a malformed one is a 422."""
    if key is not None and not _KEY_SHAPE.match(key):
        raise InvalidRequestError("Idempotency-Key must be 1 to 200 visible ASCII characters")
    return key


def find_keyed_batch(
    session: Session, *, tenant_id: UUID, key: str, fingerprint: bytes
) -> Row[Any] | None:
    """The live batch an earlier request with this Idempotency-Key made, or None. The same key
    with a different request is a 409 (as for file uploads). Serialised per key, so two parallel
    requests with one key cannot both create."""
    _lock(session, tenant_id, "key", key)
    existing = session.execute(
        select(import_batches).where(
            import_batches.c.tenant_id == tenant_id,
            import_batches.c.idempotency_key == key,
            import_batches.c.status.not_in(rules.HISTORY_STATES),
        )
    ).one_or_none()
    if existing is None:
        return None
    if bytes(existing.request_fingerprint) != fingerprint:
        raise IdempotencyConflictError("This Idempotency-Key was used for a different request")
    return existing


def receive_file(
    open_session: Callable[[], AbstractContextManager[Session]],
    *,
    store: ObjectStore,
    tenant_id: UUID,
    actor: Actor,
    now: datetime,
    as_of: date,
    file: BinaryIO,
    scanned: ScannedFile,
    filename: str | None,
    metadata: ImportBatchMetadata,
    idempotency_key: str | None = None,
) -> ImportBatchCreated:
    """Create the batch for an uploaded file, or return the one already made for it.

    Three steps, so no database transaction or lock is held while the file is sent to storage:
    1. a short read to see whether this is a replay;
    2. for a new file, store the object under a fresh random key, outside any transaction;
    3. a short transaction under an advisory lock that re-checks for a concurrent winner and
       inserts document, version, batch and audit event.
    A request that loses the race, or whose transaction fails, deletes its own blob (best
    effort) and returns the winner. Should the delete itself fail, an orphan blob remains: it
    is unreferenced, private and under this tenant's prefix, and a sweep can remove it later.
    Same bytes with different declared details, or an Idempotency-Key used for another file, is
    a 409. The original file is never overwritten (CLAUDE.md rule 4).
    """
    if not rules.acquired_on_is_valid(metadata.acquired_on, as_of):
        raise InvalidRequestError("acquired_on cannot be in the future")
    if not rules.window_is_valid(metadata.window_start, metadata.window_end, as_of):
        raise InvalidRequestError("window_start and window_end cannot be in the future")
    fingerprint = rules.request_fingerprint(metadata.declared())

    with open_session() as s:
        replay = _find_replay(
            s,
            tenant_id=tenant_id,
            sha256=scanned.sha256,
            fingerprint=fingerprint,
            idempotency_key=idempotency_key,
        )
    if replay is not None:
        return replay

    created: ImportBatchCreated | None = None
    key = new_object_key(tenant_id)
    file.seek(0)
    store.put(key, file, size=scanned.size_bytes, content_type=scanned.mime_detected)
    try:
        with open_session() as s:
            _lock(s, tenant_id, "sha", scanned.sha256)
            if idempotency_key:
                _lock(s, tenant_id, "key", idempotency_key)
            replay = _find_replay(
                s,
                tenant_id=tenant_id,
                sha256=scanned.sha256,
                fingerprint=fingerprint,
                idempotency_key=idempotency_key,
            )
            if replay is None:
                created = _insert(
                    s,
                    tenant_id=tenant_id,
                    actor=actor,
                    now=now,
                    key=key,
                    scanned=scanned,
                    filename=filename,
                    metadata=metadata,
                    idempotency_key=idempotency_key,
                    fingerprint=fingerprint,
                )
    except BaseException:
        _discard(store, key)
        raise
    if replay is not None:
        _discard(store, key)  # lost the race: the winner's blob is the one that stays
        return replay
    if created is None:  # unreachable: the transaction either inserted or found a replay
        raise StorageError("the import batch was not saved")
    return created


def _discard(store: ObjectStore, key: str) -> None:
    with suppress(StorageError):
        store.delete(key)


def _insert(
    session: Session,
    *,
    tenant_id: UUID,
    actor: Actor,
    now: datetime,
    key: str,
    scanned: ScannedFile,
    filename: str | None,
    metadata: ImportBatchMetadata,
    idempotency_key: str | None,
    fingerprint: bytes,
) -> ImportBatchCreated:
    display_name = rules.safe_filename(filename)
    document_id, version_id, batch_id = uuid7(), uuid7(), uuid7()
    session.execute(
        insert(documents).values(
            id=document_id, tenant_id=tenant_id, created_at=now, created_by=actor.actor_id
        )
    )
    session.execute(
        insert(document_versions).values(
            id=version_id,
            tenant_id=tenant_id,
            document_id=document_id,
            version=1,
            storage_key=key,
            sha256=scanned.sha256,
            size_bytes=scanned.size_bytes,
            mime_detected=scanned.mime_detected,
            original_filename=display_name,
            uploaded_by_type=actor.actor_type,
            uploaded_by_id=actor.actor_id,
            scan_state="not_scanned",
            uploaded_at=now,
        )
    )
    session.execute(
        insert(import_batches).values(
            id=batch_id,
            tenant_id=tenant_id,
            file_sha256=scanned.sha256,
            document_version_id=version_id,
            filename=display_name,
            acquisition_method=metadata.acquisition_method,
            cds_report_type=metadata.cds_report_type,
            eori=metadata.eori,
            window_start=metadata.window_start,
            window_end=metadata.window_end,
            source_owner=metadata.source_owner,
            acquired_on=metadata.acquired_on,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            status="received",
            created_at=now,
            created_by=actor.actor_id,
            row_version=1,
        )
    )
    record(
        session,
        tenant_id=tenant_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        action="import_batch.created",
        object_type="import_batch",
        object_id=batch_id,
        occurred_at=now,
        before=None,
        after={
            "status": "received",
            "file_sha256": scanned.sha256,
            "size_bytes": scanned.size_bytes,
            "document_version_id": str(version_id),
            "acquisition_method": metadata.acquisition_method,
            "cds_report_type": metadata.cds_report_type,
            "window_start": metadata.window_start.isoformat() if metadata.window_start else None,
            "window_end": metadata.window_end.isoformat() if metadata.window_end else None,
            "acquired_on": metadata.acquired_on.isoformat() if metadata.acquired_on else None,
        },
    )
    row = session.execute(
        select(import_batches).where(
            import_batches.c.tenant_id == tenant_id, import_batches.c.id == batch_id
        )
    ).one()
    return _created(row, replayed=False)


class UploadLimiter:
    """Caps uploads in flight per tenant inside this process (429 above the cap).

    A per-process guard against one client tying up the API with large streams; it is not a
    global rate limit across API replicas.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[UUID, int] = {}

    def acquire(self, tenant_id: UUID, limit: int) -> None:
        with self._lock:
            active = self._active.get(tenant_id, 0)
            if active >= limit:
                raise TooManyRequestsError("Too many uploads are in progress; retry shortly")
            self._active[tenant_id] = active + 1

    def release(self, tenant_id: UUID) -> None:
        with self._lock:
            remaining = self._active.get(tenant_id, 0) - 1
            if remaining > 0:
                self._active[tenant_id] = remaining
            else:
                self._active.pop(tenant_id, None)

    def active(self, tenant_id: UUID) -> int:
        with self._lock:
            return self._active.get(tenant_id, 0)


upload_limiter = UploadLimiter()


def get_batch(session: Session, tenant_id: UUID, batch_id: UUID) -> ImportBatchOut:
    row = session.execute(
        select(import_batches).where(
            import_batches.c.tenant_id == tenant_id, import_batches.c.id == batch_id
        )
    ).one_or_none()
    if row is None:
        raise TenantMismatchError()
    return _out(row)


def list_batches(
    session: Session,
    tenant_id: UUID,
    *,
    status: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> ImportBatchPage:
    """Newest first, keyset-paginated by id (UUIDv7 ids are time-ordered)."""
    page = clamp_limit(limit)
    query = select(import_batches).where(import_batches.c.tenant_id == tenant_id)
    if status:
        query = query.where(import_batches.c.status == status)
    if cursor:
        c = decode_cursor(cursor)
        try:
            after_id = UUID(str(c["i"]))
        except (KeyError, ValueError) as exc:
            raise InvalidRequestError("The cursor is not valid") from exc
        query = query.where(import_batches.c.id < after_id)
    rows = session.execute(query.order_by(import_batches.c.id.desc()).limit(page + 1)).all()
    items = rows[:page]
    next_cursor = encode_cursor({"i": str(items[-1].id)}) if len(rows) > page else None
    return ImportBatchPage(items=[_out(r) for r in items], next_cursor=next_cursor)


def advance_batch(
    session: Session,
    *,
    tenant_id: UUID,
    batch_id: UUID,
    target: str,
    expected_version: int,
    actor: Actor,
    now: datetime,
    progress: dict[str, int] | None = None,
    failure_reason: str | None = None,
    layout: dict[str, Any] | None = None,
) -> ImportBatchOut:
    """Move a batch forward (and update its counters), with audit. Used by the import jobs.

    The rule refuses a backward move or any change to a finished batch; the database trigger
    refuses it again (CLAUDE.md rule 17).
    """
    current = session.execute(
        select(import_batches).where(
            import_batches.c.tenant_id == tenant_id, import_batches.c.id == batch_id
        )
    ).one_or_none()
    if current is None:
        raise TenantMismatchError()
    if failure_reason is not None and not rules.is_failure_code(failure_reason):
        raise InvalidRequestError("failure_reason must be a short code such as unreadable_header")
    decision = rules.batch_transition(current.status, target)
    if decision.outcome == "BLOCKED":
        raise RuleBlockedError(decision.reason, rule_id=decision.rule_id)
    values: dict[str, Any] = {"status": target}
    for name, number in (progress or {}).items():
        if name not in _PROGRESS_COLUMNS:
            raise InvalidRequestError(f"{name} is not a progress counter")
        values[name] = number
    if failure_reason is not None:
        values["failure_reason"] = failure_reason
    for name, value in (layout or {}).items():
        if name not in _LAYOUT_COLUMNS:
            raise InvalidRequestError(f"{name} is not a layout column")
        values[name] = value
    update_versioned(
        session, "import_batches", row_id=batch_id, expected_version=expected_version, values=values
    )
    updated = session.execute(
        select(import_batches).where(
            import_batches.c.tenant_id == tenant_id, import_batches.c.id == batch_id
        )
    ).one()
    record(
        session,
        tenant_id=tenant_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        action="import_batch.status_changed",
        object_type="import_batch",
        object_id=batch_id,
        occurred_at=now,
        before={"status": current.status},
        after={
            "status": updated.status,
            **{k: _audit_value(values[k]) for k in values if k != "status"},
        },
        reason=failure_reason,
    )
    return _out(updated)


_MAX_ROW_NUMBER = 2**31 - 1
_EXCEPTION_SEVERITIES = ("error", "warning")
_EXCEPTION_STATUSES = ("open", "resolved", "waived")


def _exception_query(
    tenant_id: UUID, batch_id: UUID, severity: str | None, status: str | None
) -> Any:
    if severity is not None and severity not in _EXCEPTION_SEVERITIES:
        raise InvalidRequestError("severity must be error or warning")
    if status is not None and status not in _EXCEPTION_STATUSES:
        raise InvalidRequestError("status must be open, resolved or waived")
    query = select(row_exceptions).where(
        row_exceptions.c.tenant_id == tenant_id, row_exceptions.c.batch_id == batch_id
    )
    if severity:
        query = query.where(row_exceptions.c.severity == severity)
    if status:
        query = query.where(row_exceptions.c.status == status)
    return query


def _exception_out(row: Row[Any]) -> RowExceptionOut:
    return RowExceptionOut(
        id=row.id,
        row_number=row.row_number,
        field=row.field,
        code=row.code,
        severity=row.severity,
        message=row.message,
        status=row.status,
        row_version=row.row_version,
    )


def _exception_page(
    session: Session,
    tenant_id: UUID,
    batch_id: UUID,
    *,
    severity: str | None,
    status: str | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[Row[Any]], bool]:
    query = _exception_query(tenant_id, batch_id, severity, status)
    if cursor:
        c = decode_cursor(cursor)
        try:
            after = (int(c["r"]), UUID(str(c["i"])))
            if not 0 <= after[0] <= _MAX_ROW_NUMBER:
                raise ValueError("row number out of range")
        except (KeyError, ValueError, TypeError, OverflowError) as exc:
            raise InvalidRequestError("The cursor is not valid") from exc
        query = query.where(tuple_(row_exceptions.c.row_number, row_exceptions.c.id) > after)
    rows = session.execute(
        query.order_by(row_exceptions.c.row_number, row_exceptions.c.id).limit(limit + 1)
    ).all()
    return list(rows[:limit]), len(rows) > limit


def list_exceptions(
    session: Session,
    tenant_id: UUID,
    batch_id: UUID,
    *,
    severity: str | None = None,
    status: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> RowExceptionPage:
    """The exception report of a batch, in row order, keyset-paginated."""
    get_batch(session, tenant_id, batch_id)  # 404 for a batch of another tenant
    page = clamp_limit(limit)
    items, more = _exception_page(
        session, tenant_id, batch_id, severity=severity, status=status, limit=page, cursor=cursor
    )
    next_cursor = (
        encode_cursor({"r": items[-1].row_number, "i": str(items[-1].id)}) if more else None
    )
    return RowExceptionPage(items=[_exception_out(r) for r in items], next_cursor=next_cursor)


def iter_exception_pages(
    open_session: Callable[[], AbstractContextManager[Session]],
    tenant_id: UUID,
    batch_id: UUID,
    *,
    severity: str | None = None,
    status: str | None = None,
    page_size: int = 1000,
) -> Iterator[list[RowExceptionOut]]:
    """Every exception of a batch, a page per short transaction, so a long download holds no
    transaction open. The batch must be checked (get_batch) before the first call."""
    cursor: str | None = None
    while True:
        with open_session() as s:
            rows, more = _exception_page(
                s,
                tenant_id,
                batch_id,
                severity=severity,
                status=status,
                limit=page_size,
                cursor=cursor,
            )
        if rows:
            yield [_exception_out(r) for r in rows]
        if not more:
            return
        cursor = encode_cursor({"r": rows[-1].row_number, "i": str(rows[-1].id)})


def exceptions_csv_rows(pages: Iterator[list[RowExceptionOut]]) -> Iterator[list[str]]:
    """Header row, then one row per exception. Every cell goes through `csv_safe`, so nothing
    that came from an uploaded file can be run as a spreadsheet formula."""
    yield ["row_number", "field", "code", "severity", "message", "status"]
    for page in pages:
        for e in page:
            yield [
                rules.csv_safe(str(e.row_number)),
                rules.csv_safe(e.field),
                rules.csv_safe(e.code),
                rules.csv_safe(e.severity),
                rules.csv_safe(e.message),
                rules.csv_safe(e.status),
            ]


def retry_batch(
    session: Session,
    *,
    tenant_id: UUID,
    batch_id: UUID,
    expected_version: int,
    actor: Actor,
    now: datetime,
) -> ImportBatchCreated:
    """Retry a failed batch: a NEW batch for the same stored file and declared details.

    `failed` is final and locked (CLAUDE.md rule 17), so the old batch stays as history and
    its partial rows stay with it. Refused (409) for any other status, a stale version, or when
    the same file already has a live batch.
    """
    _lock(session, tenant_id, "retry", str(batch_id))
    old = session.execute(
        select(import_batches).where(
            import_batches.c.tenant_id == tenant_id, import_batches.c.id == batch_id
        )
    ).one_or_none()
    if old is None:
        raise TenantMismatchError()
    if old.row_version != expected_version:
        raise StaleVersionError("This record changed since you loaded it; reload and try again")
    if old.status != "failed":
        raise RuleBlockedError(
            f"Only a failed batch can be retried; this one is {old.status}",
            rule_id="R1-003.retry_failed_only",
        )
    _lock(session, tenant_id, "sha", old.file_sha256)
    live = session.execute(
        select(import_batches.c.id).where(
            import_batches.c.tenant_id == tenant_id,
            import_batches.c.file_sha256 == old.file_sha256,
            import_batches.c.status.not_in(rules.HISTORY_STATES),
        )
    ).first()
    if live is not None:
        raise RuleBlockedError(
            f"This file already has a newer batch ({live.id}); use that one",
            rule_id="R1-003.retry_failed_only",
        )
    new_id = uuid7()
    session.execute(
        insert(import_batches).values(
            id=new_id,
            tenant_id=tenant_id,
            file_sha256=old.file_sha256,
            document_version_id=old.document_version_id,
            filename=old.filename,
            acquisition_method=old.acquisition_method,
            cds_report_type=old.cds_report_type,
            eori=old.eori,
            window_start=old.window_start,
            window_end=old.window_end,
            source_owner=old.source_owner,
            acquired_on=old.acquired_on,
            idempotency_key=None,
            request_fingerprint=old.request_fingerprint,
            status="received",
            created_at=now,
            created_by=actor.actor_id,
            row_version=1,
        )
    )
    record(
        session,
        tenant_id=tenant_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        action="import_batch.retried",
        object_type="import_batch",
        object_id=new_id,
        occurred_at=now,
        before=None,
        after={"status": "received", "retry_of": str(batch_id)},
    )
    row = session.execute(
        select(import_batches).where(
            import_batches.c.tenant_id == tenant_id, import_batches.c.id == new_id
        )
    ).one()
    return _created(row, replayed=False)


def stale_batch_ids(
    session: Session, tenant_id: UUID, *, older_than: datetime, now: datetime
) -> list[UUID]:
    """Batches whose job was lost: still `received`/`queued` since before `older_than` (broker
    outage at upload, worker lost before it started), or `parsing`/`validating`/`normalising`
    with a lease that has expired at `now` (worker killed mid-file)."""
    working = import_batches.c.status.in_(("parsing", "validating", "normalising"))
    rows = session.execute(
        select(import_batches.c.id)
        .where(
            import_batches.c.tenant_id == tenant_id,
            or_(
                and_(
                    import_batches.c.status.in_(("received", "queued")),
                    func.coalesce(import_batches.c.updated_at, import_batches.c.created_at)
                    < older_than,
                ),
                and_(
                    working,
                    or_(
                        import_batches.c.lease_expires_at.is_(None),
                        import_batches.c.lease_expires_at <= now,
                    ),
                ),
            ),
        )
        .order_by(import_batches.c.id)
        .limit(1000)
    ).scalars()
    return list(rows)
