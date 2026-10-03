"""Task status machine and escalation (R1-022). Pure functions: no database, clock or network.

The Day 7/14/21/28 chase is a product workflow, not law (CLAUDE.md rule 13): escalation
thresholds are passed in by the caller from configuration.
"""

from collections.abc import Sequence
from datetime import date

from app.core.decisions import Decision

RULE_TRANSITION = "R1-022.status_transition"
RULE_VERSION = "1"

STATUSES: tuple[str, ...] = ("open", "in_progress", "blocked", "done", "cancelled")
_CLOSED = frozenset({"done", "cancelled"})
_ALLOWED: dict[str, frozenset[str]] = {
    "open": frozenset({"in_progress", "blocked", "done", "cancelled"}),
    "in_progress": frozenset({"open", "blocked", "done", "cancelled"}),
    "blocked": frozenset({"open", "in_progress", "done", "cancelled"}),
    "done": frozenset({"open"}),  # reopen only
    "cancelled": frozenset({"open"}),
}
_REASON_REQUIRED_TARGETS = frozenset({"blocked", "cancelled"})


def _decision(outcome: str, reason: str) -> Decision:
    return Decision(
        rule_id=RULE_TRANSITION,
        rule_version=RULE_VERSION,
        source_ids=(),
        outcome=outcome,
        reason=reason,
    )


def transition_decision(current: str, target: str, *, reason: str | None) -> Decision:
    """ALLOWED, BLOCKED (illegal move) or REASON_REQUIRED (legal, but a reason is mandatory)."""
    if current not in _ALLOWED or target not in STATUSES:
        return _decision("BLOCKED", f"unknown status in {current!r} -> {target!r}")
    if target == current:
        return _decision("BLOCKED", "status is unchanged")
    if target not in _ALLOWED[current]:
        return _decision("BLOCKED", f"{current} -> {target} is not allowed")
    reopening = current in _CLOSED and target == "open"
    if (reopening or target in _REASON_REQUIRED_TARGETS) and not (reason and reason.strip()):
        return _decision("REASON_REQUIRED", f"{current} -> {target} needs a reason")
    return _decision("ALLOWED", f"{current} -> {target}")


def is_escalatable(status: str) -> bool:
    return status in STATUSES and status not in _CLOSED


def next_escalation_level(
    due_date: date | None,
    as_of: date,
    current_level: int,
    thresholds_days: Sequence[int],
) -> int:
    """Escalation level for a task `as_of` a date: how many overdue thresholds it has passed.

    Never lowers a level. No due date or no thresholds means no escalation.
    """
    if due_date is None or not thresholds_days:
        return current_level
    days_overdue = (as_of - due_date).days
    reached = sum(1 for t in sorted(thresholds_days) if days_overdue >= t)
    return max(current_level, reached)
