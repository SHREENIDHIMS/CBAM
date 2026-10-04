"""R1-025: row validation is format and presence only; bad rows are reported, never fixed.

Product rules, not law: no regulatory source applies. The layout columns below are SYNTHETIC
names (DATA-DEC-002: the real HMRC layout is provisional until a masked report is available).
"""

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.modules.imports import rules
from app.modules.imports.rules import LayoutColumn

LAYOUT = (
    LayoutColumn("SYNTH_MRN", "declaration.mrn", True),
    LayoutColumn("SYNTH_DATE", "declaration.acceptance_date", True, "%d/%m/%Y"),
    LayoutColumn("SYNTH_ITEM", "line.item_no", True),
    LayoutColumn("SYNTH_CODE", "line.commodity_code", True),
    LayoutColumn("SYNTH_MASS", "line.net_mass_kg", True),
    LayoutColumn("SYNTH_VALUE", "line.customs_value", True),
    LayoutColumn("SYNTH_CCY", "line.customs_value_currency", True),
    LayoutColumn("SYNTH_ORIGIN", "line.origin_country", True),
    LayoutColumn("SYNTH_SUPPLIER", "line.supplier_ref", False),
)
GOOD = {
    "SYNTH_MRN": "27GB000000000000A1",
    "SYNTH_DATE": "05/01/2027",
    "SYNTH_ITEM": "1",
    "SYNTH_CODE": "7208100000",
    "SYNTH_MASS": "1000.500000",
    "SYNTH_VALUE": "1234.56",
    "SYNTH_CCY": "EUR",
    "SYNTH_ORIGIN": "DE",
    "SYNTH_SUPPLIER": "Acme",
}


def _codes(raw: dict[str, str]) -> list[str]:
    match = rules.match_layout(list(raw), LAYOUT)
    return [i.code for i in rules.validate_row(rules.map_row(raw, match))]


def test_r1_025_a_good_row_has_no_issues() -> None:
    assert _codes(GOOD) == []


@pytest.mark.parametrize(
    ("column", "value", "code"),
    [
        ("SYNTH_CODE", "", "COMMODITY_CODE_MISSING"),
        ("SYNTH_CODE", "7208", "COMMODITY_CODE_INVALID"),
        ("SYNTH_CODE", "72081000001", "COMMODITY_CODE_INVALID"),
        ("SYNTH_CODE", "7208 10 00", "COMMODITY_CODE_INVALID"),
        ("SYNTH_MASS", "", "NET_MASS_MISSING"),
        ("SYNTH_MASS", "-1", "NET_MASS_INVALID"),
        ("SYNTH_MASS", "1e3", "NET_MASS_INVALID"),
        ("SYNTH_MASS", "1,000", "NET_MASS_INVALID"),
        ("SYNTH_MASS", "NaN", "NET_MASS_INVALID"),
        ("SYNTH_MASS", "1.1234567", "NET_MASS_PRECISION"),
        ("SYNTH_DATE", "", "ACCEPTANCE_DATE_MISSING"),
        ("SYNTH_DATE", "2027-01-05", "ACCEPTANCE_DATE_INVALID"),
        ("SYNTH_DATE", "31/02/2027", "ACCEPTANCE_DATE_INVALID"),
        ("SYNTH_ORIGIN", "", "ORIGIN_MISSING"),
        ("SYNTH_ORIGIN", "de", "ORIGIN_INVALID"),
        ("SYNTH_ORIGIN", "DEU", "ORIGIN_INVALID"),
        ("SYNTH_VALUE", "", "VALUE_MISSING"),
        ("SYNTH_VALUE", "12.3.4", "VALUE_INVALID"),
        ("SYNTH_VALUE", "-5", "VALUE_INVALID"),
        ("SYNTH_CCY", "", "CURRENCY_MISSING"),
        ("SYNTH_CCY", "EU", "CURRENCY_INVALID"),
        ("SYNTH_MRN", "  ", "MRN_MISSING"),
        ("SYNTH_ITEM", "0", "ITEM_NO_INVALID"),
        ("SYNTH_ITEM", "x", "ITEM_NO_INVALID"),
    ],
)
def test_r1_025_each_problem_has_its_own_code(column: str, value: str, code: str) -> None:
    assert _codes({**GOOD, column: value}) == [code]


def test_r1_025_seven_decimal_places_are_reported_never_rounded() -> None:
    value, too_precise = rules.parse_plain_decimal("0.1234567", int_digits=14, scale=6)
    assert (value, too_precise) == (None, True)
    # trailing zeros carry no information, so six real places are fine
    assert rules.parse_plain_decimal("0.1234560", int_digits=14, scale=6) == (
        Decimal("0.123456"),
        False,
    )


