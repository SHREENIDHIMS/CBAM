"""R1-025 raw rows, row validation, exception report and the processing job; R1-003 replay safety.

Scenario IDs: IMP-10 500-row file with 37 seeded bad rows (Phase 3 exit gate), IMP-11 missing
column, IMP-12 layout not active / new layout, IMP-13 crash and resume, IMP-14 second run,
IMP-15 precision and exact commodity codes, IMP-16 CSV export, IMP-17 immutability and tenancy.

Product rules, not law: no regulatory source applies. The layout is the PROVISIONAL synthetic
fixture (DATA-DEC-002): every SYNTH_* column name is invented and is not an HMRC heading.
"""

import csv
import io
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.audit import verify_chain
from app.core.clock import FrozenClock, get_clock
from app.core.config import Settings, get_settings
from app.core.db import tenant_session
from app.core.errors import StorageError, TenantMismatchError
from app.core.storage import InMemoryStore, get_object_store
from app.core.tenancy import get_engine_dep, get_verifier
from app.main import create_app
from app.modules.imports import processing, service
from app.modules.imports.jobs import Enqueuer, get_enqueuer
from app.modules.imports.processing import ImportJobError, process_batch
from app.modules.imports.schemas import ImportBatchMetadata
from app.modules.imports.service import Actor
from tests.helpers_auth import bearer, verifier
from tests.integration.conftest import make_member, make_tenant, make_user
from tests.integration.refdata_setup import (
    activate,
    load,
    make_owner,
    put_source_in_force,
    reset_refdata,
)
from tests.refdata_helpers import FIXTURES, write_dataset

NOW = datetime(2027, 3, 1, 9, 0, tzinfo=UTC)
CLOCK = FrozenClock(NOW)
META = ImportBatchMetadata(
    acquisition_method="get_customs_data", cds_report_type="import_item", eori="GB123456789012"
)
SOURCE = "FIXTURE-TEST-SOURCE"
HEADERS = [
    "SYNTH_MRN",
    "SYNTH_ACCEPTANCE_DATE",
    "SYNTH_EORI",
    "SYNTH_ITEM_NO",
    "SYNTH_COMMODITY_CODE",
    "SYNTH_NET_MASS_KG",
    "SYNTH_CUSTOMS_VALUE",
    "SYNTH_CURRENCY",
    "SYNTH_ORIGIN",
    "SYNTH_VALUATION_BASIS",
    "SYNTH_SUPPLIER",
    "SYNTH_DESCRIPTION",
    "EXTRA_NOTE",
]


@pytest.fixture
def layout(app_engine: Engine, admin_engine: Engine) -> UUID:
    """The synthetic layout, loaded and ACTIVE (source in force, version activated)."""
    reset_refdata(admin_engine)
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, FIXTURES / "cds_report_layouts" / "fixture.1")
    put_source_in_force(app_engine, owner, SOURCE)
    activate(app_engine, owner, "cds_report_layouts", "fixture.1")
    return owner


def good_row(i: int) -> list[str]:
    return [
        f"MRN-SENTINEL-{i:04d}",
        "05/01/2027",
        "GB123456789012",
        str(i),
        "7208100000",
        f"{i}.500000",
        "1234.56",
        "EUR",
        "DE",
        "1",
        f"SUPPLIER-SENTINEL-{i}",
        f"DESC-SENTINEL-{i}",
        "note",
    ]


def to_csv(rows: list[list[str]], headers: list[str] | None = None) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(headers or HEADERS)
    writer.writerows(rows)
    return out.getvalue().encode()


# defect name -> (how to damage a good row, the exceptions it must produce)
def _set(index: int, value: str) -> Callable[[list[str]], list[str]]:
    def apply(row: list[str]) -> list[str]:
        row[index] = value
        return row

    return apply


COMMODITY, MASS, DATE, ORIGIN, VALUE, CCY = 4, 5, 1, 8, 6, 7
DEFECTS: list[tuple[Callable[[list[str]], list[str]], set[tuple[str, str]]]] = [
    (_set(COMMODITY, ""), {("line.commodity_code", "COMMODITY_CODE_MISSING")}),
    (_set(COMMODITY, "7208"), {("line.commodity_code", "COMMODITY_CODE_INVALID")}),
    (_set(MASS, ""), {("line.net_mass_kg", "NET_MASS_MISSING")}),
    (_set(MASS, "-4"), {("line.net_mass_kg", "NET_MASS_INVALID")}),
    (_set(MASS, "1.1234567"), {("line.net_mass_kg", "NET_MASS_PRECISION")}),
    (_set(DATE, ""), {("declaration.acceptance_date", "ACCEPTANCE_DATE_MISSING")}),
    (_set(DATE, "2027-01-05"), {("declaration.acceptance_date", "ACCEPTANCE_DATE_INVALID")}),
    (_set(ORIGIN, ""), {("line.origin_country", "ORIGIN_MISSING")}),
    (_set(ORIGIN, "Germany"), {("line.origin_country", "ORIGIN_INVALID")}),
    (_set(VALUE, ""), {("line.customs_value", "VALUE_MISSING")}),
    (_set(VALUE, "abc"), {("line.customs_value", "VALUE_INVALID")}),
    (_set(CCY, "EURO"), {("line.customs_value_currency", "CURRENCY_INVALID")}),
    (
        lambda r: _set(MASS, "x")(_set(COMMODITY, "")(r)),
        {
            ("line.commodity_code", "COMMODITY_CODE_MISSING"),
            ("line.net_mass_kg", "NET_MASS_INVALID"),
        },
    ),
    (lambda r: [*r, "one cell too many"], {("", "ROW_TOO_LONG")}),
    (
        lambda r: r[:9],  # the supplier cell is gone as well: a warning, not an error
        {("", "ROW_TOO_SHORT"), ("line.supplier_ref", "SUPPLIER_UNMAPPED")},
    ),
]
BAD_EVERY = 13
WARNING_ONLY_ROWS = (2, 3, 4)


