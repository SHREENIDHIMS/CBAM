"""R1-050 / R2-020: source activation rule, source status changes, version diffs.

Sources of the cases: docs/DATABASE.md section 5 (activation rule), CLAUDE.md rules 2 and 17.
"""

from datetime import date

import pytest

from app.modules.refdata import rules

D = date(2027, 6, 1)


def usable(**kw: object) -> str:
    args: dict[str, object] = {
        "source_id": "S",
        "status": "in_force",
        "commencement_date": None,
        "effective_from": None,
        "effective_to": None,
        "on": D,
    }
    args.update(kw)
    return rules.source_usable(**args).outcome  # type: ignore[arg-type]


@pytest.mark.parametrize("status", ["draft", "laid", "superseded"])
def test_only_in_force_or_commenced_sources_are_active(status: str) -> None:
    assert usable(status=status) == "NOT_ACTIVE"


@pytest.mark.parametrize("status", ["in_force", "commenced"])
def test_in_force_and_commenced_sources_are_active(status: str) -> None:
    assert usable(status=status) == "ACTIVE"


def test_commencement_date_is_inclusive() -> None:
    assert usable(commencement_date=D) == "ACTIVE"
    assert usable(commencement_date=date(2027, 6, 2)) == "NOT_ACTIVE"


def test_source_effective_period_end_is_exclusive() -> None:
    assert usable(effective_to=date(2027, 6, 2)) == "ACTIVE"
    assert usable(effective_to=D) == "NOT_ACTIVE"
    assert usable(effective_from=date(2027, 6, 2)) == "NOT_ACTIVE"


def test_source_status_moves_forward_only_and_needs_a_reason() -> None:
    assert (
        rules.source_status_decision("laid", "in_force", reason="SI text read").outcome == "ALLOWED"
    )
    assert rules.source_status_decision("laid", "in_force", reason=" ").outcome == "REASON_REQUIRED"
    for target in ("draft", "laid"):
        decision = rules.source_status_decision("in_force", target, reason="x")
        assert decision.outcome == "BLOCKED"
    assert rules.source_status_decision("superseded", "in_force", reason="x").outcome == "BLOCKED"
    assert rules.source_status_decision("in_force", "bogus", reason="x").outcome == "BLOCKED"


def row(
    code: str, text_: str, start: str = "2027-01-01", end: str | None = None
) -> dict[str, object]:
    return {
        "code_prefix": code,
        "description": text_,
        "effective_from": date.fromisoformat(start),
        "effective_to": date.fromisoformat(end) if end else None,
    }


KEY = ("code_prefix",)
COLS = ("code_prefix", "description")


def test_overlap_detection_uses_the_business_key_and_exclusive_end() -> None:
    rows = [row("72", "a"), row("72", "b", "2027-06-01"), row("73", "c")]
    assert rules.find_overlaps(rows, KEY) == [(0, 1)]
    touching = [row("72", "a", end="2027-06-01"), row("72", "b", "2027-06-01")]
    assert rules.find_overlaps(touching, KEY) == []


def test_diff_lists_added_removed_and_changed_rows() -> None:
    old = [row("72", "Iron"), row("7601", "Alu"), row("2804", "H2")]
    new = [row("72", "Iron and steel"), row("2804", "H2"), row("2523", "Cement")]
    diff = rules.diff_versions(old, new, key=KEY, columns=COLS)
    kinds = {(c.change, c.key["code_prefix"]) for c in diff.changes}
    assert kinds == {("changed", "72"), ("removed", "7601"), ("added", "2523")}
    assert diff.unchanged == 1
    changed = next(c for c in diff.changes if c.change == "changed")
    assert changed.before and changed.after
    assert (changed.before["description"], changed.after["description"]) == (
        "Iron",
        "Iron and steel",
    )


def test_diff_of_identical_versions_is_empty() -> None:
    rows = [row("72", "Iron")]
    diff = rules.diff_versions(rows, list(rows), key=KEY, columns=COLS)
    assert diff.changes == () and diff.unchanged == 1 and diff.coverage_gaps == ()


def test_coverage_gap_when_new_version_starts_later() -> None:
    old = [row("72", "Iron", "2027-01-01")]
    new = [row("72", "Iron", "2027-07-01")]
    gaps = rules.diff_versions(old, new, key=KEY, columns=COLS).coverage_gaps
    assert [(g.key["code_prefix"], g.start, g.end) for g in gaps] == [
        ("72", date(2027, 1, 1), date(2027, 7, 1))
    ]


def test_coverage_gap_when_a_key_disappears_entirely() -> None:
    old = [row("72", "Iron", "2027-01-01", "2028-01-01")]
    gaps = rules.diff_versions(old, [], key=KEY, columns=COLS).coverage_gaps
    assert [(g.start, g.end) for g in gaps] == [(date(2027, 1, 1), date(2028, 1, 1))]


def test_no_gap_when_the_new_version_covers_the_old_period() -> None:
    old = [row("72", "Iron", "2027-01-01")]
    new = [row("72", "Iron", "2027-01-01", "2027-07-01"), row("72", "Iron", "2027-07-01")]
    assert rules.diff_versions(old, new, key=KEY, columns=COLS).coverage_gaps == ()
