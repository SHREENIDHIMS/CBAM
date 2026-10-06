"""R1-036 liable-person rule engine. Scenario IDs LP-01 to LP-16.

The rows below are TEST DATA: the outcomes are invented to exercise the engine and are not law
(LEGAL-DEC-019 is open, so no real rule is loaded anywhere).
"""

from dataclasses import fields
from typing import Any

from app.modules.liability import rules

IMPORTER = "GB123456789012"
FORWARDER = "GB210987654321"
AGENT = "XI111111111111"


def row(
    key: str, rtype: str, relation: str, party: str, context: str | None = None
) -> dict[str, Any]:
    return {
        "rule_key": key,
        "representation_type": rtype,
        "declarant_relation": relation,
        "eori_context": context,
        "liable_party": party,
        "source_ref": "FIXTURE-TEST-SOURCE",
    }


RULES = [
    row("t.direct", "self", "same_as_importer", "importer", "GB"),
    row("t.forwarder", "self", "different_from_importer", "importer", "GB"),
    row("t.on_behalf", "direct", "any", "importer", "GB"),
    row("t.indirect", "indirect", "any", "representative", "GB"),
]


def facts(
    *,
    importer: str | None = IMPORTER,
    declarant: str | None = None,
    representative: str | None = None,
    kind: str = "self",
    context: str | None = "GB",
    source: str | None = "declared",
) -> rules.DeclarationParties:
    return rules.DeclarationParties(importer, declarant, representative, kind, context, source)


def test_lp_01_no_active_rule_is_undetermined_never_the_importer() -> None:
    d = rules.determine(facts(declarant=IMPORTER), [])
    assert (d.outcome, d.details["code"]) == ("undetermined", rules.NO_ACTIVE_RULE)
    assert "liable_party" not in d.details


def test_lp_02_importer_lodging_its_own_declaration() -> None:
    d = rules.determine(facts(declarant=IMPORTER), RULES)
    assert d.outcome == "determined"
    assert d.details["liable_party"] == "importer"
    assert d.details["rule_key"] == "t.direct"
    assert d.source_ids == ("FIXTURE-TEST-SOURCE",)


def test_lp_03_no_declarant_counts_as_absent_and_matches_no_same_or_different_rule() -> None:
    d = rules.determine(facts(declarant=None), RULES)
    assert (d.outcome, d.details["code"]) == ("undetermined", rules.NO_MATCHING_RULE)
    assert d.details["declarant_relation"] == "absent"


def test_lp_04_freight_forwarder_as_declarant_keeps_the_importer_liable() -> None:
    d = rules.determine(facts(declarant=FORWARDER), RULES)
    assert d.outcome == "determined"
    assert d.details["liable_party"] == "importer"
    assert d.details["rule_key"] == "t.forwarder"


def test_lp_05_acting_on_behalf_in_the_importers_name() -> None:
    d = rules.determine(facts(declarant=FORWARDER, representative=FORWARDER, kind="direct"), RULES)
    assert (d.outcome, d.details["liable_party"]) == ("determined", "importer")


def test_lp_06_a_rule_can_name_the_representative_only_if_the_declaration_has_one() -> None:
    ok = rules.determine(facts(declarant=FORWARDER, representative=AGENT, kind="indirect"), RULES)
    assert (ok.outcome, ok.details["liable_party"]) == ("determined", "representative")
    missing = rules.determine(facts(declarant=FORWARDER, kind="indirect"), RULES)
    assert (missing.outcome, missing.details["code"]) == (
        "undetermined",
        rules.LIABLE_PARTY_MISSING,
    )


def test_lp_07_an_eori_context_restricts_a_rule() -> None:
    d = rules.determine(
        facts(declarant=FORWARDER, representative=AGENT, kind="indirect", context="XI"), RULES
    )
    assert (d.outcome, d.details["code"]) == ("undetermined", rules.NO_MATCHING_RULE)


