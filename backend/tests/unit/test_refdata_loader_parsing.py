"""R1-050: manifest and data.csv validation (no database)."""

from datetime import date
from decimal import Decimal

import pytest

from app.core.errors import InvalidRequestError
from app.modules.refdata.datasets import DATASETS, dataset_spec
from app.modules.refdata.load import parse_rows, sha256_hex
from app.modules.refdata.manifest import Manifest, parse_manifest

SHA = "a" * 64
BASE = f"""dataset: threshold_rules
version: "t.1"
source_id: TEST
source_title: Test
source_type: guidance
retrieved_at: 2026-10-03
source_status: laid
effective_from: 2027-01-01
checksum_sha256: {SHA}
"""


def manifest(**over: object) -> Manifest:
    m = parse_manifest(BASE.encode())
    return m.model_copy(update=over)


def test_manifest_parses_and_defaults() -> None:
    m = parse_manifest(BASE.encode())
    assert (m.dataset, m.version, m.fixture, m.effective_to) == (
        "threshold_rules",
        "t.1",
        False,
        None,
    )


def test_unquoted_version_number_is_refused() -> None:
    with pytest.raises(InvalidRequestError, match="quoted"):
        parse_manifest(BASE.replace('"t.1"', "2027.1").encode())


@pytest.mark.parametrize("claimed", ["in_force", "commenced", "superseded"])
def test_manifest_cannot_claim_a_source_is_in_force(claimed: str) -> None:
    with pytest.raises(InvalidRequestError, match="domain owner"):
        parse_manifest(BASE.replace("source_status: laid", f"source_status: {claimed}").encode())


def test_manifest_rejects_unknown_fields_and_bad_checksums() -> None:
    with pytest.raises(InvalidRequestError):
        parse_manifest((BASE + "surprise: 1\n").encode())
    with pytest.raises(InvalidRequestError, match="checksum"):
        parse_manifest(BASE.replace(SHA, "XYZ").encode())


def test_parse_rows_types_and_defaults() -> None:
    spec = dataset_spec("threshold_rules")
    csv = (
        "threshold_gbp,forward_days,backward_months,backward_test_day,lookback_floor_date,"
        "warning_ratio\n50000.00,30,12,1,2027-01-01,0.8000\n"
    )
    (row,) = parse_rows(spec, manifest(), csv.encode())
    assert row["threshold_gbp"] == Decimal("50000.00")
    assert isinstance(row["threshold_gbp"], Decimal)
    assert row["forward_days"] == 30
    assert row["lookback_floor_date"] == date(2027, 1, 1)
    assert row["effective_from"] == date(2027, 1, 1) and row["effective_to"] is None


def test_parse_rows_refuses_wrong_columns() -> None:
    spec = dataset_spec("service_state")
    with pytest.raises(InvalidRequestError, match="do not match"):
        parse_rows(spec, manifest(), b"service,opening_date,bonus\nregistration,2028-01-01,x\n")
    with pytest.raises(InvalidRequestError, match="missing"):
        parse_rows(spec, manifest(), b"service\nregistration\n")


def test_parse_rows_reports_every_bad_cell_with_its_row_number() -> None:
    spec = dataset_spec("service_state")
    csv = b"service,opening_date\nregistration,not-a-date\n,2028-01-01\nok,2028-01-01\n"
    with pytest.raises(InvalidRequestError) as exc:
        parse_rows(spec, manifest(), csv)
    assert "row 2, opening_date" in exc.value.detail
    assert "row 3, service" in exc.value.detail


def test_parse_rows_refuses_overlapping_periods_for_one_key() -> None:
    spec = dataset_spec("service_state")
    csv = b"service,opening_date\nregistration,2028-01-01\nregistration,2028-02-01\n"
    with pytest.raises(InvalidRequestError, match="overlapping"):
        parse_rows(spec, manifest(), csv)


def test_parse_rows_refuses_end_before_start() -> None:
    spec = dataset_spec("customs_monthly_exchange_rates")
    csv = (
        b"currency,quote,rate,effective_from,effective_to\n"
        b"USD,foreign_per_gbp,1.25,2027-02-01,2027-01-01\n"
    )
    with pytest.raises(InvalidRequestError, match="after effective_from"):
        parse_rows(spec, manifest(), csv)


def test_no_float_in_decimal_columns() -> None:
    assert all(c.kind != "float" for s in DATASETS.values() for c in s.columns)


def test_checksum_is_sha256_of_the_bytes() -> None:
    assert sha256_hex(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
