"""Request-scoped tenant context: verify the user, check membership, then set the tenant.

Order matters (docs/API_SPEC.md section 1): the token is verified first, membership second,
and only then does a session carry `app.tenant_id`. Another tenant's id looks like it does not
exist (404). Privileged roles need an aal2 token; sensitive routes need a recent login.
"""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.auth import (
    AuthenticatedUser,
    JwksKeyResolver,
    JwtVerifier,
    require_mfa_for_roles,
    require_recent_auth,
)
from app.core.clock import Clock, get_clock
from app.core.config import Settings, get_settings
from app.core.db import get_engine, tenant_session
from app.core.errors import AuthenticationError, NotPermittedError, TenantMismatchError
from app.core.logging import bind_context
from app.core.permissions import ROLE_PERMISSIONS, mfa_required, permissions_for


@lru_cache
def get_verifier() -> JwtVerifier:
    settings = get_settings()
    if not settings.supabase_url:
        raise RuntimeError("SUPABASE_URL is not set")
    base = settings.supabase_url.rstrip("/") + "/auth/v1"
    return JwtVerifier(
        resolver=JwksKeyResolver(f"{base}/.well-known/jwks.json"),
        issuer=base,
        audience=settings.supabase_jwt_audience,
        shared_secret=settings.supabase_jwt_secret,
    )


def get_current_user(
    verifier: Annotated[JwtVerifier, Depends(get_verifier)],
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("Send the access token as 'Authorization: Bearer <token>'")
    return verifier.verify(authorization[7:].strip())


def get_engine_dep() -> Engine:
    return get_engine()


@dataclass(frozen=True)
class TenantContext:
    user: AuthenticatedUser
    tenant_id: UUID
    roles: tuple[str, ...]
    permissions: frozenset[str]
    engine: Engine

    def session(self) -> AbstractContextManager[Session]:
        """A transaction scoped to this tenant and user (row-level security applies)."""
        return tenant_session(self.engine, tenant_id=self.tenant_id, user_id=self.user.user_id)


def tenant_context(
    tenant_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    engine: Annotated[Engine, Depends(get_engine_dep)],
) -> TenantContext:
    # Membership is looked up with no tenant set: the user can only see their own rows.
    with tenant_session(engine, tenant_id=None, user_id=user.user_id) as s:
        row = s.execute(
            text(
                "select m.roles, u.status as user_status from cbam.memberships m"
                " join cbam.users u on u.id = m.user_id"
                " where m.tenant_id = :t and m.user_id = :u"
            ),
            {"t": tenant_id, "u": user.user_id},
        ).one_or_none()
    if row is None:
        raise TenantMismatchError()
    if row.user_status != "active":
        raise NotPermittedError("This account is disabled")
    roles = tuple(row.roles)
    require_mfa_for_roles(user, roles)
    with tenant_session(engine, tenant_id=tenant_id, user_id=user.user_id) as s:
        tenant_status = s.execute(text("select status from cbam.tenants")).scalar_one_or_none()
    if tenant_status != "active":
        raise NotPermittedError("This client account is not active")
    bind_context(tenant_id=str(tenant_id), user_id=str(user.user_id))
    return TenantContext(
        user=user,
        tenant_id=tenant_id,
        roles=roles,
        permissions=permissions_for(roles),
        engine=engine,
    )


def require(permission: str, *, recent_auth: bool = False) -> Callable[..., TenantContext]:
    """Route dependency: the caller needs `permission` in this tenant.

    `recent_auth=True` also demands a login within the configured window (sensitive actions).
    """

    def dependency(
        ctx: Annotated[TenantContext, Depends(tenant_context)],
        clock: Annotated[Clock, Depends(get_clock)],
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> TenantContext:
        if permission not in ctx.permissions:
            raise NotPermittedError(f"Missing permission {permission}")
        if recent_auth:
            require_recent_auth(
                ctx.user,
                now=clock.now(),
                max_age=timedelta(minutes=settings.recent_auth_minutes),
            )
        return ctx

    return dependency


@dataclass(frozen=True)
class PlatformContext:
    user: AuthenticatedUser
    permissions: frozenset[str]
    engine: Engine

    def session(self) -> AbstractContextManager[Session]:
        """Platform mode: tenants, users and memberships only; business tables stay closed."""
        return tenant_session(self.engine, tenant_id=None, user_id=self.user.user_id, platform=True)


def require_platform(
    permission: str, *, recent_auth: bool = False
) -> Callable[..., PlatformContext]:
    def dependency(
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
        engine: Annotated[Engine, Depends(get_engine_dep)],
        clock: Annotated[Clock, Depends(get_clock)],
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> PlatformContext:
        with tenant_session(engine, tenant_id=None, user_id=user.user_id) as s:
            is_admin = s.execute(
                text("select 1 from cbam.platform_admins where user_id = :u"), {"u": user.user_id}
            ).scalar_one_or_none()
        if is_admin is None:
            raise NotPermittedError("Platform administrators only")
        require_mfa_for_roles(user, ["platform_admin"])
        perms = ROLE_PERMISSIONS["platform_admin"]
        if permission not in perms:
            raise NotPermittedError(f"Missing permission {permission}")
        if recent_auth:
            require_recent_auth(
                user, now=clock.now(), max_age=timedelta(minutes=settings.recent_auth_minutes)
            )
        bind_context(user_id=str(user.user_id))
        return PlatformContext(user=user, permissions=perms, engine=engine)

    return dependency


def iter_roles_needing_mfa(roles: tuple[str, ...]) -> Iterator[str]:
    """Roles in `roles` that require MFA; used by /me to explain why."""
    return (r for r in roles if mfa_required([r]))
