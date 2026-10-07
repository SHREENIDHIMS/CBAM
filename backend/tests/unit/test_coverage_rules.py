"""R1-054 coverage calendar rules. Scenario IDs COV-01 to COV-14.

Product rules, not law. The lag value is an input (reference data), so every number here is a
test input and not an HMRC fact.
"""

from datetime import date

import pytest

from app.modules.coverage import rules
from app.modules.coverage.rules import GAP, LOADED, LOADED_WITH_ERRORS, NOT_YET_AVAILABLE, Window

D = date


def win(batch: str, start: date, end: date, *, errors: bool = False) -> Window:
    return Window(batch, start, end, errors)


def cal(windows: list[Window], **kw: object):  # type: ignore[no-untyped-def]
    args: dict[str, object] = {
        "tracking_from": D(2027, 1, 1),
        "range_from": D(2027, 1, 1),
        "range_to": D(2027, 3, 31),
        "today": D(2027, 3, 31),
        "unavailable_latest_days": None,
    }
    args.update(kw)
    return rules.build_calendar(windows, **args)  # type: ignore[arg-type]


def states(c) -> list[tuple[date, date, str]]:  # type: ignore[no-untyped-def]
    return [(p.covered_from, p.covered_to, p.state) for p in c.periods]


def test_cov_01_nothing_loaded_is_one_gap_from_the_first_day_to_cover() -> None:
    c = cal([])
    assert states(c) == [(D(2027, 1, 1), D(2027, 3, 31), GAP)]
    assert not c.complete


def test_cov_02_a_year_of_consecutive_31_day_windows_has_no_gap() -> None:
    windows = []
    start = D(2027, 1, 1)
    from datetime import timedelta

    for i in range(12):
        end = min(start + timedelta(days=30), D(2027, 12, 31))
        windows.append(win(f"b{i}", start, end))
        start = end + timedelta(days=1)
    c = cal(windows, range_to=D(2027, 12, 31), today=D(2027, 12, 31))
    assert states(c) == [(D(2027, 1, 1), D(2027, 12, 31), LOADED)]
    assert c.complete and c.overlaps == ()


def test_cov_03_a_missing_window_is_a_gap_between_two_loaded_periods() -> None:
    c = cal([win("a", D(2027, 1, 1), D(2027, 1, 31)), win("c", D(2027, 3, 3), D(2027, 3, 31))])
    assert states(c) == [
        (D(2027, 1, 1), D(2027, 1, 31), LOADED),
        (D(2027, 2, 1), D(2027, 3, 2), GAP),
        (D(2027, 3, 3), D(2027, 3, 31), LOADED),
    ]
    assert [(g.covered_from, g.covered_to) for g in c.gaps] == [(D(2027, 2, 1), D(2027, 3, 2))]


def test_cov_04_overlapping_windows_are_reported_not_faulted() -> None:
    c = cal([win("a", D(2027, 1, 1), D(2027, 1, 31)), win("b", D(2027, 1, 25), D(2027, 2, 28))])
    assert [(o.covered_from, o.covered_to, o.batch_ids) for o in c.overlaps] == [
        (D(2027, 1, 25), D(2027, 1, 31), ("a", "b"))
    ]
    assert states(c)[0] == (D(2027, 1, 1), D(2027, 2, 28), LOADED)


def test_cov_05_the_latest_days_are_not_yet_available_when_a_lag_rule_is_active() -> None:
    c = cal(
        [win("a", D(2027, 1, 1), D(2027, 3, 28))],
        unavailable_latest_days=2,
    )
    assert states(c) == [
        (D(2027, 1, 1), D(2027, 3, 28), LOADED),
        (D(2027, 3, 29), D(2027, 3, 29), GAP),
        (D(2027, 3, 30), D(2027, 3, 31), NOT_YET_AVAILABLE),
    ]
    assert not c.complete  # 29 March is a real gap


def test_cov_06_without_a_lag_rule_no_day_is_treated_as_unavailable() -> None:
    c = cal([win("a", D(2027, 1, 1), D(2027, 3, 28))], unavailable_latest_days=None)
    assert states(c)[-1] == (D(2027, 3, 29), D(2027, 3, 31), GAP)


