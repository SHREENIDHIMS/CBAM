"""Customs-data coverage routes (R1-054): the EORIs to cover, the calendar, and the scan."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response

from app.core.clock import Clock, get_clock
from app.core.tenancy import TenantContext, require
from app.core.versioning import etag, parse_if_match
from app.modules.coverage import service
from app.modules.coverage.schemas import (
    EORI_PATTERN,
    CalendarOut,
    EoriIn,
    EoriOut,
    EoriPatch,
    ReportType,
    ScanOut,
)
from app.modules.tasks.service import Actor

router = APIRouter(prefix="/tenants/{tenant_id}/customs-data", tags=["customs-data"])


@router.get("/coverage", response_model=CalendarOut)
def get_coverage(
    ctx: Annotated[TenantContext, Depends(require("imports:read"))],
    clock: Annotated[Clock, Depends(get_clock)],
    eori: Annotated[str, Query(pattern=EORI_PATTERN)],
    report_type: ReportType = "import_item",
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> CalendarOut:
    with ctx.session() as s:
        return service.calendar_for(
            s,
            tenant_id=ctx.tenant_id,
            today=clock.today_uk(),
            eori=eori,
            report_type=report_type,
            range_from=from_,
            range_to=to,
        )


@router.get("/eoris", response_model=list[EoriOut])
def list_eoris(ctx: Annotated[TenantContext, Depends(require("imports:read"))]) -> list[EoriOut]:
    with ctx.session() as s:
        return service.list_eoris(s, ctx.tenant_id)


@router.post("/eoris", response_model=EoriOut, status_code=201)
def register_eori(
    body: EoriIn,
    response: Response,
    ctx: Annotated[TenantContext, Depends(require("imports:write"))],
    clock: Annotated[Clock, Depends(get_clock)],
) -> EoriOut:
    with ctx.session() as s:
        out = service.register_eori(
            s,
            tenant_id=ctx.tenant_id,
            actor=Actor("user", ctx.user.user_id),
            now=clock.now(),
            today=clock.today_uk(),
            body=body,
        )
    response.headers["ETag"] = etag(out.row_version)
    return out


@router.patch("/eoris/{eori_id}", response_model=EoriOut)
def update_eori(
    eori_id: UUID,
    body: EoriPatch,
    response: Response,
    ctx: Annotated[TenantContext, Depends(require("imports:write"))],
    clock: Annotated[Clock, Depends(get_clock)],
    if_match: Annotated[str | None, Header()] = None,
) -> EoriOut:
    expected = parse_if_match(if_match)
    with ctx.session() as s:
        out = service.update_eori(
            s,
            tenant_id=ctx.tenant_id,
            eori_id=eori_id,
            expected_version=expected,
            actor=Actor("user", ctx.user.user_id),
            now=clock.now(),
            today=clock.today_uk(),
            body=body,
        )
    response.headers["ETag"] = etag(out.row_version)
    return out


@router.post("/coverage/scan", response_model=ScanOut)
def scan_coverage(
    ctx: Annotated[TenantContext, Depends(require("imports:write"))],
    clock: Annotated[Clock, Depends(get_clock)],
) -> ScanOut:
    """Create the gap and monthly tasks the calendars call for. Repeating it creates nothing
    new; the nightly job does the same for every client."""
    with ctx.session() as s:
        return service.scan(
            s,
            tenant_id=ctx.tenant_id,
            actor=Actor("user", ctx.user.user_id),
            now=clock.now(),
            today=clock.today_uk(),
        )
