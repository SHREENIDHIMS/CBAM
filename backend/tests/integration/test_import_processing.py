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
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
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
from app.core.ids import uuid7
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
TODAY = NOW.date()
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
        {("", "ROW_TOO_SHORT"), ("line.supplier_ref", "SUPPLIER_MISSING")},
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
            expected[number] = {("line.supplier_ref", "SUPPLIER_MISSING")}
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
    *,
    as_of: date = TODAY,
    max_bytes: int = 10_000_000,
):  # type: ignore[no-untyped-def]
    scanned = service.scan_upload(io.BytesIO(data), max_bytes=max_bytes)
    return service.receive_file(
        lambda: tenant_session(engine, tenant_id=tenant),
        store=store,
        tenant_id=tenant,
        actor=Actor("system", None),
        now=NOW,
        as_of=as_of,
        file=io.BytesIO(data),
        scanned=scanned,
        filename="a.csv",
        metadata=meta,
    )


def run(engine: Engine, store: InMemoryStore, tenant: UUID, batch: UUID, **kw: object) -> str:
    clock = kw.pop("clock", CLOCK)
    return process_batch(engine, store, clock, tenant, batch, **kw)  # type: ignore[arg-type]


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
    errors = {n for n, items in expected.items() if any(c != "SUPPLIER_MISSING" for _, c in items)}
    assert len(errors) == 37
    # a warning-only row is valid, and every row is stored (valid rows continue)
    assert exceptions(app_engine, tenant, batch.id, severity="warning") == {
        (n, f, c) for n, f, c in expected_set(expected) if c == "SUPPLIER_MISSING"
    }
    assert scalar(app_engine, tenant, "select count(*) from cbam.source_rows") == 500
    with tenant_session(app_engine, tenant_id=tenant) as s:
        # no tax point, decision or normalised line exists yet (Phase 3 step 4 and Phase 4)
        assert s.execute(text("select count(*) from cbam.decisions")).scalar_one() == 0
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
        {n for n, _, c in expected_set(expected) if c != "SUPPLIER_MISSING"}
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
    assert warnings and {w["code"] for w in warnings} == {"SUPPLIER_MISSING"}
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
    assert "SUPPLIER_MISSING" not in errors_only.text