def test_cov_07_days_not_yet_available_do_not_stop_a_calendar_being_complete() -> None:
    c = cal([win("a", D(2027, 1, 1), D(2027, 3, 29))], unavailable_latest_days=2)
    assert c.complete and c.gaps == ()


def test_cov_08_a_day_loaded_only_by_a_batch_with_errors_is_loaded_with_errors() -> None:
    c = cal([win("a", D(2027, 1, 1), D(2027, 1, 31), errors=True)], range_to=D(2027, 1, 31))
    assert states(c) == [(D(2027, 1, 1), D(2027, 1, 31), LOADED_WITH_ERRORS)]
    assert not c.complete


def test_cov_09_a_clean_batch_over_the_same_days_makes_them_loaded() -> None:
    c = cal(
        [
            win("a", D(2027, 1, 1), D(2027, 1, 31), errors=True),
            win("b", D(2027, 1, 10), D(2027, 1, 20)),
        ],
        range_to=D(2027, 1, 31),
    )
    assert states(c) == [
        (D(2027, 1, 1), D(2027, 1, 9), LOADED_WITH_ERRORS),
        (D(2027, 1, 10), D(2027, 1, 20), LOADED),
        (D(2027, 1, 21), D(2027, 1, 31), LOADED_WITH_ERRORS),
    ]


def test_cov_10_days_before_the_first_day_to_cover_and_after_today_are_ignored() -> None:
    c = cal(
        [win("a", D(2026, 12, 1), D(2027, 1, 31))],
        range_from=D(2026, 12, 1),
        range_to=D(2027, 6, 30),
        today=D(2027, 2, 10),
    )
    assert states(c) == [
        (D(2027, 1, 1), D(2027, 1, 31), LOADED),
        (D(2027, 2, 1), D(2027, 2, 10), GAP),
    ]


def test_cov_11_a_range_entirely_in_the_future_is_empty_and_complete() -> None:
    c = cal([], range_from=D(2027, 6, 1), range_to=D(2027, 6, 30), today=D(2027, 3, 1))
    assert c.periods == () and c.complete


def test_cov_12_a_backwards_or_huge_range_is_refused() -> None:
    with pytest.raises(ValueError):
        cal([], range_from=D(2027, 3, 1), range_to=D(2027, 2, 1))
    with pytest.raises(ValueError):
        cal([], tracking_from=D(2020, 1, 1), range_from=D(2020, 1, 1), range_to=D(2027, 3, 31))


def test_cov_13_month_helpers() -> None:
    assert rules.previous_month(D(2027, 3, 1)) == (D(2027, 2, 1), D(2027, 2, 28))
    assert rules.previous_month(D(2027, 1, 15)) == (D(2026, 12, 1), D(2026, 12, 31))
    assert rules.previous_month(D(2028, 3, 1)) == (D(2028, 2, 1), D(2028, 2, 29))
    assert rules.month_key(D(2027, 2, 1)) == "2027-02"
    assert rules.month_label(D(2027, 2, 1)) == "February 2027"


def test_cov_14_fetch_due_date_waits_for_the_lag_but_is_never_before_the_first() -> None:
    last = D(2027, 2, 28)
    assert rules.fetch_due_date(last, 2) == D(2027, 3, 2)
    assert rules.fetch_due_date(last, None) == D(2027, 3, 1)
    assert rules.fetch_due_date(last, 0) == D(2027, 3, 1)
    assert rules.gap_key(D(2027, 2, 1)) == "coverage_gap:2027-02-01"


def test_cov_15_fetch_due_date_for_other_lags_and_a_lag_of_zero_hides_nothing() -> None:
    last = D(2027, 2, 28)
    assert rules.fetch_due_date(last, 1) == D(2027, 3, 1)
    assert rules.fetch_due_date(last, 3) == D(2027, 3, 3)
    c = cal([win("a", D(2027, 1, 1), D(2027, 3, 30))], unavailable_latest_days=0)
    assert states(c)[-1] == (D(2027, 3, 31), D(2027, 3, 31), GAP)
