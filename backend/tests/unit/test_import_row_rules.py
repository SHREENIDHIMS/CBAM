"""R1-025: row validation is format and presence only; bad rows are reported, never fixed.

Product rules, not law: no regulatory source applies. The layout columns below are SYNTHETIC
names (DATA-DEC-002: the real HMRC layout is provisional until a masked report is available).
"""

import io
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
        ("SYNTH_VALUE", "1.123456789", "VALUE_PRECISION"),
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
        ("SUPPLIER_MISSING", "warning")
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
        ("\nx", "'\nx"),
        (" =1+1", "' =1+1"),
        ("'=1+1", "''=1+1"),
        ('"=1+1', "'\"=1+1"),
        ("\u00a0@x", "'\u00a0@x"),
        ("\uff1d1+1", "'\uff1d1+1"),
        ("\uff0bx", "'\uff0bx"),
        ("\uff0dx", "'\uff0dx"),
        ("\uff20x", "'\uff20x"),
        (";cmd", "';cmd"),
        ("|cmd", "'|cmd"),
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


def test_r1_025_every_required_mapped_field_is_enforced_not_just_the_checked_ones() -> None:
    layout = (
        LayoutColumn("E", "declaration.eori", True),
        LayoutColumn("B", "line.valuation_basis", True),
        LayoutColumn("C", "line.cpc", True),
        LayoutColumn("D", "line.description", True),
        LayoutColumn("S", "line.supplier_ref", True),
        LayoutColumn("O", "line.description", False),
    )
    raw = {"E": "", "B": " ", "C": "", "D": "", "S": ""}
    match = rules.match_layout(list(raw), layout[:5])
    issues = rules.validate_row(rules.map_row(raw, match))
    assert {i.code for i in issues} == {
        "EORI_MISSING",
        "VALUATION_BASIS_MISSING",
        "CPC_MISSING",
        "DESCRIPTION_MISSING",
        "SUPPLIER_MISSING",
    }
    # a required supplier is still only a warning, and an empty optional field is fine
    assert [i.code for i in issues if rules.issue_severity(i.code) == "warning"] == [
        "SUPPLIER_MISSING"
    ]
    assert (
        rules.validate_row(
            rules.map_row(
                {"E": ""},
                rules.match_layout(["E"], (LayoutColumn("E", "declaration.eori", False),)),
            )
        )
        == ()
    )


def test_r1_025_a_layout_with_a_date_but_no_format_or_a_doubled_field_is_invalid() -> None:
    assert rules.layout_is_invalid((LayoutColumn("D", "declaration.acceptance_date", True),))
    assert not rules.layout_is_invalid(
        (LayoutColumn("D", "declaration.acceptance_date", True, "%Y-%m-%d"),)
    )
    assert rules.layout_is_invalid(
        (LayoutColumn("A", "line.cpc", False), LayoutColumn("B", "line.cpc", False))
    )
    # unmapped or unknown targets are ignored, so they cannot clash
    assert not rules.layout_is_invalid(
        (
            LayoutColumn("A", None, False),
            LayoutColumn("B", None, False),
            LayoutColumn("C", "x", False),
        )
    )


def test_r1_025_no_guessed_date_format_a_date_without_one_is_never_accepted() -> None:
    row = rules.MappedRow(
        {"declaration.acceptance_date": "2027-01-05"},
        frozenset(),
        {},
        frozenset({"declaration.acceptance_date"}),
    )
    assert [i.code for i in rules.validate_row(row)] == ["ACCEPTANCE_DATE_INVALID"]


LIMITS = rules.ImportLimits(
    max_columns=3,
    max_heading_chars=5,
    max_cell_chars=10,
    max_row_chars=50,
    chunk_max_chars=100,
    max_attempts=8,
    lease_seconds=300,
)


def test_r1_025_header_limits_give_file_level_codes() -> None:
    assert rules.header_problem(["a", "b", "c"], LIMITS) is None
    assert rules.header_problem(["a", "b", "c", "d"], LIMITS) == "HEADER_TOO_MANY_COLUMNS"
    assert rules.header_problem(["a", "123456"], LIMITS) == "HEADER_TOO_LONG"
    for code in ("HEADER_TOO_MANY_COLUMNS", "HEADER_TOO_LONG", "ROW_TOO_LARGE", "FILE_INFECTED"):
        assert code in rules.FILE_LEVEL_CODES and code in rules.ISSUES
    assert rules.row_chars(["ab", "c"]) == 5


