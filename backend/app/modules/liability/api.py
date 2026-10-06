"""Liable-person routes (R1-036): determine and read the decision for a declaration."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.clock import Clock, get_clock
from app.core.tenancy import TenantContext, require
from app.modules.liability import service
from app.modules.liability.schemas import LiablePersonHistory, LiablePersonOut
from app.modules.tasks.service import Actor

router = APIRouter(prefix="/tenants/{tenant_id}/declarations", tags=["liability"])


@router.post("/{declaration_id}/liable-person", response_model=LiablePersonOut)
def determine_liable_person(
    declaration_id: UUID,
    ctx: Annotated[TenantContext, Depends(require("imports:write"))],
    clock: Annotated[Clock, Depends(get_clock)],
) -> LiablePersonOut:
    """Work out who is liable for this declaration from the active liable-person rules. With no
    active rule, or facts no rule covers, the answer is `undetermined` and a review task asks a
    person; the platform never guesses. Repeating the call with nothing changed writes nothing."""
    with ctx.session() as s:
        return service.determine(
            s,
            tenant_id=ctx.tenant_id,
            declaration_id=declaration_id,
            actor=Actor("user", ctx.user.user_id),
            now=clock.now(),
        )


@router.get("/{declaration_id}/liable-person", response_model=LiablePersonHistory)
def get_liable_person(
    declaration_id: UUID, ctx: Annotated[TenantContext, Depends(require("imports:read"))]
) -> LiablePersonHistory:
    with ctx.session() as s:
        return service.get_current(s, ctx.tenant_id, declaration_id)
