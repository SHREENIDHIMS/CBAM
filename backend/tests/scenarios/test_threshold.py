"""R1-012 threshold scenario catalogue TH-01..TH-11 (docs/TESTING.md section 3).

Written before implementation as skipped tests (Phase 0 step 12). Un-skip in
Phase 5 when threshold/rules.py exists. All numbers are illustrative fixture
values and the hand calculations MUST be checked by the domain owner
(GOV-DEC-009) before they are relied on.
Source: spec v1.4 R1-012 and section 29.2; threshold value comes from fixture
reference data, never from code.
"""

import pytest

pytestmark = pytest.mark.skip(reason="Phase 5: threshold/rules.py not implemented yet")


def test_r1_012_th01_forward_only_trigger() -> None:
    """R1-012 / TH-01 - Forward-only: expected imports reach £50,000 within the next 30 days.

    Input: No lines in the last 12 months; expected imports 2027-03-05 £30,000.00 and 2027-03-20 £20,000.00; as_of 2027-03-01.
    Expected: TRIGGERED; test_type 'forward'; trigger_date 2027-03-01 (the day the forward test is met); total £50,000.00.
    """
    raise NotImplementedError


def test_r1_012_th02_backward_only_trigger_on_first_of_month() -> None:
    """R1-012 / TH-02 - Backward-only: on the 1st the prior 12 months reach £50,000; 2027 look-back starts 1 Jan 2027.

    Input: Lines: 2027-02-10 £30,000.00; 2027-05-20 £20,000.00; no expected imports; as_of 2027-06-01.
    Expected: TRIGGERED; test_type 'backward'; trigger_date 2027-06-01; total £50,000.00.
    """
    raise NotImplementedError


def test_r1_012_th03_both_tests_earliest_date_wins() -> None:
    """R1-012 / TH-03 - Both tests met: earliest liability date chosen and test type recorded.

    Input: Forward test met on 2027-03-01 (as TH-01); backward test also met on 2027-06-01 (as TH-02).
    Expected: Liability date 2027-03-01; test_type 'forward'; both results kept on the event.
    """
    raise NotImplementedError


def test_r1_012_th04_below_threshold_stays_monitor() -> None:
    """R1-012 / TH-04 - Below threshold: no trigger; client stays 'monitor'.

    Input: Lines: 2027-02-10 £49,999.99; no expected imports; as_of 2027-06-01.
    Expected: No trigger; status 'monitor'; total £49,999.99. Boundary: adding £0.01 gives TRIGGERED.
    """
    raise NotImplementedError


def test_r1_012_th05_special_customs_procedure_manual_review() -> None:
    """R1-012 / TH-05 - Special customs procedure line is held for manual review.

    Input: One line under a special customs procedure with unresolved tax point, £60,000.00.
    Expected: Line held for manual review with tax-point and value-basis reason; not counted and not exempted silently.
    """
    raise NotImplementedError


def test_r1_012_th06_weight_evidence_override_needs_reason() -> None:
    """R1-012 / TH-06 - Weight evidence: source net mass kept; override needs reason and evidence.

    Input: Line with source net mass 1,200.000 kg; user overrides to 1,150.000 kg.
    Expected: Override refused without reason and evidence; with both, a new version is created and the source mass 1,200.000 kg is kept.
    """
    raise NotImplementedError


def test_r1_012_th07_backward_not_legal_event_off_first_of_month() -> None:
    """R1-012 / TH-07 - Backward test on a day other than the 1st is not a legal test.

    Input: Lines that would reach £50,000 on a rolling 12 months; as_of 2027-06-15.
    Expected: No legal backward event. The daily operational run may compute a figure but writes no legal trigger.
    """
    raise NotImplementedError


def test_r1_012_th08_lookback_excludes_pre_2027() -> None:
    """R1-012 / TH-08 - Look-back crossing 1 Jan 2027 excludes earlier lines.

    Input: Lines: 2026-11-10 £40,000.00; 2027-02-10 £9,999.99; as_of 2027-03-01.
    Expected: Total £9,999.99; no trigger. The 2026 line is excluded.
    """
    raise NotImplementedError


def test_r1_012_th09_forecast_revised_keeps_original_trigger() -> None:
    """R1-012 / TH-09 - Forecast revised down after a forward trigger.

    Input: Forward trigger recorded 2027-03-01 on a forecast of £50,000.00; forecast then revised to £20,000.00.
    Expected: New forecast version created; the original trigger event is unchanged.
    """
    raise NotImplementedError


def test_r1_012_th10_excluded_lines_not_counted() -> None:
    """R1-012 / TH-10 - Excluded, out-of-scope and UK-origin-evidenced lines are not counted.

    Input: Three lines of £20,000.00 each: one excluded, one out of scope, one with UK-origin evidence; one in-scope line of £10,000.00.
    Expected: Total £10,000.00; no trigger.
    """
    raise NotImplementedError


def test_r1_012_th11_coverage_gap_flags_result() -> None:
    """R1-012 / TH-11 - Customs-data coverage gap inside the test window.

    Input: Lines reach £50,000.00 on a backward test, but coverage tracker shows a missing 31-day period inside the window.
    Expected: Result still computed; flagged 'coverage incomplete'; a task is created (R1-054).
    """
    raise NotImplementedError