# --- record guard: limits hold even when newlines hide inside quotes -----------------------


def _guard(chars: int = 10_000, columns: int = 50) -> rules.RecordGuard:
    return rules.RecordGuard(max_record_chars=chars, max_columns=columns)


def _feed_all(text_: str, guard: rules.RecordGuard) -> None:
    for line in io.StringIO(text_, newline="").readlines():
        guard.feed(line)


def test_r1_025_a_record_spanning_many_quoted_lines_is_stopped_at_the_row_cap() -> None:
    guard = _guard(chars=1000, columns=10_000)
    with pytest.raises(rules.RecordLimitError) as caught:
        guard.feed('"x\n')  # opens a quote and never closes it: one endless record
        for _ in range(100_000):
            guard.feed("x\n")
    assert caught.value.code == "HEADER_TOO_LONG"  # the header is the first record
    guard = _guard(chars=1000, columns=10_000)
    guard.feed("h1,h2\n")
    with pytest.raises(rules.RecordLimitError) as row:
        guard.feed('"x\n')
        for _ in range(100_000):
            guard.feed("x\n")
    assert row.value.code == "ROW_TOO_LARGE"


def test_r1_025_many_two_line_quoted_cells_in_one_record_hit_the_column_cap() -> None:
    guard = _guard(chars=10**9, columns=200)
    guard.feed("a,b\n")
    with pytest.raises(rules.RecordLimitError) as caught:
        guard.feed('"x\n')
        for _ in range(10**6):
            guard.feed('y","x\n')  # closes one cell, separator, opens the next
    assert caught.value.code == "ROW_TOO_LARGE"
    header = _guard(chars=10**9, columns=200)
    with pytest.raises(rules.RecordLimitError) as head:
        header.feed(",".join("c" * 5 for _ in range(300)) + "\n")
    assert head.value.code == "HEADER_TOO_MANY_COLUMNS"


def test_r1_025_the_reader_never_buffers_more_than_the_cap_for_the_attack_shape() -> None:
    """Peak memory stays small while a practically endless attack file is read lazily."""
    import csv as csv_module
    import tracemalloc

    from app.modules.imports.processing import _bounded_lines

    class Endless(io.TextIOBase):
        def __init__(self) -> None:
            self.sent = 0
            self.first = True

        def readline(self, size: int = -1) -> str:  # type: ignore[override]
            self.sent += 1
            if self.first:
                self.first = False
                return "a,b\n"
            return 'y","x\n' if self.sent > 2 else '"x\n'

    limits = rules.ImportLimits(
        max_columns=200,
        max_heading_chars=200,
        max_cell_chars=4096,
        max_row_chars=1_048_576,
        chunk_max_chars=8_388_608,
        max_attempts=8,
        lease_seconds=300,
    )
    source = Endless()
    tracemalloc.start()
    with pytest.raises(rules.RecordLimitError):
        for _ in csv_module.reader(_bounded_lines(source, limits)):
            pass
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 5_000_000
    assert source.sent < 500  # stopped by the column cap long before the row cap


_CELL = st.text(alphabet=st.sampled_from(list('ab ,"\n\r;é')), max_size=20)


@given(st.lists(st.lists(_CELL, min_size=1, max_size=6), min_size=1, max_size=8), st.booleans())
def test_r1_025_legitimate_quoted_multiline_csv_still_parses_and_is_unchanged_by_the_guard(
    rows: list[list[str]], crlf: bool
) -> None:
    import csv as csv_module

    out = io.StringIO(newline="")
    csv_module.writer(out, lineterminator="\r\n" if crlf else "\n").writerows(rows)
    text_ = out.getvalue()
    guard = _guard(chars=10**6, columns=50)
    _feed_all(text_, guard)  # no limit is hit by an honest file
    parsed = list(csv_module.reader(io.StringIO(text_, newline="")))
    assert parsed == rows  # the writer's quoting round-trips, multi-line cells included


def test_r1_025_csv_safe_skips_any_leading_whitespace_including_unicode_spaces() -> None:
    for space in ("\u3000", "\u2000", "\u2003", "\u200a", "\u00a0", " "):
        assert rules.csv_safe(f"{space}=1+1").startswith("'"), repr(space)
        assert rules.csv_safe(f"{space}'{space}@x").startswith("'")
    assert rules.csv_safe("\u3000plain") == "\u3000plain"
