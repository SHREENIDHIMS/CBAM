# ruff: noqa: F811, S608 - imported pytest fixtures are test arguments; SQL text is test-only
"""R1-004 manual import entry and R1-010 customs-value corrections.

Scenario IDs MAN-01 to MAN-09 (manual entry) and COR-01 to COR-09 (corrections).

Product rules, not law: no regulatory source applies. File rows use the PROVISIONAL synthetic
layout (DATA-DEC-002); every value is synthetic.
"""

from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.audit import verify_chain
from app.core.db import tenant_session
from app.core.storage import InMemoryStore
from tests.integration.conftest import make_tenant
from tests.integration.test_import_processing import (  # noqa: F401
    client,
    good_row,
    layout,
    queued,
    receive,
    run,
    store,
    to_csv,
    user_for,
)

FILE_MRN = "MRN-SENTINEL-0001"  # the MRN good_row(1) carries


def entry(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "reason": "Keyed from the paper copy of the declaration",
        "mrn": "MRN-MANUAL-0001",
        "acceptance_date": "2027-01-05",
        "importer_eori": "GB123456789012",
        "item_no": 1,
        "commodity_code": "7208100000",
        "net_mass_kg": "2.500000",
        "customs_value": "100.00",
        "customs_value_currency": "GBP",
        "origin_country": "DE",
    }
    body.update(changes)
    return body


def q(engine: Engine, tenant: UUID, statement: str, **params: object) -> list[Any]:
    with tenant_session(engine, tenant_id=tenant) as s:
        return list(s.execute(text(statement), params).all())


def n(engine: Engine, tenant: UUID, table: str, where: str = "true") -> int:
    return int(q(engine, tenant, f"select count(*) from cbam.{table} where {where}")[0][0])


def base(tenant: UUID) -> str:
    return f"/api/v1/tenants/{tenant}/import-lines"


def load_file(engine: Engine, store: InMemoryStore, tenant: UUID, rows: list[list[str]]) -> None:
    batch = receive(engine, store, tenant, to_csv(rows))
    assert run(engine, store, tenant, batch.id) == "completed"


# --- manual entry -------------------------------------------------------------------------


