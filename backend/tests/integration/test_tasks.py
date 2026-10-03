"""R1-022: tasks have due date, owner, status and escalation history."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.audit import verify_chain
from app.core.clock import FrozenClock, get_clock
from app.core.db import tenant_session
from app.core.tenancy import get_engine_dep, get_verifier
from app.main import create_app
from app.modules.tasks import service
from app.modules.tasks.service import Actor
from tests.helpers_auth import bearer, verifier
from tests.integration.conftest import make_member, make_tenant, make_user

NOW = datetime(2027, 3, 1, 9, 0, tzinfo=UTC)
SYSTEM = Actor("system", None)


@pytest.fixture
def client(app_engine: Engine) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_verifier] = verifier
    app.dependency_overrides[get_engine_dep] = lambda: app_engine
    app.dependency_overrides[get_clock] = lambda: FrozenClock(NOW)
    with TestClient(app) as c:
        yield c


def _task(
    engine: Engine,
    tenant: UUID,
    title: str = "Chase supplier",
    due: date | None = date(2027, 3, 10),
    owner: UUID | None = None,
) -> UUID:
    with tenant_session(engine, tenant_id=tenant) as s:
        return service.create_task(
            s,
            tenant_id=tenant,
            task_type="supplier_follow_up",
            title=title,
            actor=SYSTEM,
            now=NOW,
            due_date=due,
            due_rule="outreach_day_7",
            owner_id=owner,
        )


def _ops(engine: Engine, tenant: UUID) -> UUID:
    user = make_user(engine)
    make_member(engine, tenant, user, "operations")
    return user


def _h(user: UUID, **kw: str) -> dict[str, str]:
    return bearer(user, aal="aal2", **kw)  # type: ignore[arg-type]


def _url(tenant: UUID, task: UUID | None = None, suffix: str = "") -> str:
    base = f"/api/v1/tenants/{tenant}/tasks"
    return f"{base}/{task}{suffix}" if task else base


def test_task_has_owner_due_date_status_and_rule(client: TestClient, app_engine: Engine) -> None:
    t = make_tenant(app_engine)
    user = _ops(app_engine, t)
    task = _task(app_engine, t, owner=user)
    body = client.get(_url(t, task), headers=_h(user)).json()
    assert body["status"] == "open"
    assert body["due_date"] == "2027-03-10"
    assert body["due_rule"] == "outreach_day_7"
    assert body["owner_id"] == str(user)
    assert body["escalation_level"] == 0
    assert body["row_version"] == 1


def test_list_filters_and_paginates_without_gaps_or_repeats(
    client: TestClient, app_engine: Engine
) -> None:
    t = make_tenant(app_engine)
    user = _ops(app_engine, t)
    ids = [
        _task(app_engine, t, f"t{i}", due=date(2027, 3, 1 + (i % 4)) if i % 5 else None)
        for i in range(11)
    ]
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        params = {"limit": 4, **({"cursor": cursor} if cursor else {})}
        page = client.get(_url(t), params=params, headers=_h(user)).json()
        seen += [i["id"] for i in page["items"]]
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert pages == 3
    assert sorted(seen) == sorted(str(i) for i in ids)
    assert len(seen) == len(set(seen))
    # Tasks with no due date sort last, ascending and descending.
    asc = client.get(_url(t), params={"limit": 200}, headers=_h(user)).json()["items"]
    assert asc[-1]["due_date"] is None
    desc = client.get(_url(t), params={"limit": 200, "sort": "-due_date"}, headers=_h(user)).json()[
        "items"
    ]
    assert desc[-1]["due_date"] is None
    dated = [i["due_date"] for i in asc if i["due_date"]]
    assert dated == sorted(dated)
    # Filters.
    before = client.get(_url(t), params={"due_before": "2027-03-03"}, headers=_h(user)).json()[
        "items"
    ]
    assert before and all(i["due_date"] < "2027-03-03" for i in before)


def test_bad_cursor_is_422(client: TestClient, app_engine: Engine) -> None:
    t = make_tenant(app_engine)
    user = _ops(app_engine, t)
    r = client.get(_url(t), params={"cursor": "garbage"}, headers=_h(user))
    assert r.status_code == 422


def test_patch_changes_status_with_history_audit_and_new_version(
    client: TestClient, app_engine: Engine
) -> None:
    t = make_tenant(app_engine)
    user = _ops(app_engine, t)
    task = _task(app_engine, t)
    r = client.patch(
        _url(t, task), json={"status": "in_progress"}, headers={**_h(user), "If-Match": '"1"'}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress"
    assert r.json()["row_version"] == 2
    assert r.headers["etag"] == '"2"'
    history = client.get(_url(t, task, "/history"), headers=_h(user)).json()
    assert [h["event_type"] for h in history] == ["created", "status_changed"]
    assert history[1]["actor_id"] == str(user)
    with tenant_session(app_engine, tenant_id=t) as s:
        actions = (
            s.execute(text("select action from cbam.audit_events order by chain_seq"))
            .scalars()
            .all()
        )
        assert actions == ["task.created", "task.updated"]
        assert verify_chain(s, t).ok


def test_stale_and_missing_if_match(client: TestClient, app_engine: Engine) -> None:
    t = make_tenant(app_engine)
    user = _ops(app_engine, t)
    task = _task(app_engine, t)
    ok = client.patch(
        _url(t, task), json={"status": "in_progress"}, headers={**_h(user), "If-Match": '"1"'}
    )
    assert ok.status_code == 200
    stale = client.patch(
        _url(t, task), json={"status": "done"}, headers={**_h(user), "If-Match": '"1"'}
    )
    assert stale.status_code == 409
    assert stale.json()["type"].endswith("/stale-version")
    missing = client.patch(_url(t, task), json={"status": "done"}, headers=_h(user))
    assert missing.status_code == 428
    assert client.get(_url(t, task), headers=_h(user)).json()["status"] == "in_progress"


def test_illegal_transition_is_409_with_rule_id(client: TestClient, app_engine: Engine) -> None:
    t = make_tenant(app_engine)
    user = _ops(app_engine, t)
    task = _task(app_engine, t)
    h = {**_h(user), "If-Match": '"1"'}
    assert client.patch(_url(t, task), json={"status": "done"}, headers=h).status_code == 200
    r = client.patch(
        _url(t, task), json={"status": "in_progress"}, headers={**_h(user), "If-Match": '"2"'}
    )
    assert r.status_code == 409
    assert r.json()["rule_id"] == "R1-022.status_transition"


def test_reason_is_required_to_cancel_reopen_or_move_a_due_date(
    client: TestClient, app_engine: Engine
) -> None:
    t = make_tenant(app_engine)
    user = _ops(app_engine, t)
    task = _task(app_engine, t)
    no_reason = client.patch(
        _url(t, task), json={"status": "cancelled"}, headers={**_h(user), "If-Match": '"1"'}
    )
    assert no_reason.status_code == 422
    assert no_reason.json()["type"].endswith("/reason-required")
    moved = client.patch(
        _url(t, task), json={"due_date": "2027-04-01"}, headers={**_h(user), "If-Match": '"1"'}
    )
    assert moved.status_code == 422
    ok = client.patch(
        _url(t, task),
        json={"due_date": "2027-04-01", "reason": "supplier on holiday"},
        headers={**_h(user), "If-Match": '"1"'},
    )
    assert ok.status_code == 200
    assert ok.json()["due_date"] == "2027-04-01"
    assert ok.json()["due_rule"] == "manual"
    history = client.get(_url(t, task, "/history"), headers=_h(user)).json()
    assert history[-1]["reason"] == "supplier on holiday"


def test_assigning_an_owner_must_be_a_member_of_the_tenant(
    client: TestClient, app_engine: Engine
) -> None:
    t, other = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    user = _ops(app_engine, t)
    colleague = make_user(app_engine)
    make_member(app_engine, t, colleague, "reviewer")
    outsider = make_user(app_engine)
    make_member(app_engine, other, outsider, "reviewer")
    task = _task(app_engine, t)
    bad = client.patch(
        _url(t, task), json={"owner_id": str(outsider)}, headers={**_h(user), "If-Match": '"1"'}
    )
    assert bad.status_code == 422
    good = client.patch(
        _url(t, task), json={"owner_id": str(colleague)}, headers={**_h(user), "If-Match": '"1"'}
    )
    assert good.status_code == 200
    assert good.json()["owner_id"] == str(colleague)
    unassign = client.patch(
        _url(t, task), json={"owner_id": None}, headers={**_h(user), "If-Match": '"2"'}
    )
    assert unassign.status_code == 200
    assert unassign.json()["owner_id"] is None


def test_empty_patch_and_unknown_fields_are_refused(client: TestClient, app_engine: Engine) -> None:
    t = make_tenant(app_engine)
    user = _ops(app_engine, t)
    task = _task(app_engine, t)
    h = {**_h(user), "If-Match": '"1"'}
    assert client.patch(_url(t, task), json={}, headers=h).status_code == 422
    assert client.patch(_url(t, task), json={"title": "x"}, headers=h).status_code == 422


def test_permissions_tenant_isolation_and_roles(client: TestClient, app_engine: Engine) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    task_a = _task(app_engine, a)
    agent = make_user(app_engine)
    make_member(app_engine, a, agent, "tax_agent")
    ops_b = _ops(app_engine, b)
    # A tax agent may read tasks but not change them.
    assert client.get(_url(a, task_a), headers=bearer(agent)).status_code == 200
    denied = client.patch(
        _url(a, task_a), json={"status": "done"}, headers={**bearer(agent), "If-Match": '"1"'}
    )
    assert denied.status_code == 403
    # Another tenant's staff cannot see or change it, and get "not found".
    assert client.get(_url(a, task_a), headers=_h(ops_b)).status_code == 404
    assert client.get(_url(b, task_a), headers=_h(ops_b)).status_code == 404
    assert (
        client.patch(
            _url(b, task_a), json={"status": "done"}, headers={**_h(ops_b), "If-Match": '"1"'}
        ).status_code
        == 404
    )
    assert client.get(_url(b), headers=_h(ops_b)).json()["items"] == []


def test_task_events_are_append_only(app_engine: Engine) -> None:
    t = make_tenant(app_engine)
    _task(app_engine, t)
    from sqlalchemy.exc import ProgrammingError

    for sql in ("update cbam.task_events set reason = 'x'", "delete from cbam.task_events"):
        with pytest.raises(ProgrammingError), tenant_session(app_engine, tenant_id=t) as s:
            s.execute(text(sql))


def test_escalation_follows_overdue_days_and_is_idempotent(app_engine: Engine) -> None:
    t = make_tenant(app_engine)
    due = date(2027, 3, 10)
    overdue = _task(app_engine, t, "overdue", due=due)
    fresh = _task(app_engine, t, "fresh", due=date(2027, 4, 30))
    no_due = _task(app_engine, t, "no due date", due=None)

    def run(as_of: date) -> int:
        with tenant_session(app_engine, tenant_id=t) as s:
            return service.escalate_overdue(
                s, tenant_id=t, as_of=as_of, thresholds_days=(7, 14, 28), now=NOW
            )

    assert run(date(2027, 3, 16)) == 0  # 6 days overdue
    assert run(date(2027, 3, 17)) == 1  # 7 days -> level 1
    assert run(date(2027, 3, 17)) == 0  # same day again: nothing new
    assert run(date(2027, 4, 7)) == 1  # 28 days -> level 3 (jumps past 14)
    with tenant_session(app_engine, tenant_id=t) as s:
        levels = {
            r.id: r.escalation_level
            for r in s.execute(text("select id, escalation_level from cbam.tasks"))
        }
        assert levels[overdue] == 3
        assert levels[fresh] == 0
        assert levels[no_due] == 0
        events = service.task_history(s, overdue)
        escalations = [e for e in events if e.event_type == "escalated"]
        assert [(e.from_value, e.to_value) for e in escalations] == [("0", "1"), ("1", "3")]
        assert all(e.actor_type == "job" for e in escalations)
        assert verify_chain(s, t).ok


def test_closed_tasks_are_not_escalated(app_engine: Engine) -> None:
    t = make_tenant(app_engine)
    task = _task(app_engine, t, due=date(2027, 1, 1))
    with tenant_session(app_engine, tenant_id=t) as s:
        service.update_task(
            s, tenant_id=t, task_id=task, expected_version=1, actor=SYSTEM, now=NOW, status="done"
        )
        n = service.escalate_overdue(
            s, tenant_id=t, as_of=date(2027, 12, 1), thresholds_days=(7,), now=NOW
        )
    assert n == 0


def test_nightly_job_escalates_every_active_tenant(
    app_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import db
    from app.core.jobs import escalate_overdue_tasks

    t = make_tenant(app_engine)
    task = _task(app_engine, t, due=date(2020, 1, 1))
    monkeypatch.setattr(db, "get_engine", lambda: app_engine)
    escalate_overdue_tasks()
    with tenant_session(app_engine, tenant_id=t) as s:
        level = s.execute(
            text("select escalation_level from cbam.tasks where id = :i"), {"i": task}
        ).scalar_one()
    assert level == 3
