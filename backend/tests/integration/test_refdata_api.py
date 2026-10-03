"""R1-050 reference-data API: who may read, prepare and activate (ADR-0003)."""

from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.db import tenant_session
from tests.helpers_auth import bearer
from tests.integration.conftest import make_member, make_tenant, make_user
from tests.integration.test_refdata import clean, load, make_owner  # noqa: F401
from tests.refdata_helpers import write_dataset

P = "/api/v1/platform"
ACTIVATE = {"reason": "Reviewed the impact report", "acknowledge_warnings": True}


def h(user: UUID, **kw: object) -> dict[str, str]:
    return bearer(user, aal="aal2", **kw)  # type: ignore[arg-type]


@pytest.fixture
def platform_admin(app_engine: Engine) -> UUID:
    uid = make_user(app_engine)
    with tenant_session(app_engine, tenant_id=None, platform=True) as s:
        s.execute(text("insert into cbam.platform_admins (user_id) values (:u)"), {"u": uid})
    return uid


def test_unauthenticated_and_ordinary_users_are_refused(
    client: TestClient, app_engine: Engine, platform_admin: UUID
) -> None:
    assert client.get(f"{P}/datasets").status_code == 401
    tenant = make_tenant(app_engine)
    for role in ("client_admin", "operations", "domain_owner"):
        user = make_user(app_engine)
        make_member(app_engine, tenant, user, role)
        assert client.get(f"{P}/datasets", headers=h(user)).status_code == 403, role
    # a client can hand out the domain_owner role in its own client; it never reaches global law
    assert client.get(f"{P}/datasets", headers=h(platform_admin)).status_code == 200


def test_privileged_readers_need_mfa(client: TestClient, platform_admin: UUID) -> None:
    assert (
        client.get(f"{P}/datasets", headers=bearer(platform_admin, aal="aal1")).status_code == 403
    )


def test_platform_admins_can_read_but_not_prepare_or_activate(
    client: TestClient, app_engine: Engine, platform_admin: UUID, tmp_path: Path
) -> None:
    load(app_engine, write_dataset(tmp_path))
    assert client.get(f"{P}/sources", headers=h(platform_admin)).status_code == 200
    assert client.get(
        f"{P}/datasets/cbam_commodity_codes/versions", headers=h(platform_admin)
    ).json()
    version = f"{P}/datasets/cbam_commodity_codes/versions/t.1"
    assert client.post(f"{version}/impact", headers=h(platform_admin)).status_code == 403
    activate = client.post(
        f"{version}/activate", headers={**h(platform_admin), "If-Match": '"1"'}, json=ACTIVATE
    )
    assert activate.status_code == 403
    status = client.post(
        f"{P}/sources/TEST-SOURCE/status",
        headers={**h(platform_admin), "If-Match": '"1"'},
        json={"status": "in_force", "reason": "x"},
    )
    assert status.status_code == 403


def test_a_domain_owner_activates_end_to_end(
    client: TestClient, app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, write_dataset(tmp_path))
    versions = client.get(f"{P}/datasets/cbam_commodity_codes/versions", headers=h(owner)).json()
    assert [(v["version"], v["status"], v["source_status"]) for v in versions] == [
        ("t.1", "pending", "laid")
    ]
    url = f"{P}/datasets/cbam_commodity_codes/versions/t.1"
    # no impact report yet
    pending = client.get(url, headers=h(owner))
    assert pending.headers["etag"] == '"1"' and pending.json()["impact_report"] is None
    blocked = client.post(f"{url}/activate", headers={**h(owner), "If-Match": '"1"'}, json=ACTIVATE)
    assert blocked.status_code == 409 and "impact report" in blocked.json()["detail"]
    # a missing If-Match is refused outright
    assert client.post(f"{url}/activate", headers=h(owner), json=ACTIVATE).status_code == 428

    report = client.post(f"{url}/impact", headers=h(owner))
    assert report.status_code == 200
    assert report.json()["rows"]["added"] == 3
    version = client.get(url, headers=h(owner))
    assert version.json()["has_impact_report"] is True
    stale = client.post(f"{url}/activate", headers={**h(owner), "If-Match": '"99"'}, json=ACTIVATE)
    assert stale.status_code == 409
    done = client.post(
        f"{url}/activate", headers={**h(owner), "If-Match": version.headers["etag"]}, json=ACTIVATE
    )
    assert done.status_code == 200 and done.json()["status"] == "active"
    assert done.json()["activated_by"] == str(owner)

    datasets = {d["name"]: d for d in client.get(f"{P}/datasets", headers=h(owner)).json()}
    assert datasets["cbam_commodity_codes"]["active_version"] == "t.1"


