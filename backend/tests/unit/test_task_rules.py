"""R1-022: task status machine and escalation, as pure rules."""

from datetime import date

import pytest

from app.modules.tasks import rules


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("open", "in_progress"),
        ("open", "done"),
        ("in_progress", "open"),
        ("in_progress", "done"),
        ("blocked", "in_progress"),
    ],
)
def test_ordinary_transitions_are_allowed(current: str, target: str) -> None:
    d = rules.transition_decision(current, target, reason=None)
    assert d.outcome == "ALLOWED"
    assert d.rule_id == "R1-022.status_transition"


def test_same_status_is_not_a_transition() -> None:
    assert rules.transition_decision("open", "open", reason="x").outcome == "BLOCKED"


def test_unknown_status_is_blocked() -> None:
    assert rules.transition_decision("open", "archived", reason="x").outcome == "BLOCKED"
    assert rules.transition_decision("weird", "open", reason="x").outcome == "BLOCKED"


@pytest.mark.parametrize("target", ["in_progress", "blocked", "done", "cancelled"])
def test_done_and_cancelled_can_only_be_reopened(target: str) -> None:
    for closed in ("done", "cancelled"):
        if target == closed:
            continue
        assert rules.transition_decision(closed, target, reason="why").outcome == "BLOCKED"


@pytest.mark.parametrize(
    ("current", "target"),
    [("open", "blocked"), ("in_progress", "cancelled"), ("done", "open"), ("cancelled", "open")],
)
def test_blocking_cancelling_and_reopening_need_a_reason(current: str, target: str) -> None:
    assert rules.transition_decision(current, target, reason=None).outcome == "REASON_REQUIRED"
    assert rules.transition_decision(current, target, reason="   ").outcome == "REASON_REQUIRED"
    assert (
        rules.transition_decision(current, target, reason="supplier asked for time").outcome
        == "ALLOWED"
    )


@pytest.mark.parametrize(
    ("overdue_days", "level"),
    [(-3, 0), (0, 0), (6, 0), (7, 1), (13, 1), (14, 2), (27, 2), (28, 3), (400, 3)],
)
def test_escalation_level_follows_days_overdue(overdue_days: int, level: int) -> None:
    due = date(2027, 3, 1)
    as_of = date.fromordinal(due.toordinal() + overdue_days)
    assert rules.next_escalation_level(due, as_of, 0, (7, 14, 28)) == level


def test_escalation_never_goes_down() -> None:
    assert rules.next_escalation_level(date(2027, 3, 1), date(2027, 3, 2), 2, (7, 14, 28)) == 2


def test_no_due_date_never_escalates() -> None:
    assert rules.next_escalation_level(None, date(2030, 1, 1), 0, (7, 14, 28)) == 0


def test_no_thresholds_means_no_escalation() -> None:
    assert rules.next_escalation_level(date(2027, 1, 1), date(2027, 12, 1), 0, ()) == 0


@pytest.mark.parametrize("status", ["done", "cancelled"])
def test_closed_tasks_do_not_escalate(status: str) -> None:
    assert not rules.is_escalatable(status)


@pytest.mark.parametrize("status", ["open", "in_progress", "blocked"])
def test_open_tasks_can_escalate(status: str) -> None:
    assert rules.is_escalatable(status)
