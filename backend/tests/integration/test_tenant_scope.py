"""R1-042 / R1-002: token -> membership -> MFA -> permission -> tenant-scoped session."""

from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.core.clock import get_clock  # noqa: F401 - re-exported for clarity in overrides
from app.core.db import tenant_session
from app.core.ids import uuid7
from app.core.logging import current_context
from app.core.tenancy import (
    PlatformContext,
    TenantContext,
    get_engine_dep,
    get_verifier,
    require,
    require_platform,
)
from app.main import create_app
from tests.helpers_auth import bearer, verifier
from tests.integration.conftest import make_tenant

T = "/api/v1/tenants"


def _user(engine: Engine, *, status: str = "active") -> UUID:
    uid = uuid7()
    with tenant_session(engine, tenant_id=None, platform=True) as s:
        s.execute(
            text("insert into cbam.users (id, email, status) values (:i, :e, :s)"),
            {"i": uid, "e": f"u-{uid.hex}@example.test", "s": status},
        )
    return uid


def _member(engine: Engine, tenant: UUID, user: UUID, *roles: str) -> None:
    with tenant_session(engine, tenant_id=tenant) as s:
        s.execute(
            text(
                "insert into cbam.memberships (id, user_id, tenant_id, roles)"
                " values (:i, :u, :t, cast(:r as text[]))"
            ),
            {"i": uuid7(), "u": user, "t": tenant, "r": list(roles)},
        )


def _platform_admin(engine: Engine, user: UUID) -> None:
    with tenant_session(engine, tenant_id=None, platform=True) as s:
        s.execute(text("insert into cbam.platform_admins (user_id) values (:u)"), {"u": user})


@pytest.fixture
def client(app_engine: Engine) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_verifier] = verifier
    app.dependency_overrides[get_engine_dep] = lambda: app_engine

    router = APIRouter(prefix="/api/v1")

    @router.get("/tenants/{tenant_id}/probe-read")
    def probe_read(
        ctx: Annotated[TenantContext, Depends(require("tenant:read"))],
    ) -> dict[str, object]:
        with ctx.session() as s:
            visible = s.execute(text("select count(*) from cbam.tenants")).scalar_one()
        return {"roles": list(ctx.roles), "tenants_visible": visible}

    @router.get("/tenants/{tenant_id}/probe-members")
    def probe_members(
        ctx: Annotated[TenantContext, Depends(require("tenant:members_manage"))],
    ) -> dict[str, str]:
        return {"ok": "yes"}

    @router.get("/tenants/{tenant_id}/probe-sensitive")
    def probe_sensitive(
        ctx: Annotated[TenantContext, Depends(require("tenant:members_manage", recent_auth=True))],
    ) -> dict[str, str]:
        return {"ok": "yes"}

    @router.get("/tenants/{tenant_id}/probe-log-context")
    def probe_log_context(
        ctx: Annotated[TenantContext, Depends(require("tenant:read"))],
    ) -> dict[str, object]:
        return current_context()

    @router.get("/platform/probe")
    def probe_platform(
        ctx: Annotated[PlatformContext, Depends(require_platform("platform:tenants_manage"))],
    ) -> dict[str, str]:
        return {"ok": "yes"}

    app.include_router(router)
    with TestClient(app) as c:
        yield c


