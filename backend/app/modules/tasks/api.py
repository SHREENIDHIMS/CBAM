from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response

from app.core.clock import Clock, get_clock
from app.core.tenancy import TenantContext, require
from app.core.versioning import etag, parse_if_match
from app.modules.tasks import service
from app.modules.tasks.schemas import TaskEventOut, TaskOut, TaskPage, TaskPatch
from app.modules.tasks.service import Actor

router = APIRouter(prefix="/tenants/{tenant_id}/tasks", tags=["tasks"])


@router.get("", response_model=TaskPage)
def list_tasks(
    ctx: Annotated[TenantContext, Depends(require("tasks:read"))],
    status: str | None = None,
    owner_id: UUID | None = None,
    due_before: date | None = None,
    sort: Literal["due_date", "-due_date"] = "due_date",
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    cursor: str | None = None,
) -> TaskPage:
    with ctx.session() as s:
        return service.list_tasks(
            s,
            status=status,
            owner_id=owner_id,
            due_before=due_before,
            sort=sort,
            limit=limit,
            cursor=cursor,
        )


@router.get("/{task_id}", response_model=TaskOut)
def get_task(
    task_id: UUID,
    response: Response,
    ctx: Annotated[TenantContext, Depends(require("tasks:read"))],
) -> TaskOut:
    with ctx.session() as s:
        task = service.get_task(s, task_id)
    response.headers["ETag"] = etag(task.row_version)
    return task


@router.get("/{task_id}/history", response_model=list[TaskEventOut])
def task_history(
    task_id: UUID, ctx: Annotated[TenantContext, Depends(require("tasks:read"))]
) -> list[TaskEventOut]:
    with ctx.session() as s:
        service.get_task(s, task_id)  # 404 if it is not this tenant's task
        return service.task_history(s, task_id)


@router.patch("/{task_id}", response_model=TaskOut)
def patch_task(
    task_id: UUID,
    body: TaskPatch,
    response: Response,
    ctx: Annotated[TenantContext, Depends(require("tasks:write"))],
    clock: Annotated[Clock, Depends(get_clock)],
    if_match: Annotated[str | None, Header()] = None,
) -> TaskOut:
    expected = parse_if_match(if_match)
    sent = body.model_fields_set
    with ctx.session() as s:
        task = service.update_task(
            s,
            tenant_id=ctx.tenant_id,
            task_id=task_id,
            expected_version=expected,
            actor=Actor("user", ctx.user.user_id),
            now=clock.now(),
            status=body.status,
            owner_id=body.owner_id if "owner_id" in sent else service.UNSET,
            due_date=body.due_date if "due_date" in sent else service.UNSET,
            reason=body.reason,
        )
    response.headers["ETag"] = etag(task.row_version)
    return task