def test_imp_16_r1_025_csv_escapes_anything_that_starts_like_a_formula(
    client: TestClient, app_engine: Engine, admin_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    """Defence in depth: even a field or message that did come from a file is neutralised."""
    tenant = make_tenant(app_engine, "A")
    headers = user_for(app_engine, tenant, "operations")
    batch = receive(app_engine, store, tenant, to_csv([good_row(1)]))  # still open for rows
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


def test_imp_16_r1_003_a_new_upload_is_queued_and_an_overdue_unprocessed_replay_is_queued_again(
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
    # still `received` but inside the stale window: not queued again (the sweeper owns it)
    assert queued == [(tenant, UUID(first.json()["id"]))]
    later = create_app()
    later.dependency_overrides.update(client.app.dependency_overrides)
    later.dependency_overrides[get_clock] = lambda: FrozenClock(NOW + timedelta(hours=1))
    with TestClient(later) as c2:
        overdue = c2.post(
            url(tenant, "")[:-1],
            files={"file": ("a.csv", data, "text/csv")},
            data=meta,
            headers=headers,
        )
    assert overdue.json()["replayed"] is True
    assert len(queued) == 2  # overdue and still unprocessed: queued again (idempotent job)


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
    with pytest.raises(DBAPIError, match="cannot change again"):
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
    batch_a = receive(app_engine, InMemoryStore(), a, to_csv([good_row(1)]))  # not final
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
        "('report_layout_version_id','layout_status','attempts')) or "
        "(table_name = 'ref_cds_report_layouts' and column_name = 'date_format'))"
    )
    functions = (
        "select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
        "where n.nspname = 'cbam' and p.proname in "
        "('source_rows_block_change', 'row_exceptions_guard', 'import_rows_block_terminal')"
    )
    assert (_scalar(tables), _scalar(columns), _scalar(functions)) == (2, 4, 3)
    command.downgrade(cfg, "0009")
    assert (_scalar(tables), _scalar(columns), _scalar(functions)) == (0, 0, 0)
    # the 0009 guard is back, and the layout view still works
    assert _scalar("select count(*) from cbam.v_active_cds_report_layouts") is not None
    command.upgrade(cfg, "head")
    assert (_scalar(tables), _scalar(columns), _scalar(functions)) == (2, 4, 3)


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


# --- resource limits, crash loops, stale batches, layout dates (security and review fixes) ----


def limits(**changes: int) -> processing.rules.ImportLimits:
    base = processing.limits_from_settings(Settings())
    return processing.rules.ImportLimits(**{**base.__dict__, **changes})


def only_object(store: InMemoryStore) -> str:
    (key,) = store.objects
    return key


def test_imp_18_r1_025_four_hundred_huge_headings_are_rejected_without_reading_them_all(
    app_engine: Engine, layout: UUID
) -> None:
    """Security H1: a header that is 40 MB on one line is refused at the line cap."""
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    data = ("a," + ",".join("h" * 100_000 for _ in range(400)) + "\n1,2\n").encode()
    batch = receive(app_engine, store, tenant, data, max_bytes=50_000_000)
    assert run(app_engine, store, tenant, batch.id) == "rejected"
    assert exceptions(app_engine, tenant, batch.id) == {(0, "", "FILE_UNREADABLE")}
    assert scalar(app_engine, tenant, "select count(*) from cbam.source_rows") == 0


def test_imp_18_r1_025_too_many_columns_and_too_long_headings_are_file_level_codes(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    wide = receive(app_engine, store, tenant, to_csv([], headers=[f"c{i}" for i in range(300)]))
    assert run(app_engine, store, tenant, wide.id) == "rejected"
    assert exceptions(app_engine, tenant, wide.id) == {(0, "", "HEADER_TOO_MANY_COLUMNS")}
    long_ = receive(app_engine, store, tenant, to_csv([], headers=["h" * 300, "b"]))
    assert run(app_engine, store, tenant, long_.id) == "rejected"
    assert exceptions(app_engine, tenant, long_.id) == {(0, "", "HEADER_TOO_LONG")}
    row = batch_row(app_engine, tenant, long_.id)
    assert (row.failure_reason, row.layout_status) == ("header_too_long", "unreadable")


def test_imp_18_r1_025_a_cell_over_the_cell_limit_or_a_row_over_the_row_limit_stops_the_file(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    row = good_row(2)
    row[11] = "z" * 60
    big_cell = receive(app_engine, store, tenant, to_csv([good_row(1), row]))
    assert (
        run(app_engine, store, tenant, big_cell.id, limits=limits(max_cell_chars=50)) == "rejected"
    )
    assert {c for _, _, c in exceptions(app_engine, tenant, big_cell.id)} == {"FILE_UNREADABLE"}
    assert (
        scalar(
            app_engine,
            tenant,
            "select count(*) from cbam.source_rows where batch_id = :b",
            b=big_cell.id,
        )
        == 1
    )  # rows saved before the problem stay, with their counters
    assert batch_row(app_engine, tenant, big_cell.id).rows_total == 1

    multi = good_row(1)
    multi[11] = "\n".join(["line"] * 40)  # short lines, but one record of 200+ characters
    big_row = receive(app_engine, store, tenant, to_csv([multi]))
    assert (
        run(app_engine, store, tenant, big_row.id, limits=limits(max_row_chars=300)) == "rejected"
    )
    assert exceptions(app_engine, tenant, big_row.id) == {(0, "", "ROW_TOO_LARGE")}


def test_imp_18_r1_025_five_thousand_comma_only_rows_are_processed_in_bounded_chunks(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    data = (",".join(HEADERS) + "\n" + (",".join([""] * 13) + "\n") * 5000).encode()
    batch = receive(app_engine, store, tenant, data)
    assert run(app_engine, store, tenant, batch.id) == "completed_with_errors"
    row = batch_row(app_engine, tenant, batch.id)
    assert (row.rows_total, row.rows_rejected, row.rows_valid) == (5000, 5000, 0)
    sizes = [
        e["rows"]
        for e in scalar(  # type: ignore[union-attr]
            app_engine,
            tenant,
            "select json_agg(after order by id) from cbam.audit_events"
            " where action = 'import_batch.rows_processed'",
        )
    ]
    assert sizes == [500] * 10


def test_imp_18_r1_025_a_chunk_is_saved_when_its_character_budget_is_reached(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv([good_row(i) for i in range(1, 31)]))
    assert (
        run(app_engine, store, tenant, batch.id, limits=limits(chunk_max_chars=500)) == "completed"
    )
    sizes = [
        e["rows"]
        for e in scalar(  # type: ignore[union-attr]
            app_engine,
            tenant,
            "select json_agg(after order by id) from cbam.audit_events"
            " where action = 'import_batch.rows_processed'",
        )
    ]
    assert sum(sizes) == 30 and len(sizes) >= 6 and max(sizes) <= 5  # not one chunk of 30
    assert batch_row(app_engine, tenant, batch.id).rows_total == 30


def test_imp_18_r1_025_a_nul_character_anywhere_rejects_the_file(
    app_engine: Engine, layout: UUID
) -> None:
    """Upload refuses NUL bytes already; the job refuses them too if the stored file has one."""
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    for where in ("cell", "header"):
        data = to_csv([good_row(1), good_row(2)], headers=HEADERS)
        store = InMemoryStore()
        batch = receive(app_engine, store, tenant, data + f"# {where}\n".encode())
        stored = store.objects[only_object(store)]
        poisoned = (
            stored.replace(b"SYNTH_MRN", b"SYNTH\x00MRN", 1)
            if where == "header"
            else (stored.replace(b"MRN-SENTINEL-0002", b"MRN-SENT\x00NEL-0002"))
        )
        store.objects[only_object(store)] = poisoned
        assert run(app_engine, store, tenant, batch.id) == "rejected"
        assert "FILE_UNREADABLE" in {c for _, _, c in exceptions(app_engine, tenant, batch.id)}


def test_imp_18_r1_003_a_batch_started_too_many_times_is_failed_as_a_crash_loop(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv([good_row(i) for i in range(1, 8)]))

    def crash(_rows: int) -> None:
        raise RuntimeError("killed")

    for attempt in (1, 2, 3):
        with pytest.raises(ImportJobError):
            run(
                app_engine,
                store,
                tenant,
                batch.id,
                chunk_rows=2,
                after_chunk=crash,
                limits=limits(max_attempts=3),
            )
        assert batch_row(app_engine, tenant, batch.id).attempts == attempt
    assert run(app_engine, store, tenant, batch.id, limits=limits(max_attempts=3)) == "failed"
    row = batch_row(app_engine, tenant, batch.id)
    assert (row.status, row.failure_reason) == ("failed", "worker_crash_loop")
    assert run(app_engine, store, tenant, batch.id) == "failed"  # and stays stopped


def test_imp_18_r1_003_permanent_errors_fail_fast_and_are_marked_failed(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    with pytest.raises(ImportJobError) as caught:
        run(app_engine, store, tenant, UUID(int=1))  # a batch that does not exist
    assert caught.value.permanent is True
    other = make_tenant(app_engine, "B")
    batch = receive(app_engine, store, tenant, to_csv([good_row(1)]))
    with pytest.raises(ImportJobError) as foreign:  # another tenant's batch looks absent
        run(app_engine, store, other, batch.id)
    assert foreign.value.permanent is True
    assert batch_row(app_engine, tenant, batch.id).status == "received"  # untouched


def test_imp_18_r1_025_an_infected_file_is_never_parsed(
    app_engine: Engine, admin_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv([good_row(1)]))
    with owner(admin_engine, tenant) as s:  # stand-in for the Phase 7 scanner
        s.execute(
            text("alter table cbam.document_versions disable trigger document_versions_immutable")
        )
        s.execute(text("update cbam.document_versions set scan_state = 'infected'"))
        s.execute(
            text("alter table cbam.document_versions enable trigger document_versions_immutable")
        )
    store.objects.clear()  # prove the file is not even opened
    assert run(app_engine, store, tenant, batch.id) == "rejected"
    assert exceptions(app_engine, tenant, batch.id) == {(0, "", "FILE_INFECTED")}
    assert batch_row(app_engine, tenant, batch.id).failure_reason == "file_infected"


def test_imp_18_r1_025_a_pending_scan_still_processes_until_phase_7_gates_on_clean(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv([good_row(1)]))
    assert (
        scalar(app_engine, tenant, "select scan_state from cbam.document_versions") == "not_scanned"
    )
    assert run(app_engine, store, tenant, batch.id) == "completed"


LAYOUT_NO_FORMAT = """report_type,column_name,maps_to,required,date_format
import_item,Code,line.commodity_code,true,
import_item,Accepted,declaration.acceptance_date,true,
"""
LAYOUT_DOUBLED = """report_type,column_name,maps_to,required,date_format
import_item,Code,line.commodity_code,true,
import_item,Code2,line.commodity_code,false,
"""


@pytest.mark.parametrize(
    ("version", "csv_text"), [("bad.1", LAYOUT_NO_FORMAT), ("bad.2", LAYOUT_DOUBLED)]
)
def test_imp_19_r1_025_an_ambiguous_or_incomplete_layout_rejects_the_batch(
    app_engine: Engine,
    admin_engine: Engine,
    layout: UUID,
    tmp_path: object,
    version: str,
    csv_text: str,
) -> None:
    load(
        app_engine,
        write_dataset(
            tmp_path,
            dataset="cds_report_layouts",
            version=version,
            csv=csv_text,
            source_id="BAD-LAYOUT-SOURCE",
        ),
    )  # type: ignore[arg-type]
    put_source_in_force(app_engine, layout, "BAD-LAYOUT-SOURCE")
    activate(app_engine, layout, "cds_report_layouts", version)
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, b"Code,Code2,Accepted\n72081000,x,2027-01-01\n")
    assert run(app_engine, store, tenant, batch.id) == "rejected"
    assert exceptions(app_engine, tenant, batch.id) == {(0, "", "LAYOUT_INVALID")}
    row = batch_row(app_engine, tenant, batch.id)
    assert (row.layout_status, row.failure_reason) == ("invalid", "layout_invalid")


def test_imp_19_r1_025_the_layout_is_chosen_for_the_date_the_report_was_acquired(
    app_engine: Engine, admin_engine: Engine, layout: UUID, tmp_path: object
) -> None:
    """A new layout version applies from its own date, whatever day the job runs."""
    load(
        app_engine,
        write_dataset(
            tmp_path,  # type: ignore[arg-type]
            dataset="cds_report_layouts",
            version="synthetic.4",
            csv=LAYOUT_V2,
            source_id="LAYOUT-V4-SOURCE",
            effective_from=date(2027, 6, 1),
        ),
    )
    put_source_in_force(app_engine, layout, "LAYOUT-V4-SOURCE")
    activate(app_engine, layout, "cds_report_layouts", "synthetic.4")
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    data = b"Commodity Code,Net Mass,Accepted\n7208100000,1.5,2027-01-05\n"
    late = FrozenClock(datetime(2027, 9, 1, 9, 0, tzinfo=UTC))

    def meta(day: date) -> ImportBatchMetadata:
        return ImportBatchMetadata(
            acquisition_method="get_customs_data", cds_report_type="import_item", acquired_on=day
        )

    before = receive(
        app_engine, store, tenant, data, meta(date(2027, 3, 1)), as_of=date(2027, 12, 31)
    )
    # running in September does not make a March report use the June layout
    assert run(app_engine, store, tenant, before.id, clock=late) == "rejected"
    assert exceptions(app_engine, tenant, before.id) == {(0, "", "LAYOUT_NOT_ACTIVE")}
    after = receive(
        app_engine, store, tenant, data + b"\n", meta(date(2027, 7, 1)), as_of=date(2027, 12, 31)
    )
    assert run(app_engine, store, tenant, after.id) == "completed"  # job clock is still March


def test_imp_19_r1_025_with_no_acquisition_date_the_received_date_is_used(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv([good_row(1)]))  # created 1 March 2027
    late = FrozenClock(datetime(2030, 1, 1, tzinfo=UTC))
    assert run(app_engine, store, tenant, batch.id, clock=late) == "completed"


def test_imp_20_r1_003_a_stale_received_batch_is_requeued_by_the_sweeper_and_then_processes(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    """Broker outage at upload leaves the batch `received`; the beat sweeper recovers it."""
    from app.modules.imports.jobs import sweep_stale

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
            data={"acquisition_method": "get_customs_data", "cds_report_type": "import_item"},
            headers=headers,
        )
    batch_id = UUID(response.json()["id"])

    sent: list[tuple[UUID, UUID]] = []
    fresh = FrozenClock(NOW + timedelta(minutes=5))
    sweep_stale(app_engine, fresh, lambda t, b: sent.append((t, b)), minutes=10)
    assert (tenant, batch_id) not in sent  # not stale yet
    stale = FrozenClock(NOW + timedelta(minutes=11))
    sweep_stale(app_engine, stale, lambda t, b: sent.append((t, b)), minutes=10)
    assert (tenant, batch_id) in sent
    # the queued job then does the work; a second sweep after completion leaves it alone
    assert run(app_engine, store, tenant, batch_id) == "completed"
    sent.clear()
    sweep_stale(app_engine, stale, lambda t, b: sent.append((t, b)), minutes=10)
    assert (tenant, batch_id) not in sent
    # a broker that is still down does not break the sweep
    assert sweep_stale(app_engine, stale, broken, minutes=10) >= 0


def test_imp_20_r1_003_the_sweeper_task_is_scheduled_by_beat() -> None:
    from app.core.jobs import celery_app

    entry = celery_app.conf.beat_schedule["imports-sweep-stale-batches"]
    assert entry["task"] == "imports.sweep_stale_batches"
    assert entry["schedule"] <= 300


def test_imp_21_r1_025_no_rows_or_exceptions_can_be_added_to_a_final_batch(
    app_engine: Engine, admin_engine: Engine, layout: UUID
) -> None:
    """M2: enforced by a trigger, for the app role and for the owner. The job's own flow
    (rows, then the final status) is the other tests in this file."""
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch, _ = processed_batch(app_engine, store, tenant, total=5, bad=1)
    row_sql = (
        "insert into cbam.source_rows (id, tenant_id, batch_id, row_number, raw, row_sha256)"
        " values (gen_random_uuid(), :t, :b, 999, '{}', repeat('a', 64))"
    )
    exc_sql = (
        "insert into cbam.row_exceptions (id, tenant_id, batch_id, row_number, field, code,"
        " severity, message) values (gen_random_uuid(), :t, :b, 0, '', 'X', 'error', 'm')"
    )
    params = {"t": tenant, "b": batch.id}
    for statement in (row_sql, exc_sql):
        with pytest.raises(DBAPIError, match="is final"):
            sql(app_engine, tenant, statement, **params)
        with pytest.raises(DBAPIError, match="is final"), owner(admin_engine, tenant) as s:
            s.execute(text(statement), params)
    for status in ("failed", "rejected"):
        other = receive(
            app_engine, InMemoryStore(), tenant, to_csv([good_row(3)]) + status.encode()
        )
        with owner(admin_engine, tenant) as s:
            s.execute(
                text("update cbam.import_batches set status = :s where id = :b"),
                {"s": status, "b": other.id},
            )
        with pytest.raises(DBAPIError, match="is final"):
            sql(app_engine, tenant, exc_sql, t=tenant, b=other.id)


def test_imp_21_r1_025_once_resolved_the_whole_resolution_is_locked(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    processed_batch(app_engine, store, tenant, total=10, bad=2)
    one = "(select id from cbam.row_exceptions order by id limit 1)"
    sql(
        app_engine,
        tenant,
        "update cbam.row_exceptions set status = 'waived', resolved_at = now(),"  # noqa: S608
        f" resolution_reason = 'ok' where id = {one}",
    )
    for change in (
        "resolution_reason = 'changed'",
        "resolved_at = now() + interval '1 day'",
        f"resolved_by = '{uuid7()}'",
    ):
        with pytest.raises(DBAPIError, match="cannot change again"):
            sql(app_engine, tenant, f"update cbam.row_exceptions set {change} where id = {one}")  # noqa: S608


def test_imp_21_r1_025_a_huge_or_negative_cursor_is_a_clean_422(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    from app.core.pagination import encode_cursor

    tenant = make_tenant(app_engine, "A")
    headers = user_for(app_engine, tenant, "operations")
    batch, _ = processed_batch(app_engine, store, tenant, total=10, bad=2)
    for r in (10**12, -1, 2**63):
        cursor = encode_cursor({"r": r, "i": str(uuid7())})
        response = client.get(
            url(tenant, batch.id, "/exceptions"), params={"cursor": cursor}, headers=headers
        )
        assert response.status_code == 422, r


# --- leases, takeovers, duplicate deliveries, quoted-newline records ----------------------------


class Killed(BaseException):
    """A worker killed mid-file (SIGKILL/OOM): not an Exception, so no cleanup code runs."""


def kill(_rows: int) -> None:
    raise Killed()


def at(minutes: float) -> FrozenClock:
    return FrozenClock(NOW + timedelta(minutes=minutes))


def sweep(engine: Engine, clock: FrozenClock) -> set[tuple[UUID, UUID]]:
    from app.modules.imports.jobs import sweep_stale

    sent: list[tuple[UUID, UUID]] = []
    sweep_stale(engine, clock, lambda t, b: sent.append((t, b)), minutes=10)
    return set(sent)


def test_imp_22_r1_003_a_killed_worker_is_taken_over_after_its_lease_expires(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    data, expected = seeded_file(total=60, bad=5)
    batch = receive(app_engine, store, tenant, data)
    with pytest.raises(Killed):
        run(app_engine, store, tenant, batch.id, chunk_rows=20, after_chunk=kill)
    mid = batch_row(app_engine, tenant, batch.id)
    assert (mid.status, mid.attempts, mid.rows_total) == ("validating", 1, 20)
    assert mid.lease_expires_at == NOW + timedelta(seconds=300)

    # inside the lease: a duplicate delivery and the sweeper both leave it alone
    assert (tenant, batch.id) not in sweep(app_engine, at(1))
    assert run(app_engine, store, tenant, batch.id, clock=at(1)) == "validating"
    after_dup = batch_row(app_engine, tenant, batch.id)
    assert (after_dup.attempts, after_dup.rows_total) == (1, 20)

    # lease expired: the sweeper queues it, and the job takes over and finishes
    assert (tenant, batch.id) in sweep(app_engine, at(6))
    assert run(app_engine, store, tenant, batch.id, clock=at(6), chunk_rows=20) == (
        "completed_with_errors"
    )
    done = batch_row(app_engine, tenant, batch.id)
    assert (done.attempts, done.rows_total) == (2, 60)
    assert exceptions(app_engine, tenant, batch.id) == expected_set(expected)
    assert (tenant, batch.id) not in sweep(app_engine, at(60))  # finished: never swept again


def test_imp_22_r1_003_repeated_takeovers_end_in_a_crash_loop_failure(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv([good_row(i) for i in range(1, 9)]))
    two = limits(max_attempts=2)
    for minute in (0, 10):
        with pytest.raises(Killed):
            run(
                app_engine,
                store,
                tenant,
                batch.id,
                clock=at(minute),
                chunk_rows=2,
                after_chunk=kill,
                limits=two,
            )
    assert (tenant, batch.id) in sweep(app_engine, at(20))
    assert run(app_engine, store, tenant, batch.id, clock=at(20), limits=two) == "failed"
    row = batch_row(app_engine, tenant, batch.id)
    assert (row.status, row.failure_reason, row.attempts) == ("failed", "worker_crash_loop", 3)
    assert (tenant, batch.id) not in sweep(app_engine, at(40))


def test_imp_22_r1_003_duplicate_deliveries_and_sweeps_never_fail_a_healthy_slow_batch(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv([good_row(i) for i in range(1, 9)]))
    with pytest.raises(Killed):
        run(
            app_engine,
            store,
            tenant,
            batch.id,
            chunk_rows=2,
            after_chunk=kill,
            limits=limits(max_attempts=2),
        )
    for step in range(20):  # a sweeper and redeliveries every few seconds for the lease length
        clock = FrozenClock(NOW + timedelta(seconds=10 * step))
        assert (
            run(app_engine, store, tenant, batch.id, clock=clock, limits=limits(max_attempts=2))
            == "validating"
        )
    row = batch_row(app_engine, tenant, batch.id)
    assert (row.status, row.attempts, row.rows_total) == ("validating", 1, 2)


def test_imp_22_r1_003_two_jobs_started_together_parse_once(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    data, expected = seeded_file(total=200, bad=6)
    batch = receive(app_engine, store, tenant, data)
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(lambda _: run(app_engine, store, tenant, batch.id, chunk_rows=50), range(2))
        )
    assert set(results) <= {"completed_with_errors", "validating", "parsing"}
    row = batch_row(app_engine, tenant, batch.id)
    assert (row.status, row.attempts, row.rows_total) == ("completed_with_errors", 1, 200)
    assert exceptions(app_engine, tenant, batch.id) == expected_set(expected)
    chunks = scalar(
        app_engine,
        tenant,
        "select count(*) from cbam.audit_events where action = 'import_batch.rows_processed'",
    )
    assert chunks == 4  # each chunk audited once: no parallel duplicate work


def test_imp_22_r1_003_the_lease_is_renewed_after_every_chunk(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv([good_row(i) for i in range(1, 7)]))
    clock = FrozenClock(NOW)
    seen: list[object] = []

    def tick(_rows: int) -> None:
        seen.append(batch_row(app_engine, tenant, batch.id).lease_expires_at)
        clock.advance(timedelta(seconds=100))

    assert (
        process_batch(app_engine, store, clock, tenant, batch.id, chunk_rows=2, after_chunk=tick)
        == "completed"
    )
    assert seen == [
        NOW + timedelta(seconds=300),
        NOW + timedelta(seconds=400),
        NOW + timedelta(seconds=500),
    ]


def test_imp_22_r1_003_a_failed_attempt_releases_the_lease_so_a_retry_can_start_at_once(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv([good_row(i) for i in range(1, 5)]))

    def boom(_rows: int) -> None:
        raise RuntimeError("transient")

    with pytest.raises(ImportJobError):
        run(app_engine, store, tenant, batch.id, chunk_rows=2, after_chunk=boom)
    assert run(app_engine, store, tenant, batch.id, chunk_rows=2) == "completed"  # same instant
    assert batch_row(app_engine, tenant, batch.id).attempts == 2


def test_imp_22_r1_003_attempts_can_never_go_down_but_the_lease_can_move_either_way(
    app_engine: Engine, admin_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, to_csv([good_row(1)]))
    with pytest.raises(Killed):
        run(app_engine, store, tenant, batch.id, chunk_rows=1, after_chunk=kill)
    for engine_ctx in ("app", "owner"):
        statement = "update cbam.import_batches set attempts = attempts - 1 where id = :i"
        if engine_ctx == "app":
            with pytest.raises(DBAPIError, match="cannot go down"):
                sql(app_engine, tenant, statement, i=batch.id)
        else:
            with (
                pytest.raises(DBAPIError, match="cannot go down"),
                owner(admin_engine, tenant) as s,
            ):
                s.execute(text(statement), {"i": batch.id})
    assert (
        sql(
            app_engine,
            tenant,
            "update cbam.import_batches set lease_expires_at = lease_expires_at - interval '1 hour' where id = :i",
            i=batch.id,
        )
        == 1
    )


def test_imp_22_r1_025_reject_does_nothing_when_the_batch_is_already_final(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch, _ = processed_batch(app_engine, store, tenant, total=5, bad=1)
    before = exceptions(app_engine, tenant, batch.id)
    status = processing._reject(
        app_engine, CLOCK, tenant, batch.id, [processing.rules.Issue("FILE_UNREADABLE", "")], None
    )
    assert status == "completed_with_errors"
    assert exceptions(app_engine, tenant, batch.id) == before


def test_imp_22_r1_025_the_csv_cell_limit_is_restored_after_the_job(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    before = csv.field_size_limit()
    batch = receive(app_engine, store, tenant, to_csv([good_row(1)]))
    run(app_engine, store, tenant, batch.id, limits=limits(max_cell_chars=777))
    assert csv.field_size_limit() == before
    failing = receive(app_engine, store, tenant, to_csv([good_row(2)]))
    store.objects.clear()
    with pytest.raises(ImportJobError):
        run(app_engine, store, tenant, failing.id, limits=limits(max_cell_chars=777))
    assert csv.field_size_limit() == before


def test_imp_23_r1_025_a_record_hiding_newlines_in_quotes_is_rejected_by_the_row_and_column_caps(
    app_engine: Engine, layout: UUID
) -> None:
    """Security H1: one record of hundreds of thousands of two-line quoted cells."""
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    attack = '"x\n' + 'y","x\n' * 300_000 + 'y"\n'
    data = (",".join(HEADERS) + "\n" + ",".join(good_row(1)) + "\n" + attack).encode()
    batch = receive(app_engine, store, tenant, data)
    assert run(app_engine, store, tenant, batch.id) == "rejected"
    assert exceptions(app_engine, tenant, batch.id) == {(0, "", "ROW_TOO_LARGE")}
    assert batch_row(app_engine, tenant, batch.id).rows_total == 1  # the row before it is kept

    one_cell = ",".join(HEADERS) + "\n" + '"' + "line\n" * 400_000 + '"\n'
    endless = receive(app_engine, store, tenant, one_cell.encode())
    assert run(app_engine, store, tenant, endless.id) == "rejected"  # one endless quoted cell
    assert exceptions(app_engine, tenant, endless.id) == {(0, "", "FILE_UNREADABLE")}  # cell cap

    header_attack = 'a,"x\n' + 'y","x\n' * 300_000 + 'y"\n1,2\n'
    head = receive(app_engine, store, tenant, header_attack.encode())
    assert run(app_engine, store, tenant, head.id) == "rejected"
    assert exceptions(app_engine, tenant, head.id) == {(0, "", "HEADER_TOO_MANY_COLUMNS")}


def test_imp_23_r1_025_honest_quoted_newlines_doubled_quotes_crlf_and_bom_still_import(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    rows = []
    for i in range(1, 6):
        row = good_row(i)
        row[11] = f'say "hi"\r\nsecond line {i}\n, third'
        rows.append(row)
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(HEADERS)
    writer.writerows(rows)
    data = b"\xef\xbb\xbf" + out.getvalue().encode()
    batch = receive(app_engine, store, tenant, data)
    assert run(app_engine, store, tenant, batch.id) == "completed"
    raws = scalar(
        app_engine, tenant, "select json_agg(raw order by row_number) from cbam.source_rows"
    )
    assert [r["SYNTH_DESCRIPTION"] for r in raws] == [r[11] for r in rows]  # type: ignore[union-attr]
