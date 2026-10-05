"""Import ledger routes (R1-005): normalised lines and declarations with their lineage."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.tenancy import TenantContext, require
from app.modules.imports import ledger
from app.modules.imports.schemas import (
    DeclarationOut,
    EntryMethod,
    ImportLineDetail,
    ImportLinePage,
)

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["import-ledger"])


@router.get("/import-lines", response_model=ImportLinePage)
def list_import_lines(
    ctx: Annotated[TenantContext, Depends(require("imports:read"))],
    commodity_code: Annotated[str | None, Query(description="Code prefix, 1 to 10 digits")] = None,
    origin: str | None = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    batch_id: UUID | None = None,
    entry_method: EntryMethod | None = None,
    has_open_exceptions: bool | None = None,
    include_superseded: bool = False,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    cursor: str | None = None,
) -> ImportLinePage:
    """Current versions by default. `from`/`to` filter the acceptance date as reported (it is
    not a tax point)."""
    with ctx.session() as s:
        return ledger.list_lines(
            s,
            ctx.tenant_id,
            commodity_code=commodity_code,
            origin=origin,
            date_from=date_from,
            date_to=date_to,
            batch_id=batch_id,
            entry_method=entry_method,
            has_open_exceptions=has_open_exceptions,
            include_superseded=include_superseded,
            limit=limit,
            cursor=cursor,
        )


@router.get("/import-lines/{line_id}", response_model=ImportLineDetail)
def get_import_line(
    line_id: UUID, ctx: Annotated[TenantContext, Depends(require("imports:read"))]
) -> ImportLineDetail:
    with ctx.session() as s:
        return ledger.get_line(s, ctx.tenant_id, line_id)


@router.get("/declarations/{declaration_id}", response_model=DeclarationOut)
def get_declaration(
    declaration_id: UUID, ctx: Annotated[TenantContext, Depends(require("imports:read"))]
) -> DeclarationOut:
    with ctx.session() as s:
        return ledger.get_declaration(s, ctx.tenant_id, declaration_id)
