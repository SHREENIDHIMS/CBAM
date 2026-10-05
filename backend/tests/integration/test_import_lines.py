# ruff: noqa: F811, S608 - imported pytest fixtures are test arguments; SQL text is test-only
"""R1-005 / R1-006 / R1-010 normalisation into parties, declarations and import lines, with lineage.

Scenario IDs: IMP-37 replay and overlap create no duplicates (Phase 3 exit gate 3), IMP-38 every
line resolves to its source row, batch and file hash (exit gate 4), IMP-39 a changed source row is
a new version, IMP-40 exact code and mass, IMP-41 append-only tables, IMP-42 no tax point or
scope anywhere, IMP-43 customs value, IMP-44 rows with errors never normalise, IMP-45 the 500-row
gate, IMP-46 tenant isolation, IMP-49 impact provider, IMP-50 API.

Product rules, not law: no regulatory source applies. The layout is the PROVISIONAL synthetic
fixture (DATA-DEC-002); every value is synthetic.
"""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.audit import verify_chain
from app.core.db import tenant_session
from app.core.errors import TenantMismatchError
from app.core.storage import InMemoryStore
from app.modules.imports import impact, ledger
from app.modules.imports.processing import ImportJobError
from app.modules.refdata import rules as refdata_rules
from app.modules.refdata import service as refdata_service
from app.modules.refdata.service import Actor as RefActor
from tests.integration.conftest import make_tenant
from tests.integration.refdata_setup import activate, load, put_source_in_force
from tests.integration.test_import_processing import (  # noqa: F401
    CLOCK,
    HEADERS,
    NOW,
    batch_row,
    client,
    exceptions,
    expected_set,
    good_row,
    layout,
    owner,
    queued,
    receive,
    run,
    scalar,
    seeded_file,
    sql,
    store,
    to_csv,
    url,
    user_for,
)
from tests.refdata_helpers import CODES_V1, write_dataset

COMMODITY, MASS, DATE_COL, VALUE, CCY, ORIGIN, DESC = 4, 5, 1, 6, 7, 8, 11


def rows_for(numbers: range, **changes: dict[int, str]) -> list[list[str]]:
    out = []
    for i in numbers:
        row = good_row(i)
        for index, value in changes.get(str(i), {}).items():  # type: ignore[call-overload]
            row[index] = value
        out.append(row)
    return out


def q(engine: Engine, tenant: UUID, statement: str, **params: object) -> list[tuple]:  # type: ignore[type-arg]
    with tenant_session(engine, tenant_id=tenant) as s:
        return [tuple(r) for r in s.execute(text(statement), params)]


def count(engine: Engine, tenant: UUID, table: str) -> int:
    return int(q(engine, tenant, f"select count(*) from cbam.{table}")[0][0])


def import_rows(
    engine: Engine, store: InMemoryStore, tenant: UUID, rows: list[list[str]], **kw: object
) -> UUID:
    batch = receive(engine, store, tenant, to_csv(rows))
    run(engine, store, tenant, batch.id, **kw)
    return batch.id


# --- IMP-37: replay and overlapping files (exit gate 3) ---------------------------------------