def seeded_file(total: int = 500, bad: int = 37) -> tuple[bytes, dict[int, set[tuple[str, str]]]]:
    """A file with `bad` damaged rows spread over the error codes, and `expected` problems."""
    expected: dict[int, set[tuple[str, str]]] = {}
    rows = []
    for number in range(1, total + 1):
        row = good_row(number)
        if number == 7:
            row[11] = "a quoted\nnew line, with a comma"  # one row spanning two lines
        if number in WARNING_ONLY_ROWS:
            row[10] = ""
            expected[number] = {("line.supplier_ref", "SUPPLIER_UNMAPPED")}
        rows.append(row)
    step = (total - 5) // bad if bad else 1
    for k in range(bad):
        number = 5 + step * k
        damage, problems = DEFECTS[k % len(DEFECTS)]
        rows[number - 1] = damage(rows[number - 1])
        expected[number] = problems
    return to_csv(rows), expected


def receive(
    engine: Engine,
    store: InMemoryStore,
    tenant: UUID,
    data: bytes,
    meta: ImportBatchMetadata = META,
):  # type: ignore[no-untyped-def]
    scanned = service.scan_upload(io.BytesIO(data), max_bytes=10_000_000)
    return service.receive_file(
        lambda: tenant_session(engine, tenant_id=tenant),
        store=store,
        tenant_id=tenant,
        actor=Actor("system", None),
        now=NOW,
        as_of=NOW.date(),
        file=io.BytesIO(data),
        scanned=scanned,
        filename="a.csv",
        metadata=meta,
    )


def run(engine: Engine, store: InMemoryStore, tenant: UUID, batch: UUID, **kw: object) -> str:
    return process_batch(engine, store, CLOCK, tenant, batch, **kw)  # type: ignore[arg-type]


def batch_row(engine: Engine, tenant: UUID, batch: UUID):  # type: ignore[no-untyped-def]
    with tenant_session(engine, tenant_id=tenant) as s:
        return s.execute(
            text("select * from cbam.import_batches where id = :i"), {"i": batch}
        ).one()


def exceptions(
    engine: Engine, tenant: UUID, batch: UUID, **where: object
) -> set[tuple[int, str, str]]:
    sql = "select row_number, field, code from cbam.row_exceptions where batch_id = :b"
    sql += "".join(f" and {k} = :{k}" for k in where)
    with tenant_session(engine, tenant_id=tenant) as s:
        return {(r[0], r[1], r[2]) for r in s.execute(text(sql), {"b": batch, **where})}


def scalar(engine: Engine, tenant: UUID | None, sql: str, **params: object) -> object:
    with tenant_session(engine, tenant_id=tenant) as s:
        return s.execute(text(sql), params).scalar()


def expected_set(expected: dict[int, set[tuple[str, str]]]) -> set[tuple[int, str, str]]:
    return {(n, f, c) for n, items in expected.items() for f, c in items}


# --- IMP-10: the exit gate ---------------------------------------------------------------


def test_imp_10_r1_025_500_rows_with_37_bad_rows_report_each_and_valid_rows_continue(
    app_engine: Engine, layout: UUID
) -> None:
    """Phase 3 exit gate 1: bad rows appear in an actionable exception report, valid rows go on."""
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    data, expected = seeded_file()
    batch = receive(app_engine, store, tenant, data)
    assert run(app_engine, store, tenant, batch.id) == "completed_with_errors"

    row = batch_row(app_engine, tenant, batch.id)
    assert (row.rows_total, row.rows_processed) == (500, 500)
    assert (row.rows_rejected, row.rows_valid) == (37, 463)
    assert row.layout_status == "matched" and row.report_layout_version_id is not None
    assert row.failure_reason is None
    assert exceptions(app_engine, tenant, batch.id) == expected_set(expected)
    errors = {n for n, items in expected.items() if any(c != "SUPPLIER_UNMAPPED" for _, c in items)}
    assert len(errors) == 37
    # a warning-only row is valid, and every row is stored (valid rows continue)
    assert exceptions(app_engine, tenant, batch.id, severity="warning") == {
        (n, f, c) for n, f, c in expected_set(expected) if c == "SUPPLIER_UNMAPPED"
    }
    assert scalar(app_engine, tenant, "select count(*) from cbam.source_rows") == 500
    with tenant_session(app_engine, tenant_id=tenant) as s:
        # a tax point or a normalised line is not created by this step
        assert (
            s.execute(
                text(
                    "select count(*) from cbam.audit_events where action = 'import_batch.rows_processed'"
                )
            ).scalar_one()
            == 1
        )