def test_activation_and_source_changes_need_a_recent_login(
    client: TestClient, app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, write_dataset(tmp_path))
    old = h(owner, login_age_s=16 * 60)
    version = f"{P}/datasets/cbam_commodity_codes/versions/t.1"
    activate = client.post(f"{version}/activate", headers={**old, "If-Match": '"1"'}, json=ACTIVATE)
    assert activate.status_code == 403
    source = client.post(
        f"{P}/sources/TEST-SOURCE/status",
        headers={**old, "If-Match": '"1"'},
        json={"status": "in_force", "reason": "x"},
    )
    assert source.status_code == 403


def test_a_domain_owner_sets_a_source_in_force_with_a_reason(
    client: TestClient, app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, write_dataset(tmp_path))
    url = f"{P}/sources/TEST-SOURCE"
    source = client.get(url, headers=h(owner))
    assert source.json()["status"] == "laid"
    no_reason = client.post(
        f"{url}/status",
        headers={**h(owner), "If-Match": source.headers["etag"]},
        json={"status": "in_force", "reason": ""},
    )
    assert no_reason.status_code == 422
    ok = client.post(
        f"{url}/status",
        headers={**h(owner), "If-Match": source.headers["etag"]},
        json={
            "status": "in_force",
            "reason": "Primary text read",
            "commencement_date": "2027-01-01",
        },
    )
    assert ok.status_code == 200
    assert (ok.json()["status"], ok.json()["commencement_date"]) == ("in_force", "2027-01-01")
    assert client.get(f"{P}/sources/NOPE", headers=h(owner)).status_code == 404
    assert (
        client.get(f"{P}/datasets/cbam_commodity_codes/versions/zzz", headers=h(owner)).status_code
        == 404
    )


def test_me_says_whether_the_user_is_a_domain_owner(
    client: TestClient, app_engine: Engine, admin_engine: Engine
) -> None:
    owner = make_owner(app_engine, admin_engine)
    other = make_user(app_engine)
    mine = client.get("/api/v1/me", headers=h(owner)).json()
    assert (mine["domain_owner"], mine["mfa"]["required"]) == (True, True)
    assert client.get("/api/v1/me", headers=h(other)).json()["domain_owner"] is False


def test_bootstrap_registers_a_domain_owner_once(admin_engine: Engine) -> None:
    from datetime import UTC, datetime

    from app.cli.bootstrap_domain_owner import bootstrap
    from app.core.ids import uuid7

    uid = uuid7()
    mail = f"owner-{uid.hex[:10]}@example.test"
    now = datetime(2027, 3, 1, 9, 0, tzinfo=UTC)
    assert bootstrap(admin_engine, user_id=uid, email=mail.upper(), now=now) is True
    assert bootstrap(admin_engine, user_id=uid, email=mail, now=now) is False
    # Platform mode, because audit_events is under forced row-level security.
    with tenant_session(admin_engine, tenant_id=None, platform=True) as s:
        audited = s.execute(
            text(
                "select count(*) from cbam.audit_events where tenant_id is null"
                " and action = 'domain_owner.registered' and object_id = :u"
            ),
            {"u": uid},
        ).scalar()
    assert audited == 1
