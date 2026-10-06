"""Routes for manual import entry (R1-004) and customs-value corrections (R1-010)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response

from app.core.clock import Clock, get_clock
from app.core.tenancy import TenantContext, require
from app.core.versioning import etag, parse_if_match
from app.modules.imports import corrections, manual
from app.modules.imports.manual_schemas import (
    ManualEntryIn,
    ManualEntryOut,
    ValueCorrectionIn,
    ValueCorrectionOut,
)
from app.modules.imports.service import Actor, check_idempotency_key

router = APIRouter(prefix="/tenants/{tenant_id}/import-lines", tags=["import-ledger"])


@router.post("/manual", response_model=ManualEntryOut, status_code=201)
def create_manual_entry(
    body: ManualEntryIn,
    response: Response,
    ctx: Annotated[TenantContext, Depends(require("imports:write"))],
    clock: Annotated[Clock, Depends(get_clock)],
    idempotency_key: Annotated[str | None, Header()] = None,
) -> ManualEntryOut:
    """Key one import line by hand, with a reason. It meets the same validation as a file row;
    an invalid entry is a 422 listing every problem and stores nothing. It never replaces a line
    that came from a file, nor one a correction or an earlier manual entry settled (409: use a
    correction). The same Idempotency-Key and entry replays the first answer with 200."""
    key = check_idempotency_key(idempotency_key)
    with ctx.session() as s:
        out = manual.create_manual_entry(
            s,
            tenant_id=ctx.tenant_id,
            actor=Actor("user", ctx.user.user_id),
            now=clock.now(),
            today=clock.today_uk(),
            entry=body,
            idempotency_key=key,
        )
    if out.replayed:
        response.status_code = 200
    return out


@router.post("/{line_id}/corrections", response_model=ValueCorrectionOut, status_code=201)
def correct_customs_value(
    line_id: UUID,
    body: ValueCorrectionIn,
    response: Response,
    ctx: Annotated[TenantContext, Depends(require("imports:correct"))],
    clock: Annotated[Clock, Depends(get_clock)],
    if_match: Annotated[str | None, Header()] = None,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> ValueCorrectionOut:
    """Correct the customs value of the current version of a line. The old version is kept and
    the new one links to it; a reason is required. `If-Match` carries the line version the user
    saw (a newer one is a 409). A tax agent cannot do this."""
    expected = parse_if_match(if_match)
    key = check_idempotency_key(idempotency_key)
    with ctx.session() as s:
        out = corrections.correct_value(
            s,
            tenant_id=ctx.tenant_id,
            line_id=line_id,
            actor=Actor("user", ctx.user.user_id),
            permissions=ctx.permissions,
            now=clock.now(),
            today=clock.today_uk(),
            body=body,
            expected_version=expected,
            idempotency_key=key,
        )
    if out.replayed:
        response.status_code = 200
    response.headers["ETag"] = etag(out.version)
    return out
