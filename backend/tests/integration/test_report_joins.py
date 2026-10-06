# ruff: noqa: F811 - imported pytest fixtures are test arguments; SQL text is test-only
"""R1-054 header and tax-lines reports are joined to import lines by declaration reference.

Scenario IDs JOIN-01 to JOIN-10. The layout is the PROVISIONAL synthetic fixture (DATA-DEC-002):
every SYNTH_* column is invented. The join is lineage only: it never copies a fact onto a line.
"""

from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.core.db import tenant_session
from app.core.storage import InMemoryStore
from app.modules.imports import ledger
from app.modules.imports.schemas import ImportBatchMetadata
from tests.integration.conftest import make_tenant
from tests.integration.test_import_processing import (  # noqa: F401
    good_row,
    layout,
    owner,
    receive,
    run,
    store,
    to_csv,
)

HEADER_COLS = ["SYNTH_H_MRN", "SYNTH_H_PROCEDURE"]
TAX_COLS = ["SYNTH_T_MRN", "SYNTH_T_ITEM_NO", "SYNTH_T_DUTY"]
EORI = "GB123456789012"


def meta(report_type: str) -> ImportBatchMetadata:
    return ImportBatchMetadata(
        acquisition_method="get_customs_data", cds_report_type=report_type, eori=EORI
    )  # type: ignore[arg-type]


def load(
    engine: Engine,
    store: InMemoryStore,
    tenant: UUID,
    report_type: str,
    rows: list[list[str]],
    headers: list[str] | None = None,
) -> tuple[UUID, str]:
    cols = (
        headers
        or {
            "import_item": None,
            "import_header": HEADER_COLS,
            "import_tax_lines": TAX_COLS,
        }[report_type]
    )
    batch = receive(engine, store, tenant, to_csv(rows, cols), meta(report_type))
    return batch.id, run(engine, store, tenant, batch.id)


def items(engine: Engine, store: InMemoryStore, tenant: UUID, *numbers: int) -> None:
    _, status = load(engine, store, tenant, "import_item", [good_row(n) for n in numbers])
    assert status == "completed"


def mrn(n: int) -> str:
    return f"MRN-SENTINEL-{n:04d}"


def q(engine: Engine, tenant: UUID, statement: str, **params: object) -> list:  # type: ignore[type-arg]
    with tenant_session(engine, tenant_id=tenant) as s:
        return list(s.execute(text(statement), params).all())


def links(engine: Engine, tenant: UUID, role: str) -> list[tuple[str, int]]:
    """(mrn, item_no) of every line with a link of this role, one entry per link."""
    rows = q(
        engine,
        tenant,
        "select d.mrn, l.item_no from cbam.import_line_sources s"
        " join cbam.import_lines l on l.tenant_id = s.tenant_id and l.id = s.import_line_id"
        " join cbam.declarations d on d.tenant_id = l.tenant_id and d.id = l.declaration_id"
        " where s.role = :r order by d.mrn, l.item_no, s.created_at",
        r=role,
    )
    return [(r.mrn, r.item_no) for r in rows]


