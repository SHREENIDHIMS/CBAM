"""R1-005 / R1-006 / R1-010 normalisation rules (pure): exact facts, no float, stable hashes.

Product rules, not law: no regulatory source applies. Values are synthetic. Scenario IDs:
IMP-40 exact commodity code and mass, IMP-43 customs value GBP versus other currencies,
IMP-42 nothing is decided here, IMP-47 hashing and reconciliation, IMP-48 value-correction guard.
"""

import dataclasses
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.permissions import ROLE_PERMISSIONS, TAX_AGENT_FORBIDDEN
from app.modules.imports import rules

CTX = rules.NormalisationContext(batch_eori="GB123456789012", entry_method="gcd")
FORMATS = {"declaration.acceptance_date": "%d/%m/%Y"}


def mapped(**over: str) -> rules.MappedRow:
    values = {
        "declaration.mrn": "MRN-1",
        "declaration.acceptance_date": "05/01/2027",
        "line.item_no": "1",
        "line.commodity_code": "7208100000",
        "line.net_mass_kg": "12.500000",
        "line.customs_value": "1234.56",
        "line.customs_value_currency": "GBP",
        "line.origin_country": "DE",
        **{k.replace("__", "."): v for k, v in over.items()},
    }
    return rules.MappedRow(values, frozenset(), FORMATS, frozenset(values))


def line(**over: str) -> rules.NormalisedLine:
    result = rules.normalise_row(mapped(**over), CTX)
    assert result.line is not None, result.issues
    return result.line


def test_imp_40_r1_005_the_commodity_code_is_kept_exactly_and_mass_at_six_places() -> None:
    kept = line(line__commodity_code="0102030405", line__net_mass_kg="0.000001")
    assert kept.commodity_code == "0102030405"  # leading zero and all 10 digits
    assert kept.net_mass_kg == Decimal("0.000001")
    assert line(line__commodity_code="72081000").commodity_code == "72081000"


def test_imp_40_r1_005_origin_and_valuation_basis_are_kept_as_declared() -> None:
    kept = line(line__origin_country="TR", line__valuation_basis="  1 ")
    assert kept.country_of_origin_declared == "TR"
    assert kept.valuation_basis == "1"  # as declared, not interpreted


def test_imp_43_r1_010_gbp_value_is_set_only_for_gbp_without_rounding() -> None:
    gbp = line()
    assert gbp.customs_value_gbp == Decimal("1234.56")
    assert gbp.customs_value_gbp_note is None
    assert gbp.value_source == "declared"


def test_imp_43_r1_010_a_non_gbp_value_is_kept_in_its_currency_with_no_fx() -> None:
    eur = line(line__customs_value_currency="EUR")
    assert eur.customs_value_source == Decimal("1234.56")
    assert eur.customs_value_currency == "EUR"
    assert eur.customs_value_gbp is None
    assert eur.customs_value_gbp_note == "non_gbp_no_fx"


def test_imp_43_r1_010_a_gbp_value_with_more_than_two_places_is_not_rounded() -> None:
    odd = line(line__customs_value="10.005")
    assert odd.customs_value_source == Decimal("10.005")
    assert odd.customs_value_gbp is None
    assert odd.customs_value_gbp_note == "gbp_more_than_2dp"


def test_imp_42_r1_005_a_normalised_line_has_no_tax_point_scope_quarter_or_threshold() -> None:
    names = {f.name for f in dataclasses.fields(rules.NormalisedLine)}
    names |= {f.name for f in dataclasses.fields(rules.DeclarationFacts)}
    for banned in ("tax_point", "scope", "quarter", "threshold", "period", "liable"):
        assert not any(banned in n for n in names), banned


def test_r1_006_party_roles_are_captured_as_reported_and_liability_is_not_inferred() -> None:
    plain = line()
    assert plain.declaration.representation_type == "unknown"
    assert plain.declaration.importer_eori == "GB123456789012"  # the batch EORI fills a gap
    assert plain.declaration.eori_context == "GB"
    acting = line(
        declaration__eori="XI123456789012",
        declaration__declarant_eori="GB999999999999",
        declaration__representative_eori="GB888888888888",
        declaration__representation_type="Indirect",
    ).declaration
    assert (acting.importer_eori, acting.declarant_eori, acting.representative_eori) == (
        "XI123456789012",
        "GB999999999999",
        "GB888888888888",
    )
    assert (acting.representation_type, acting.eori_context) == ("indirect", "XI")


