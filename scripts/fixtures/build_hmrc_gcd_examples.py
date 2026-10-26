"""Build synthetic Get customs data CSV fixtures from HMRC's official blank examples.

The downloaded ODS workbooks contain headers only. This script verifies their pinned
SHA-256 digests, extracts the headers without a spreadsheet dependency, and writes fake
rows beneath them. It never downloads or handles client data.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree

TABLE_NS = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
NS = {"table": TABLE_NS, "text": TEXT_NS}

SOURCES = {
    "item": {
        "filename": "item.ods",
        "sha256": "9b7bb64bee2ed12a51ec73a761b56f81b2efcb4283e99283b99475b5d4a3efef",
        "url": "https://assets.publishing.service.gov.uk/media/6abd0b8f26660e5f62a7f169/Example_imports_item_report.ods",
    },
    "header": {
        "filename": "header.ods",
        "sha256": "1d4860904f6928b7b60acfa3f7326e7ce6d2bf2487eebb14a0bd8f54c0c579cf",
        "url": "https://assets.publishing.service.gov.uk/media/6abd0b4a55bc01d752a7f15a/Example_imports_header_report.ods",
    },
    "tax_lines": {
        "filename": "tax_lines.ods",
        "sha256": "84bbe12c3fde426a1d26ff86d7696219cfed91125d9558ee368617f5d699ceba",
        "url": "https://assets.publishing.service.gov.uk/media/6abd0ad3f04a15f5337227c1/Example_imports_tax_lines_report.ods",
    },
}

MRN = "27GB000000000000A1"
IMPORTER = "GB123456789012"
DECLARANT = "GB999999999999"


def _headers(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        # The whole ODS is hash-pinned before this parser sees its XML.
        root = ElementTree.fromstring(archive.read("content.xml"))  # noqa: S314
    row = root.find(".//table:table/table:table-row", NS)
    if row is None:
        raise ValueError(f"{path} contains no header row")
    headers: list[str] = []
    repeat_key = f"{{{TABLE_NS}}}number-columns-repeated"
    for cell in row.findall("table:table-cell", NS):
        text = " ".join("".join(p.itertext()) for p in cell.findall(".//text:p", NS)).strip()
        headers.extend([text] * int(cell.attrib.get(repeat_key, "1")))
    while headers and not headers[-1]:
        headers.pop()
    if not headers or len(headers) != len(set(headers)):
        raise ValueError(f"{path} has no headers or contains duplicate headers")
    return headers


def _verified_headers(source_dir: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for report_type, source in SOURCES.items():
        path = source_dir / source["filename"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != source["sha256"]:
            raise ValueError(f"unexpected SHA-256 for {path}: {digest}")
        result[report_type] = _headers(path)
    return result


def _base() -> dict[str, str]:
    return {
        "Declaration Data Source": "CDS",
        "Importer EORI": IMPORTER,
        "Entry Identifier": MRN,
        "Entry Date": "05/01/2027",
        "Acceptance Date": "05/01/2027",
        "Clearance Date": "06/01/2027",
        "Declarant EORI": DECLARANT,
        "Trader Reference": "SYNTHETIC-DECLARATION-001",
        "DUCR": "SYNTHETIC-DUCR-001",
    }


def _rows() -> dict[str, list[dict[str, str]]]:
    header = {
        **_base(),
        "Declaration Category": "H1",
        "Declarant Representative": "2",
        "Item Count": "2",
        "Total Packages": "2",
        "Transport Country": "DE",
        "Transport Mode": "1",
        "Customs Value": "20000.00",
        "Invoice Currency": "GBP",
        "Invoice Total": "19500.00",
        "Invoice Total GBP": "19500.00",
    }
    item_one = {
        **_base(),
        "Item Number": "1",
        "Commodity Code": "7208100000",
        "CPC": "4000",
        "Country of Origin": "DE",
        "Invoice Currency": "GBP",
        "Item Price": "12000.00",
        "Customs Value": "12500.00",
        "Net Mass": "10000.000000",
        "Gross Mass": "10100.000000",
        "Goods Description": "SYNTHETIC HOT-ROLLED STEEL COILS",
        "Valuation Method": "1",
        "Consignor": "SYNTHETIC SUPPLIER",
    }
    item_two = {
        **_base(),
        "Item Number": "2",
        "Commodity Code": "7601100000",
        "CPC": "4000",
        "Country of Origin": "NO",
        "Invoice Currency": "GBP",
        "Item Price": "7200.00",
        "Customs Value": "7500.00",
        "Net Mass": "2500.000000",
        "Gross Mass": "2550.000000",
        "Goods Description": "SYNTHETIC UNWROUGHT ALUMINIUM",
        "Valuation Method": "1",
        "Consignor": "SYNTHETIC SUPPLIER",
    }
    tax_one = {
        **_base(),
        "Item Number": "1",
        "Commodity Code": "7208100000",
        "CPC": "4000",
        "Country of Origin": "DE",
        "Customs Value": "12500.00",
        "Tax Type 1": "A00",
        "Method of Payment 1": "G",
        "Tax Amount 1": "250.00",
    }
    tax_two = {
        **_base(),
        "Item Number": "2",
        "Commodity Code": "7601100000",
        "CPC": "4000",
        "Country of Origin": "NO",
        "Customs Value": "7500.00",
        "Tax Type 1": "A00",
        "Method of Payment 1": "G",
        "Tax Amount 1": "150.00",
    }
    return {"item": [item_one, item_two], "header": [header], "tax_lines": [tax_one, tax_two]}


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_layout(root: Path) -> None:
    folder = root / "backend/tests/fixtures/refdata/cds_report_layouts/hmrc-example.2026-02-26"
    layout = [
        ("import_item", "Entry Identifier", "declaration.mrn", "true", ""),
        ("import_item", "Acceptance Date", "declaration.acceptance_date", "true", "%d/%m/%Y"),
        ("import_item", "Importer EORI", "declaration.eori", "true", ""),
        ("import_item", "Declarant EORI", "declaration.declarant_eori", "false", ""),
        ("import_item", "Item Number", "line.item_no", "true", ""),
        ("import_item", "Commodity Code", "line.commodity_code", "true", ""),
        ("import_item", "Net Mass", "line.net_mass_kg", "true", ""),
        ("import_item", "Customs Value", "line.customs_value", "true", ""),
        # Sample-only: both invoice and customs values in our fake rows are GBP. A real report
        # is still required before this field can be treated as the customs-value currency.
        ("import_item", "Invoice Currency", "line.customs_value_currency", "true", ""),
        ("import_item", "Country of Origin", "line.origin_country", "true", ""),
        ("import_item", "Valuation Method", "line.valuation_basis", "false", ""),
        ("import_item", "CPC", "line.cpc", "false", ""),
        ("import_item", "Goods Description", "line.description", "false", ""),
        ("import_header", "Entry Identifier", "declaration.mrn", "true", ""),
        ("import_tax_lines", "Entry Identifier", "declaration.mrn", "true", ""),
        ("import_tax_lines", "Item Number", "line.item_no", "false", ""),
    ]
    folder.mkdir(parents=True, exist_ok=True)
    data_path = folder / "data.csv"
    with data_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("report_type", "column_name", "maps_to", "required", "date_format"))
        writer.writerows(layout)
    checksum = hashlib.sha256(data_path.read_bytes()).hexdigest()
    manifest = "\n".join(
        (
            "dataset: cds_report_layouts",
            'version: "hmrc-example.2026-02-26"',
            "source_id: HMRC-GCD-EXAMPLES-2026-02-26",
            "source_title: HMRC Get customs data example reports",
            "source_type: guidance",
            "source_url: https://www.gov.uk/guidance/get-customs-data-for-import-and-export-declarations",
            "publication_date: 2026-02-26",
            "retrieved_at: 2026-10-26",
            "source_status: draft",
            "fixture: true",
            "effective_from: 2026-02-26",
            "effective_to: null",
            f"checksum_sha256: {checksum}",
            'notes: "FIXTURE ONLY. Official headers with synthetic values. Date and currency '
            'mapping remain provisional pending a masked real report (DATA-DEC-002)."',
            "",
        )
    )
    (folder / "manifest.yaml").write_text(manifest, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    headers = _verified_headers(args.source_dir)
    rows = _rows()
    fixture_dir = args.repo_root / "backend/tests/fixtures/cds/hmrc_official_examples"
    for report_type in ("item", "header", "tax_lines"):
        _write_csv(
            fixture_dir / f"import_{report_type}.csv", headers[report_type], rows[report_type]
        )
    (fixture_dir / "sources.json").write_text(
        json.dumps(SOURCES, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_layout(args.repo_root)


if __name__ == "__main__":
    main()
