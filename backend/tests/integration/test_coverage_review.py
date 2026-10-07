# ruff: noqa: F811 - imported pytest fixtures are test arguments; SQL text is test-only
"""R1-054 review follow-ups: audit trail, register guard, no-op edits, stable gap tasks, nightly job.

Scenario IDs COV-32 to COV-39. Product rules, not law.
"""

from datetime import date
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.core.db import tenant_session
from tests.integration.conftest import make_tenant
from tests.integration.test_coverage import EORI, q, register, scan
from tests.integration.test_import_processing import (  # noqa: F401
    client,
    layout,
    owner,
    queued,
    store,
    user_for,
)


def audit_actions(engine: Engine, tenant: UUID) -> list[str]:
    rows = q(
        engine,
        tenant,
        "select action from cbam.audit_events where action like 'customs_data.%' order by id",
    )
    return [r.action for r in rows]


def test_cov_32_register_and_update_write_audit_events_that_show_what_changed(
    client: TestClient, app_engine: Engine, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    base = f"/api/v1/tenants/{tenant}/customs-data/eoris"
    item = client.post(base, json={"eori": EORI, "tracking_from": "2027-01-01"}, headers=ops).json()
    url = f"{base}/{item['id']}"
    changed = client.patch(
        url, json={"third_party_access": "granted"}, headers={**ops, "If-Match": '"1"'}
    )
    assert changed.status_code == 200
    noted = client.patch(url, json={"note": "private"}, headers={**ops, "If-Match": '"2"'})
    assert noted.status_code == 200
    assert audit_actions(app_engine, tenant) == [
        "customs_data.eori_registered",
        "customs_data.eori_updated",
        "customs_data.eori_updated",
    ]
    events = q(
        app_engine,
        tenant,
        "select before, after from cbam.audit_events"
        " where action = 'customs_data.eori_updated' order by id",
    )
    assert events[0].after["third_party_access"] == "granted"
    assert events[0].after["note_changed"] is False
    assert events[1].after["note_changed"] is True
    assert "private" not in str(events[1].before) + str(events[1].after)  # free text stays out


def test_cov_33_an_edit_that_changes_nothing_writes_no_version_and_no_audit(
    client: TestClient, app_engine: Engine, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    base = f"/api/v1/tenants/{tenant}/customs-data/eoris"
    item = client.post(base, json={"eori": EORI, "tracking_from": "2027-01-01"}, headers=ops).json()
    url = f"{base}/{item['id']}"
    same = client.patch(
        url, json={"third_party_access": "unknown"}, headers={**ops, "If-Match": '"1"'}
    )
    assert same.status_code == 200 and same.json()["row_version"] == 1
    assert audit_actions(app_engine, tenant) == ["customs_data.eori_registered"]
    stale = client.patch(
        url, json={"third_party_access": "unknown"}, headers={**ops, "If-Match": '"9"'}
    )
    assert stale.status_code == 409


def test_cov_34_an_empty_patch_or_a_null_access_status_is_refused(
    client: TestClient, app_engine: Engine, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    base = f"/api/v1/tenants/{tenant}/customs-data/eoris"
    item = client.post(base, json={"eori": EORI, "tracking_from": "2027-01-01"}, headers=ops).json()
    headers = {**ops, "If-Match": '"1"'}
    for body in ({}, {"third_party_access": None}, {"third_party_access": "maybe"}):
        assert client.patch(f"{base}/{item['id']}", json=body, headers=headers).status_code == 422


def test_cov_35_the_register_cannot_be_deleted_or_have_its_first_day_moved(
    app_engine: Engine, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    register(app_engine, tenant, date(2027, 1, 1))
    for statement in (
        "update cbam.customs_data_eoris set tracking_from = '2027-06-01'",
        "update cbam.customs_data_eoris set eori = 'GB000000000000'",
        "delete from cbam.customs_data_eoris",
        "truncate cbam.customs_data_eoris",
    ):
        with pytest.raises(DBAPIError):
            q(app_engine, tenant, statement)
    assert q(app_engine, tenant, "select count(*) from cbam.customs_data_eoris")[0][0] == 1
    # the allowed edit (access status) still works for the application role
    with tenant_session(app_engine, tenant_id=tenant) as s:
        s.execute(text("update cbam.customs_data_eoris set third_party_access = 'granted'"))


def test_cov_36_another_clients_eori_cannot_be_edited_through_your_url(
    client: TestClient, app_engine: Engine, layout: UUID
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    mine = register(app_engine, a, date(2027, 1, 1))
    stranger = user_for(app_engine, b, "operations")
    response = client.patch(
        f"/api/v1/tenants/{b}/customs-data/eoris/{mine}",
        json={"third_party_access": "granted"},
        headers={**stranger, "If-Match": '"1"'},
    )
    assert response.status_code == 404


def test_cov_37_a_long_gap_keeps_the_same_task_from_one_day_to_the_next(
    app_engine: Engine, layout: UUID
) -> None:
    """The scan window used to slide with today, so a gap older than 2000 days got a new key
    (and a new task) every day."""
    tenant = make_tenant(app_engine, "A")
    register(app_engine, tenant, date(2020, 1, 1))
    first = scan(app_engine, tenant, date(2027, 3, 1))
    assert first.gap_tasks_created == 2  # two fixed 2000-day chunks from the first day to cover
    again = scan(app_engine, tenant, date(2027, 3, 2))
    assert again.gap_tasks_created == 0
    keys = q(app_engine, tenant, "select due_rule from cbam.tasks where type = 'customs_data.gap'")
    assert sorted(k.due_rule for k in keys) == [
        "coverage_gap:2020-01-01",
        "coverage_gap:2025-06-23",
    ]


def test_cov_38_the_nightly_job_scans_every_client(
    app_engine: Engine, layout: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import db, jobs

    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    register(app_engine, a, date(2026, 9, 1))
    register(app_engine, b, date(2026, 9, 1))
    monkeypatch.setattr(db, "get_engine", lambda: app_engine)
    assert jobs.scan_customs_data_coverage() >= 2
    for tenant in (a, b):
        assert q(app_engine, tenant, "select count(*) from cbam.tasks")[0][0] >= 1


def test_cov_39_one_clients_failure_does_not_stop_the_others_and_is_reported(
    app_engine: Engine, layout: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import db, jobs
    from app.modules.coverage import service

    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    register(app_engine, a, date(2026, 9, 1))
    register(app_engine, b, date(2026, 9, 1))
    real = service.scan

    def flaky(session, *, tenant_id, **kw):  # type: ignore[no-untyped-def]
        if tenant_id == a:
            raise ValueError("boom")
        return real(session, tenant_id=tenant_id, **kw)

    monkeypatch.setattr(db, "get_engine", lambda: app_engine)
    monkeypatch.setattr(service, "scan", flaky)
    with pytest.raises(RuntimeError, match="1 client"):
        jobs.scan_customs_data_coverage()
    assert q(app_engine, a, "select count(*) from cbam.tasks")[0][0] == 0
    assert q(app_engine, b, "select count(*) from cbam.tasks")[0][0] >= 1
