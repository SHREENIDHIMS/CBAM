"""Routes for manual import entry (R1-004) and customs-value corrections (R1-010)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.clock import Clock, get_clock
from app.core.tenancy import TenantContext, require
from app.modules.imports import corrections, manual
from app.modules.imports.manual_schemas import (
    ManualEntryIn,
    ManualEntryOut,
    ValueCorrectionIn,
    ValueCorrectionOut,
)
from app.modules.imports.service import Actor

router = APIRouter(prefix="/tenants/{tenant_id}/import-lines", tags=["import-ledger"])


@router.post("/manual", response_model=ManualEntryOut, status_code=201)
def create_manual_entry(
    body: ManualEntryIn,
    ctx: Annotated[TenantContext, Depends(require("imports:write"))],
    clock: Annotated[Clock, Depends(get_clock)],
) -> ManualEntryOut:
    """Key one import line by hand, with a reason. It meets the same validation as a file row;
    an invalid entry is a 422 listing every problem and stores nothing. It never replaces a line
    that a correction or an earlier manual entry settled (409)."""
    with ctx.session() as s:
        return manual.create_manual_entry(
            s,
            tenant_id=ctx.tenant_id,
            actor=Actor("user", ctx.user.user_id),
            now=clock.now(),
            today=clock.today_uk(),
            entry=body,
        )


@router.post("/{line_id}/corrections", response_model=ValueCorrectionOut, status_code=201)
def correct_customs_value(
    line_id: UUID,
    body: ValueCorrectionIn,
    ctx: Annotated[TenantContext, Depends(require("imports:correct"))],
    clock: Annotated[Clock, Depends(get_clock)],
) -> ValueCorrectionOut:
    """Correct the customs value of the current version of a line. The old version is kept and
    the new one links to it; a reason is required. A tax agent cannot do this."""
    with ctx.session() as s:
        return corrections.correct_value(
            s,
            tenant_id=ctx.tenant_id,
            line_id=line_id,
            actor=Actor("user", ctx.user.user_id),
            permissions=ctx.permissions,
            now=clock.now(),
            today=clock.today_uk(),
            body=body,
        )
