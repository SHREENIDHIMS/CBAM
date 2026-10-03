"""R1-001: a platform admin creates clients, invites people and assigns roles."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.cli.bootstrap_platform_admin import bootstrap
from app.core.audit import verify_chain
from app.core.db import tenant_session
from app.core.ids import uuid7
from app.core.supabase_admin import get_auth_admin
from app.core.tenancy import get_engine_dep, get_verifier
from app.main import create_app
from tests.helpers_auth import bearer, verifier
from tests.integration.conftest import make_member, make_tenant, make_user

NOW = datetime(2027, 3, 1, 9, 0, tzinfo=UTC)
P = "/api/v1/platform"


def _mail(tag: str) -> str:
    """A unique address per call: the test database persists between runs."""
    return f"{tag}-{uuid7().hex[:12]}@example.test"


class FakeAuthAdmin:
    def __init__(self) -> None:
        self.invited: list[str] = []
        self.ids: dict[str, UUID] = {}

    def invite(self, email: str, *, redirect_to: str | None) -> UUID:
        self.invited.append(email)
        self.redirect_to = redirect_to
        return self.ids.setdefault(email, uuid7())


@pytest.fixture
def fake_admin() -> FakeAuthAdmin:
    return FakeAuthAdmin()


@pytest.fixture
def client(app_engine: Engine, fake_admin: FakeAuthAdmin) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_verifier] = verifier
    app.dependency_overrides[get_engine_dep] = lambda: app_engine
    app.dependency_overrides[get_auth_admin] = lambda: fake_admin
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin(app_engine: Engine) -> UUID:
    uid = make_user(app_engine)
    with tenant_session(app_engine, tenant_id=None, platform=True) as s:
        s.execute(text("insert into cbam.platform_admins (user_id) values (:u)"), {"u": uid})
    return uid


def _h(user: UUID, **kw: object) -> dict[str, str]:
    return bearer(user, aal="aal2", **kw)  # type: ignore[arg-type]


def test_only_platform_admins_reach_the_platform_api(
    client: TestClient, app_engine: Engine, admin: UUID
) -> None:
    t = make_tenant(app_engine)
    ops = make_user(app_engine)
    make_member(app_engine, t, ops, "operations")
    assert client.get(f"{P}/tenants", headers=_h(ops)).status_code == 403
    assert client.get(f"{P}/tenants").status_code == 401
    assert client.get(f"{P}/tenants", headers=bearer(admin, aal="aal1")).status_code == 403
    assert client.get(f"{P}/tenants", headers=_h(admin)).status_code == 200


def test_create_and_list_tenants_with_audit(
    client: TestClient, app_engine: Engine, admin: UUID
) -> None:
    r = client.post(f"{P}/tenants", json={"name": "  Gamma Imports Ltd "}, headers=_h(admin))
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Gamma Imports Ltd"
    assert body["status"] == "active"
    assert body["row_version"] == 1
    assert r.headers["etag"] == '"1"'
    names = [t["name"] for t in client.get(f"{P}/tenants", headers=_h(admin)).json()]
    assert "Gamma Imports Ltd" in names
    with tenant_session(app_engine, tenant_id=None, platform=True) as s:
        row = s.execute(
            text(
                "select action, actor_id, object_id from cbam.audit_events"
                " where tenant_id is null and action = 'tenant.created' order by chain_seq desc limit 1"
            )
        ).one()
        assert row.actor_id == admin
        assert str(row.object_id) == body["id"]
        assert verify_chain(s, None).ok


def test_blank_name_and_unknown_fields_are_422(client: TestClient, admin: UUID) -> None:
    assert client.post(f"{P}/tenants", json={"name": "   "}, headers=_h(admin)).status_code == 422
    assert (
        client.post(
            f"{P}/tenants", json={"name": "x", "status": "closed"}, headers=_h(admin)
        ).status_code
        == 422
    )


def test_sensitive_actions_need_a_recent_login(client: TestClient, admin: UUID) -> None:
    stale = client.post(
        f"{P}/tenants", json={"name": "Late"}, headers=_h(admin, login_age_s=2 * 3600)
    )
    assert stale.status_code == 403
    assert stale.json()["type"].endswith("/recent-auth-required")
    # Reading does not need a recent login.
    assert client.get(f"{P}/tenants", headers=_h(admin, login_age_s=2 * 3600)).status_code == 200


def test_suspend_and_reactivate_with_reason_and_version(
    client: TestClient, app_engine: Engine, admin: UUID
) -> None:
    t = make_tenant(app_engine, "Delta")
    url = f"{P}/tenants/{t}"
    no_reason = client.patch(
        url, json={"status": "suspended"}, headers={**_h(admin), "If-Match": '"1"'}
    )
    assert no_reason.status_code == 422
    ok = client.patch(
        url,
        json={"status": "suspended", "reason": "unpaid"},
        headers={**_h(admin), "If-Match": '"1"'},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "suspended"
    assert ok.json()["row_version"] == 2
    stale = client.patch(
        url, json={"status": "active", "reason": "paid"}, headers={**_h(admin), "If-Match": '"1"'}
    )
    assert stale.status_code == 409
    assert (
        client.patch(
            url, json={"status": "active", "reason": "paid"}, headers=_h(admin)
        ).status_code
        == 428
    )


def test_a_closed_tenant_cannot_be_reopened(
    client: TestClient, app_engine: Engine, admin: UUID
) -> None:
    t = make_tenant(app_engine, "Epsilon")
    url = f"{P}/tenants/{t}"
    closed = client.patch(
        url, json={"status": "closed", "reason": "left"}, headers={**_h(admin), "If-Match": '"1"'}
    )
    assert closed.status_code == 200
    reopen = client.patch(
        url,
        json={"status": "active", "reason": "mistake"},
        headers={**_h(admin), "If-Match": '"2"'},
    )
    assert reopen.status_code == 409
    assert reopen.json()["rule_id"] == "R1-001.tenant_status"


def test_invite_creates_user_and_membership(
    client: TestClient, app_engine: Engine, admin: UUID, fake_admin: FakeAuthAdmin
) -> None:
    t = make_tenant(app_engine, "Zeta")
    mail = _mail("new.person")
    r = client.post(
        f"{P}/tenants/{t}/invitations",
        json={
            "email": f" {mail.upper()} ",
            "roles": ["operations", "operations"],
            "display_name": "New Person",
        },
        headers=_h(admin),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == mail
    assert body["roles"] == ["operations"]
    assert fake_admin.invited == [mail]
    assert fake_admin.redirect_to == "http://localhost:5173/reset-password/update"
    members = client.get(f"{P}/tenants/{t}/members", headers=_h(admin)).json()
    assert [m["email"] for m in members] == [mail]
    # The invited person can now see exactly that client.
    token = bearer(UUID(body["user_id"]), aal="aal2")
    me = client.get("/api/v1/me", headers=token).json()
    assert [m["tenant_name"] for m in me["memberships"]] == ["Zeta"]


def test_invite_refuses_bad_input(
    client: TestClient, app_engine: Engine, admin: UUID, fake_admin: FakeAuthAdmin
) -> None:
    t = make_tenant(app_engine, "Eta")
    url = f"{P}/tenants/{t}/invitations"
    for payload in (
        {"email": "not-an-email", "roles": ["operations"]},
        {"email": "a@example.test", "roles": []},
        {"email": "a@example.test", "roles": ["platform_admin"]},
        {"email": "a@example.test", "roles": ["superuser"]},
    ):
        assert client.post(url, json=payload, headers=_h(admin)).status_code == 422, payload
    assert fake_admin.invited == []


def test_invite_twice_is_refused_and_suspended_tenants_cannot_invite(
    client: TestClient, app_engine: Engine, admin: UUID
) -> None:
    t = make_tenant(app_engine, "Theta")
    url = f"{P}/tenants/{t}/invitations"
    payload = {"email": _mail("dup"), "roles": ["reviewer"]}
    assert client.post(url, json=payload, headers=_h(admin)).status_code == 201
    again = client.post(url, json=payload, headers=_h(admin))
    assert again.status_code == 422
    assert "already a member" in again.json()["detail"]
    client.patch(
        f"{P}/tenants/{t}",
        json={"status": "suspended", "reason": "x"},
        headers={**_h(admin), "If-Match": '"1"'},
    )
    blocked = client.post(
        url, json={"email": _mail("late"), "roles": ["reviewer"]}, headers=_h(admin)
    )
    assert blocked.status_code == 409


def test_an_existing_user_is_not_invited_again_and_can_join_several_tenants(
    client: TestClient, app_engine: Engine, admin: UUID, fake_admin: FakeAuthAdmin
) -> None:
    a, b = make_tenant(app_engine, "Iota"), make_tenant(app_engine, "Kappa")
    mail = _mail("shared")
    payload = {"email": mail, "roles": ["client_admin"]}
    first = client.post(f"{P}/tenants/{a}/invitations", json=payload, headers=_h(admin)).json()
    second = client.post(f"{P}/tenants/{b}/invitations", json=payload, headers=_h(admin)).json()
    assert first["user_id"] == second["user_id"]
    assert fake_admin.invited == [mail]


def test_change_roles_with_version_and_audit(
    client: TestClient, app_engine: Engine, admin: UUID
) -> None:
    t = make_tenant(app_engine, "Lambda")
    member = client.post(
        f"{P}/tenants/{t}/invitations",
        json={"email": _mail("r"), "roles": ["reviewer"]},
        headers=_h(admin),
    ).json()
    url = f"{P}/tenants/{t}/members/{member['user_id']}"
    changed = client.patch(
        url,
        json={"roles": ["approver", "reviewer"]},
        headers={**_h(admin), "If-Match": f'"{member["row_version"]}"'},
    )
    assert changed.status_code == 200
    assert changed.json()["roles"] == ["approver", "reviewer"]
    assert changed.json()["row_version"] == member["row_version"] + 1
    stale = client.patch(
        url,
        json={"roles": ["operations"]},
        headers={**_h(admin), "If-Match": f'"{member["row_version"]}"'},
    )
    assert stale.status_code == 409
    bad = client.patch(
        url, json={"roles": ["platform_admin"]}, headers={**_h(admin), "If-Match": '"2"'}
    )
    assert bad.status_code == 422
    same = client.patch(
        url, json={"roles": ["approver", "reviewer"]}, headers={**_h(admin), "If-Match": '"2"'}
    )
    assert same.status_code == 422
    with tenant_session(app_engine, tenant_id=None, platform=True) as s:
        actions = (
            s.execute(
                text(
                    "select action from cbam.audit_events where tenant_id is null and object_type = 'membership' and action like 'membership.%' and after->>'tenant_id' = :t order by chain_seq"
                ),
                {"t": str(t)},
            )
            .scalars()
            .all()
        )
        assert actions == ["membership.invited", "membership.roles_changed"]


def test_remove_member_and_unknown_member(
    client: TestClient, app_engine: Engine, admin: UUID
) -> None:
    t = make_tenant(app_engine, "Mu")
    member = client.post(
        f"{P}/tenants/{t}/invitations",
        json={"email": _mail("gone"), "roles": ["tax_agent"]},
        headers=_h(admin),
    ).json()
    assert (
        client.delete(f"{P}/tenants/{t}/members/{member['user_id']}", headers=_h(admin)).status_code
        == 204
    )
    assert client.get(f"{P}/tenants/{t}/members", headers=_h(admin)).json() == []
    assert (
        client.delete(f"{P}/tenants/{t}/members/{member['user_id']}", headers=_h(admin)).status_code
        == 404
    )
    assert client.get(f"{P}/tenants/{uuid7()}/members", headers=_h(admin)).status_code == 404


def test_a_tenant_admin_cannot_use_the_platform_api(client: TestClient, app_engine: Engine) -> None:
    t = make_tenant(app_engine, "Nu")
    boss = make_user(app_engine)
    make_member(app_engine, t, boss, "client_admin")
    assert client.post(f"{P}/tenants", json={"name": "Mine"}, headers=_h(boss)).status_code == 403
    assert (
        client.post(
            f"{P}/tenants/{t}/invitations",
            json={"email": "x@example.test", "roles": ["reviewer"]},
            headers=_h(boss),
        ).status_code
        == 403
    )


def test_missing_supabase_configuration_is_503(app_engine: Engine, admin: UUID) -> None:
    app = create_app()
    app.dependency_overrides[get_verifier] = verifier
    app.dependency_overrides[get_engine_dep] = lambda: app_engine
    with TestClient(app) as c:
        t = make_tenant(app_engine, "Xi")
        r = c.post(
            f"{P}/tenants/{t}/invitations",
            json={"email": "x@example.test", "roles": ["reviewer"]},
            headers=_h(admin),
        )
    assert r.status_code == 503


def test_bootstrap_creates_the_first_platform_admin_once(
    app_engine: Engine, admin_engine: Engine
) -> None:
    uid = uuid7()
    mail = f"first-{uid.hex}@example.test"
    assert bootstrap(admin_engine, user_id=uid, email=mail.upper(), now=NOW) is True
    assert bootstrap(admin_engine, user_id=uid, email=mail, now=NOW) is False
    with tenant_session(app_engine, tenant_id=None, user_id=uid) as s:
        assert (
            s.execute(
                text("select count(*) from cbam.platform_admins where user_id = :u"), {"u": uid}
            ).scalar_one()
            == 1
        )
    with tenant_session(app_engine, tenant_id=None, platform=True) as s:
        n = s.execute(
            text(
                "select count(*) from cbam.audit_events where tenant_id is null and action = 'platform_admin.bootstrapped' and object_id = :u"
            ),
            {"u": uid},
        ).scalar_one()
        assert n == 1
        assert verify_chain(s, None).ok


def test_bootstrap_command_reports_conflicts_without_a_stack_trace(
    admin_engine: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.cli.bootstrap_platform_admin import main
    from tests.integration.conftest import TEST_URL

    assert TEST_URL
    monkeypatch.setenv("MIGRATIONS_DATABASE_URL", TEST_URL)
    mail = f"cli-{uuid7().hex}@example.test"
    assert main(["--user-id", str(uuid7()), "--email", mail]) == 0
    assert "platform admin created" in capsys.readouterr().out
    assert main(["--user-id", str(uuid7()), "--email", mail]) == 1
    assert "different user id" in capsys.readouterr().err
    assert main(["--user-id", str(uuid7()), "--email", "nonsense"]) == 2
    monkeypatch.delenv("MIGRATIONS_DATABASE_URL")
    assert main(["--user-id", str(uuid7()), "--email", mail]) == 2
