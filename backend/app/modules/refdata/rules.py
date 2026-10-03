"""Reference-data rules (R1-050, R2-020). Pure functions: no database, clock or network.

The source activation rule (CLAUDE.md rule 2, docs/DATABASE.md section 5) is written here once
for tests and for the impact report, and once in SQL in the `v_active_*` views. A test runs
both against the same cases so they cannot drift apart.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.core.decisions import Decision

RULE_SOURCE_ACTIVE = "R1-050.source_activation"
RULE_SOURCE_STATUS = "R2-020.source_status"
RULE_VERSION = "1"

ACTIVE_SOURCE_STATUSES = frozenset({"in_force", "commenced"})

# One-way: a source is never moved back to draft; a mistake is fixed by superseding it.
_SOURCE_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"laid", "in_force", "commenced", "superseded"}),
    "laid": frozenset({"in_force", "commenced", "superseded"}),
    "in_force": frozenset({"superseded"}),
    "commenced": frozenset({"superseded"}),
    "superseded": frozenset(),
}

Row = Mapping[str, Any]


def source_usable(
    *,
    source_id: str,
    status: str,
    commencement_date: date | None,
    effective_from: date | None,
    effective_to: date | None,
    on: date,
) -> Decision:
    """May a rule backed by this source drive a decision on legal date `on`?"""

    def decide(outcome: str, reason: str) -> Decision:
        return Decision(RULE_SOURCE_ACTIVE, RULE_VERSION, (source_id,), outcome, reason)

    if status not in ACTIVE_SOURCE_STATUSES:
        return decide("NOT_ACTIVE", f"source status is {status}; only in_force or commenced counts")
    if commencement_date is not None and on < commencement_date:
        return decide("NOT_ACTIVE", f"source commences on {commencement_date.isoformat()}")
    if effective_from is not None and on < effective_from:
        return decide("NOT_ACTIVE", f"source applies from {effective_from.isoformat()}")
    if effective_to is not None and on >= effective_to:
        return decide("NOT_ACTIVE", f"source stopped applying on {effective_to.isoformat()}")
    return decide("ACTIVE", "source is in force on this date")


def source_status_decision(current: str, target: str, *, reason: str | None) -> Decision:
    def decide(outcome: str, text: str) -> Decision:
        return Decision(RULE_SOURCE_STATUS, RULE_VERSION, (), outcome, text)

    if current not in _SOURCE_TRANSITIONS or target not in _SOURCE_TRANSITIONS:
        return decide("BLOCKED", f"unknown status in {current!r} -> {target!r}")
    if target not in _SOURCE_TRANSITIONS[current]:
        return decide("BLOCKED", f"{current} -> {target} is not allowed")
    if not (reason and reason.strip()):
        return decide("REASON_REQUIRED", f"{current} -> {target} needs a reason")
    return decide("ALLOWED", f"{current} -> {target}")


def row_usable_on(row: Row, on: date) -> bool:
    """Is a row's own effective period open on `on`? (`effective_to` is exclusive.)"""
    effective_to = row.get("effective_to")
    return row["effective_from"] <= on and (effective_to is None or on < effective_to)


def _period_end(row: Row) -> date:
    return row["effective_to"] or date.max


def find_overlaps(rows: Sequence[Row], key: Sequence[str]) -> list[tuple[int, int]]:
    """Index pairs of rows with the same business key and overlapping periods."""
    found: list[tuple[int, int]] = []
    for i, first in enumerate(rows):
        for j in range(i + 1, len(rows)):
            second = rows[j]
            if any(first[k] != second[k] for k in key):
                continue
            if first["effective_from"] < _period_end(second) and (
                second["effective_from"] < _period_end(first)
            ):
                found.append((i, j))
    return found


@dataclass(frozen=True)
class Change:
    change: str  # added | removed | changed
    key: dict[str, Any]
    effective_from: date
    before: dict[str, Any] | None
    after: dict[str, Any] | None


@dataclass(frozen=True)
class CoverageGap:
    key: dict[str, Any]
    start: date
    end: date | None  # exclusive; None = open ended


@dataclass(frozen=True)
class VersionDiff:
    changes: tuple[Change, ...]
    unchanged: int
    coverage_gaps: tuple[CoverageGap, ...]

    def count(self, kind: str) -> int:
        return sum(1 for c in self.changes if c.change == kind)


def _identity(row: Row, key: Sequence[str]) -> tuple[Any, ...]:
    return (*(row[k] for k in key), row["effective_from"])


def _values(row: Row, columns: Sequence[str]) -> dict[str, Any]:
    return {c: row.get(c) for c in columns}


def _gaps(old: Sequence[Row], new: Sequence[Row], key: Sequence[str]) -> list[CoverageGap]:
    """Periods the old version covered for a key that the new version no longer covers."""
    gaps: list[CoverageGap] = []
    for old_row in old:
        same_key = [n for n in new if all(n[k] == old_row[k] for k in key)]
        cursor = old_row["effective_from"]
        end = _period_end(old_row)
        for n in sorted(same_key, key=lambda r: r["effective_from"]):
            if _period_end(n) <= cursor or n["effective_from"] >= end:
                continue
            if n["effective_from"] > cursor:
                gaps.append(_gap(old_row, key, cursor, n["effective_from"]))
            cursor = max(cursor, _period_end(n))
            if cursor >= end:
                break
        if cursor < end:
            gaps.append(_gap(old_row, key, cursor, old_row["effective_to"]))
    return gaps


def _gap(row: Row, key: Sequence[str], start: date, end: date | None) -> CoverageGap:
    return CoverageGap(key={k: row[k] for k in key}, start=start, end=end)


def diff_versions(
    old: Sequence[Row], new: Sequence[Row], *, key: Sequence[str], columns: Sequence[str]
) -> VersionDiff:
    """What activating `new` instead of `old` would change, row by row."""
    old_by = {_identity(r, key): r for r in old}
    new_by = {_identity(r, key): r for r in new}
    compared = [*columns, "effective_to"]
    changes: list[Change] = []
    unchanged = 0
    for ident in sorted(old_by.keys() | new_by.keys(), key=repr):
        before, after = old_by.get(ident), new_by.get(ident)
        row = after if after is not None else before
        if row is None:  # unreachable: the identity came from one of the two versions
            continue
        keyed = {k: row[k] for k in key}
        if before is None:
            kind = "added"
        elif after is None:
            kind = "removed"
        elif _values(before, compared) != _values(after, compared):
            kind = "changed"
        else:
            unchanged += 1
            continue
        changes.append(
            Change(
                change=kind,
                key=keyed,
                effective_from=row["effective_from"],
                before=None if before is None else _values(before, compared),
                after=None if after is None else _values(after, compared),
            )
        )
    return VersionDiff(
        changes=tuple(changes), unchanged=unchanged, coverage_gaps=tuple(_gaps(old, new, key))
    )