def test_join_01_a_header_report_after_the_items_links_to_each_line_of_its_declaration(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    items(app_engine, store, tenant, 1, 2, 3)
    _, status = load(
        app_engine, store, tenant, "import_header", [[mrn(1), "4000"], [mrn(2), "4200"]]
    )
    assert status == "completed"
    assert links(app_engine, tenant, "header") == [(mrn(1), 1), (mrn(2), 2)]
    # nothing else changed: still three lines, and the join added no fact to any of them
    assert q(app_engine, tenant, "select count(*) from cbam.import_lines")[0][0] == 3
    assert q(app_engine, tenant, "select count(*) from cbam.declarations")[0][0] == 3


def test_join_02_the_line_detail_lists_the_header_row_next_to_the_item_row(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    items(app_engine, store, tenant, 1)
    load(app_engine, store, tenant, "import_header", [[mrn(1), "4000"]])
    line = q(app_engine, tenant, "select id from cbam.import_lines")[0].id
    with tenant_session(app_engine, tenant_id=tenant) as s:
        detail = ledger.get_line(s, tenant, line)
    assert sorted(x.role for x in detail.sources) == ["header", "primary"]
    header = next(x for x in detail.sources if x.role == "header")
    assert (header.report_type, header.raw["SYNTH_H_PROCEDURE"]) == ("import_header", "4000")


def test_join_03_reports_may_arrive_in_either_order(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    # header and tax lines first: no line exists yet, so nothing links and nothing fails
    _, hstatus = load(app_engine, store, tenant, "import_header", [[mrn(1), "4000"]])
    _, tstatus = load(app_engine, store, tenant, "import_tax_lines", [[mrn(1), "1", "12.00"]])
    assert (hstatus, tstatus) == ("completed", "completed")
    assert links(app_engine, tenant, "header") == [] and links(app_engine, tenant, "tax_line") == []
    assert q(app_engine, tenant, "select count(*) from cbam.report_row_keys")[0][0] == 2
    # the item report lands second and makes both links
    items(app_engine, store, tenant, 1, 2)
    assert links(app_engine, tenant, "header") == [(mrn(1), 1)]
    assert links(app_engine, tenant, "tax_line") == [(mrn(1), 1)]


def test_join_04_a_tax_line_with_an_item_number_joins_that_line_only(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    # two lines of ONE declaration: reuse MRN 1 for item 2 by editing the second row
    second = good_row(2)
    second[0] = mrn(1)
    _, status = load(app_engine, store, tenant, "import_item", [good_row(1), second])
    assert status == "completed"
    load(app_engine, store, tenant, "import_tax_lines", [[mrn(1), "2", "5.00"]])
    assert links(app_engine, tenant, "tax_line") == [(mrn(1), 2)]


def test_join_05_a_tax_line_without_an_item_number_joins_every_line_of_the_declaration(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    second = good_row(2)
    second[0] = mrn(1)
    load(app_engine, store, tenant, "import_item", [good_row(1), second])
    load(app_engine, store, tenant, "import_tax_lines", [[mrn(1), "", "9.00"]])
    assert links(app_engine, tenant, "tax_line") == [(mrn(1), 1), (mrn(1), 2)]


def test_join_06_rows_without_a_usable_key_get_an_error_and_no_key(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    items(app_engine, store, tenant, 1)
    batch, status = load(
        app_engine,
        store,
        tenant,
        "import_tax_lines",
        [["", "1", "1"], [mrn(1), "abc", "2"], [mrn(1), "1", "3"]],
    )
    assert status == "completed_with_errors"
    codes = {
        (r.row_number, r.code)
        for r in q(app_engine, tenant, "select row_number, code from cbam.row_exceptions")
    }
    assert codes == {(1, "MRN_MISSING"), (2, "ITEM_NO_INVALID")}
    # only the good row has a key and a link; the bad item number did NOT join to every line
    assert q(app_engine, tenant, "select count(*) from cbam.report_row_keys")[0][0] == 1
    assert links(app_engine, tenant, "tax_line") == [(mrn(1), 1)]
    assert (
        q(
            app_engine,
            tenant,
            "select rows_total, rows_rejected from cbam.import_batches where id = :b",
            b=batch,
        )[0][1]
        == 2
    )


def test_join_07_a_changed_item_row_makes_a_new_version_that_carries_the_links_too(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    items(app_engine, store, tenant, 1)
    load(app_engine, store, tenant, "import_header", [[mrn(1), "4000"]])
    changed = good_row(1)
    changed[6] = "99.00"
    _, status = load(app_engine, store, tenant, "import_item", [changed])
    assert status == "completed"
    rows = q(
        app_engine,
        tenant,
        "select l.version, count(s.id) filter (where s.role = 'header') as headers"
        " from cbam.import_lines l left join cbam.import_line_sources s"
        " on s.tenant_id = l.tenant_id and s.import_line_id = l.id group by l.version"
        " order by l.version",
    )
    assert [tuple(r) for r in rows] == [(1, 1), (2, 1)]


def test_join_08_repeating_a_header_file_adds_no_duplicate_links(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    items(app_engine, store, tenant, 1)
    rows = [[mrn(1), "4000"]]
    first, _ = load(app_engine, store, tenant, "import_header", rows)
    again = receive(app_engine, store, tenant, to_csv(rows, HEADER_COLS), meta("import_header"))
    assert again.replayed and again.id == first
    assert run(app_engine, store, tenant, first) == "completed"  # a second run changes nothing
    assert links(app_engine, tenant, "header") == [(mrn(1), 1)]
    assert q(app_engine, tenant, "select count(*) from cbam.report_row_keys")[0][0] == 1


def test_join_09_keys_are_append_only_and_private_to_their_tenant(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    items(app_engine, store, a, 1)
    load(app_engine, store, a, "import_header", [[mrn(1), "4000"]])
    assert q(app_engine, b, "select count(*) from cbam.report_row_keys")[0][0] == 0
    for statement in (
        "update cbam.report_row_keys set mrn = 'x'",
        "delete from cbam.report_row_keys",
        "truncate cbam.report_row_keys",
    ):
        with pytest.raises(DBAPIError):
            q(app_engine, a, statement)
    with pytest.raises(DBAPIError):
        with owner(app_engine, a) as s:
            s.execute(text("delete from cbam.report_row_keys"))


def test_join_10_a_headerless_report_layout_is_refused_up_front(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    """A header report whose file lacks the MRN column cannot join anything: the file is rejected."""
    tenant = make_tenant(app_engine, "A")
    batch, status = load(
        app_engine,
        store,
        tenant,
        "import_header",
        [["4000", "note"]],
        headers=["SYNTH_H_PROCEDURE", "SYNTH_HEADER_NOTE"],
    )
    assert status == "rejected"
    codes = q(
        app_engine,
        tenant,
        "select code, field from cbam.row_exceptions where batch_id = :b",
        b=batch,
    )
    assert [(c.code, c.field) for c in codes] == [("COLUMN_MISSING", "SYNTH_H_MRN")]
