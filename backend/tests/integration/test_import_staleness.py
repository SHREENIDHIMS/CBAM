# ruff: noqa: F811 - imported pytest fixtures are test arguments; SQL text is test-only
"""R1-005 / R1-010: stale or hand-made data never replaces newer facts, and the ledger always
shows the CURRENT declaration. Review fixes for the normalisation step.

Scenario IDs: IMP-54 stale overlapping files, corrections and older extracts, IMP-55 the current
declaration is resolved for every line, IMP-56 the impact report shows totals to a platform admin,
IMP-57 a job that lost its lease cannot complete or reject the batch, IMP-58 lineage of superseded
and re-seen lines, IMP-59 a crash that is a lost worker while normalising.
Product rules, not law. Fixtures are synthetic.
"""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.db import tenant_session
from app.core.storage import InMemoryStore
from app.modules.imports import impact, ledger, processing
from app.modules.imports.processing import LeaseLostError
from app.modules.imports.schemas import ImportBatchMetadata
from app.modules.refdata import service as refdata_service
from app.modules.refdata.service import Actor as RefActor
from tests.helpers_auth import bearer
from tests.integration.conftest import make_tenant, make_user
from tests.integration.refdata_setup import activate, load, put_source_in_force
from tests.integration.test_import_lines import (
    COMMODITY,
    DATE_COL,
    VALUE,
    count,
    q,
    rows_for,
)
from tests.integration.test_import_processing import (  # noqa: F401
    CLOCK,
    NOW,
    Killed,
    at,
    batch_row,
    client,
    exceptions,
    good_row,
    kill,
    layout,
    owner,
    queued,
    receive,
    run,
    store,
    to_csv,
)
from tests.refdata_helpers import CODES_V1, write_dataset


def meta(acquired_on: date | None = None, **kw: object) -> ImportBatchMetadata:
    return ImportBatchMetadata(
        acquisition_method="get_customs_data",
        cds_report_type="import_item",
        eori="GB123456789012",
        acquired_on=acquired_on,
        **kw,  # type: ignore[arg-type]
    )


def load_file(
    engine: Engine,
    store: InMemoryStore,
    tenant: UUID,
    rows: list[list[str]],
    on: date | None = None,
) -> UUID:
    batch = receive(engine, store, tenant, to_csv(rows), meta(on))
    run(engine, store, tenant, batch.id)
    return batch.id


def item_versions(engine: Engine, tenant: UUID, item: int) -> list[tuple]:  # type: ignore[type-arg]
    return q(
        engine,
        tenant,
        "select version, customs_value_source, entry_method from cbam.import_lines"
        " where item_no = :i order by version",
        i=item,
    )


# --- IMP-54 ---------------------------------------------------------------------------------------


def test_imp_54_r1_005_a_stale_overlapping_file_never_supersedes_a_newer_version(
    app_engine: Engine, layout: UUID
) -> None:
    """A -> B (version 2) -> an overlapping file that still has A's facts: only a sighting."""
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    load_file(app_engine, store, tenant, rows_for(range(1, 4)))
    corrected = rows_for(range(1, 4))
    corrected[2][VALUE] = "500.00"
    load_file(app_engine, store, tenant, corrected)
    stale = rows_for(range(1, 5))  # item 3 is back to A's value; item 4 makes the bytes differ
    third = load_file(app_engine, store, tenant, stale)
    assert [v[:2] for v in item_versions(app_engine, tenant, 3)] == [
        (1, Decimal("1234.56000000")),
        (2, Decimal("500.00000000")),
    ]  # no version 3
    assert exceptions(app_engine, tenant, third) == set()
    seen = q(
        app_engine,
        tenant,
        "select l.version from cbam.import_line_sources s join cbam.import_lines l"
        " on l.id = s.import_line_id join cbam.source_rows sr on sr.id = s.source_row_id"
        " where s.role = 'duplicate_seen' and sr.batch_id = :b and l.item_no = 3",
        b=third,
    )
    assert seen == [(1,)]  # the sighting points at the version it matches