def test_r1_025_commodity_code_is_judged_as_given_and_never_truncated() -> None:
    assert _codes({**GOOD, "SYNTH_CODE": "0123456789"}) == []  # leading zero, 10 digits
    assert _codes({**GOOD, "SYNTH_CODE": "01234567"}) == []  # 8 digits


def test_r1_025_no_scope_or_tax_point_decision_is_made() -> None:
    """A code that is certainly not on any list and a date far in the past are format-valid."""
    assert _codes({**GOOD, "SYNTH_CODE": "99999999", "SYNTH_DATE": "01/01/1990"}) == []


def test_r1_025_supplier_is_a_warning_only_and_the_row_stays_valid() -> None:
    issues = rules.validate_row(
        rules.map_row({**GOOD, "SYNTH_SUPPLIER": ""}, rules.match_layout(list(GOOD), LAYOUT))
    )
    assert [(i.code, rules.issue_severity(i.code)) for i in issues] == [
        ("SUPPLIER_UNMAPPED", "warning")
    ]
    assert rules.row_is_valid(issues)
    assert not rules.row_is_valid([rules.Issue("NET_MASS_INVALID", "line.net_mass_kg")])


def test_r1_025_an_empty_optional_column_is_not_a_problem() -> None:
    layout = (LayoutColumn("A", "line.net_mass_kg", False),)
    match = rules.match_layout(["A"], layout)
    assert rules.validate_row(rules.map_row({"A": ""}, match)) == ()


def test_r1_025_layout_matching_ignores_case_extra_columns_and_bom() -> None:
    headers = rules.raw_headers(["﻿ synth_mrn ", "extra thing", "SYNTH_DATE"])
    match = rules.match_layout(headers, LAYOUT[:2])
    assert match.ok
    assert match.headers[0] == " synth_mrn "  # kept as read, only the BOM is dropped
    missing = rules.match_layout(["SYNTH_MRN"], LAYOUT[:2])
    assert missing.missing_required == ("SYNTH_DATE",)
    assert not rules.match_layout(["a", "A"], LAYOUT[:1]).ok


def test_r1_025_unknown_maps_to_target_is_ignored_not_trusted() -> None:
    match = rules.match_layout(["X"], (LayoutColumn("X", "line.not_a_field", True),))
    assert match.ok and not match.by_header


def test_r1_025_build_raw_keeps_every_cell_as_read() -> None:
    raw, issues = rules.build_raw(["a", "b"], [" 007 ", "=1+1", "extra"])
    assert raw == {"a": " 007 ", "b": "=1+1", rules.EXTRA_CELLS_KEY: ["extra"]}
    assert [i.code for i in issues] == ["ROW_TOO_LONG"]
    raw, issues = rules.build_raw(["a", "b"], ["x"])
    assert raw == {"a": "x"} and [i.code for i in issues] == ["ROW_TOO_SHORT"]
    assert rules.row_hash(raw) == rules.row_hash(dict(reversed(list(raw.items()))))


def test_r1_025_messages_are_fixed_text_and_codes_are_short() -> None:
    for code, (severity, message) in rules.ISSUES.items():
        assert severity in ("error", "warning")
        assert rules.re.match(r"^[A-Z0-9_]{1,64}$", code)
        assert "{" not in message and len(message) <= 500


@pytest.mark.parametrize(
    ("cell", "safe"),
    [
        ("=cmd|' /C calc'!A0", "'=cmd|' /C calc'!A0"),
        ("+1", "'+1"),
        ("-1", "'-1"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tx", "'\tx"),
        ("\rx", "'\rx"),
        ("plain", "plain"),
        ("", ""),
    ],
)
def test_r1_025_csv_cells_that_could_run_as_formulas_are_escaped(cell: str, safe: str) -> None:
    assert rules.csv_safe(cell) == safe


@given(st.text(max_size=60), st.text(max_size=60), st.text(max_size=60))
def test_r1_025_validate_row_never_raises_for_arbitrary_text(a: str, b: str, c: str) -> None:
    raw = {**GOOD, "SYNTH_MASS": a, "SYNTH_DATE": b, "SYNTH_CODE": c, "SYNTH_VALUE": a + b}
    match = rules.match_layout(list(raw), LAYOUT)
    issues = rules.validate_row(rules.map_row(raw, match))
    assert all(i.code in rules.ISSUES for i in issues)


@given(st.integers(0, 10**12), st.integers(0, 6), st.integers(0, 10**6))
def test_r1_025_decimal_parsing_is_exact_and_never_goes_through_a_float(
    whole: int, places: int, frac_seed: int
) -> None:
    frac = str(frac_seed).zfill(places)[:places] if places else ""
    text = f"{whole}.{frac}" if places else str(whole)
    value, too_precise = rules.parse_plain_decimal(text, int_digits=14, scale=6)
    assert not too_precise
    assert value == Decimal(text)  # exact: a float round trip would not hold at these sizes
    assert isinstance(value, Decimal)
