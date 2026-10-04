"""Import batch service: stores the original file, then saves document, version, batch and
audit event in one transaction (R1-003). Replaying the same file creates nothing new."""

import hashlib
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, BinaryIO
from uuid import UUID

from sqlalchemy import Row, insert, select, text
from sqlalchemy.orm import Session

from app.core.audit import ActorType, record
from app.core.errors import (
    IdempotencyConflictError,
    InvalidRequestError,
    PayloadTooLargeError,
    RuleBlockedError,
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
from app.modules.imports.models import document_versions, documents, import_batches
from app.modules.imports.schemas import (
    ImportBatchCreated,
    ImportBatchMetadata,
    ImportBatchOut,
    ImportBatchPage,
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
        after={"status": updated.status, **{k: values[k] for k in values if k != "status"}},
        reason=failure_reason,
    )
    return _out(updated)
