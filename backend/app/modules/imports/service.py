"""Import batch service: stores the original file, then saves document, version, batch and
audit event in one transaction (R1-003). Replaying the same file creates nothing new."""

import hashlib
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
    TenantMismatchError,
    UnsupportedMediaError,
)
from app.core.ids import uuid7
from app.core.pagination import clamp_limit, decode_cursor, encode_cursor
from app.core.storage import ObjectStore, content_key
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
    """Serialise concurrent requests for the same file (or key) within a tenant."""
    session.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"imports:{kind}:{tenant_id}:{value}"},
    )


def receive_file(
    session: Session,
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

    Same bytes and same declared details: the existing batch, `replayed=True`, nothing written.
    Same bytes but different declared details, or an Idempotency-Key used for another file:
    409. The original file is never overwritten (CLAUDE.md rule 4).
    """
    if not rules.acquired_on_is_valid(metadata.acquired_on, as_of):
        raise InvalidRequestError("acquired_on cannot be in the future")
    fingerprint = rules.request_fingerprint(metadata.declared())

    _lock(session, tenant_id, "sha", scanned.sha256)
    if idempotency_key:
        _lock(session, tenant_id, "key", idempotency_key)

    existing = session.execute(
        select(import_batches).where(import_batches.c.file_sha256 == scanned.sha256)
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
            select(import_batches.c.id).where(import_batches.c.idempotency_key == idempotency_key)
        ).first()
        if by_key is not None:
            raise IdempotencyConflictError("This Idempotency-Key was used for a different file")

    key = content_key(tenant_id, scanned.sha256)
    file.seek(0)
    store.put(key, file, size=scanned.size_bytes, content_type=scanned.mime_detected)

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
    created = session.execute(select(import_batches).where(import_batches.c.id == batch_id)).one()
    return _created(created, replayed=False)


def get_batch(session: Session, batch_id: UUID) -> ImportBatchOut:
    row = session.execute(
        select(import_batches).where(import_batches.c.id == batch_id)
    ).one_or_none()
    if row is None:
        raise TenantMismatchError()
    return _out(row)


def list_batches(
    session: Session,
    *,
    status: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> ImportBatchPage:
    """Newest first, keyset-paginated by id (UUIDv7 ids are time-ordered)."""
    page = clamp_limit(limit)
    query = select(import_batches)
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
        select(import_batches).where(import_batches.c.id == batch_id)
    ).one_or_none()
    if current is None:
        raise TenantMismatchError()
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
    updated = session.execute(select(import_batches).where(import_batches.c.id == batch_id)).one()
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
