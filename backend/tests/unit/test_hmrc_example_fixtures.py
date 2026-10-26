"""R1-054 / DATA-DEC-002: HMRC-header fixtures stay synthetic and importer-compatible."""

import csv
import json
from pathlib import Path

from app.modules.imports import rules

ROOT = Path(__file__).resolve().parents[1] / "fixtures"
REPORTS = ROOT / "cds" / "hmrc_official_examples"
LAYOUT = ROOT / "refdata" / "cds_report_layouts" / "hmrc-example.2026-02-26"


def _read(name: str) -> tuple[list[str], list[dict[str, str]]]:
    with (REPORTS / name).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or ()), list(reader)


def _layout() -> list[dict[str, object]]:
    with (LAYOUT / "data.csv").open(encoding="utf-8", newline="") as handle:
        return [
            {
                **row,
                "required": row["required"].casefold() == "true",
            }
            for row in csv.DictReader(handle)
        ]


def test_official_header_snapshots_cover_the_three_import_reports() -> None:
    item, item_rows = _read("import_item.csv")
    header, header_rows = _read("import_header.csv")
    tax, tax_rows = _read("import_tax_lines.csv")

    assert len(item) == 80 and len(header) == 63 and len(tax) == 95
    assert {"Entry Identifier", "Commodity Code", "Valuation Method"} <= set(item)
    assert {"Entry Identifier", "Item Count", "Customs Value"} <= set(header)
    assert {"Entry Identifier", "Item Number", "Tax Type 1"} <= set(tax)
    assert (len(item_rows), len(header_rows), len(tax_rows)) == (2, 1, 2)


def test_every_checked_in_value_is_obviously_synthetic() -> None:
    for filename in ("import_item.csv", "import_header.csv", "import_tax_lines.csv"):
        _, rows = _read(filename)
        for row in rows:
            assert row["Entry Identifier"] == "27GB000000000000A1"
            assert row["Importer EORI"] == "GB123456789012"
            assert "SYNTHETIC" in row["Trader Reference"]


def test_pinned_sources_are_official_https_assets() -> None:
    sources = json.loads((REPORTS / "sources.json").read_text(encoding="utf-8"))
    assert set(sources) == {"item", "header", "tax_lines"}
    for source in sources.values():
        assert source["url"].startswith("https://assets.publishing.service.gov.uk/")
        assert len(source["sha256"]) == 64


def test_item_fixture_matches_the_provisional_layout_and_validates() -> None:
    headers, rows = _read("import_item.csv")
    columns = rules.layout_columns(_layout(), "import_item")
    match = rules.match_layout(headers, columns)

    assert match.ok
    assert not rules.layout_is_invalid(columns)
    assert rules.missing_line_fields(match) == ()
    for row in rows:
        assert rules.validate_row(rules.map_row(row, match)) == ()


def test_header_and_tax_fixtures_expose_the_join_keys() -> None:
    layout = _layout()
    for filename, report_type in (
        ("import_header.csv", "import_header"),
        ("import_tax_lines.csv", "import_tax_lines"),
    ):
        headers, rows = _read(filename)
        match = rules.match_layout(headers, rules.layout_columns(layout, report_type))
        assert match.ok
        mapped = [rules.map_row(row, match).values for row in rows]
        assert all(row["declaration.mrn"] == "27GB000000000000A1" for row in mapped)
        if report_type == "import_tax_lines":
            assert [row["line.item_no"] for row in mapped] == ["1", "2"]