def test_r1_006_a_bad_eori_or_representation_type_is_an_issue_not_a_guess() -> None:
    bad = rules.normalise_row(
        mapped(declaration__declarant_eori="FR123", declaration__representation_type="agent"), CTX
    )
    assert bad.line is None
    assert {(i.field, i.code) for i in bad.issues} == {
        ("declaration.declarant_eori", "EORI_INVALID"),
        ("declaration.representation_type", "REPRESENTATION_TYPE_INVALID"),
    }


def test_r1_006_validation_flags_the_same_problems_before_normalisation() -> None:
    found = rules.validate_row(
        mapped(declaration__declarant_eori="FR123", declaration__representation_type="agent")
    )
    assert {i.code for i in found} == {"EORI_INVALID", "REPRESENTATION_TYPE_INVALID"}


def test_r1_005_a_value_longer_than_the_stored_field_is_a_row_error() -> None:
    found = rules.validate_row(mapped(declaration__mrn="M" * 101))
    assert [(i.field, i.code) for i in found] == [("declaration.mrn", "FIELD_TOO_LONG")]


def test_parse_eori_context() -> None:
    assert rules.parse_eori_context("GB123456789012") == "GB"
    assert rules.parse_eori_context("XI123456789012") == "XI"
    for value in (None, "", "FR123456789012", "GB12345", "gb123456789012"):
        assert rules.parse_eori_context(value) is None


def test_line_key_is_the_mrn_and_the_numeric_item_number() -> None:
    assert rules.line_key(mapped(line__item_no="007")) == ("MRN-1", 7)
    assert rules.line_key(mapped(line__item_no="x")) is None
    assert rules.line_key(mapped(declaration__mrn=" ")) is None


def test_imp_47_r1_003_reconcile_says_new_same_changed_or_conflict() -> None:
    assert rules.reconcile(None, "a") == "new"
    assert rules.reconcile("a", "a") == "same"
    assert rules.reconcile("a", "b") == "changed"
    assert rules.reconcile("a", "b", same_batch=True) == "conflict"
    assert rules.reconcile("a", "a", same_batch=True) == "same"


def test_imp_47_r1_003_the_hash_ignores_trailing_zeros_but_not_content() -> None:
    assert (
        line(line__net_mass_kg="1.50").content_sha256
        == line(line__net_mass_kg="1.5").content_sha256
    )
    assert line().content_sha256 != line(line__commodity_code="7208100001").content_sha256
    assert line().content_sha256 != line(declaration__eori="GB000000000001").content_sha256
    assert line(line__item_no="1").content_sha256 != line(line__item_no="2").content_sha256


def test_imp_47_hashing_refuses_a_float() -> None:
    with pytest.raises(TypeError):
        rules.content_hash({"x": 1.5})


@settings(max_examples=60, deadline=None)
@given(
    mass=st.decimals(min_value=0, max_value=10**13, places=6),
    value=st.decimals(min_value=0, max_value=10**15, places=8),
    code=st.from_regex(r"^[0-9]{8,10}$", fullmatch=True),
)
def test_imp_47_normalisation_never_makes_a_float_and_the_hash_is_stable(
    mass: Decimal, value: Decimal, code: str
) -> None:
    row = mapped(
        line__net_mass_kg=format(mass, "f"),
        line__customs_value=format(value, "f"),
        line__commodity_code=code,
    )
    first, second = rules.normalise_row(row, CTX), rules.normalise_row(row, CTX)
    assert first == second and first.line is not None
    got = first.line
    assert got.net_mass_kg == mass and got.customs_value_source == value
    assert got.commodity_code == code
    for f in dataclasses.fields(got):
        assert not isinstance(getattr(got, f.name), float)
    assert not isinstance(got.customs_value_gbp, float)
    assert len(got.content_sha256) == 64