def test_imp_10_r1_025_every_raw_row_is_kept_exactly_as_read_with_its_hash(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    data, _ = seeded_file(total=20, bad=0)
    batch = receive(app_engine, store, tenant, data)
    run(app_engine, store, tenant, batch.id)
    parsed = list(csv.reader(io.StringIO(data.decode(), newline="")))
    with tenant_session(app_engine, tenant_id=tenant) as s:
        rows = s.execute(
            text("select row_number, raw, row_sha256 from cbam.source_rows order by row_number")
        ).all()
    assert len(rows) == 20
    for stored, cells in zip(rows, parsed[1:], strict=True):
        assert stored.raw == dict(zip(parsed[0], cells, strict=True))
        assert len(stored.row_sha256) == 64
    assert rows[6].raw["SYNTH_DESCRIPTION"] == "a quoted\nnew line, with a comma"


def test_imp_10_r1_025_audit_has_one_event_per_chunk_and_no_cell_values(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    data, _ = seeded_file(total=250, bad=0)
    batch = receive(app_engine, store, tenant, data)
    run(app_engine, store, tenant, batch.id, chunk_rows=100)
    with tenant_session(app_engine, tenant_id=tenant) as s:
        events = s.execute(
            text("select action, after from cbam.audit_events where object_id = :b order by id"),
            {"b": batch.id},
        ).all()
        everything = s.execute(
            text(
                "select coalesce(string_agg(after::text || before::text, ' '), '') from cbam.audit_events"
            )
        ).scalar_one()
    chunks = [e.after for e in events if e.action == "import_batch.rows_processed"]
    assert [c["rows"] for c in chunks] == [100, 100, 50]
    assert chunks[-1]["rows_total"] == 250
    statuses = [e.after["status"] for e in events if e.action == "import_batch.status_changed"]
    assert statuses == ["queued", "parsing", "validating", "completed"]
    for sentinel in ("SENTINEL", "a.csv", "GB123456789012", "1234.56"):
        assert sentinel not in everything, sentinel
    with tenant_session(app_engine, tenant_id=tenant) as s:
        assert verify_chain(s, tenant).ok  # the job's events join the tenant's hash chain


def test_imp_10_r1_025_exception_messages_are_fixed_text_without_cell_values(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    row = good_row(1)
    row[COMMODITY] = "SECRET-CODE-VALUE"
    row[MASS] = "SECRET-MASS-VALUE"
    batch = receive(app_engine, store, tenant, to_csv([row]))
    assert run(app_engine, store, tenant, batch.id) == "completed_with_errors"
    with tenant_session(app_engine, tenant_id=tenant) as s:
        messages = list(s.execute(text("select message from cbam.row_exceptions")).scalars())
    assert len(messages) == 2
    assert not any("SECRET" in m for m in messages)
    assert all(len(m) > 20 for m in messages)


def test_imp_10_r1_025_a_clean_file_completes_with_no_exceptions(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv([good_row(i) for i in range(1, 4)]))
    assert run(app_engine, store, tenant, batch.id) == "completed"
    assert scalar(app_engine, tenant, "select count(*) from cbam.row_exceptions") == 0
    row = batch_row(app_engine, tenant, batch.id)
    assert (row.rows_total, row.rows_valid, row.rows_rejected) == (3, 3, 0)


def test_imp_10_r1_025_bom_and_unknown_columns_are_fine(app_engine: Engine, layout: UUID) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    data = b"\xef\xbb\xbf" + to_csv([good_row(1)], headers=[*HEADERS[:-1], "WHO KNOWS"])
    batch = receive(app_engine, store, tenant, data)
    assert run(app_engine, store, tenant, batch.id) == "completed"
    raw = scalar(app_engine, tenant, "select raw from cbam.source_rows")
    assert raw["SYNTH_MRN"] == "MRN-SENTINEL-0001" and raw["WHO KNOWS"] == "note"  # type: ignore[index]


# --- IMP-11 / IMP-12: layout -------------------------------------------------------------


def test_imp_11_r1_025_a_missing_required_column_rejects_the_file_naming_each_column(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    keep = [h for h in HEADERS if h not in ("SYNTH_NET_MASS_KG", "SYNTH_ORIGIN")]
    rows = [[c for h, c in zip(HEADERS, good_row(1), strict=True) if h in keep]]
    batch = receive(app_engine, store, tenant, to_csv(rows, headers=keep))
    assert run(app_engine, store, tenant, batch.id) == "rejected"
    row = batch_row(app_engine, tenant, batch.id)
    assert (row.layout_status, row.failure_reason) == ("columns_missing", "column_missing")
    assert exceptions(app_engine, tenant, batch.id) == {
        (0, "SYNTH_NET_MASS_KG", "COLUMN_MISSING"),
        (0, "SYNTH_ORIGIN", "COLUMN_MISSING"),
    }
    assert scalar(app_engine, tenant, "select count(*) from cbam.source_rows") == 0
    # the same bytes can be sent again once the file is fixed: a rejected batch is history
    assert receive(app_engine, store, tenant, to_csv(rows, headers=keep)).id != batch.id


def test_imp_11_r1_025_duplicate_headings_and_a_blank_header_row_are_rejected(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    dup = receive(app_engine, store, tenant, to_csv([], headers=[*HEADERS, "synth_mrn"]))
    assert run(app_engine, store, tenant, dup.id) == "rejected"
    assert exceptions(app_engine, tenant, dup.id) == {(0, "", "HEADER_DUPLICATE")}
    blank = receive(app_engine, store, tenant, b",,\n1,2,3\n")
    assert run(app_engine, store, tenant, blank.id) == "rejected"
    assert exceptions(app_engine, tenant, blank.id) == {(0, "", "HEADER_MISSING")}


def test_imp_11_r1_025_no_declared_report_type_is_rejected_with_a_code(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    meta = ImportBatchMetadata(acquisition_method="cds_export")
    batch = receive(app_engine, store, tenant, to_csv([good_row(1)]), meta)
    assert run(app_engine, store, tenant, batch.id) == "rejected"
    assert exceptions(app_engine, tenant, batch.id) == {(0, "", "REPORT_TYPE_MISSING")}


@pytest.mark.parametrize("state", ["not_loaded", "pending", "source_laid"])
def test_imp_12_r1_025_a_layout_that_is_not_active_is_never_used(
    app_engine: Engine, admin_engine: Engine, state: str
) -> None:
    """DATA-DEC-002 / CLAUDE.md rule 2: loaded is not active."""
    reset_refdata(admin_engine)
    owner = make_owner(app_engine, admin_engine)
    if state != "not_loaded":
        load(app_engine, FIXTURES / "cds_report_layouts" / "fixture.1")
    if state == "source_laid":
        activate(app_engine, owner, "cds_report_layouts", "fixture.1")  # source still `laid`
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv([good_row(1)]))
    assert run(app_engine, store, tenant, batch.id) == "rejected"
    row = batch_row(app_engine, tenant, batch.id)
    assert (row.layout_status, row.failure_reason) == ("not_active", "layout_not_active")
    assert row.report_layout_version_id is None
    assert exceptions(app_engine, tenant, batch.id) == {(0, "", "LAYOUT_NOT_ACTIVE")}
    assert scalar(app_engine, tenant, "select count(*) from cbam.source_rows") == 0


LAYOUT_V2 = """report_type,column_name,maps_to,required,date_format
import_item,Commodity Code,line.commodity_code,true,
import_item,Net Mass,line.net_mass_kg,true,
import_item,Accepted,declaration.acceptance_date,true,%Y-%m-%d
"""


def test_imp_12_r1_025_a_new_activated_layout_version_needs_no_code_change(
    app_engine: Engine, admin_engine: Engine, layout: UUID, tmp_path: object
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    old = receive(app_engine, store, tenant, to_csv([good_row(1)]))
    assert run(app_engine, store, tenant, old.id) == "completed"
    old_version = batch_row(app_engine, tenant, old.id).report_layout_version_id

    load(
        app_engine,
        write_dataset(
            tmp_path,  # type: ignore[arg-type]
            dataset="cds_report_layouts",
            version="synthetic.2",
            csv=LAYOUT_V2,
            source_id="LAYOUT-V2-SOURCE",
        ),
    )
    put_source_in_force(app_engine, layout, "LAYOUT-V2-SOURCE")
    activate(app_engine, layout, "cds_report_layouts", "synthetic.2")
    data = (
        b"Commodity Code,Net Mass,Accepted,Other\n7208100000,1.5,2027-01-05,x\n72,2,2027-13-45,y\n"
    )
    new = receive(app_engine, store, tenant, data)
    assert run(app_engine, store, tenant, new.id) == "completed_with_errors"
    row = batch_row(app_engine, tenant, new.id)
    assert row.report_layout_version_id not in (None, old_version)
    assert exceptions(app_engine, tenant, new.id) == {
        (2, "line.commodity_code", "COMMODITY_CODE_INVALID"),
        (2, "declaration.acceptance_date", "ACCEPTANCE_DATE_INVALID"),
    }
    # the first batch keeps the layout version it was read with
    assert batch_row(app_engine, tenant, old.id).report_layout_version_id == old_version


# --- IMP-13 / IMP-14: resume and replay --------------------------------------------------


def test_imp_13_r1_003_a_crash_mid_file_resumes_without_duplicates(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    data, expected = seeded_file(total=250, bad=18)
    batch = receive(app_engine, store, tenant, data)

    def crash(_rows: int) -> None:
        raise RuntimeError("worker killed after chunk 1")

    with pytest.raises(ImportJobError) as caught:
        run(app_engine, store, tenant, batch.id, chunk_rows=100, after_chunk=crash)
    assert str(caught.value) == "RuntimeError"  # only the class name survives
    assert caught.value.__cause__ is None
    mid = batch_row(app_engine, tenant, batch.id)
    assert (mid.status, mid.rows_total) == ("validating", 100)

    assert run(app_engine, store, tenant, batch.id, chunk_rows=100) == "completed_with_errors"
    row = batch_row(app_engine, tenant, batch.id)
    assert (row.rows_total, row.rows_processed) == (250, 250)
    assert scalar(app_engine, tenant, "select count(*) from cbam.source_rows") == 250
    assert (
        scalar(app_engine, tenant, "select count(distinct row_number) from cbam.source_rows") == 250
    )
    assert exceptions(app_engine, tenant, batch.id) == expected_set(expected)
    assert row.rows_rejected == len(
        {n for n, _, c in expected_set(expected) if c != "SUPPLIER_UNMAPPED"}
    )
    assert row.rows_valid == 250 - row.rows_rejected
    events = scalar(
        app_engine,
        tenant,
        "select count(*) from cbam.audit_events where action = 'import_batch.rows_processed'",
    )
    assert events == 3  # 100 + 100 + 50, each audited once


def test_imp_13_r1_003_a_resumed_batch_keeps_the_layout_version_it_started_with(
    app_engine: Engine, admin_engine: Engine, layout: UUID, tmp_path: object
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv([good_row(i) for i in range(1, 6)]))

    def crash(_rows: int) -> None:
        raise RuntimeError("killed")

    with pytest.raises(ImportJobError):
        run(app_engine, store, tenant, batch.id, chunk_rows=2, after_chunk=crash)
    started_with = batch_row(app_engine, tenant, batch.id).report_layout_version_id
    load(
        app_engine,
        write_dataset(
            tmp_path,  # type: ignore[arg-type]
            dataset="cds_report_layouts",
            version="synthetic.3",
            csv=LAYOUT_V2,
            source_id="LAYOUT-V3-SOURCE",
        ),
    )
    put_source_in_force(app_engine, layout, "LAYOUT-V3-SOURCE")
    activate(app_engine, layout, "cds_report_layouts", "synthetic.3")
    assert run(app_engine, store, tenant, batch.id, chunk_rows=2) == "completed"
    assert batch_row(app_engine, tenant, batch.id).report_layout_version_id == started_with
    assert scalar(app_engine, tenant, "select count(*) from cbam.row_exceptions") == 0


def test_imp_14_r1_003_running_a_completed_batch_again_changes_nothing(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    data, _ = seeded_file(total=60, bad=5)
    batch = receive(app_engine, store, tenant, data)
    assert run(app_engine, store, tenant, batch.id) == "completed_with_errors"
    before = (
        batch_row(app_engine, tenant, batch.id),
        scalar(app_engine, tenant, "select count(*) from cbam.source_rows"),
        scalar(app_engine, tenant, "select count(*) from cbam.row_exceptions"),
        scalar(app_engine, tenant, "select count(*) from cbam.audit_events"),
    )
    assert run(app_engine, store, tenant, batch.id) == "completed_with_errors"
    assert run(app_engine, store, tenant, batch.id) == "completed_with_errors"
    after = (
        batch_row(app_engine, tenant, batch.id),
        scalar(app_engine, tenant, "select count(*) from cbam.source_rows"),
        scalar(app_engine, tenant, "select count(*) from cbam.row_exceptions"),
        scalar(app_engine, tenant, "select count(*) from cbam.audit_events"),
    )
    assert after == before


def test_imp_14_r1_003_the_same_rows_inserted_twice_are_ignored(
    app_engine: Engine, layout: UUID
) -> None:
    """A chunk replayed by a second worker finds its rows and writes nothing, not even audit."""
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv([good_row(1), good_row(2)]))
    run(app_engine, store, tenant, batch.id)
    match = processing.rules.match_layout(
        processing.rules.raw_headers(HEADERS),
        processing.rules.layout_columns(
            [
                {
                    "report_type": "import_item",
                    "column_name": "SYNTH_MRN",
                    "maps_to": "declaration.mrn",
                    "required": True,
                }
            ],
            "import_item",
        ),
    )
    audit_before = scalar(app_engine, tenant, "select count(*) from cbam.audit_events")
    # chunk() refuses a finished batch outright; a live one ignores rows already stored
    assert (
        processing._chunk(
            app_engine, CLOCK, tenant, batch.id, tuple(HEADERS), match, [(1, good_row(1))]
        )
        == 0
    )
    assert scalar(app_engine, tenant, "select count(*) from cbam.audit_events") == audit_before


def test_imp_13_r1_003_retries_that_run_out_mark_the_batch_failed_with_a_short_code(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv([good_row(1)]))
    store.objects.clear()  # the stored file cannot be read
    with pytest.raises(ImportJobError, match="StorageError"):
        run(app_engine, store, tenant, batch.id)
    assert batch_row(app_engine, tenant, batch.id).status == "parsing"  # will be retried
    with pytest.raises(ImportJobError):
        run(app_engine, store, tenant, batch.id, final_attempt=True)
    row = batch_row(app_engine, tenant, batch.id)
    assert (row.status, row.failure_reason) == ("failed", "storage_unavailable")
    assert run(app_engine, store, tenant, batch.id) == "failed"  # final: nothing more happens


def test_imp_13_r1_003_an_unreadable_csv_is_rejected_not_retried(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    huge = "x" * 200_000  # larger than the csv module allows for one cell
    batch = receive(app_engine, store, tenant, to_csv([good_row(1), [huge, *good_row(2)[1:]]]))
    assert run(app_engine, store, tenant, batch.id) == "rejected"
    assert "FILE_UNREADABLE" in {c for _, _, c in exceptions(app_engine, tenant, batch.id)}
    assert scalar(app_engine, tenant, "select count(*) from cbam.source_rows") == 1


# --- IMP-15: precision and exact codes ---------------------------------------------------


def test_imp_15_r1_025_seven_decimal_places_are_reported_and_codes_stay_exact(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    rows = []
    for number, (code, mass) in enumerate(
        [("0123456789", "0.1234567"), ("01234567", "0.123456"), ("7208100000", "10.5000000")], 1
    ):
        row = good_row(number)
        row[COMMODITY], row[MASS] = code, mass
        rows.append(row)
    batch = receive(app_engine, store, tenant, to_csv(rows))
    assert run(app_engine, store, tenant, batch.id) == "completed_with_errors"
    assert exceptions(app_engine, tenant, batch.id) == {
        (1, "line.net_mass_kg", "NET_MASS_PRECISION")
    }
    with tenant_session(app_engine, tenant_id=tenant) as s:
        raw = (
            s.execute(text("select raw from cbam.source_rows order by row_number")).scalars().all()
        )
    assert [r["SYNTH_COMMODITY_CODE"] for r in raw] == ["0123456789", "01234567", "7208100000"]
    assert [r["SYNTH_NET_MASS_KG"] for r in raw] == ["0.1234567", "0.123456", "10.5000000"]


def test_imp_15_r1_025_no_tax_point_or_scope_is_decided_by_row_validation(
    app_engine: Engine, layout: UUID
) -> None:
    """The acceptance date is kept as given; nothing here writes a tax point or a decision."""
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    row = good_row(1)
    row[COMMODITY], row[DATE] = "99999999", "01/01/1990"  # not on any list, long before 2027
    batch = receive(app_engine, store, tenant, to_csv([row]))
    assert run(app_engine, store, tenant, batch.id) == "completed"
    assert scalar(app_engine, tenant, "select count(*) from cbam.decisions") == 0


# --- API: exception report, CSV, retry, enqueue ------------------------------------------


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def queued() -> list[tuple[UUID, UUID]]:
    return []


@pytest.fixture
def client(
    app_engine: Engine, store: InMemoryStore, queued: list[tuple[UUID, UUID]]
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_verifier] = verifier
    app.dependency_overrides[get_engine_dep] = lambda: app_engine
    app.dependency_overrides[get_clock] = lambda: FrozenClock(NOW)
    app.dependency_overrides[get_object_store] = lambda: store
    app.dependency_overrides[get_settings] = lambda: Settings(import_max_file_bytes=1_000_000)
    enqueue: Enqueuer = lambda t, b: queued.append((t, b))  # noqa: E731
    app.dependency_overrides[get_enqueuer] = lambda: enqueue
    with TestClient(app) as c:
        yield c


def user_for(engine: Engine, tenant: UUID, role: str) -> dict[str, str]:
    uid = make_user(engine)
    make_member(engine, tenant, uid, role)
    return bearer(uid, aal="aal2")


def url(tenant: UUID, batch: object, tail: str = "") -> str:
    return f"/api/v1/tenants/{tenant}/import-batches/{batch}{tail}"


def processed_batch(engine: Engine, store: InMemoryStore, tenant: UUID, **kw: int):  # type: ignore[no-untyped-def]
    data, expected = seeded_file(**kw)
    batch = receive(engine, store, tenant, data)
    run(engine, store, tenant, batch.id)
    return batch, expected


def test_imp_16_r1_025_exceptions_json_is_paginated_filtered_and_in_row_order(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    headers = user_for(app_engine, tenant, "operations")
    batch, expected = processed_batch(app_engine, store, tenant, total=120, bad=8)
    seen: list[dict] = []  # type: ignore[type-arg]
    cursor = None
    while True:
        params = {"limit": 3, **({"cursor": cursor} if cursor else {})}
        body = client.get(
            url(tenant, batch.id, "/exceptions"), params=params, headers=headers
        ).json()
        seen += body["items"]
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert {(i["row_number"], i["field"], i["code"]) for i in seen} == expected_set(expected)
    assert [i["row_number"] for i in seen] == sorted(i["row_number"] for i in seen)
    assert len(seen) == len(expected_set(expected))
    warnings = client.get(
        url(tenant, batch.id, "/exceptions"), params={"severity": "warning"}, headers=headers
    ).json()["items"]
    assert warnings and {w["code"] for w in warnings} == {"SUPPLIER_UNMAPPED"}
    assert (
        client.get(
            url(tenant, batch.id, "/exceptions"), params={"status": "resolved"}, headers=headers
        ).json()["items"]
        == []
    )
    assert (
        client.get(
            url(tenant, batch.id, "/exceptions"), params={"severity": "x"}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.get(
            url(tenant, batch.id, "/exceptions"), params={"cursor": "zz"}, headers=headers
        ).status_code
        == 422
    )


def test_imp_16_r1_025_exceptions_csv_has_a_header_row_streams_all_rows_and_has_no_cell_values(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    headers = user_for(app_engine, tenant, "operations")
    data, expected = seeded_file(total=300, bad=20)
    data = data.replace(b"7208100000,10.500000", b"=cmd|' /C calc'!A0,10.500000", 1)
    expected[10] = {("line.commodity_code", "COMMODITY_CODE_INVALID")}
    batch = receive(app_engine, store, tenant, data)
    run(app_engine, store, tenant, batch.id)
    response = client.get(
        url(tenant, batch.id, "/exceptions"), params={"format": "csv"}, headers=headers
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0] == ["row_number", "field", "code", "severity", "message", "status"]
    assert len(rows) - 1 == len(expected_set(expected))
    assert {(int(r[0]), r[1], r[2]) for r in rows[1:]} == expected_set(expected)
    assert "cmd|" not in response.text and "SENTINEL" not in response.text
    errors_only = client.get(
        url(tenant, batch.id, "/exceptions"),
        params={"format": "csv", "severity": "error"},
        headers=headers,
    )
    assert "SUPPLIER_UNMAPPED" not in errors_only.text


def test_imp_16_r1_025_csv_escapes_anything_that_starts_like_a_formula(
    client: TestClient, app_engine: Engine, admin_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    """Defence in depth: even a field or message that did come from a file is neutralised."""
    tenant = make_tenant(app_engine, "A")
    headers = user_for(app_engine, tenant, "operations")
    batch, _ = processed_batch(app_engine, store, tenant, total=3, bad=0)
    with tenant_session(admin_engine, tenant_id=tenant) as s:
        s.execute(text("set local role cbam_owner"))
        s.execute(
            text(
                "insert into cbam.row_exceptions (id, tenant_id, batch_id, row_number, field, code,"
                " severity, message) values (gen_random_uuid(), :t, :b, 0, :f, 'X', 'error', :m)"
            ),
            {"t": tenant, "b": batch.id, "f": "=cmd|' /C calc'!A0", "m": "@SUM(1+1)"},
        )
    text_ = client.get(
        url(tenant, batch.id, "/exceptions"), params={"format": "csv"}, headers=headers
    ).text
    rows = list(csv.reader(io.StringIO(text_)))
    hostile = next(r for r in rows if r[2] == "X")
    assert hostile[1] == "'=cmd|' /C calc'!A0" and hostile[4] == "'@SUM(1+1)"
    assert not any(c.startswith(("=", "@", "+", "-")) for r in rows for c in r)


def test_imp_16_r1_025_exception_endpoints_need_imports_read_and_stay_in_the_tenant(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    batch, _ = processed_batch(app_engine, store, a, total=10, bad=2)
    ok = user_for(app_engine, a, "tax_agent")
    assert client.get(url(a, batch.id, "/exceptions"), headers=ok).status_code == 200
    assert (
        client.get(
            url(a, batch.id, "/exceptions"), params={"format": "csv"}, headers=ok
        ).status_code
        == 200
    )
    assert client.get(url(a, batch.id, "/exceptions")).status_code == 401
    assert (
        client.get(
            url(a, batch.id, "/exceptions"), headers=user_for(app_engine, a, "supplier")
        ).status_code
        == 403
    )
    other = user_for(app_engine, b, "operations")
    assert client.get(url(b, batch.id, "/exceptions"), headers=other).status_code == 404
    assert (
        client.get(
            url(b, batch.id, "/exceptions"), params={"format": "csv"}, headers=other
        ).status_code
        == 404
    )
    assert (
        client.get(url(a, batch.id, "/exceptions"), headers=other).status_code == 404
    )  # not a member


def test_imp_16_r1_003_a_new_upload_is_queued_once_and_a_replay_is_not(
    client: TestClient, app_engine: Engine, queued: list[tuple[UUID, UUID]], layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    headers = user_for(app_engine, tenant, "operations")
    data = to_csv([good_row(1)])
    meta = {"acquisition_method": "get_customs_data", "cds_report_type": "import_item"}
    first = client.post(
        url(tenant, "")[:-1],
        files={"file": ("a.csv", data, "text/csv")},
        data=meta,
        headers=headers,
    )
    assert first.status_code == 202
    assert queued == [(tenant, UUID(first.json()["id"]))]
    again = client.post(
        url(tenant, "")[:-1],
        files={"file": ("a.csv", data, "text/csv")},
        data=meta,
        headers=headers,
    )
    assert again.status_code == 200 and again.json()["replayed"] is True
    assert len(queued) == 1


def test_imp_16_r1_003_a_broker_outage_does_not_fail_an_accepted_upload(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    def broken(_t: UUID, _b: UUID) -> None:
        raise ConnectionError("redis is down")

    app = create_app()
    app.dependency_overrides[get_verifier] = verifier
    app.dependency_overrides[get_engine_dep] = lambda: app_engine
    app.dependency_overrides[get_clock] = lambda: FrozenClock(NOW)
    app.dependency_overrides[get_object_store] = lambda: store
    app.dependency_overrides[get_enqueuer] = lambda: broken
    tenant = make_tenant(app_engine, "A")
    headers = user_for(app_engine, tenant, "operations")
    with TestClient(app) as c:
        response = c.post(
            f"/api/v1/tenants/{tenant}/import-batches",
            files={"file": ("a.csv", to_csv([good_row(1)]), "text/csv")},
            data={"acquisition_method": "cds_export"},
            headers=headers,
        )
    assert response.status_code == 202
    assert scalar(app_engine, tenant, "select status from cbam.import_batches") == "received"


def failed_batch(engine: Engine, store: InMemoryStore, tenant: UUID):  # type: ignore[no-untyped-def]
    batch = receive(engine, store, tenant, to_csv([good_row(1)]))
    stored = dict(store.objects)
    store.objects.clear()
    with pytest.raises(ImportJobError):
        run(engine, store, tenant, batch.id, final_attempt=True)
    store.objects.update(stored)
    return batch


def test_imp_14_r1_003_retry_makes_a_new_batch_for_a_failed_one_only(
    client: TestClient,
    app_engine: Engine,
    store: InMemoryStore,
    queued: list[tuple[UUID, UUID]],
    layout: UUID,
) -> None:
    tenant = make_tenant(app_engine, "A")
    headers = user_for(app_engine, tenant, "operations")
    failed = failed_batch(app_engine, store, tenant)
    version = batch_row(app_engine, tenant, failed.id).row_version

    assert client.post(url(tenant, failed.id, "/retry"), headers=headers).status_code == 428
    stale = client.post(
        url(tenant, failed.id, "/retry"), headers={**headers, "If-Match": str(version + 5)}
    )
    assert stale.status_code == 409
    response = client.post(
        url(tenant, failed.id, "/retry"), headers={**headers, "If-Match": f'"{version}"'}
    )
    assert response.status_code == 202
    new = response.json()
    assert new["id"] != str(failed.id) and new["status"] == "received" and new["replayed"] is False
    assert response.headers["location"].endswith(f"/import-batches/{new['id']}")
    assert queued == [(tenant, UUID(new["id"]))]
    assert batch_row(app_engine, tenant, failed.id).status == "failed"  # history stays
    # the new batch really processes from the same stored file
    assert run(app_engine, store, tenant, UUID(new["id"])) == "completed"
    # a second retry of the same failed batch: its file now has a live batch
    again = client.post(
        url(tenant, failed.id, "/retry"), headers={**headers, "If-Match": f'"{version}"'}
    )
    assert again.status_code == 409


def test_imp_14_r1_003_retry_is_refused_for_batches_that_are_not_failed(
    client: TestClient,
    app_engine: Engine,
    store: InMemoryStore,
    queued: list[tuple[UUID, UUID]],
    layout: UUID,
) -> None:
    tenant = make_tenant(app_engine, "A")
    headers = user_for(app_engine, tenant, "operations")
    done, _ = processed_batch(app_engine, store, tenant, total=5, bad=1)
    received = receive(app_engine, store, tenant, to_csv([good_row(9)]))
    for batch in (done, received):
        version = batch_row(app_engine, tenant, batch.id).row_version
        response = client.post(
            url(tenant, batch.id, "/retry"), headers={**headers, "If-Match": str(version)}
        )
        assert response.status_code == 409, batch
    assert queued == []


def test_imp_14_r1_003_retry_needs_imports_write_and_stays_in_the_tenant(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    failed = failed_batch(app_engine, store, a)
    h = {"If-Match": "2"}
    for role in ("tax_agent", "reviewer", "supplier"):
        assert (
            client.post(
                url(a, failed.id, "/retry"), headers={**user_for(app_engine, a, role), **h}
            ).status_code
            == 403
        )
    assert client.post(url(a, failed.id, "/retry"), headers=h).status_code == 401
    other = {**user_for(app_engine, b, "operations"), **h}
    assert client.post(url(b, failed.id, "/retry"), headers=other).status_code == 404


# --- IMP-17: immutability, tenancy, migration -------------------------------------------


@contextmanager
def owner(engine: Engine, tenant: UUID) -> Iterator[Session]:
    with tenant_session(engine, tenant_id=tenant) as s:
        s.execute(text("set local role cbam_owner"))
        yield s


def sql(engine: Engine, tenant: UUID | None, statement: str, **params: object) -> int:
    with tenant_session(engine, tenant_id=tenant) as s:
        return s.execute(text(statement), params).rowcount


def test_imp_17_r1_025_source_rows_cannot_be_changed_or_deleted_by_app_or_owner(
    app_engine: Engine, admin_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch, _ = processed_batch(app_engine, store, tenant, total=5, bad=1)
    for statement in (
        "update cbam.source_rows set raw = '{}'::jsonb",
        "update cbam.source_rows set row_number = 99",
        "delete from cbam.source_rows",
        "truncate cbam.source_rows cascade",
    ):
        with pytest.raises(DBAPIError):
            sql(app_engine, tenant, statement)
    for statement in (
        "update cbam.source_rows set raw = '{}'::jsonb",
        "delete from cbam.source_rows",
        "truncate cbam.source_rows cascade",
    ):
        with pytest.raises(DBAPIError, match="immutable"), owner(admin_engine, tenant) as s:
            s.execute(text(statement))
    assert (
        scalar(
            app_engine,
            tenant,
            "select count(*) from cbam.source_rows where batch_id = :b",
            b=batch.id,
        )
        == 5
    )


def test_imp_17_r1_025_exception_facts_are_immutable_only_the_resolution_can_move(
    app_engine: Engine, admin_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    processed_batch(app_engine, store, tenant, total=10, bad=2)
    for statement in (
        "update cbam.row_exceptions set message = 'x'",
        "update cbam.row_exceptions set code = 'OTHER'",
        "update cbam.row_exceptions set severity = 'warning'",
        "update cbam.row_exceptions set row_number = 3",
        "delete from cbam.row_exceptions",
        "truncate cbam.row_exceptions",
    ):
        with pytest.raises(DBAPIError):
            sql(app_engine, tenant, statement)
    for statement in (
        "update cbam.row_exceptions set message = 'x'",
        "delete from cbam.row_exceptions",
    ):
        with (
            pytest.raises(DBAPIError, match=r"immutable|deleted"),
            owner(admin_engine, tenant) as s,
        ):
            s.execute(text(statement))
    # a resolution is allowed once, and a code cannot be long free text
    one = "(select id from cbam.row_exceptions order by id limit 1)"
    assert (
        sql(
            app_engine,
            tenant,
            f"update cbam.row_exceptions set status = 'waived', resolved_at = now(), resolution_reason = 'ok' where id = {one}",  # noqa: S608
        )
        == 1
    )
    with pytest.raises(DBAPIError, match="cannot change status"):
        sql(app_engine, tenant, f"update cbam.row_exceptions set status = 'open' where id = {one}")  # noqa: S608
    with pytest.raises(DBAPIError):  # a status other than open needs a resolution time
        sql(
            app_engine,
            tenant,
            "update cbam.row_exceptions set status = 'resolved' where status = 'open'",
        )
    with pytest.raises(DBAPIError):
        with owner(admin_engine, tenant) as s:
            s.execute(text("update cbam.row_exceptions set code = 'bad code!'"))


def test_imp_17_r1_025_codes_and_cross_tenant_links_are_constrained(
    app_engine: Engine, admin_engine: Engine, layout: UUID
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    batch_a, _ = processed_batch(app_engine, InMemoryStore(), a, total=3, bad=0)
    store_b = InMemoryStore()
    processed_batch(app_engine, store_b, b, total=4, bad=0)
    with tenant_session(app_engine, tenant_id=b) as s:
        row_b = s.execute(text("select id, batch_id from cbam.source_rows limit 1")).one()
    insert = (
        "insert into cbam.row_exceptions (id, tenant_id, batch_id, source_row_id, row_number,"
        " field, code, severity, message) values (gen_random_uuid(), :t, :b, :s, :n, '', :c, 'error', 'm')"
    )
    for params in (
        {"t": a, "b": batch_a.id, "s": None, "n": 5, "c": "OK"},  # row without a source row
        {"t": a, "b": batch_a.id, "s": row_b.id, "n": 1, "c": "OK"},  # another tenant's row
        {"t": a, "b": row_b.batch_id, "s": None, "n": 0, "c": "OK"},  # another tenant's batch
        {"t": a, "b": batch_a.id, "s": None, "n": 0, "c": "lower case"},
        {"t": a, "b": batch_a.id, "s": None, "n": 0, "c": "X" * 65},
    ):
        with pytest.raises(DBAPIError), owner(admin_engine, a) as s:
            s.execute(text(insert), params)
    with pytest.raises(DBAPIError, match="foreign key"), owner(admin_engine, a) as s:
        s.execute(
            text(
                "insert into cbam.source_rows (id, tenant_id, batch_id, row_number, raw, row_sha256)"
                " values (gen_random_uuid(), :t, :b, 999, '{}', repeat('a', 64))"
            ),
            {"t": a, "b": row_b.batch_id},
        )


def test_imp_17_r1_025_tenant_b_cannot_see_or_write_tenant_as_rows(
    app_engine: Engine, layout: UUID
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    batch, _ = processed_batch(app_engine, InMemoryStore(), a, total=10, bad=2)
    for table in ("source_rows", "row_exceptions"):
        assert scalar(app_engine, a, f"select count(*) from cbam.{table}") > 0  # type: ignore[operator]  # noqa: S608
        assert scalar(app_engine, b, f"select count(*) from cbam.{table}") == 0  # noqa: S608
        assert scalar(app_engine, None, f"select count(*) from cbam.{table}") == 0  # noqa: S608
    with pytest.raises(DBAPIError):
        sql(
            app_engine,
            b,
            "insert into cbam.source_rows (id, tenant_id, batch_id, row_number, raw, row_sha256)"
            " values (gen_random_uuid(), :t, :b, 99, '{}', repeat('a', 64))",
            t=a,
            b=batch.id,
        )
    with pytest.raises(TenantMismatchError):
        with tenant_session(app_engine, tenant_id=b) as s:
            service.list_exceptions(s, b, batch.id)


def test_imp_17_r1_025_the_app_filters_by_tenant_even_when_row_level_security_is_off(
    app_engine: Engine, admin_engine: Engine, layout: UUID
) -> None:
    """CLAUDE.md rule 7: with forced RLS off for the owner (rolled back after), tenant B's
    queries and the job still cannot see or touch tenant A's rows."""
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    store_a = InMemoryStore()
    batch_a, _ = processed_batch(app_engine, store_a, a, total=10, bad=3)
    with admin_engine.connect() as conn:
        outer = conn.begin()
        try:
            conn.execute(text("set local role cbam_owner"))
            for table in ("import_batches", "source_rows", "row_exceptions"):
                conn.execute(text(f"alter table cbam.{table} no force row level security"))
            session = Session(conn)
            total = session.execute(text("select count(*) from cbam.row_exceptions")).scalar_one()
            assert total > 0, "row-level security should be off for this check"
            with pytest.raises(TenantMismatchError):
                service.list_exceptions(session, b, batch_a.id)
            # the CSV pages are filtered by tenant too (the route checks the batch first)
            assert list(service.iter_exception_pages(lambda: _same(session), b, batch_a.id)) == []
            assert service.list_exceptions(session, a, batch_a.id).items
            with pytest.raises(TenantMismatchError):
                processing._batch(session, b, batch_a.id)
            with pytest.raises(TenantMismatchError):
                processing._load_start(session, b, batch_a.id)
            counters = processing._recount(session, b, batch_a.id)
            assert counters["rows_total"] == 0
            with pytest.raises(TenantMismatchError):
                service.retry_batch(
                    session,
                    tenant_id=b,
                    batch_id=batch_a.id,
                    expected_version=1,
                    actor=Actor("system", None),
                    now=NOW,
                )
        finally:
            outer.rollback()


@contextmanager
def _same(session: Session) -> Iterator[Session]:
    yield session


def test_imp_17_r1_025_migration_0010_goes_down_and_up_again(
    admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alembic import command

    from tests.integration.test_migrations import BACKEND, _config, _scalar

    cfg = _config(monkeypatch)
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")
    tables = (
        "select count(*) from information_schema.tables where table_schema = 'cbam' "
        "and table_name in ('source_rows','row_exceptions')"
    )
    columns = (
        "select count(*) from information_schema.columns where table_schema = 'cbam' and "
        "((table_name = 'import_batches' and column_name in "
        "('report_layout_version_id','layout_status')) or "
        "(table_name = 'ref_cds_report_layouts' and column_name = 'date_format'))"
    )
    functions = (
        "select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
        "where n.nspname = 'cbam' and p.proname in "
        "('source_rows_block_change', 'row_exceptions_guard')"
    )
    assert (_scalar(tables), _scalar(columns), _scalar(functions)) == (2, 3, 2)
    command.downgrade(cfg, "0009")
    assert (_scalar(tables), _scalar(columns), _scalar(functions)) == (0, 0, 0)
    # the 0009 guard is back, and the layout view still works
    assert _scalar("select count(*) from cbam.v_active_cds_report_layouts") is not None
    command.upgrade(cfg, "head")
    assert (_scalar(tables), _scalar(columns), _scalar(functions)) == (2, 3, 2)


# --- properties --------------------------------------------------------------------------


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    st.lists(
        st.lists(
            st.text(
                alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00\r"),
                max_size=25,
            ),
            min_size=1,
            max_size=15,
        ),
        min_size=1,
        max_size=12,
    )
)
def test_imp_10_r1_025_arbitrary_rows_never_crash_the_job_and_counters_add_up(
    app_engine: Engine, layout: UUID, rows: list[list[str]]
) -> None:
    tenant, store = make_tenant(app_engine, "P"), InMemoryStore()
    data = to_csv(rows)
    try:
        batch = receive(app_engine, store, tenant, data)
    except Exception:  # not a CSV the upload accepts (for example a lone newline cell)
        return
    status = run(app_engine, store, tenant, batch.id, chunk_rows=5)
    row = batch_row(app_engine, tenant, batch.id)
    assert status == row.status
    assert row.rows_valid + row.rows_rejected == row.rows_total == row.rows_processed
    stored = scalar(app_engine, tenant, "select count(*) from cbam.source_rows")
    assert stored == row.rows_total
    raw_all = json.dumps(
        scalar(app_engine, tenant, "select coalesce(json_agg(raw), '[]') from cbam.source_rows")
    )
    assert isinstance(raw_all, str)
    # a failure reason, if any, is always a short code
    assert row.failure_reason is None or processing.rules.is_failure_code(row.failure_reason)


def test_imp_10_r1_025_job_failures_carry_no_stored_error_text(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv([good_row(1)]))

    class Broken(InMemoryStore):
        def open(self, key: str):  # type: ignore[no-untyped-def]
            raise StorageError("secret-token-in-url")

    with pytest.raises(ImportJobError) as caught:
        process_batch(app_engine, Broken(), CLOCK, tenant, batch.id, final_attempt=True)
    assert "secret" not in str(caught.value) and caught.value.__cause__ is None
    assert caught.value.__suppress_context__
    assert batch_row(app_engine, tenant, batch.id).failure_reason == "storage_unavailable"