def test_lp_08_unknown_representation_type_is_undetermined_unless_a_rule_covers_it() -> None:
    d = rules.determine(facts(declarant=FORWARDER, kind="unknown"), RULES)
    assert (d.outcome, d.details["code"]) == ("undetermined", rules.NO_MATCHING_RULE)
    covered = [*RULES, row("t.unknown", "unknown", "any", "importer", "GB")]
    assert rules.determine(facts(declarant=FORWARDER, kind="unknown"), covered).outcome == (
        "determined"
    )


def test_lp_09_two_matching_rows_are_ambiguous_and_nothing_is_picked() -> None:
    both = [*RULES, row("t.overlap", "self", "any", "declarant", "GB")]
    d = rules.determine(facts(declarant=FORWARDER), both)
    assert (d.outcome, d.details["code"]) == ("undetermined", rules.AMBIGUOUS_RULES)
    assert d.details["rule_keys"] == ["t.forwarder", "t.overlap"]


def test_lp_10_an_unknown_importer_is_undetermined() -> None:
    d = rules.determine(facts(importer=None, declarant=FORWARDER), RULES)
    assert (d.outcome, d.details["code"]) == ("undetermined", rules.IMPORTER_UNKNOWN)


def test_lp_11_a_declarant_is_not_liable_unless_a_rule_says_so() -> None:
    for kind in ("self", "direct", "indirect", "unknown"):
        d = rules.determine(facts(declarant=FORWARDER, representative=AGENT, kind=kind), RULES)
        assert d.details.get("liable_party") != "declarant"


def test_lp_12_every_undetermined_reason_is_fixed_text() -> None:
    for code in (
        rules.NO_ACTIVE_RULE,
        rules.NO_MATCHING_RULE,
        rules.AMBIGUOUS_RULES,
        rules.IMPORTER_UNKNOWN,
        rules.LIABLE_PARTY_MISSING,
        rules.IMPORTER_INFERRED,
    ):
        assert rules._REASONS[code]
        assert IMPORTER not in rules._REASONS[code]


def test_lp_13_r1_036_an_importer_taken_from_the_batch_is_never_treated_as_declared() -> None:
    for source in ("batch_fallback", None):
        d = rules.determine(facts(declarant=IMPORTER, source=source), RULES)
        assert (d.outcome, d.details["code"]) == ("undetermined", rules.IMPORTER_INFERRED)
        assert "liable_party" not in d.details
    # with no importer at all the older, more basic reason still wins
    d = rules.determine(facts(importer=None, declarant=FORWARDER, source=None), RULES)
    assert d.details["code"] == rules.IMPORTER_UNKNOWN


def test_lp_14_r1_036_a_row_with_no_eori_context_matches_nothing() -> None:
    blank = [
        row("t.blank", "self", "any", "importer", None),
        row("t.empty", "self", "any", "importer", ""),
    ]
    for context in ("GB", "XI", None):
        d = rules.determine(facts(declarant=IMPORTER, context=context), blank)
        assert (d.outcome, d.details["code"]) == ("undetermined", rules.NO_MATCHING_RULE)
    # an XI declaration is not settled by a GB row either
    d = rules.determine(facts(declarant=IMPORTER, context="XI"), RULES)
    assert d.outcome == "undetermined"


def test_lp_15_r1_036_facts_the_engine_does_not_model_never_default_to_determined() -> None:
    """No-duty, overseas importer and express/postal cases (LEGAL-DEC-019) are not inputs: the
    engine cannot see them, so a declaration only comes out `determined` when an active rule row
    names it, and with unknown representation and no declarant it stays undetermined."""
    assert {f.name for f in fields(rules.DeclarationParties)} == {
        "importer_eori",
        "declarant_eori",
        "representative_eori",
        "representation_type",
        "eori_context",
        "importer_eori_source",
    }
    d = rules.determine(facts(declarant=None, kind="unknown"), RULES)
    assert (d.outcome, d.details["code"]) == ("undetermined", rules.NO_MATCHING_RULE)
    assert rules.determine(facts(declarant=None, kind="unknown"), []).outcome == "undetermined"