def test_imp_54_r1_010_a_file_never_supersedes_a_correction_or_manual_entry(
    app_engine: Engine, admin_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    load_file(app_engine, store, tenant, rows_for(range(1, 3)))
    with owner(admin_engine, tenant) as s:  # a human correction (the endpoint is a later step)
        s.execute(
            text(
                "insert into cbam.import_lines (id, tenant_id, declaration_id, item_no, version,"
                " supersedes_id, commodity_code, net_mass_kg, customs_value_source,"
                " customs_value_currency, country_of_origin_declared, batch_id, source_row_id,"
                " entry_method, value_source, value_override_reason, change_reason,"
                " content_sha256) select gen_random_uuid(), tenant_id, declaration_id, item_no, 2,"
                " id, commodity_code, net_mass_kg, 77, 'GBP', 'DE', batch_id, source_row_id,"
                " 'correction', 'correction', 'Invoice re-issued', 'value_correction',"
                " repeat('c', 64) from cbam.import_lines where item_no = 1"
            )
        )
    changed = rows_for(range(1, 3))
    changed[0][VALUE] = "9.99"  # a different value for the corrected item
    batch = load_file(app_engine, store, tenant, changed)
    assert exceptions(app_engine, tenant, batch) == {
        (1, "line.item_no", "SOURCE_CONFLICTS_WITH_CORRECTION")
    }
    assert [v[0] for v in item_versions(app_engine, tenant, 1)] == [1, 2]  # no version 3
    assert item_versions(app_engine, tenant, 1)[1][1:] == (Decimal("77.00000000"), "correction")
    row = batch_row(app_engine, tenant, batch)
    assert (row.status, row.rows_rejected, row.lines_unchanged) == (
        "completed_with_errors",
        1,
        1,
    )  # the other item is still just seen again


def test_imp_54_r1_005_an_older_extract_loaded_later_does_not_replace_newer_facts(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    newer = rows_for(range(1, 3))
    newer[0][VALUE] = "200.00"
    load_file(app_engine, store, tenant, newer, date(2027, 2, 10))
    older = rows_for(range(1, 3))
    older[0][VALUE] = "100.00"  # a third, different value from the OLDER report
    batch = load_file(app_engine, store, tenant, older, date(2027, 1, 10))
    assert exceptions(app_engine, tenant, batch) == {(1, "line.item_no", "OLDER_EXTRACT_CONFLICT")}
    assert [v[:2] for v in item_versions(app_engine, tenant, 1)] == [(1, Decimal("200.00000000"))]


def test_imp_54_r1_005_a_newer_extract_still_supersedes_and_equal_dates_let_the_later_win(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    first = rows_for(range(1, 3))
    first[0][VALUE] = "100.00"
    load_file(app_engine, store, tenant, first, date(2027, 1, 10))
    newer = rows_for(range(1, 3))
    newer[0][VALUE] = "200.00"
    load_file(app_engine, store, tenant, newer, date(2027, 2, 10))
    same_day = rows_for(range(1, 3))
    same_day[0][VALUE] = "300.00"
    batch = load_file(app_engine, store, tenant, same_day, date(2027, 2, 10))
    assert exceptions(app_engine, tenant, batch) == set()
    assert [v[0] for v in item_versions(app_engine, tenant, 1)] == [1, 2, 3]
    assert item_versions(app_engine, tenant, 1)[2][1] == Decimal("300.00000000")


def test_imp_54_r1_005_a_changed_header_from_an_older_extract_is_left_for_a_human(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    load_file(app_engine, store, tenant, rows_for(range(1, 2)), date(2027, 2, 10))
    older = rows_for(range(1, 2))
    older[0][DATE_COL] = "06/01/2027"
    batch = load_file(app_engine, store, tenant, older, date(2027, 1, 10))
    assert exceptions(app_engine, tenant, batch) == {
        (1, "declaration.mrn", "OLDER_EXTRACT_CONFLICT")
    }
    assert count(app_engine, tenant, "declarations") == 1


# --- IMP-55 ---------------------------------------------------------------------------------------


def three_items(
    date_text: str = "05/01/2027", only: tuple[int, ...] = (1, 2, 3)
) -> list[list[str]]:
    out = []
    for item in only:
        row = good_row(item)
        row[0], row[3], row[DATE_COL] = "MRN-SHARED-1", str(item), date_text
        out.append(row)
    return out


def test_imp_55_r1_005_every_line_shows_the_current_declaration_after_a_header_correction(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    load_file(app_engine, store, tenant, three_items())
    # a later file corrects the header but only carries item 1
    load_file(app_engine, store, tenant, three_items("20/01/2027", only=(1,)))
    with tenant_session(app_engine, tenant_id=tenant) as s:
        page = ledger.list_lines(s, tenant)
        by_item = {i.item_no: i for i in page.items}
        assert {i: by_item[i].acceptance_date for i in (1, 2, 3)} == {
            1: date(2027, 1, 20),
            2: date(2027, 1, 20),
            3: date(2027, 1, 20),
        }
        assert [by_item[i].declaration_superseded for i in (1, 2, 3)] == [False, True, True]
        assert by_item[2].declaration_id != by_item[2].current_declaration_id
        assert by_item[2].current_declaration_id == by_item[1].declaration_id
        detail = ledger.get_line(s, tenant, by_item[3].id)
        assert (detail.declaration.version, detail.declaration.acceptance_date) == (
            2,
            date(2027, 1, 20),
        )
        assert detail.declaration.is_current and detail.line.declaration_superseded
        assert ledger.current_declaration(s, tenant, "MRN-SHARED-1").id == detail.declaration.id
        # the date filters use the current declaration too
        assert len(ledger.list_lines(s, tenant, date_from=date(2027, 1, 10)).items) == 3
        assert ledger.list_lines(s, tenant, date_to=date(2027, 1, 10)).items == []


def test_imp_55_r1_005_the_api_returns_the_current_declaration_and_the_flag(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    from tests.integration.conftest import make_member

    tenant = make_tenant(app_engine, "A")
    load_file(app_engine, store, tenant, three_items())
    load_file(app_engine, store, tenant, three_items("20/01/2027", only=(1,)))
    uid = make_user(app_engine)
    make_member(app_engine, tenant, uid, "operations")
    items = client.get(
        f"/api/v1/tenants/{tenant}/import-lines", headers=bearer(uid, aal="aal2")
    ).json()["items"]
    assert {i["acceptance_date"] for i in items} == {"2027-01-20"}
    assert sorted((i["item_no"], i["declaration_superseded"]) for i in items) == [
        (1, False),
        (2, True),
        (3, True),
    ]


# --- IMP-56: the impact report ----------------------------------------------------------------------


def test_imp_56_r1_005_a_platform_admin_sees_totals_and_a_domain_owner_sees_clients(
    client: TestClient, app_engine: Engine, admin_engine: Engine, layout: UUID, tmp_path: Path
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    store = InMemoryStore()
    for tenant, first in ((a, 1), (b, 30)):
        rows = rows_for(range(first, first + 2))
        rows[0][COMMODITY] = "7204100000"
        load_file(app_engine, store, tenant, rows)
    load(app_engine, write_dataset(tmp_path))
    put_source_in_force(app_engine, layout, "TEST-SOURCE")
    activate(app_engine, layout, "cbam_commodity_codes", "t.1")
    refdata_service.clear_impact_providers()
    impact.register()
    v2 = CODES_V1.replace("7204,Except 7204,iron_and_steel,Ferrous waste and scrap,,false,72\n", "")
    load(app_engine, write_dataset(tmp_path, version="t.2", csv=v2))
    with tenant_session(app_engine, tenant_id=None, user_id=layout, platform=True) as s:
        refdata_service.build_impact_report(s, RefActor(layout), NOW, "cbam_commodity_codes", "t.2")
    admin = make_user(app_engine)
    with tenant_session(app_engine, tenant_id=None, platform=True) as s:
        s.execute(text("insert into cbam.platform_admins (user_id) values (:u)"), {"u": admin})
    url = "/api/v1/platform/datasets/cbam_commodity_codes/versions/t.2"
    as_owner = client.get(url, headers=bearer(layout, aal="aal2")).json()["impact_report"]
    as_admin = client.get(url, headers=bearer(admin, aal="aal2")).json()["impact_report"]
    assert {i["ref"] for i in as_owner["affected"]["items"]} == {str(a), str(b)}
    (total,) = as_admin["affected"]["items"]
    assert total["detail"] == "2 current record(s) across 2 client(s) under 7204"
    for tenant in (a, b):
        assert str(tenant) not in str(as_admin)
    # the stored report (for activation) still has the full detail
    assert as_admin["rows"] == as_owner["rows"]


def test_imp_56_r1_005_redaction_leaves_items_without_a_group_untouched() -> None:
    report = {"affected": {"count": 1, "items": [{"kind": "x", "ref": "r", "detail": "d"}]}}
    assert refdata_service.redact_impact_report(report) == report
    assert refdata_service.redact_impact_report(None) is None


# --- IMP-57: a lost lease cannot finish the batch ------------------------------------------------------


def test_imp_57_r1_025_a_job_that_lost_its_lease_cannot_complete_the_batch(
    app_engine: Engine, layout: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv(rows_for(range(1, 4))), meta())
    thief = uuid4()

    def steal_during_normalising(*_a: object, **_k: object) -> None:
        with tenant_session(app_engine, tenant_id=tenant) as s:
            s.execute(
                text("update cbam.import_batches set lease_owner = :t where id = :b"),
                {"t": thief, "b": batch.id},
            )

    monkeypatch.setattr(processing, "_normalise", steal_during_normalising)
    assert run(app_engine, store, tenant, batch.id) == "validating"  # reported, not completed
    row = batch_row(app_engine, tenant, batch.id)
    assert (row.status, row.lease_owner) == ("validating", thief)


def test_imp_57_r1_025_reject_and_validation_steps_check_the_lease_owner(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv(rows_for(range(1, 3))), meta())
    with pytest.raises(Killed):
        run(app_engine, store, tenant, batch.id, chunk_rows=1, after_chunk=kill)
    stale = processing._Lease()
    issues = [processing.rules.Issue("FILE_UNREADABLE", "")]
    with pytest.raises(LeaseLostError):
        processing._reject(app_engine, CLOCK, tenant, batch.id, issues, None, stale)
    assert batch_row(app_engine, tenant, batch.id).status == "validating"
    with tenant_session(app_engine, tenant_id=tenant) as s:
        with pytest.raises(LeaseLostError):
            processing._require_lease(s, tenant, batch.id, stale)
        held = batch_row(app_engine, tenant, batch.id).lease_owner
        ours = processing._Lease(token=held)
        processing._require_lease(s, tenant, batch.id, ours)  # the holder passes


def test_imp_57_r1_025_the_retry_margin_keeps_an_early_retry_off_a_fresh_lease(
    app_engine: Engine, layout: UUID
) -> None:
    from tests.integration.test_import_processing import limits

    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv(rows_for(range(1, 5))), meta())

    def boom(_rows: int) -> None:
        raise RuntimeError("outage")

    with pytest.raises(processing.ImportJobError):
        run(
            app_engine, store, tenant, batch.id,
            chunk_rows=2, after_chunk=boom, release_delay_seconds=60, limits=limits(retry_margin_seconds=7),
        )  # fmt: skip
    assert batch_row(app_engine, tenant, batch.id).lease_expires_at == NOW + timedelta(seconds=67)
    # a retry a few seconds early still finds the lease held, the one on time takes over
    clock_early = type(CLOCK)(NOW + timedelta(seconds=62))
    assert run(app_engine, store, tenant, batch.id, clock=clock_early, chunk_rows=2) == "validating"
    assert run(app_engine, store, tenant, batch.id, clock=at(1.2), chunk_rows=2) == "completed"


# --- IMP-58 / IMP-59: lineage details and a lost worker while normalising ---------------------------------


def test_imp_58_r1_005_a_superseded_line_and_a_sighting_resolve_to_their_own_files(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    data1, data2 = to_csv(rows_for(range(1, 4))), None
    b1 = receive(app_engine, store, tenant, data1, meta())
    run(app_engine, store, tenant, b1.id)
    changed = rows_for(range(1, 4))
    changed[0][VALUE] = "8.00"
    data2 = to_csv(changed)
    b2 = receive(app_engine, store, tenant, data2, meta())
    run(app_engine, store, tenant, b2.id)
    rows = q(
        app_engine,
        tenant,
        "select l.item_no, l.version, s.role, sr.batch_id, v.sha256, lb.id"
        " from cbam.import_line_sources s"
        " join cbam.import_lines l on l.id = s.import_line_id"
        " join cbam.import_batches lb on lb.id = l.batch_id"
        " join cbam.source_rows sr on sr.id = s.source_row_id"
        " join cbam.import_batches b on b.id = sr.batch_id"
        " join cbam.document_versions v on v.id = b.document_version_id"
        " order by l.item_no, l.version, s.role",
    )
    import hashlib

    sha1, sha2 = hashlib.sha256(data1).hexdigest(), hashlib.sha256(data2).hexdigest()
    by_key = {(r[0], r[1], r[2]): r for r in rows}
    # item 1: version 1 is its first file's row, version 2 is the second file's row
    assert by_key[(1, 1, "primary")][3:5] == (b1.id, sha1)
    assert by_key[(1, 2, "primary")][3:5] == (b2.id, sha2)
    # item 2 was only seen again: the sighting is in file 2, the line belongs to file 1
    assert by_key[(2, 1, "primary")][3:5] == (b1.id, sha1)
    assert by_key[(2, 1, "duplicate_seen")][3:5] == (b2.id, sha2)
    assert by_key[(2, 1, "duplicate_seen")][5] == b1.id
    assert not any(r[2] == "duplicate_seen" and r[0] == 1 for r in rows)
    assert q(
        app_engine,
        tenant,
        "select count(*) from cbam.import_lines l where not exists (select 1 from"
        " cbam.import_line_sources s where s.import_line_id = l.id and s.role = 'primary')",
    ) == [(0,)]


def test_imp_59_r1_003_a_lost_worker_while_normalising_resumes_without_duplicates(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv(rows_for(range(1, 51))), meta())
    with pytest.raises(Killed):
        run(app_engine, store, tenant, batch.id, chunk_rows=20, after_normalise_chunk=kill)
    mid = batch_row(app_engine, tenant, batch.id)
    assert (mid.status, mid.lines_created) == ("normalising", 20)
    assert run(app_engine, store, tenant, batch.id, clock=at(10), chunk_rows=20) == "completed"
    done = batch_row(app_engine, tenant, batch.id)
    assert (done.attempts, done.lines_created, done.lines_unchanged) == (2, 50, 0)
    assert count(app_engine, tenant, "import_lines") == 50
    assert count(app_engine, tenant, "import_line_sources") == 50