@given(st.text(max_size=40), st.text(max_size=40), st.text(max_size=40))
def test_imp_47_normalise_row_never_raises_for_any_cell_text(a: str, b: str, c: str) -> None:
    rules.normalise_row(mapped(line__net_mass_kg=a, line__customs_value=b, declaration__mrn=c), CTX)


def test_entry_method_follows_the_acquisition_method() -> None:
    assert rules.entry_method_for("get_customs_data") == "gcd"
    assert rules.entry_method_for("cds_export") == "cds"
    # `manual` is reserved for human-keyed entry (R1-004): an uploaded file is never `manual`
    assert rules.entry_method_for("manual_upload") == "cds"
    assert rules.entry_method_for("data_request") == "cds"
    assert rules.entry_method_for("manual_entry") == "manual"


def test_imp_48_r1_010_a_value_correction_needs_the_permission_and_a_reason() -> None:
    ops = frozenset(ROLE_PERMISSIONS["operations"])
    assert rules.check_value_correction(ops, "Invoice re-issued").outcome == "ALLOWED"
    assert rules.check_value_correction(ops, "  ").outcome == "BLOCKED"
    assert rules.check_value_correction(ops, None).outcome == "BLOCKED"
    assert rules.check_value_correction(frozenset({"imports:write"}), "x").outcome == "BLOCKED"


def test_imp_48_r1_010_only_operations_and_client_admin_may_correct_never_a_tax_agent() -> None:
    holders = {r for r, p in ROLE_PERMISSIONS.items() if "imports:correct" in p}
    assert holders == {"operations", "client_admin"}
    assert "imports:correct" in TAX_AGENT_FORBIDDEN


def test_the_gbp_helper_quantises_exactly() -> None:
    assert rules.customs_value_gbp(Decimal("5"), "GBP") == (Decimal("5.00"), None)
    assert rules.customs_value_gbp(Decimal("0.1"), "GBP") == (Decimal("0.10"), None)


def decide(**over: object) -> str:
    base: dict[str, object] = {
        "current_hash": "b",
        "current_entry_method": "gcd",
        "current_value_source": "declared",
        "current_batch_id": 1,
        "current_recency": date(2027, 2, 1),
        "earlier_hashes": frozenset({"a"}),
        "incoming_hash": "c",
        "incoming_batch_id": 2,
        "incoming_recency": date(2027, 2, 1),
    }
    return rules.reconcile_version(**{**base, **over})  # type: ignore[arg-type]


def test_imp_47_r1_005_stale_data_never_supersedes_newer_data_or_a_correction() -> None:
    assert decide(current_hash=None) == "new"
    assert decide(incoming_hash="b") == "same"
    assert decide(incoming_hash="a") == "seen_earlier"  # a stale overlapping file
    assert decide() == "changed"  # equal recency: the later-loaded report wins
    assert decide(incoming_recency=date(2027, 3, 1)) == "changed"
    assert decide(incoming_recency=date(2027, 1, 1)) == "older_extract"
    assert decide(incoming_batch_id=1) == "conflict"
    for kind in ("correction", "manual"):
        assert decide(current_entry_method=kind) == "blocked_by_correction"
        assert decide(current_value_source=kind) == "blocked_by_correction"
    # a correction still lets a file that agrees with it, or with history, be a mere sighting
    assert decide(current_entry_method="correction", incoming_hash="b") == "same"
    assert decide(current_entry_method="correction", incoming_hash="a") == "seen_earlier"


def test_imp_47_r1_003_the_hash_carries_a_schema_version() -> None:
    base = {"x": "1"}
    assert rules.content_hash(base) == rules.content_hash(dict(base))
    original = rules.HASH_VERSION
    try:
        rules.HASH_VERSION = original + 1
        bumped = rules.content_hash(base)
    finally:
        rules.HASH_VERSION = original
    assert bumped != rules.content_hash(base)  # a new version never matches old hashes silently


def test_imp_47_r1_005_the_new_issue_codes_have_fixed_messages() -> None:
    for code in ("SOURCE_CONFLICTS_WITH_CORRECTION", "OLDER_EXTRACT_CONFLICT"):
        assert rules.issue_severity(code) == "error"
        assert len(rules.issue_message(code)) > 20