def test_member_reaches_their_tenant_and_sees_only_it(
    client: TestClient, app_engine: Engine
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    user = _user(app_engine)
    _member(app_engine, a, user, "client_admin")
    r = client.get(f"{T}/{a}/probe-read", headers=bearer(user))
    assert r.status_code == 200
    assert r.json() == {"roles": ["client_admin"], "tenants_visible": 1}
    # The same user asking for a tenant they do not belong to gets "not found".
    r = client.get(f"{T}/{b}/probe-read", headers=bearer(user))
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")


def test_missing_or_bad_token_is_401(client: TestClient, app_engine: Engine) -> None:
    a = make_tenant(app_engine)
    r = client.get(f"{T}/{a}/probe-read")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert (
        client.get(f"{T}/{a}/probe-read", headers={"Authorization": "Bearer nonsense"}).status_code
        == 401
    )
    assert (
        client.get(f"{T}/{a}/probe-read", headers={"Authorization": "Basic abc"}).status_code == 401
    )


def test_privileged_role_without_mfa_is_refused_then_allowed_with_mfa(
    client: TestClient, app_engine: Engine
) -> None:
    """Phase 1 exit gate: a privileged role without MFA is refused (via the real API)."""
    a = make_tenant(app_engine)
    user = _user(app_engine)
    _member(app_engine, a, user, "operations")
    refused = client.get(f"{T}/{a}/probe-read", headers=bearer(user, aal="aal1"))
    assert refused.status_code == 403
    assert refused.json()["type"].endswith("/mfa-required")
    assert client.get(f"{T}/{a}/probe-read", headers=bearer(user, aal="aal2")).status_code == 200


def test_unprivileged_role_does_not_need_mfa(client: TestClient, app_engine: Engine) -> None:
    a = make_tenant(app_engine)
    user = _user(app_engine)
    _member(app_engine, a, user, "tax_agent")
    assert client.get(f"{T}/{a}/probe-read", headers=bearer(user)).status_code == 200


def test_permission_is_enforced_per_route(client: TestClient, app_engine: Engine) -> None:
    a = make_tenant(app_engine)
    agent, admin = _user(app_engine), _user(app_engine)
    _member(app_engine, a, agent, "tax_agent")
    _member(app_engine, a, admin, "client_admin")
    denied = client.get(f"{T}/{a}/probe-members", headers=bearer(agent))
    assert denied.status_code == 403
    assert denied.json()["type"].endswith("/not-permitted")
    assert client.get(f"{T}/{a}/probe-members", headers=bearer(admin)).status_code == 200


def test_sensitive_route_needs_a_recent_login(client: TestClient, app_engine: Engine) -> None:
    a = make_tenant(app_engine)
    user = _user(app_engine)
    _member(app_engine, a, user, "client_admin")
    ok = client.get(f"{T}/{a}/probe-sensitive", headers=bearer(user, login_age_s=60))
    assert ok.status_code == 200
    stale = client.get(f"{T}/{a}/probe-sensitive", headers=bearer(user, login_age_s=2 * 3600))
    assert stale.status_code == 403
    assert stale.json()["type"].endswith("/recent-auth-required")


def test_disabled_user_and_suspended_tenant_are_refused(
    client: TestClient, app_engine: Engine
) -> None:
    a = make_tenant(app_engine)
    disabled = _user(app_engine, status="disabled")
    _member(app_engine, a, disabled, "client_admin")
    assert client.get(f"{T}/{a}/probe-read", headers=bearer(disabled)).status_code == 403
    active = _user(app_engine)
    _member(app_engine, a, active, "client_admin")
    with tenant_session(app_engine, tenant_id=None, platform=True) as s:
        s.execute(text("update cbam.tenants set status = 'suspended' where id = :i"), {"i": a})
    assert client.get(f"{T}/{a}/probe-read", headers=bearer(active)).status_code == 403


def test_tenant_and_user_ids_are_bound_to_the_log_context(
    client: TestClient, app_engine: Engine
) -> None:
    a = make_tenant(app_engine)
    user = _user(app_engine)
    _member(app_engine, a, user, "client_admin")
    body = client.get(f"{T}/{a}/probe-log-context", headers=bearer(user)).json()
    assert body["tenant_id"] == str(a)
    assert body["user_id"] == str(user)
    assert "email" not in body


def test_me_lists_tenants_roles_permissions_and_mfa_state(
    client: TestClient, app_engine: Engine
) -> None:
    a, b = make_tenant(app_engine, "Alpha Ltd"), make_tenant(app_engine, "Beta Ltd")
    user = _user(app_engine)
    _member(app_engine, a, user, "client_admin")
    _member(app_engine, b, user, "approver")
    r = client.get("/api/v1/me", headers=bearer(user, aal="aal1"))
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == str(user)
    assert body["platform_admin"] is False
    assert body["mfa"] == {"required": True, "passed": False}
    by_name = {m["tenant_name"]: m for m in body["memberships"]}
    assert set(by_name) == {"Alpha Ltd", "Beta Ltd"}
    assert by_name["Alpha Ltd"]["roles"] == ["client_admin"]
    assert "registration:submit_as_liable_person" in by_name["Alpha Ltd"]["permissions"]
    assert by_name["Beta Ltd"]["mfa_required"] is True
    assert client.get("/api/v1/me").status_code == 401


def test_me_does_not_leak_other_users_memberships(client: TestClient, app_engine: Engine) -> None:
    a = make_tenant(app_engine)
    mine, theirs = _user(app_engine), _user(app_engine)
    _member(app_engine, a, theirs, "client_admin")
    assert client.get("/api/v1/me", headers=bearer(mine)).json()["memberships"] == []


def test_platform_routes_need_platform_admin_with_mfa(
    client: TestClient, app_engine: Engine
) -> None:
    ordinary, admin = _user(app_engine), _user(app_engine)
    _platform_admin(app_engine, admin)
    t = make_tenant(app_engine)
    _member(app_engine, t, ordinary, "client_admin")
    assert client.get("/api/v1/platform/probe", headers=bearer(ordinary)).status_code == 403
    no_mfa = client.get("/api/v1/platform/probe", headers=bearer(admin, aal="aal1"))
    assert no_mfa.status_code == 403
    assert no_mfa.json()["type"].endswith("/mfa-required")
    assert (
        client.get("/api/v1/platform/probe", headers=bearer(admin, aal="aal2")).status_code == 200
    )


def test_platform_admin_is_not_a_tenant_role(app_engine: Engine) -> None:
    """A tenant admin can never hand out the platform role (database constraint)."""
    a = make_tenant(app_engine)
    user = _user(app_engine)
    with pytest.raises(DBAPIError), tenant_session(app_engine, tenant_id=a) as s:
        s.execute(
            text(
                "insert into cbam.memberships (id, user_id, tenant_id, roles)"
                " values (:i, :u, :t, array['platform_admin'])"
            ),
            {"i": uuid7(), "u": user, "t": a},
        )


def test_only_platform_mode_can_grant_platform_admin(app_engine: Engine) -> None:
    a = make_tenant(app_engine)
    user = _user(app_engine)
    with pytest.raises(DBAPIError), tenant_session(app_engine, tenant_id=a, user_id=user) as s:
        s.execute(text("insert into cbam.platform_admins (user_id) values (:u)"), {"u": user})
