"""Which party is liable for CBAM on a declaration (R1-036). Pure: no database, clock or network.

The law that says who is liable is NOT in this file. It is the `liable_person_rules` reference
dataset (CLAUDE.md rule 1), usable only while its source is `in_force` or `commenced` (rule 2).
LEGAL-DEC-019 (indirect representation, the "no duty" branch of FA 2026 s.144(5), overseas
importers of record, express and postal consignments, Northern Ireland) is still open, so until a
domain owner loads and activates rules the answer is always `undetermined` and the declaration
waits for a person (rule 3 spirit; rule 15: no invented behaviour).

What this file does decide is bookkeeping, not law: it reads the facts as reported, works out the
relation between the declarant and the importer by comparing their EORIs, and picks the one rule
row that matches. Zero matches, several matches, or a matched party with no EORI are all
`undetermined`: the engine never guesses between rows and never falls back to "the importer".

A tax agent or broker named on a declaration never becomes liable by that fact (rule 14): only a
rule row can name the declarant or representative as the liable party.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.core.decisions import Decision

RULE_ID = "R1-036.liable_person"
RULE_VERSION = "1"

DETERMINED = "determined"
UNDETERMINED = "undetermined"

# Why a declaration is undetermined. Short upper-case codes, never free text from a file.
NO_ACTIVE_RULE = "NO_ACTIVE_RULE"
NO_MATCHING_RULE = "NO_MATCHING_RULE"
AMBIGUOUS_RULES = "AMBIGUOUS_RULES"
IMPORTER_UNKNOWN = "IMPORTER_UNKNOWN"
LIABLE_PARTY_MISSING = "LIABLE_PARTY_MISSING"

_REASONS: Mapping[str, str] = {
    NO_ACTIVE_RULE: "no liable-person rule is active for this date: a person must decide",
    NO_MATCHING_RULE: "no active liable-person rule covers these facts: a person must decide",
    AMBIGUOUS_RULES: "more than one active liable-person rule matches: a person must decide",
    IMPORTER_UNKNOWN: "the importer is not known on this declaration: a person must decide",
    LIABLE_PARTY_MISSING: "the rule names a party this declaration lacks: a person must decide",
}


@dataclass(frozen=True)
class DeclarationParties:
    """Facts about one declaration, as reported (never inferred)."""

    importer_eori: str | None
    declarant_eori: str | None
    representative_eori: str | None
    representation_type: str  # self | direct | indirect | unknown
    eori_context: str | None  # GB | XI, from the importer's EORI


def declarant_relation(facts: DeclarationParties) -> str:
    """`absent`, `same_as_importer` or `different_from_importer`. The importer must be known."""
    if facts.declarant_eori is None:
        return "absent"
    if facts.declarant_eori == facts.importer_eori:
        return "same_as_importer"
    return "different_from_importer"


def _matches(row: Mapping[str, Any], facts: DeclarationParties, relation: str) -> bool:
    if row["representation_type"] != facts.representation_type:
        return False
    if row["declarant_relation"] not in (relation, "any"):
        return False
    context = row.get("eori_context")
    return context is None or context == facts.eori_context


def _undetermined(code: str, **details: Any) -> Decision:
    return Decision(
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        source_ids=(),
        outcome=UNDETERMINED,
        reason=_REASONS[code],
        details={"code": code, **details},
    )


def determine(facts: DeclarationParties, rows: Sequence[Mapping[str, Any]]) -> Decision:
    """The liable party for one declaration, given the `liable_person_rules` rows usable on the
    legal date. `outcome` is `determined` (with `details.liable_party`: importer, declarant or
    representative) or `undetermined` (with `details.code`)."""
    if not rows:
        return _undetermined(NO_ACTIVE_RULE)
    if facts.importer_eori is None:
        return _undetermined(IMPORTER_UNKNOWN)
    relation = declarant_relation(facts)
    matched = [r for r in rows if _matches(r, facts, relation)]
    if not matched:
        return _undetermined(NO_MATCHING_RULE, declarant_relation=relation)
    if len(matched) > 1:
        return _undetermined(AMBIGUOUS_RULES, rule_keys=sorted(str(r["rule_key"]) for r in matched))
    rule = matched[0]
    party = str(rule["liable_party"])
    eori = {
        "importer": facts.importer_eori,
        "declarant": facts.declarant_eori,
        "representative": facts.representative_eori,
    }[party]
    if eori is None:
        return _undetermined(LIABLE_PARTY_MISSING, rule_key=str(rule["rule_key"]), party=party)
    return Decision(
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        source_ids=(str(rule["source_ref"]),) if rule.get("source_ref") else (),
        outcome=DETERMINED,
        reason=f"rule {rule['rule_key']} names the {party}",
        details={
            "rule_key": str(rule["rule_key"]),
            "liable_party": party,
            "declarant_relation": relation,
        },
    )
