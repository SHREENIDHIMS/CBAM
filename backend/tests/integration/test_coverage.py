# ruff: noqa: F811 - imported pytest fixtures are test arguments; SQL text is test-only
"""R1-054 customs-data coverage tracker: calendar, gaps, overlaps, EORI register, tasks.

Scenario IDs COV-20 to COV-31. Product rules, not law: the HMRC lag is the fixture dataset
`customs_data_service/fixture.1` (a test input, not an HMRC fact). File rows use the PROVISIONAL
synthetic layout (DATA-DEC-002).
"""

from datetime import date, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.core.db import tenant_session
from app.core.storage import InMemoryStore
from app.modules.coverage import service
from app.modules.imports.schemas import ImportBatchMetadata
from app.modules.tasks.service import Actor
from tests.integration.conftest import make_tenant
from tests.integration.refdata_setup import activate, load
from tests.integration.test_import_processing import (  # noqa: F401
    NOW,
    client,
    good_row,
    layout,
    owner,
    queued,
    receive,
    run,
    store,
    to_csv,
    user_for,
)
from tests.refdata_helpers import FIXTURES

EORI = "GB123456789012"
OTHER_EORI = "XI987654321098"
HEADER_COLS = ["SYNTH_H_MRN", "SYNTH_H_PROCEDURE"]
LATE = date(2028, 1, 15)  # the day files are received in the year-long scenario
ACTOR = Actor("job", None)


def report(
    engine: Engine,
    store: InMemoryStore,
    tenant: UUID,
    start: date | None,
    end: date | None,
    rows: list[list[str]] | None = None,
    *,
    report_type: str = "import_item",
    eori: str | None = EORI,
    headers: list[str] | None = None,
    as_of: date = LATE,
) -> tuple[UUID, str]:
    meta = ImportBatchMetadata(
        acquisition_method="get_customs_data",
        cds_report_type=report_type,  # type: ignore[arg-type]
        eori=eori,
        window_start=start,
        window_end=end,
    )
    data = to_csv(rows if rows is not None else [good_row(1)], headers)
    batch = receive(engine, store, tenant, data, meta, as_of=as_of)
    return batch.id, run(engine, store, tenant, batch.id)


def q(engine: Engine, tenant: UUID, statement: str, **params: object) -> list:  # type: ignore[type-arg]
    with tenant_session(engine, tenant_id=tenant) as s:
        return list(s.execute(text(statement), params).all())


def calendar(engine: Engine, tenant: UUID, today: date, **kw: object):  # type: ignore[no-untyped-def]
    args: dict[str, object] = {
        "eori": EORI,
        "report_type": "import_item",
        "range_from": None,
        "range_to": None,
    }
    args.update(kw)
    with tenant_session(engine, tenant_id=tenant) as s:
        return service.calendar_for(s, tenant_id=tenant, today=today, **args)  # type: ignore[arg-type]


def register(engine: Engine, tenant: UUID, tracking: date, **kw: object) -> UUID:
    from app.modules.coverage.schemas import EoriIn

    with tenant_session(engine, tenant_id=tenant) as s:
        out = service.register_eori(
            s,
            tenant_id=tenant,
            actor=Actor("system", None),
            now=NOW,
            today=NOW.date(),
            body=EoriIn(eori=EORI, tracking_from=tracking, **kw),  # type: ignore[arg-type]
        )
    return out.id


def scan(engine: Engine, tenant: UUID, today: date):  # type: ignore[no-untyped-def]
    with tenant_session(engine, tenant_id=tenant) as s:
        return service.scan(s, tenant_id=tenant, actor=ACTOR, now=NOW, today=today)


def lag_active(engine: Engine, owner_id: UUID) -> None:
    load(engine, FIXTURES / "customs_data_service" / "fixture.1")
    activate(engine, owner_id, "customs_data_service", "fixture.1")


# --- recording coverage -------------------------------------------------------------------------