def test_man_01_a_keyed_line_is_stored_with_its_reason_lineage_and_audit(
    client: TestClient, app_engine: Engine, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    res = client.post(f"{base(tenant)}/manual", json=entry(), headers=ops)
    assert res.status_code == 201, res.text
    body = res.json()
    assert (body["result"], body["version"], body["warnings"]) == (
        "created",
        1,
        [
            {
                "field": "line.supplier_ref",
                "code": "SUPPLIER_MISSING",
                "message": body["warnings"][0]["message"],
            }
        ],
    )
    line = q(
        app_engine,
        tenant,
        "select entry_method, value_source, value_override_reason, customs_value_gbp,"
        " net_mass_kg, change_reason from cbam.import_lines where id = :i",
        i=body["line_id"],
    )[0]
    assert tuple(line)[:3] == ("manual", "manual", "Keyed from the paper copy of the declaration")
    assert str(line.customs_value_gbp) == "100.00" and str(line.net_mass_kg) == "2.500000"
    batch = q(
        app_engine,
        tenant,
        "select acquisition_method, status, file_sha256, rows_total, rows_valid, lines_created,"
        " lines_unchanged from cbam.import_batches where id = :i",
        i=body["batch_id"],
    )[0]
    assert tuple(batch) == ("manual_entry", "completed", None, 1, 1, 1, 0)
    raw = q(
        app_engine,
        tenant,
        "select raw from cbam.source_rows where batch_id = :b",
        b=body["batch_id"],
    )[0].raw
    assert raw["declaration.mrn"] == "MRN-MANUAL-0001"
    assert raw["entry_reason"] == "Keyed from the paper copy of the declaration"
    # the line detail shows the keyed source row like a file row
    detail = client.get(f"{base(tenant)}/{body['line_id']}", headers=ops).json()
    assert detail["line"]["entry_method"] == "manual"
    assert detail["sources"][0]["raw"]["line.commodity_code"] == "7208100000"
    assert detail["file"]["sha256"] is None
    events = q(
        app_engine,
        tenant,
        "select reason from cbam.audit_events where action = 'import_line.manual_entry'",
    )
    assert [e.reason for e in events] == ["Keyed from the paper copy of the declaration"]
    with tenant_session(app_engine, tenant_id=tenant) as s:
        assert verify_chain(s, tenant).ok


def test_man_02_an_invalid_entry_lists_every_problem_and_stores_nothing(
    client: TestClient, app_engine: Engine, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    bad = entry(
        commodity_code="7208",
        net_mass_kg="1.1234567",
        customs_value="abc",
        customs_value_currency="eu",
        origin_country="de",
        importer_eori="DE123",
    )
    res = client.post(f"{base(tenant)}/manual", json=bad, headers=ops)
    assert res.status_code == 422, res.text
    codes = {(e["field"], e["code"]) for e in res.json()["errors"]}
    assert ("line.commodity_code", "COMMODITY_CODE_INVALID") in codes
    assert ("line.net_mass_kg", "NET_MASS_PRECISION") in codes
    assert ("line.customs_value", "VALUE_INVALID") in codes
    assert ("line.origin_country", "ORIGIN_INVALID") in codes
    assert ("declaration.eori", "EORI_INVALID") in codes
    for table in ("import_batches", "source_rows", "import_lines", "declarations"):
        assert n(app_engine, tenant, table) == 0


def test_man_03_a_reason_is_required_and_a_blank_one_does_not_count(
    client: TestClient, app_engine: Engine, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    for reason in ("", "   ", "x" * 1001):
        res = client.post(f"{base(tenant)}/manual", json=entry(reason=reason), headers=ops)
        assert res.status_code == 422, (reason[:5], res.text)
    missing = entry()
    del missing["reason"]
    assert client.post(f"{base(tenant)}/manual", json=missing, headers=ops).status_code == 422
    assert n(app_engine, tenant, "import_batches") == 0


def test_man_04_keying_the_same_facts_twice_adds_no_second_line(
    client: TestClient, app_engine: Engine, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    first = client.post(f"{base(tenant)}/manual", json=entry(), headers=ops).json()
    second = client.post(f"{base(tenant)}/manual", json=entry(), headers=ops)
    assert second.status_code == 201, second.text
    assert second.json()["result"] == "duplicate_seen"
    assert second.json()["line_id"] == first["line_id"]
    assert (n(app_engine, tenant, "import_lines"), n(app_engine, tenant, "declarations")) == (1, 1)
    assert n(app_engine, tenant, "import_line_sources", "role = 'duplicate_seen'") == 1
    assert n(app_engine, tenant, "import_batches", "lines_unchanged = 1") == 1


def test_man_05_a_keyed_value_supersedes_a_file_line_and_a_later_file_cannot_undo_it(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    load_file(app_engine, store, tenant, [good_row(1)])
    keyed = entry(mrn=FILE_MRN, customs_value="9.99", customs_value_currency="EUR")
    res = client.post(f"{base(tenant)}/manual", json=keyed, headers=ops)
    assert res.status_code == 201, res.text
    assert (res.json()["result"], res.json()["version"]) == ("superseded", 2)
    versions = q(
        app_engine,
        tenant,
        "select version, entry_method, value_source, change_reason from cbam.import_lines"
        " order by version",
    )
    assert [tuple(v) for v in versions] == [
        (1, "gcd", "declared", None),
        (2, "manual", "manual", "manual_entry"),
    ]
    # a different file value is NOT allowed to replace the keyed one
    changed = good_row(1)
    changed[6] = "777.00"
    batch = receive(app_engine, store, tenant, to_csv([changed]))
    assert run(app_engine, store, tenant, batch.id) == "completed_with_errors"
    codes = q(app_engine, tenant, "select code from cbam.row_exceptions")
    assert [c.code for c in codes] == ["SOURCE_CONFLICTS_WITH_CORRECTION"]
    assert n(app_engine, tenant, "import_lines") == 2
    # the original file value again is only a sighting of version 1
    again = receive(app_engine, store, tenant, to_csv([good_row(1), good_row(2)]))
    assert run(app_engine, store, tenant, again.id) == "completed"
    assert n(app_engine, tenant, "import_lines", "item_no = 2") == 1
    assert n(app_engine, tenant, "import_lines") == 3


def test_man_06_a_second_different_keyed_value_is_refused_and_leaves_nothing(
    client: TestClient, app_engine: Engine, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    assert client.post(f"{base(tenant)}/manual", json=entry(), headers=ops).status_code == 201
    batches = n(app_engine, tenant, "import_batches")
    res = client.post(f"{base(tenant)}/manual", json=entry(customs_value="55.00"), headers=ops)
    assert res.status_code == 409, res.text
    assert (n(app_engine, tenant, "import_batches"), n(app_engine, tenant, "import_lines")) == (
        batches,
        1,
    )


def test_man_07_a_tax_agent_cannot_key_entries_and_tenants_stay_apart(
    client: TestClient, app_engine: Engine, layout: UUID
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    agent = user_for(app_engine, a, "tax_agent")
    assert client.post(f"{base(a)}/manual", json=entry(), headers=agent).status_code == 403
    stranger = user_for(app_engine, b, "operations")
    assert client.post(f"{base(a)}/manual", json=entry(), headers=stranger).status_code == 404
    assert n(app_engine, a, "import_lines") == 0


def test_man_08_unknown_fields_and_floats_are_not_accepted(
    client: TestClient, app_engine: Engine, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    assert (
        client.post(
            f"{base(tenant)}/manual", json=entry(tax_point="2027-01-05"), headers=ops
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{base(tenant)}/manual", json=entry(customs_value=100.5), headers=ops
        ).status_code
        == 422
    )


def test_man_09_a_keyed_line_decides_nothing_about_tax_point_scope_or_liability(
    client: TestClient, app_engine: Engine, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    client.post(f"{base(tenant)}/manual", json=entry(), headers=ops)
    columns = {
        c.column_name
        for c in q(
            app_engine,
            tenant,
            "select column_name from information_schema.columns"
            " where table_schema = 'cbam' and table_name in ('import_lines','declarations')",
        )
    }
    assert not {c for c in columns if "tax_point" in c or "scope" in c or "liable" in c}
    assert n(app_engine, tenant, "decisions") == 0


# --- corrections ----------------------------------------------------------------------------


def first_line(engine: Engine, tenant: UUID) -> UUID:
    return q(engine, tenant, "select id from cbam.import_lines where version = 1")[0].id


def test_cor_01_a_correction_is_a_new_version_and_the_original_stays(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    load_file(app_engine, store, tenant, [good_row(1)])
    line = first_line(app_engine, tenant)
    res = client.post(
        f"{base(tenant)}/{line}/corrections",
        json={"reason": "Invoice shows a different value", "customs_value": "1000.00"},
        headers=ops,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert (body["version"], body["customs_value_source"], body["customs_value_gbp"]) == (
        2,
        "1000.00000000",
        None,  # still EUR: no FX in Phase 3, so no GBP value is invented
    )
    assert body["superseded_line_id"] == str(line)
    rows = q(
        app_engine,
        tenant,
        "select version, customs_value_source, entry_method, value_source,"
        " value_override_reason, change_reason, supersedes_id from cbam.import_lines"
        " order by version",
    )
    assert str(rows[0].customs_value_source) == "1234.56000000" and rows[0].entry_method == "gcd"
    assert (rows[1].entry_method, rows[1].value_source, rows[1].change_reason) == (
        "correction",
        "correction",
        "value_corrected",
    )
    assert rows[1].value_override_reason == "Invoice shows a different value"
    assert rows[1].supersedes_id == line
    # the original raw file row is untouched and the correction has its own source row
    assert n(app_engine, tenant, "source_rows") == 2
    detail = client.get(f"{base(tenant)}/{body['line_id']}", headers=ops).json()
    assert [v["version"] for v in detail["versions"]] == [1, 2]
    raw = detail["sources"][0]["raw"]
    assert (raw["old_value"], raw["new_value"], raw["entry_reason"]) == (
        "1234.56000000",
        "1000.00",
        "Invoice shows a different value",
    )
    audit = q(
        app_engine,
        tenant,
        "select reason, before::text, after::text from cbam.audit_events"
        " where action = 'import_line.value_corrected'",
    )
    assert len(audit) == 1 and audit[0].reason == "Invoice shows a different value"
    assert "1234.56000000" in audit[0].before and "1000.00000000" in audit[0].after


def test_cor_02_correcting_the_currency_to_gbp_sets_the_gbp_value_exactly(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    load_file(app_engine, store, tenant, [good_row(1)])
    res = client.post(
        f"{base(tenant)}/{first_line(app_engine, tenant)}/corrections",
        json={
            "reason": "Declared in the wrong currency",
            "customs_value": "820.10",
            "customs_value_currency": "GBP",
        },
        headers=ops,
    )
    assert res.status_code == 201, res.text
    assert (res.json()["customs_value_currency"], res.json()["customs_value_gbp"]) == (
        "GBP",
        "820.10",
    )


def test_cor_03_a_tax_agent_cannot_correct_and_a_reason_is_required(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    load_file(app_engine, store, tenant, [good_row(1)])
    line = first_line(app_engine, tenant)
    url = f"{base(tenant)}/{line}/corrections"
    agent = user_for(app_engine, tenant, "tax_agent")
    assert (
        client.post(url, json={"reason": "x", "customs_value": "1"}, headers=agent).status_code
        == 403
    )
    ops = user_for(app_engine, tenant, "operations")
    for reason in ("", "   "):
        res = client.post(url, json={"reason": reason, "customs_value": "1"}, headers=ops)
        assert res.status_code == 422, res.text
    assert n(app_engine, tenant, "import_lines") == 1


def test_cor_04_invalid_or_unchanged_values_are_refused(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    load_file(app_engine, store, tenant, [good_row(1)])
    url = f"{base(tenant)}/{first_line(app_engine, tenant)}/corrections"
    for value in ("abc", "-5", "1e3", "", "1.123456789"):
        res = client.post(url, json={"reason": "fix", "customs_value": value}, headers=ops)
        assert res.status_code == 422, (value, res.text)
    same = client.post(url, json={"reason": "fix", "customs_value": "1234.56"}, headers=ops)
    assert same.status_code == 422 and "nothing to change" in same.json()["detail"]
    badccy = client.post(
        url,
        json={"reason": "fix", "customs_value": "5", "customs_value_currency": "euro"},
        headers=ops,
    )
    assert badccy.status_code == 422
    assert n(app_engine, tenant, "import_lines") == 1


def test_cor_05_only_the_current_version_can_be_corrected(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    load_file(app_engine, store, tenant, [good_row(1)])
    old = first_line(app_engine, tenant)
    url = f"{base(tenant)}/{old}/corrections"
    assert (
        client.post(url, json={"reason": "r", "customs_value": "5"}, headers=ops).status_code == 201
    )
    stale = client.post(url, json={"reason": "r", "customs_value": "6"}, headers=ops)
    assert stale.status_code == 409, stale.text
    assert n(app_engine, tenant, "import_lines") == 2
    # correcting the new current version works and extends the chain
    current = q(app_engine, tenant, "select id from cbam.import_lines where version = 2")[0].id
    again = client.post(
        f"{base(tenant)}/{current}/corrections",
        json={"reason": "second fix", "customs_value": "6"},
        headers=ops,
    )
    assert again.status_code == 201 and again.json()["version"] == 3


def test_cor_06_a_later_file_cannot_undo_a_correction(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    load_file(app_engine, store, tenant, [good_row(1)])
    client.post(
        f"{base(tenant)}/{first_line(app_engine, tenant)}/corrections",
        json={"reason": "invoice", "customs_value": "50.00"},
        headers=ops,
    )
    # the same original row again: only a sighting, no new version
    replay = receive(app_engine, store, tenant, to_csv([good_row(1), good_row(2)]))
    assert run(app_engine, store, tenant, replay.id) == "completed"
    assert n(app_engine, tenant, "import_lines", "item_no = 1") == 2
    # a file that disagrees with the correction is held for a human
    other = good_row(1)
    other[6] = "4321.00"
    batch = receive(app_engine, store, tenant, to_csv([other]))
    assert run(app_engine, store, tenant, batch.id) == "completed_with_errors"
    assert n(app_engine, tenant, "row_exceptions", "code = 'SOURCE_CONFLICTS_WITH_CORRECTION'") == 1
    assert n(app_engine, tenant, "import_lines", "item_no = 1") == 2


def test_cor_07_other_clients_cannot_see_or_correct_a_line(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    load_file(app_engine, store, a, [good_row(1)])
    line = first_line(app_engine, a)
    stranger = user_for(app_engine, b, "operations")
    res = client.post(
        f"{base(b)}/{line}/corrections",
        json={"reason": "r", "customs_value": "5"},
        headers=stranger,
    )
    assert res.status_code == 404
    assert n(app_engine, a, "import_lines") == 1


def test_cor_08_the_ledger_shows_corrections_and_filters_by_entry_method(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    load_file(app_engine, store, tenant, [good_row(1), good_row(2)])
    client.post(
        f"{base(tenant)}/{first_line(app_engine, tenant)}/corrections",
        json={"reason": "r", "customs_value": "5"},
        headers=ops,
    )
    page = client.get(f"{base(tenant)}?entry_method=correction", headers=ops).json()
    assert [(i["version"], i["entry_method"]) for i in page["items"]] == [(2, "correction")]
    current = client.get(base(tenant), headers=ops).json()["items"]
    assert len(current) == 2


def test_cor_09_the_audit_chain_still_verifies_after_manual_entries_and_corrections(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    ops = user_for(app_engine, tenant, "operations")
    load_file(app_engine, store, tenant, [good_row(1)])
    client.post(f"{base(tenant)}/manual", json=entry(), headers=ops)
    client.post(
        f"{base(tenant)}/{first_line(app_engine, tenant)}/corrections",
        json={"reason": "r", "customs_value": "5"},
        headers=ops,
    )
    with tenant_session(app_engine, tenant_id=tenant) as s:
        assert verify_chain(s, tenant).ok
