import csv
import io
import re
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from datetime import timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.core.clock import Clock, get_clock
from app.core.config import Settings, get_settings
from app.core.errors import InvalidRequestError, PayloadTooLargeError, UnsupportedMediaError
from app.core.storage import ObjectStore, get_object_store
from app.core.tenancy import TenantContext, require
from app.core.versioning import etag, parse_if_match
from app.modules.imports import service
from app.modules.imports.jobs import Enqueuer, get_enqueuer, safe_enqueue
from app.modules.imports.schemas import (
    ImportBatchCreated,
    ImportBatchMetadata,
    ImportBatchOut,
    ImportBatchPage,
    RowExceptionPage,
)

router = APIRouter(prefix="/tenants/{tenant_id}/import-batches", tags=["imports"])

# The multipart envelope and the small text fields add a little to the file's own size.
_ENVELOPE_ALLOWANCE = 64 * 1024
_FIELDS = tuple(ImportBatchMetadata.model_fields)
_IDEMPOTENCY_KEY = re.compile(r"^[\x21-\x7e]{1,200}$")

_UPLOAD_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file", "acquisition_method"],
                    "properties": {
                        "file": {"type": "string", "format": "binary"},
                        **{name: {"type": "string"} for name in _FIELDS},
                    },
                }
            }
        },
    }
}


async def _capped(stream: AsyncIterator[bytes], limit: int) -> AsyncGenerator[bytes, None]:
    """Stop reading the request body as soon as it is larger than any allowed upload."""
    total = 0
    async for chunk in stream:
        total += len(chunk)
        if total > limit:
            raise PayloadTooLargeError("The upload is larger than the allowed file size")
        yield chunk