def test_cov_20_a_completed_report_with_an_eori_and_window_records_its_days(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    batch, status = report(app_engine, store, tenant, date(2027, 1, 1), date(2027, 1, 31))
    assert status == "completed"
    rows = q(
        app_engine,
        tenant,
        "select eori, report_type, covered_from, covered_to, has_errors, batch_id"
        " from cbam.customs_data_coverage",
    )
    assert [tuple(r) for r in rows] == [
        (EORI, "import_item", date(2027, 1, 1), date(2027, 1, 31), False, batch)
    ]


def test_cov_21_no_window_or_no_eori_means_no_coverage_and_a_guess_is_never_made(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    assert report(app_engine, store, tenant, None, None, [good_row(1)])[1] == "completed"
    assert (
        report(
            app_engine, store, tenant, date(2027, 1, 1), date(2027, 1, 31), [good_row(2)], eori=None
        )[1]
        == "completed"
    )
    assert q(app_engine, tenant, "select count(*) from cbam.customs_data_coverage")[0][0] == 0


def test_cov_22_a_rejected_batch_leaves_no_coverage_and_one_with_errors_is_flagged(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    bad = good_row(1)
    bad[5] = ""  # a missing net mass: a row error, the file still completes with errors
    _, status = report(
        app_engine, store, tenant, date(2027, 1, 1), date(2027, 1, 31), [bad, good_row(2)]
    )
    assert status == "completed_with_errors"
    rows = q(app_engine, tenant, "select has_errors from cbam.customs_data_coverage")
    assert [r.has_errors for r in rows] == [True]
    # a file with a missing required column is rejected: no coverage for it
    _, rejected = report(
        app_engine,
        store,
        tenant,
        date(2027, 2, 1),
        date(2027, 2, 28),
        [["x", "y"]],
        headers=["A", "B"],
    )
    assert rejected == "rejected"
    assert q(app_engine, tenant, "select count(*) from cbam.customs_data_coverage")[0][0] == 1


# --- the exit gate: a year of reports -------------------------------------------------------------


def month_windows() -> list[tuple[date, date]]:
    out = []
    for m in range(1, 13):
        first = date(2027, m, 1)
        last = date(2027 + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
        out.append((first, last))
    return out


def test_cov_23_a_year_of_reports_loads_without_duplicates_and_a_missing_month_is_a_gap_with_a_task(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    """Phase 3 exit gate 2."""
    tenant = make_tenant(app_engine, "A")
    register(app_engine, tenant, date(2027, 1, 1), third_party_access="granted")
    previous_last: list[str] | None = None
    for index, (first, last) in enumerate(month_windows(), start=1):
        if index == 6:  # June is never loaded
            continue
        rows = [good_row(index * 10 + n) for n in (1, 2, 3)]
        if previous_last is not None:
            rows.insert(0, previous_last)  # the report overlaps the one before it by a row
        previous_last = rows[-1]
        _, status = report(app_engine, store, tenant, first, last, rows)
        assert status == "completed", (index, status)
    # 11 files x 3 new rows (+ the repeated rows are sightings, not lines); June's row is absent
    # so May's last row (index 5) was repeated into July's file as the "previous" one.
    lines = q(app_engine, tenant, "select count(*) from cbam.import_lines")[0][0]
    assert lines == 33
    assert (
        q(
            app_engine,
            tenant,
            "select count(*) from cbam.import_line_sources where role = 'duplicate_seen'",
        )[0][0]
        == 10
    )
    year_end = date(2027, 12, 31)
    cal = calendar(app_engine, tenant, year_end)
    assert not cal.complete
    assert [(g.covered_from, g.covered_to) for g in cal.gaps] == [
        (date(2027, 6, 1), date(2027, 6, 30))
    ]
    result = scan(app_engine, tenant, year_end)
    assert (result.gap_tasks_created, result.month_tasks_created) == (1, 1)
    tasks = q(app_engine, tenant, "select type, title, due_rule from cbam.tasks order by type")
    assert [t.type for t in tasks] == ["customs_data.fetch_month", "customs_data.gap"]
    assert tasks[1].title == "Customs data gap: load reports for 2027-06-01 to 2027-06-30"
    assert tasks[1].due_rule == "coverage_gap:2027-06-01"
    # a second scan changes nothing
    again = scan(app_engine, tenant, year_end)
    assert (again.gap_tasks_created, again.month_tasks_created) == (0, 0)
    # loading June makes the calendar complete
    _, status = report(
        app_engine, store, tenant, date(2027, 6, 1), date(2027, 6, 30), [good_row(61)]
    )
    assert status == "completed"
    assert calendar(app_engine, tenant, year_end).complete


# --- the calendar and its rules --------------------------------------------------------------------


def test_cov_24_overlapping_reports_show_as_overlaps_and_the_calendar_is_per_report_type(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    register(app_engine, tenant, date(2027, 1, 1))
    a, _ = report(app_engine, store, tenant, date(2027, 1, 1), date(2027, 1, 31), [good_row(1)])
    b, _ = report(app_engine, store, tenant, date(2027, 1, 25), date(2027, 2, 28), [good_row(2)])
    cal = calendar(app_engine, tenant, date(2027, 2, 28))
    assert cal.complete
    assert [(o.covered_from, o.covered_to, sorted(o.batch_ids)) for o in cal.overlaps] == [
        (date(2027, 1, 25), date(2027, 1, 31), sorted([str(a), str(b)]))
    ]
    # a header report for January does not make the ITEM calendar any fuller, nor the reverse
    report(
        app_engine,
        store,
        tenant,
        date(2027, 1, 1),
        date(2027, 1, 31),
        [["MRN-X", "1"]],
        report_type="import_header",
        headers=HEADER_COLS,
    )
    header = calendar(app_engine, tenant, date(2027, 2, 28), report_type="import_header")
    assert [(g.covered_from, g.covered_to) for g in header.gaps] == [
        (date(2027, 2, 1), date(2027, 2, 28))
    ]
    assert calendar(app_engine, tenant, date(2027, 2, 28)).complete


def test_cov_25_the_lag_rule_comes_from_reference_data_and_is_off_without_it(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    register(app_engine, tenant, date(2027, 1, 1))
    report(app_engine, store, tenant, date(2027, 1, 1), date(2027, 2, 26))
    today = date(2027, 3, 1)
    off = calendar(app_engine, tenant, today)
    assert off.unavailable_latest_days is None and off.dataset_version_ids == []
    assert [p.state for p in off.periods] == ["loaded", "gap"]
    lag_active(app_engine, layout)
    on = calendar(app_engine, tenant, today)
    assert on.unavailable_latest_days == 2 and len(on.dataset_version_ids) == 1
    assert [(p.covered_from, p.covered_to, p.state) for p in on.periods] == [
        (date(2027, 1, 1), date(2027, 2, 26), "loaded"),
        (date(2027, 2, 27), date(2027, 2, 27), "gap"),
        (date(2027, 2, 28), date(2027, 3, 1), "not_yet_available"),
    ]


# --- tasks ------------------------------------------------------------------------------------------


def test_cov_26_a_growing_gap_keeps_one_open_task_and_a_closed_one_is_asked_again(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    register(app_engine, tenant, date(2027, 1, 1))
    report(app_engine, store, tenant, date(2027, 1, 1), date(2027, 1, 31))
    assert scan(app_engine, tenant, date(2027, 2, 15)).gap_tasks_created == 1
    assert scan(app_engine, tenant, date(2027, 2, 16)).gap_tasks_created == 0  # same gap start
    assert scan(app_engine, tenant, date(2027, 2, 17)).gap_tasks_created == 0
    gap_tasks = q(app_engine, tenant, "select id from cbam.tasks where type = 'customs_data.gap'")
    assert len(gap_tasks) == 1
    # a person closes it but the gap is still there: the next scan raises it again
    with tenant_session(app_engine, tenant_id=tenant) as s:
        s.execute(text("update cbam.tasks set status = 'done' where type = 'customs_data.gap'"))
    assert scan(app_engine, tenant, date(2027, 2, 18)).gap_tasks_created == 1


def test_cov_27_the_monthly_task_is_once_per_month_names_access_and_is_due_after_the_lag(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    granted = register(app_engine, tenant, date(2027, 1, 1), third_party_access="granted")
    lag_active(app_engine, layout)
    first = scan(app_engine, tenant, date(2027, 3, 1))
    assert first.month_tasks_created == 1
    task = q(
        app_engine,
        tenant,
        "select title, due_date, subject_id from cbam.tasks where type = 'customs_data.fetch_month'",
    )[0]
    assert task.title == "Request customs data for February 2027"
    assert task.due_date == date(2027, 3, 2)  # 28 Feb + 2 days of lag
    assert task.subject_id == granted
    assert scan(app_engine, tenant, date(2027, 3, 2)).month_tasks_created == 0
    assert scan(app_engine, tenant, date(2027, 4, 1)).month_tasks_created == 1  # a new month


def test_cov_28_without_third_party_access_the_task_says_to_ask_the_client_first(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    register(app_engine, tenant, date(2027, 1, 1))  # access unknown
    scan(app_engine, tenant, date(2027, 3, 1))
    title = q(
        app_engine, tenant, "select title from cbam.tasks where type = 'customs_data.fetch_month'"
    )[0].title
    assert title.startswith("Ask the client to grant third-party access")
    assert title.endswith("February 2027")


def test_cov_29_no_monthly_task_for_a_month_that_ended_before_the_first_day_to_cover(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    register(app_engine, tenant, date(2027, 3, 1))
    assert scan(app_engine, tenant, date(2027, 3, 1)).month_tasks_created == 0
    assert scan(app_engine, tenant, date(2027, 4, 1)).month_tasks_created == 1


# --- API ------------------------------------------------------------------------------------------


def test_cov_30_api_register_update_with_if_match_and_read_the_calendar(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    agent = user_for(app_engine, tenant, "tax_agent")
    base = f"/api/v1/tenants/{tenant}/customs-data"
    body = {"eori": EORI, "tracking_from": "2027-01-01"}
    assert client.post(f"{base}/eoris", json=body, headers=agent).status_code == 403
    created = client.post(f"{base}/eoris", json=body, headers=ops)
    assert created.status_code == 201, created.text
    item = created.json()
    assert (item["third_party_access"], item["access_recorded_on"], item["row_version"]) == (
        "unknown",
        None,
        1,
    )
    assert client.post(f"{base}/eoris", json=body, headers=ops).status_code == 409
    for bad in ({"eori": "FR123456789012", "tracking_from": "2027-01-01"}, {**body, "extra": 1}):
        assert client.post(f"{base}/eoris", json=bad, headers=ops).status_code == 422
    url = f"{base}/eoris/{item['id']}"
    assert client.patch(url, json={"third_party_access": "granted"}, headers=ops).status_code == 428
    patched = client.patch(
        url, json={"third_party_access": "granted"}, headers={**ops, "If-Match": '"1"'}
    )
    assert patched.status_code == 200, patched.text
    assert (patched.json()["third_party_access"], patched.json()["access_recorded_on"]) == (
        "granted",
        "2027-03-01",
    )
    stale = client.patch(url, json={"note": "x"}, headers={**ops, "If-Match": '"1"'})
    assert stale.status_code == 409
    moved = client.patch(
        url, json={"tracking_from": "2027-02-01"}, headers={**ops, "If-Match": '"2"'}
    )
    assert moved.status_code == 422  # the first day to cover cannot be edited
    report(app_engine, store, tenant, date(2027, 1, 1), date(2027, 1, 31))
    cal = client.get(f"{base}/coverage", params={"eori": EORI}, headers=agent)
    assert cal.status_code == 200, cal.text
    out = cal.json()
    assert (out["complete"], out["third_party_access"], out["tracking_from"]) == (
        False,
        "granted",
        "2027-01-01",
    )
    assert [(p["covered_from"], p["covered_to"], p["state"]) for p in out["periods"]] == [
        ("2027-01-01", "2027-01-31", "loaded"),
        ("2027-02-01", "2027-03-01", "gap"),
    ]
    assert [g["days"] for g in out["gaps"]] == [29]
    listed = client.get(f"{base}/eoris", headers=agent).json()
    assert [e["third_party_access"] for e in listed] == ["granted"]
    scanned = client.post(f"{base}/coverage/scan", headers=ops).json()
    assert (scanned["eoris_scanned"], scanned["gap_tasks_created"]) == (1, 1)
    assert client.post(f"{base}/coverage/scan", headers=agent).status_code == 403


def test_cov_31_other_clients_see_nothing_and_coverage_is_append_only(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    register(app_engine, a, date(2027, 1, 1))
    report(app_engine, store, a, date(2027, 1, 1), date(2027, 1, 31))
    stranger = user_for(app_engine, b, "operations")
    base_b = f"/api/v1/tenants/{b}/customs-data"
    assert client.get(f"{base_b}/eoris", headers=stranger).json() == []
    assert (
        client.get(f"{base_b}/coverage", params={"eori": EORI}, headers=stranger).status_code == 404
    )
    assert q(app_engine, b, "select count(*) from cbam.customs_data_coverage")[0][0] == 0
    for statement in (
        "update cbam.customs_data_coverage set eori = 'GB000000000000'",
        "delete from cbam.customs_data_coverage",
        "truncate cbam.customs_data_coverage",
    ):
        with pytest.raises(DBAPIError):
            q(app_engine, a, statement)
    with pytest.raises(DBAPIError), tenant_session(app_engine, tenant_id=a) as s:
        s.execute(text("set local role cbam_owner"))
        s.execute(text("delete from cbam.customs_data_coverage"))