def test_imp_37_r1_003_replaying_a_file_creates_no_new_declarations_or_lines(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    data = to_csv(rows_for(range(1, 31)))
    first = receive(app_engine, store, tenant, data)
    assert run(app_engine, store, tenant, first.id) == "completed"
    before = {t: count(app_engine, tenant, t) for t in TABLES}
    assert before == {
        "declarations": 30,
        "import_lines": 30,
        "import_line_sources": 30,
        "parties": 1,
    }
    replay = receive(app_engine, store, tenant, data)
    assert replay.replayed and replay.id == first.id  # the same bytes make no new batch
    assert run(app_engine, store, tenant, first.id) == "completed"  # nor does a second run
    assert {t: count(app_engine, tenant, t) for t in TABLES} == before


TABLES = ("declarations", "import_lines", "import_line_sources", "parties")


def test_imp_37_r1_003_an_overlapping_file_records_sightings_but_creates_nothing_new(
    app_engine: Engine, layout: UUID
) -> None:
    """Two 31-day-style reports that share days: different bytes, same rows for the overlap."""
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    one = import_rows(app_engine, store, tenant, rows_for(range(1, 41)))
    two = import_rows(app_engine, store, tenant, rows_for(range(21, 61)))
    assert count(app_engine, tenant, "declarations") == 60  # 1..60, the overlap not repeated
    assert count(app_engine, tenant, "import_lines") == 60
    a, b = batch_row(app_engine, tenant, one), batch_row(app_engine, tenant, two)
    assert (a.lines_created, a.lines_unchanged) == (40, 0)
    assert (b.lines_created, b.lines_unchanged) == (20, 20)
    assert (b.status, b.rows_valid) == ("completed", 40)
    seen = q(
        app_engine,
        tenant,
        "select l.batch_id, sr.batch_id from cbam.import_line_sources s"
        " join cbam.import_lines l on l.id = s.import_line_id"
        " join cbam.source_rows sr on sr.id = s.source_row_id where s.role = 'duplicate_seen'",
    )
    assert len(seen) == 20
    assert {(x, y) for x, y in seen} == {(one, two)}  # the sighting points at the first line


def test_imp_37_r1_003_two_overlapping_files_processed_at_once_make_no_duplicates(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    one = receive(app_engine, store, tenant, to_csv(rows_for(range(1, 41))))
    two = receive(app_engine, store, tenant, to_csv(rows_for(range(21, 61))))
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(lambda b: run(app_engine, store, tenant, b.id, chunk_rows=10), (one, two))
        )
    assert results == ["completed", "completed"]
    assert count(app_engine, tenant, "declarations") == 60
    assert count(app_engine, tenant, "import_lines") == 60
    created = batch_row(app_engine, tenant, one.id).lines_created
    created += batch_row(app_engine, tenant, two.id).lines_created
    assert created == 60


def test_imp_37_r1_003_a_crash_while_normalising_resumes_without_duplicates(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv(rows_for(range(1, 51))))

    def crash(_rows: int) -> None:
        raise RuntimeError("worker lost mid-normalisation")

    with pytest.raises(ImportJobError):
        run(app_engine, store, tenant, batch.id, chunk_rows=20, after_normalise_chunk=crash)
    mid = batch_row(app_engine, tenant, batch.id)
    assert (mid.status, mid.lines_created) == ("normalising", 20)
    assert run(app_engine, store, tenant, batch.id, chunk_rows=20) == "completed"
    done = batch_row(app_engine, tenant, batch.id)
    assert (done.lines_created, done.lines_unchanged) == (50, 0)
    assert count(app_engine, tenant, "import_lines") == 50
    assert count(app_engine, tenant, "import_line_sources") == 50


# --- IMP-38: lineage (exit gate 4) ---------------------------------------------------------------


def test_imp_38_r1_005_every_line_resolves_to_its_source_row_batch_and_file_hash(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    data = to_csv(rows_for(range(1, 26)))
    batch = receive(app_engine, store, tenant, data)
    run(app_engine, store, tenant, batch.id)
    assert q(
        app_engine,
        tenant,
        "select count(*) from cbam.import_lines l where not exists (select 1 from"
        " cbam.import_line_sources s where s.import_line_id = l.id and s.role = 'primary')",
    ) == [(0,)]
    rows = q(
        app_engine,
        tenant,
        "select l.item_no, sr.row_number, sr.batch_id, v.sha256, sr.raw ->> 'SYNTH_ITEM_NO'"
        " from cbam.import_lines l"
        " join cbam.import_line_sources s on s.import_line_id = l.id and s.role = 'primary'"
        " join cbam.source_rows sr on sr.id = s.source_row_id"
        " join cbam.import_batches b on b.id = sr.batch_id"
        " join cbam.document_versions v on v.id = b.document_version_id",
    )
    assert len(rows) == 25
    for item_no, row_number, source_batch, sha, raw_item in rows:
        assert source_batch == batch.id
        assert sha == hashlib.sha256(data).hexdigest()
        assert row_number == item_no == int(raw_item)  # the exact row, not just the file


def test_imp_38_r1_005_the_database_refuses_a_line_without_a_source_row(
    app_engine: Engine, admin_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    import_rows(app_engine, store, tenant, rows_for(range(1, 3)))
    with pytest.raises(DBAPIError, match="source_row_id"), owner(admin_engine, tenant) as s:
        s.execute(text(_INSERT_LINE.format(source="null", extra="")))


_INSERT_LINE = """
insert into cbam.import_lines (id, tenant_id, declaration_id, item_no, version, commodity_code,
  net_mass_kg, customs_value_source, customs_value_currency, country_of_origin_declared,
  batch_id, source_row_id, entry_method, content_sha256)
select gen_random_uuid(), tenant_id, declaration_id, 99{extra}, 1, '7208100000', 1, 1, 'GBP', 'DE',
  batch_id, {source}, 'cds', repeat('a', 64) from cbam.import_lines limit 1
"""


# --- IMP-39: a changed source row is a new version ---------------------------------------------


def test_imp_39_r1_005_a_changed_row_makes_version_two_and_keeps_version_one(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    one = import_rows(app_engine, store, tenant, rows_for(range(1, 6)))
    changed = rows_for(range(1, 6))
    changed[2][VALUE] = "9999.99"  # row 3: the customs value was corrected at source
    two = import_rows(app_engine, store, tenant, changed)
    b = batch_row(app_engine, tenant, two)
    assert (b.lines_created, b.lines_unchanged) == (1, 4)
    versions = q(
        app_engine,
        tenant,
        "select l.id, l.version, l.supersedes_id, l.change_reason, l.customs_value_source,"
        " l.batch_id from cbam.import_lines l where l.item_no = 3 order by l.version",
    )
    (v1, v2) = versions
    assert (v1[1], v1[2], v1[3], v1[4], v1[5]) == (1, None, None, Decimal("1234.56"), one)
    assert (v2[1], v2[2], v2[3], v2[4], v2[5]) == (
        2,
        v1[0],
        "source_changed",
        Decimal("9999.99"),
        two,
    )
    assert count(app_engine, tenant, "import_lines") == 6
    with tenant_session(app_engine, tenant_id=tenant) as s:
        current = ledger.list_lines(s, tenant)
        everything = ledger.list_lines(s, tenant, include_superseded=True)
        events = s.execute(
            text(
                "select after from cbam.audit_events where action = 'import_batch.lines_normalised'"
                " and object_id = :b"
            ),
            {"b": two},
        ).scalar_one()
    assert len(current.items) == 5 and all(i.is_current for i in current.items)
    assert len(everything.items) == 6
    assert {i.version for i in everything.items if i.item_no == 3} == {1, 2}
    assert events["superseded"] == [{"old": str(v1[0]), "new": str(v2[0])}]
    assert events["duplicates_seen"] == 4 and events["lines_superseded"] == 1


def test_imp_39_r1_005_a_changed_declaration_makes_version_two_under_the_same_reference(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    import_rows(app_engine, store, tenant, rows_for(range(1, 3)))
    changed = rows_for(range(1, 3))
    changed[0][DATE_COL] = "06/01/2027"
    import_rows(app_engine, store, tenant, changed)
    decls = q(
        app_engine,
        tenant,
        "select version, supersedes_id is not null, acceptance_date from cbam.declarations"
        " where mrn = 'MRN-SENTINEL-0001' order by version",
    )
    assert decls == [(1, False, date(2027, 1, 5)), (2, True, date(2027, 1, 6))]
    lines = q(
        app_engine,
        tenant,
        "select l.version, d.version from cbam.import_lines l join cbam.declarations d"
        " on d.id = l.declaration_id where d.mrn = 'MRN-SENTINEL-0001' order by l.version",
    )
    assert lines == [(1, 1), (2, 2)]  # the new line version sits under the new declaration


def test_imp_39_r1_005_conflicting_rows_in_one_file_are_all_rejected_not_first_wins(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    rows = rows_for(range(1, 4))
    twin = list(rows[0])
    twin[VALUE] = "1.00"  # same MRN and item as row 1, different value
    clash = list(good_row(2))
    clash[0] = rows[1][0]  # same MRN as row 2, another item, another acceptance date
    clash[3] = "9"
    clash[DATE_COL] = "09/09/2027"
    batch = import_rows(app_engine, store, tenant, [*rows, twin, clash])
    assert exceptions(app_engine, tenant, batch) == {
        (1, "line.item_no", "LINE_CONFLICT_IN_FILE"),  # BOTH rows of a key are rejected
        (4, "line.item_no", "LINE_CONFLICT_IN_FILE"),
        (2, "declaration.mrn", "DECLARATION_FACTS_CONFLICT"),  # and both of a declaration
        (5, "declaration.mrn", "DECLARATION_FACTS_CONFLICT"),
    }
    assert [r[0] for r in q(app_engine, tenant, "select item_no from cbam.import_lines")] == [3]
    row = batch_row(app_engine, tenant, batch)
    assert (row.status, row.rows_rejected, row.lines_created) == ("completed_with_errors", 4, 1)


def test_imp_39_r1_005_identical_rows_in_one_file_are_not_a_conflict(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = import_rows(app_engine, store, tenant, [*rows_for(range(1, 3)), good_row(1)])
    assert exceptions(app_engine, tenant, batch) == set()
    row = batch_row(app_engine, tenant, batch)
    assert (row.lines_created, row.lines_unchanged) == (2, 1)


# --- IMP-40 .. IMP-44 ------------------------------------------------------------------------------


def test_imp_40_r1_005_the_exact_code_and_six_decimal_mass_are_stored(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    rows = rows_for(range(1, 4))
    rows[0][COMMODITY], rows[0][MASS] = "0102030405", "0.000001"
    rows[1][COMMODITY], rows[1][MASS] = "72081000", "123456789.123456"
    rows[2][COMMODITY], rows[2][MASS] = "7208100099", "7"
    import_rows(app_engine, store, tenant, rows)
    got = q(
        app_engine,
        tenant,
        "select commodity_code, net_mass_kg, pg_typeof(net_mass_kg)::text from cbam.import_lines"
        " order by item_no",
    )
    assert [(c, m) for c, m, _ in got] == [
        ("0102030405", Decimal("0.000001")),
        ("72081000", Decimal("123456789.123456")),
        ("7208100099", Decimal("7.000000")),
    ]
    assert (
        str(got[0][1]) == "0.000001" and str(got[2][1]) == "7.000000"
    )  # six places, never rounded


def test_imp_41_r1_010_normalised_facts_are_append_only_for_the_app_and_the_owner(
    app_engine: Engine, admin_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    import_rows(app_engine, store, tenant, rows_for(range(1, 4)))
    for table in ("declarations", "import_lines", "import_line_sources", "parties"):
        for statement in (
            f"update cbam.{table} set tenant_id = tenant_id",
            f"delete from cbam.{table}",
        ):
            with pytest.raises(ProgrammingError, match="permission denied"):
                sql(app_engine, tenant, statement)
        with pytest.raises(ProgrammingError, match="permission denied"):
            sql(app_engine, tenant, f"truncate cbam.{table} cascade")
        for statement in (
            f"update cbam.{table} set tenant_id = tenant_id",
            f"delete from cbam.{table}",
            f"truncate cbam.{table} cascade",
        ):
            with pytest.raises(DBAPIError, match="append-only"), owner(admin_engine, tenant) as s:
                s.execute(text(statement))


@pytest.mark.parametrize(
    "column,value",
    [
        ("customs_value_source", "1"),
        ("net_mass_kg", "1"),
        ("customs_value_gbp", "1"),
        ("commodity_code", "'7208100001'"),
        ("value_source", "'manual'"),
    ],
)
def test_imp_41_r1_010_value_fields_of_a_line_cannot_be_changed_in_place(
    app_engine: Engine, admin_engine: Engine, layout: UUID, column: str, value: str
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    import_rows(app_engine, store, tenant, rows_for(range(1, 3)))
    with pytest.raises(ProgrammingError, match="permission denied"):
        sql(app_engine, tenant, f"update cbam.import_lines set {column} = {value}")
    with pytest.raises(DBAPIError, match="append-only"), owner(admin_engine, tenant) as s:
        s.execute(text(f"update cbam.import_lines set {column} = {value}"))


def test_imp_41_r1_010_a_correction_needs_a_reason_and_a_valid_chain_even_from_the_owner(
    app_engine: Engine, admin_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    import_rows(app_engine, store, tenant, rows_for(range(1, 3)))
    correction = (
        "insert into cbam.import_lines (id, tenant_id, declaration_id, item_no, version,"
        " supersedes_id, commodity_code, net_mass_kg, customs_value_source,"
        " customs_value_currency, country_of_origin_declared, batch_id, source_row_id,"
        " entry_method, value_source, value_override_reason, change_reason, content_sha256)"
        " select gen_random_uuid(), tenant_id, declaration_id, item_no, {version}, {sup},"
        " commodity_code, net_mass_kg, 5, 'GBP', 'DE', batch_id, source_row_id, 'correction',"
        " 'correction', {reason}, 'value_correction', repeat('b', 64)"
        " from cbam.import_lines where item_no = 1"
    )
    cases = [
        ("2", "id", "null", "value_override_reason"),  # no reason
        ("2", "id", "'  '", "value_override_reason"),  # blank reason
        ("2", "null", "'x'", "check"),  # a correction must supersede something
        ("3", "id", "'x'", "chain is broken"),  # skips version 2
    ]
    for version, sup, reason, message in cases:
        with pytest.raises(DBAPIError, match=message), owner(admin_engine, tenant) as s:
            s.execute(text(correction.format(version=version, sup=sup, reason=reason)))
    with owner(admin_engine, tenant) as s:  # a proper correction is accepted
        s.execute(text(correction.format(version="2", sup="id", reason="'Invoice re-issued'")))
    assert count(app_engine, tenant, "import_lines") == 3


def test_imp_42_r1_005_no_normalised_table_has_a_tax_point_scope_quarter_or_threshold(
    app_engine: Engine, layout: UUID
) -> None:
    columns = {
        r[0]
        for r in q(
            app_engine,
            make_tenant(app_engine, "A"),
            "select column_name from information_schema.columns where table_schema = 'cbam'"
            " and table_name in ('declarations','import_lines','import_line_sources','parties')",
        )
    }
    assert "acceptance_date" in columns  # as the report gave it
    for banned in ("tax_point", "scope", "quarter", "threshold", "period", "liable"):
        assert not any(banned in c for c in columns), banned


def test_imp_42_r1_005_the_acceptance_date_is_never_copied_into_a_tax_point(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    import_rows(app_engine, store, tenant, rows_for(range(1, 3)))
    with tenant_session(app_engine, tenant_id=tenant) as s:
        page = ledger.list_lines(s, tenant)
    for item in page.items:
        assert not hasattr(item, "tax_point") and not hasattr(item, "quarter")
        assert item.acceptance_date == date(2027, 1, 5)
    assert count(app_engine, tenant, "decisions") == 0
    assert count(app_engine, tenant, "tasks") == 0


def test_imp_43_r1_010_the_gbp_value_is_set_only_for_a_gbp_declaration(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    rows = rows_for(range(1, 5))
    rows[1][CCY] = "GBP"
    rows[2][CCY], rows[2][VALUE] = "GBP", "10.005"
    rows[3][CCY], rows[3][VALUE] = "USD", "5"
    import_rows(app_engine, store, tenant, rows)
    got = q(
        app_engine,
        tenant,
        "select item_no, customs_value_source, customs_value_currency, customs_value_gbp,"
        " customs_value_gbp_note, fx_method, value_source from cbam.import_lines order by item_no",
    )
    assert got == [
        (1, Decimal("1234.56000000"), "EUR", None, "non_gbp_no_fx", None, "declared"),
        (2, Decimal("1234.56000000"), "GBP", Decimal("1234.56"), None, None, "declared"),
        (3, Decimal("10.00500000"), "GBP", None, "gbp_more_than_2dp", None, "declared"),
        (4, Decimal("5.00000000"), "USD", None, "non_gbp_no_fx", None, "declared"),
    ]


def test_imp_44_r1_025_rows_with_errors_never_normalise_and_warning_only_rows_do(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    rows = rows_for(range(1, 5))
    rows[0][COMMODITY] = "7208"  # error
    rows[1][10] = ""  # supplier missing: a warning only
    rows[2][MASS] = "-1"  # error
    batch = import_rows(app_engine, store, tenant, rows)
    assert {i[0] for i in q(app_engine, tenant, "select item_no from cbam.import_lines")} == {2, 4}
    assert q(app_engine, tenant, "select count(*) from cbam.import_line_sources") == [(2,)]
    row = batch_row(app_engine, tenant, batch)
    assert (row.status, row.rows_rejected, row.rows_valid, row.lines_created) == (
        "completed_with_errors",
        2,
        2,
        2,
    )
    warned = q(
        app_engine,
        tenant,
        "select l.item_no, count(e.id) from cbam.import_lines l"
        " join cbam.import_line_sources s on s.import_line_id = l.id"
        " left join cbam.row_exceptions e on e.source_row_id = s.source_row_id"
        " and e.severity = 'warning' group by l.item_no order by l.item_no",
    )
    assert warned == [(2, 1), (4, 0)]


def test_imp_44_r1_025_a_layout_missing_a_line_field_is_refused_before_any_row_is_read(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    headers = [h for h in HEADERS if h != "SYNTH_ORIGIN"]
    rows = [[c for i, c in enumerate(r) if i != ORIGIN] for r in rows_for(range(1, 3))]
    batch = receive(app_engine, store, tenant, to_csv(rows, headers))
    assert run(app_engine, store, tenant, batch.id) == "rejected"
    assert exceptions(app_engine, tenant, batch.id) == {(0, "SYNTH_ORIGIN", "COLUMN_MISSING")}
    assert count(app_engine, tenant, "import_lines") == 0


# --- IMP-45: the 500-row gate, end to end ------------------------------------------------------------


def test_imp_45_r1_025_the_500_row_file_with_37_bad_rows_makes_463_lines_and_37_exceptions(
    app_engine: Engine, layout: UUID
) -> None:
    """Phase 3 exit gate 1, end to end: valid rows become lines, bad rows are reported per row."""
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    data, expected = seeded_file()
    batch = receive(app_engine, store, tenant, data)
    assert run(app_engine, store, tenant, batch.id) == "completed_with_errors"
    row = batch_row(app_engine, tenant, batch.id)
    assert (row.rows_total, row.rows_valid, row.rows_rejected) == (500, 463, 37)
    assert (row.lines_created, row.lines_unchanged) == (463, 0)
    assert exceptions(app_engine, tenant, batch.id) == expected_set(expected)  # nothing new
    assert count(app_engine, tenant, "import_lines") == 463
    assert count(app_engine, tenant, "declarations") == 463
    assert count(app_engine, tenant, "import_line_sources") == 463
    with tenant_session(app_engine, tenant_id=tenant) as s:
        events = list(
            s.execute(
                text(
                    "select after::text from cbam.audit_events"
                    " where action = 'import_batch.lines_normalised'"
                )
            ).scalars()
        )
        everything = s.execute(
            text(
                "select coalesce(string_agg(after::text || before::text, ' '), '') from cbam.audit_events"
            )
        ).scalar_one()
        assert verify_chain(s, tenant).ok
    assert len(events) == 1
    for sentinel in ("SENTINEL", "GB123456789012", "7208100000", "1234.56", "a.csv"):
        assert sentinel not in everything, sentinel


def test_imp_45_r1_025_the_audit_event_of_a_chunk_has_counts_and_at_most_500_ids(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = import_rows(app_engine, store, tenant, rows_for(range(1, 1201)), chunk_rows=1000)
    with tenant_session(app_engine, tenant_id=tenant) as s:
        events = [
            e
            for e in s.execute(
                text(
                    "select after from cbam.audit_events where object_id = :b"
                    " and action = 'import_batch.lines_normalised' order by id"
                ),
                {"b": batch},
            ).scalars()
        ]
    assert [e["rows"] for e in events] == [500, 500, 200]  # a chunk never exceeds 500 rows
    assert all(len(e["line_ids"]) <= 500 and len(e["declaration_ids"]) <= 500 for e in events)
    assert sum(e["lines_created"] for e in events) == 1200


# --- IMP-46: tenant isolation --------------------------------------------------------------------------


def test_imp_46_r1_005_tenant_b_sees_none_of_tenant_as_lines_declarations_parties_or_sources(
    app_engine: Engine, layout: UUID
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    store = InMemoryStore()
    import_rows(app_engine, store, a, rows_for(range(1, 4)))
    for table in TABLES:
        assert count(app_engine, a, table) > 0
        assert count(app_engine, b, table) == 0
    line_id = q(app_engine, a, "select id from cbam.import_lines limit 1")[0][0]
    with tenant_session(app_engine, tenant_id=b) as s:
        with pytest.raises(TenantMismatchError):
            ledger.get_line(s, b, line_id)
        assert ledger.list_lines(s, b).items == []
    with pytest.raises(DBAPIError):  # B cannot write rows for A either
        sql(
            app_engine,
            b,
            "insert into cbam.parties (id, tenant_id, eori) values (gen_random_uuid(), :a,"
            " 'GB000000000001')",
            a=a,
        )


def test_imp_46_r1_005_the_app_filters_by_tenant_even_when_row_level_security_is_off(
    app_engine: Engine, admin_engine: Engine, layout: UUID
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    store = InMemoryStore()
    import_rows(app_engine, store, a, rows_for(range(1, 4)))
    import_rows(app_engine, store, b, rows_for(range(10, 12)))
    line_a = q(app_engine, a, "select id from cbam.import_lines limit 1")[0][0]
    decl_a = q(app_engine, a, "select id from cbam.declarations limit 1")[0][0]
    with admin_engine.connect() as conn:
        outer = conn.begin()
        try:
            conn.execute(text("set local role cbam_owner"))
            for table in (*TABLES, "source_rows", "row_exceptions", "import_batches"):
                conn.execute(text(f"alter table cbam.{table} no force row level security"))
            session = Session(conn)
            assert session.execute(text("select count(*) from cbam.import_lines")).scalar_one() == 5
            with pytest.raises(TenantMismatchError):
                ledger.get_line(session, b, line_a)
            with pytest.raises(TenantMismatchError):
                ledger.get_declaration(session, b, decl_a)
            assert len(ledger.list_lines(session, b).items) == 2
            assert len(ledger.list_lines(session, a).items) == 3
            assert {i.batch_id for i in ledger.list_lines(session, a).items} == {
                ledger.get_line(session, a, line_a).line.batch_id
            }
        finally:
            outer.rollback()


# --- IMP-49: the commodity-code impact provider ----------------------------------------------------------


def test_imp_49_r1_005_the_impact_function_returns_counts_only_and_is_locked_down(
    app_engine: Engine, admin_engine: Engine, layout: UUID
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    store = InMemoryStore()
    rows = rows_for(range(1, 4))
    rows[0][COMMODITY] = "7204100000"
    import_rows(app_engine, store, a, rows)
    changed = rows_for(range(1, 4))
    changed[0][COMMODITY], changed[0][VALUE] = "7204100000", "5"  # a new version supersedes
    import_rows(app_engine, store, a, changed)
    other = rows_for(range(20, 22))
    other[0][COMMODITY] = "7204200000"
    import_rows(app_engine, store, b, other)
    with tenant_session(app_engine, tenant_id=None, platform=True) as s:
        cur = s.execute(
            text("select * from cbam.impact_line_counts_by_code_prefix(array['7204','xx%','72'])")
        )
        assert list(cur.keys()) == ["prefix", "tenant_id", "line_count"]  # no id, no value
        got = {(r[0], r[1]): r[2] for r in cur}
    # A: the superseded version is not counted; 'xx%' matches nothing
    assert got == {("7204", a): 1, ("7204", b): 1, ("72", a): 3, ("72", b): 2}
    with tenant_session(app_engine, tenant_id=None, platform=True) as s:
        assert {
            (r[0], r[1]): r[2]
            for r in s.execute(
                text("select * from cbam.impact_line_counts_by_code_prefix(array['7204'])")
            )
        } == {("7204", a): 1, ("7204", b): 1}
        assert (
            s.execute(text("select * from cbam.impact_line_counts_by_code_prefix(array[''])")).all()
            == []
        )
    meta = q(
        app_engine,
        a,
        "select p.prosecdef, pg_get_userbyid(p.proowner), p.proconfig::text,"
        " has_function_privilege('cbam_app', p.oid, 'execute'),"
        " has_function_privilege('public', p.oid, 'execute'),"
        " (select count(*) from pg_proc q2 where q2.proname = p.proname)"
        " from pg_proc p where p.proname = 'impact_line_counts_by_code_prefix'",
    )
    assert meta == [(True, "cbam_impact_reader", '{"search_path=cbam, pg_temp"}', True, False, 1)]
    # the function refuses a tenant session and an oversized list; it is for platform mode only
    with pytest.raises(DBAPIError, match="platform"):
        q(app_engine, a, "select * from cbam.impact_line_counts_by_code_prefix(array['72'])")
    with (
        pytest.raises(DBAPIError, match="at most 1000"),
        tenant_session(app_engine, tenant_id=None, platform=True) as s,
    ):
        s.execute(
            text(
                "select * from cbam.impact_line_counts_by_code_prefix(array_fill('72'::text, array[1001]))"
            )
        )
    with tenant_session(app_engine, tenant_id=None, platform=True) as s:  # 1000 is still fine
        assert (
            s.execute(
                text(
                    "select count(*) from cbam.impact_line_counts_by_code_prefix(array_fill('7204'::text, array[1000]))"
                )
            ).scalar_one()
            == 2
        )
    # neither the table owner nor the app role has a cross-tenant policy on the lines
    assert q(
        app_engine,
        a,
        "select count(*) from pg_policies where tablename = 'import_lines'"
        " and ('cbam_owner' = any(roles) or 'cbam_app' = any(roles))",
    ) == [(0,)]
    # a table read is still tenant-isolated for the app role: only the function crosses tenants
    assert count(app_engine, b, "import_lines") == 2


def test_imp_49_r1_005_the_phase_2_report_shows_counts_per_tenant_for_a_changed_prefix(
    app_engine: Engine, admin_engine: Engine, layout: UUID, tmp_path: object
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    store = InMemoryStore()
    rows = rows_for(range(1, 4))
    rows[0][COMMODITY] = "7204100000"
    rows[1][COMMODITY] = "7204300000"
    import_rows(app_engine, store, a, rows)
    other = rows_for(range(30, 32))
    other[0][COMMODITY] = "7204200000"
    import_rows(app_engine, store, b, other)

    load(app_engine, write_dataset(tmp_path))  # type: ignore[arg-type]
    put_source_in_force(app_engine, layout, "TEST-SOURCE")
    activate(app_engine, layout, "cbam_commodity_codes", "t.1")
    refdata_service.clear_impact_providers()
    impact.register()
    v2 = CODES_V1.replace("7204,Except 7204,iron_and_steel,Ferrous waste and scrap,,false,72\n", "")
    load(app_engine, write_dataset(tmp_path, version="t.2", csv=v2))  # type: ignore[arg-type]
    with tenant_session(app_engine, tenant_id=None, user_id=layout, platform=True) as s:
        report = refdata_service.build_impact_report(
            s, RefActor(layout), NOW, "cbam_commodity_codes", "t.2"
        )
    assert report["affected"]["provider_registered"] is True
    items = {i["ref"]: i for i in report["affected"]["items"]}
    assert set(items) == {str(a), str(b)}
    assert items[str(a)] == {
        "kind": "import_lines",
        "ref": str(a),
        "detail": "2 current line(s) under 7204",
        "group": "7204",
        "count": 2,
    }
    assert items[str(b)]["detail"] == "1 current line(s) under 7204"
    assert isinstance(refdata_rules.VersionDiff, type)


# --- IMP-50: API -------------------------------------------------------------------------------------------


def test_imp_50_r1_005_the_line_detail_shows_every_source_row_the_batch_and_the_file(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    headers = user_for(app_engine, tenant, "tax_agent")
    data = to_csv(rows_for(range(1, 4)))
    batch = receive(app_engine, store, tenant, data)
    run(app_engine, store, tenant, batch.id)
    again = rows_for(range(2, 6))
    again[0][VALUE] = "7.00"  # item 2 changes; item 3 is only seen again
    second = import_rows(app_engine, store, tenant, again)
    base = f"/api/v1/tenants/{tenant}"
    page = client.get(f"{base}/import-lines?include_superseded=true", headers=headers).json()
    two = next(i for i in page["items"] if i["item_no"] == 2 and i["version"] == 2)
    detail = client.get(f"{base}/import-lines/{two['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["line"]["customs_value_source"] == "7.00000000"
    assert body["line"]["customs_value_gbp"] is None
    assert [v["version"] for v in body["versions"]] == [1, 2]
    assert [v["is_current"] for v in body["versions"]] == [False, True]
    assert body["batch"]["id"] == str(second)
    assert body["file"]["sha256"] and body["file"]["size_bytes"] > 0
    assert "download" not in str(body).lower() and "storage_key" not in str(body)
    assert [s["role"] for s in body["sources"]] == ["primary"]
    assert body["sources"][0]["raw"]["SYNTH_MRN"] == "MRN-SENTINEL-0002"
    assert body["declaration"]["id"] == two["declaration_id"]
    assert body["declaration"]["importer"]["eori"] == "GB123456789012"
    assert body["declaration"]["representation_type"] == "unknown"
    assert body["declaration"]["eori_context"] == "GB"
    for banned in ("tax_point", "scope", "quarter", "threshold"):
        assert banned not in str(body)
    # item 3 was seen again: its detail lists both rows (and both files)
    three = next(i for i in page["items"] if i["item_no"] == 3)
    seen = client.get(f"{base}/import-lines/{three['id']}", headers=headers).json()
    assert sorted(s["role"] for s in seen["sources"]) == ["duplicate_seen", "primary"]
    assert {s["batch_id"] for s in seen["sources"]} == {str(batch.id), str(second)}
    decl = client.get(f"{base}/declarations/{two['declaration_id']}", headers=headers)
    assert decl.status_code == 200 and decl.json()["mrn"] == "MRN-SENTINEL-0002"


def test_imp_50_r1_005_list_filters_and_pagination(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    headers = user_for(app_engine, tenant, "operations")
    rows = rows_for(range(1, 9))
    rows[0][COMMODITY], rows[1][COMMODITY] = "7204100000", "7204200000"
    rows[2][ORIGIN] = "TR"
    rows[3][DATE_COL] = "20/02/2027"
    rows[4][10] = ""  # supplier warning: an open exception on the line
    batch = import_rows(app_engine, store, tenant, rows)
    base = f"/api/v1/tenants/{tenant}/import-lines"

    def items(query: str = "") -> list[dict]:  # type: ignore[type-arg]
        r = client.get(f"{base}?{query}", headers=headers)
        assert r.status_code == 200, r.text
        return r.json()["items"]  # type: ignore[no-any-return]

    assert len(items()) == 8
    assert {i["item_no"] for i in items("commodity_code=7204")} == {1, 2}
    assert {i["item_no"] for i in items("commodity_code=72041")} == {1}
    assert {i["item_no"] for i in items("origin=TR")} == {3}
    assert {i["item_no"] for i in items("from=2027-02-01")} == {4}
    assert {i["item_no"] for i in items("to=2027-01-31")} == {1, 2, 3, 5, 6, 7, 8}
    assert len(items(f"batch_id={batch}")) == 8 and items(f"batch_id={UUID(int=1)}") == []
    assert len(items("entry_method=gcd")) == 8 and items("entry_method=cds") == []
    assert {i["item_no"] for i in items("has_open_exceptions=true")} == {5}
    assert len(items("has_open_exceptions=false")) == 7
    first = client.get(f"{base}?limit=3", headers=headers).json()
    assert len(first["items"]) == 3 and first["next_cursor"]
    seen = {i["id"] for i in first["items"]}
    cursor = first["next_cursor"]
    while cursor:
        nxt = client.get(f"{base}?limit=3&cursor={cursor}", headers=headers).json()
        assert not seen & {i["id"] for i in nxt["items"]}
        seen |= {i["id"] for i in nxt["items"]}
        cursor = nxt["next_cursor"]
    assert len(seen) == 8
    for bad in ("commodity_code=ab", "origin=de", "entry_method=x", "cursor=%%", "limit=0"):
        assert client.get(f"{base}?{bad}", headers=headers).status_code in (400, 422), bad


def test_imp_50_r1_005_permissions_and_tenancy_of_the_ledger_routes(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    import_rows(app_engine, store, a, rows_for(range(1, 3)))
    line = q(app_engine, a, "select id, declaration_id from cbam.import_lines limit 1")[0]
    base = f"/api/v1/tenants/{a}"
    paths = [
        f"{base}/import-lines",
        f"{base}/import-lines/{line[0]}",
        f"{base}/declarations/{line[1]}",
    ]
    for role, expected in (("tax_agent", 200), ("operations", 200), ("supplier", 403)):
        headers = user_for(app_engine, a, role)
        assert [client.get(p, headers=headers).status_code for p in paths] == [expected] * 3, role
    outsider = user_for(app_engine, b, "operations")  # a member of another tenant only
    assert [client.get(p, headers=outsider).status_code for p in paths] == [404] * 3
    other = f"/api/v1/tenants/{b}"
    own = user_for(app_engine, b, "operations")
    assert client.get(f"{other}/import-lines/{line[0]}", headers=own).status_code == 404
    assert client.get(f"{other}/declarations/{line[1]}", headers=own).status_code == 404
    assert client.get(f"{other}/import-lines", headers=own).json()["items"] == []
    assert url(a, line[0])  # the batch URL helper stays importable for the module


def test_imp_50_r1_005_nothing_the_api_returns_for_a_line_is_a_float() -> None:
    from app.modules.imports.schemas import ImportLineOut

    for name, field in ImportLineOut.model_fields.items():
        assert "float" not in str(field.annotation), name