def _metadata(fields: dict[str, str]) -> ImportBatchMetadata:
    raw = {name: fields[name].strip() or None for name in _FIELDS if name in fields}
    try:
        return ImportBatchMetadata.model_validate(raw)
    except ValidationError as exc:
        errors = [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"]} for e in exc.errors()]
        raise InvalidRequestError("The import details are not valid", errors=errors) from None


@router.post(
    "",
    response_model=ImportBatchCreated,
    status_code=202,
    openapi_extra=_UPLOAD_BODY,
    responses={200: {"model": ImportBatchCreated, "description": "Already received (replay)"}},
)
async def create_import_batch(
    request: Request,
    response: Response,
    ctx: Annotated[TenantContext, Depends(require("imports:write"))],
    clock: Annotated[Clock, Depends(get_clock)],
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
    enqueue: Annotated[Enqueuer, Depends(get_enqueuer)],
    idempotency_key: Annotated[str | None, Header()] = None,
) -> ImportBatchCreated:
    """Upload a customs file. 202 for a new batch, 200 with `replayed: true` for a file that
    was already received (same SHA-256 and same declared details). A new batch is queued for
    processing after it is saved; a replay is queued again only if its job never started."""
    max_bytes = settings.import_max_file_bytes
    service.upload_limiter.acquire(ctx.tenant_id, settings.import_max_concurrent_uploads_per_tenant)
    try:
        result = await _receive(request, response, ctx, clock, store, idempotency_key, max_bytes)
    finally:
        service.upload_limiter.release(ctx.tenant_id)
    # A replay of a batch whose job never started is queued again only once it is overdue (older
    # than the stale window); the job is idempotent and the sweeper covers the rest.
    overdue = (
        result.status in ("received", "queued")
        and result.created_at is not None
        and clock.now() - result.created_at > timedelta(minutes=settings.import_stale_batch_minutes)
    )
    if not result.replayed or overdue:
        await run_in_threadpool(safe_enqueue, enqueue, ctx.tenant_id, result.id)
    return result


async def _receive(
    request: Request,
    response: Response,
    ctx: TenantContext,
    clock: Clock,
    store: ObjectStore,
    idempotency_key: str | None,
    max_bytes: int,
) -> ImportBatchCreated:
    if idempotency_key is not None and not _IDEMPOTENCY_KEY.match(idempotency_key):
        raise InvalidRequestError("Idempotency-Key must be 1 to 200 visible ASCII characters")
    declared = request.headers.get("content-length")
    if (
        declared is not None
        and declared.isdigit()
        and int(declared) > max_bytes + _ENVELOPE_ALLOWANCE
    ):
        raise PayloadTooLargeError(f"Files can be at most {max_bytes} bytes")
    if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
        raise UnsupportedMediaError("Send the file as multipart/form-data")

    parser = MultiPartParser(
        request.headers,
        _capped(request.stream(), max_bytes + _ENVELOPE_ALLOWANCE),
        max_files=1,
        max_fields=len(_FIELDS) + 2,
    )
    try:
        form = await parser.parse()
    except MultiPartException:
        raise InvalidRequestError("The upload is not valid multipart form data") from None
    try:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise InvalidRequestError("Send the file in the 'file' form field")
        fields = {k: v for k, v in form.items() if isinstance(v, str)}
        metadata = _metadata(fields)
        actor = service.Actor("user", ctx.user.user_id)
        now = clock.now()
        as_of = clock.today_uk()

        def work() -> ImportBatchCreated:
            scanned = service.scan_upload(upload.file, max_bytes=max_bytes)
            return service.receive_file(
                ctx.session,
                store=store,
                tenant_id=ctx.tenant_id,
                actor=actor,
                now=now,
                as_of=as_of,
                file=upload.file,
                scanned=scanned,
                filename=upload.filename,
                metadata=metadata,
                idempotency_key=idempotency_key,
            )

        result = await run_in_threadpool(work)
    finally:
        await form.close()
    if result.replayed:
        response.status_code = 200
    response.headers["ETag"] = etag(result.row_version)
    response.headers["Location"] = f"{request.url.path.rstrip('/')}/{result.id}"
    return result


@router.get("", response_model=ImportBatchPage)
def list_import_batches(
    ctx: Annotated[TenantContext, Depends(require("imports:read"))],
    status: str | None = None,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    cursor: str | None = None,
) -> ImportBatchPage:
    with ctx.session() as s:
        return service.list_batches(s, ctx.tenant_id, status=status, limit=limit, cursor=cursor)


@router.get("/{batch_id}", response_model=ImportBatchOut)
def get_import_batch(
    batch_id: UUID,
    response: Response,
    ctx: Annotated[TenantContext, Depends(require("imports:read"))],
) -> ImportBatchOut:
    with ctx.session() as s:
        batch = service.get_batch(s, ctx.tenant_id, batch_id)
    response.headers["ETag"] = etag(batch.row_version)
    return batch


@router.get("/{batch_id}/exceptions", response_model=RowExceptionPage)
def list_exceptions(
    batch_id: UUID,
    ctx: Annotated[TenantContext, Depends(require("imports:read"))],
    severity: Literal["error", "warning"] | None = None,
    status: Literal["open", "resolved", "waived"] | None = None,
    export: Annotated[Literal["json", "csv"], Query(alias="format")] = "json",
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    cursor: str | None = None,
) -> Any:
    """The exception report. JSON is cursor-paginated; `format=csv` streams every matching row
    with a header row and spreadsheet-formula escaping."""
    if export == "json":
        with ctx.session() as s:
            return service.list_exceptions(
                s,
                ctx.tenant_id,
                batch_id,
                severity=severity,
                status=status,
                limit=limit,
                cursor=cursor,
            )
    with ctx.session() as s:
        service.get_batch(s, ctx.tenant_id, batch_id)  # 404 before any byte is sent

    def lines() -> Iterator[str]:
        rows = service.exceptions_csv_rows(
            service.iter_exception_pages(
                ctx.session, ctx.tenant_id, batch_id, severity=severity, status=status
            )
        )
        for row in rows:
            buffer = io.StringIO()
            csv.writer(buffer).writerow(row)
            yield buffer.getvalue()

    return StreamingResponse(
        lines(),
        media_type="text/csv; charset=utf-8",
        headers={
            "content-disposition": f'attachment; filename="exceptions-{batch_id}.csv"',
            "cache-control": "no-store",
            "x-content-type-options": "nosniff",
        },
    )


@router.post("/{batch_id}/retry", response_model=ImportBatchCreated, status_code=202)
def retry_import_batch(
    batch_id: UUID,
    request: Request,
    response: Response,
    ctx: Annotated[TenantContext, Depends(require("imports:write"))],
    clock: Annotated[Clock, Depends(get_clock)],
    enqueue: Annotated[Enqueuer, Depends(get_enqueuer)],
    if_match: Annotated[str | None, Header()] = None,
) -> ImportBatchCreated:
    """Retry a failed batch (409 for any other status). A failed batch is final, so this makes
    a new batch for the same stored file and queues it; the old one stays as history."""
    expected = parse_if_match(if_match)
    with ctx.session() as s:
        created = service.retry_batch(
            s,
            tenant_id=ctx.tenant_id,
            batch_id=batch_id,
            expected_version=expected,
            actor=service.Actor("user", ctx.user.user_id),
            now=clock.now(),
        )
    safe_enqueue(enqueue, ctx.tenant_id, created.id)
    base = request.url.path.rsplit("/", 2)[0]
    response.headers["ETag"] = etag(created.row_version)
    response.headers["Location"] = f"{base}/{created.id}"
    return created
