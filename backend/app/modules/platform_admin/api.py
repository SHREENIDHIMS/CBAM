from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status

from app.core.clock import Clock, get_clock
from app.core.config import Settings, get_settings
from app.core.supabase_admin import AuthAdmin, get_auth_admin
from app.core.tenancy import PlatformContext, require_platform
from app.core.versioning import etag, parse_if_match
from app.modules.platform_admin import service
from app.modules.platform_admin.schemas import (
    InviteIn,
    MemberOut,
    RolesPatch,
    TenantCreate,
    TenantOut,
    TenantPatch,
)
from app.modules.platform_admin.service import Admin

router = APIRouter(prefix="/platform", tags=["platform"])

Tenants = Annotated[PlatformContext, Depends(require_platform("platform:tenants_manage"))]
TenantsSensitive = Annotated[
    PlatformContext, Depends(require_platform("platform:tenants_manage", recent_auth=True))
]
Users = Annotated[PlatformContext, Depends(require_platform("platform:users_manage"))]
UsersSensitive = Annotated[
    PlatformContext, Depends(require_platform("platform:users_manage", recent_auth=True))
]
Now = Annotated[Clock, Depends(get_clock)]


@router.get("/tenants", response_model=list[TenantOut])
def list_tenants(ctx: Tenants) -> list[TenantOut]:
    with ctx.session() as s:
        return service.list_tenants(s)


@router.post("/tenants", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
def create_tenant(
    body: TenantCreate, response: Response, ctx: TenantsSensitive, clock: Now
) -> TenantOut:
    with ctx.session() as s:
        tenant = service.create_tenant(s, Admin(ctx.user.user_id), clock.now(), body.name)
    response.headers["ETag"] = etag(tenant.row_version)
    return tenant


@router.patch("/tenants/{tenant_id}", response_model=TenantOut)
def change_tenant_status(
    tenant_id: UUID,
    body: TenantPatch,
    response: Response,
    ctx: TenantsSensitive,
    clock: Now,
    if_match: Annotated[str | None, Header()] = None,
) -> TenantOut:
    expected = parse_if_match(if_match)
    with ctx.session() as s:
        tenant = service.change_tenant_status(
            s,
            Admin(ctx.user.user_id),
            clock.now(),
            tenant_id,
            expected_version=expected,
            status=body.status,
            reason=body.reason,
        )
    response.headers["ETag"] = etag(tenant.row_version)
    return tenant


@router.get("/tenants/{tenant_id}/members", response_model=list[MemberOut])
def list_members(tenant_id: UUID, ctx: Users) -> list[MemberOut]:
    with ctx.session() as s:
        return service.list_members(s, tenant_id)


@router.post(
    "/tenants/{tenant_id}/invitations",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
)
def invite_member(
    tenant_id: UUID,
    body: InviteIn,
    response: Response,
    ctx: UsersSensitive,
    clock: Now,
    auth_admin: Annotated[AuthAdmin, Depends(get_auth_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MemberOut:
    redirect = f"{settings.frontend_base_url.rstrip('/')}/reset-password/update"
    with ctx.session() as s:
        member = service.invite_member(
            s,
            Admin(ctx.user.user_id),
            auth_admin,
            clock.now(),
            tenant_id,
            email=body.email,
            roles=body.roles,
            display_name=body.display_name,
            redirect_to=redirect,
        )
    response.headers["ETag"] = etag(member.row_version)
    return member


@router.patch("/tenants/{tenant_id}/members/{user_id}", response_model=MemberOut)
def set_member_roles(
    tenant_id: UUID,
    user_id: UUID,
    body: RolesPatch,
    response: Response,
    ctx: UsersSensitive,
    clock: Now,
    if_match: Annotated[str | None, Header()] = None,
) -> MemberOut:
    expected = parse_if_match(if_match)
    with ctx.session() as s:
        member = service.set_member_roles(
            s,
            Admin(ctx.user.user_id),
            clock.now(),
            tenant_id,
            user_id,
            expected_version=expected,
            roles=body.roles,
        )
    response.headers["ETag"] = etag(member.row_version)
    return member


@router.delete("/tenants/{tenant_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(tenant_id: UUID, user_id: UUID, ctx: UsersSensitive, clock: Now) -> Response:
    with ctx.session() as s:
        service.remove_member(s, Admin(ctx.user.user_id), clock.now(), tenant_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
