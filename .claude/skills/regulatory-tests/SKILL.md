---
name: regulatory-tests
description: How to write CBAM regulatory scenario tests - naming with requirement IDs, citing sources, fixture reference data, frozen clock, exact Decimal assertions, and the mandatory scenario catalogue. Use when writing or reviewing tests for rules.py, threshold, tax point, registration, emissions, CPR, returns or penalties.
---

# Regulatory scenario tests

Catalogue of mandatory scenarios: `docs/TESTING.md` §3.

## Template
```python
from datetime import date
from decimal import Decimal

from app.modules.threshold import rules
from tests.fixtures.refdata import load_fixture_snapshot


def test_r1_012_th02_backward_trigger_on_first_of_month():
    """R1-012 / TH-02 — backward test is applied on the first day of each month;
    2027 look-back cannot start before 1 Jan 2027.
    Source: HMRC 'Work out the date you'll need to register for CBAM' (retrieved <date>);
    spec v1.4 §3 and §29.2.
    Fixture values: threshold £50,000 from tests/fixtures/refdata/threshold_rules/fixture-1.
    """
    ref = load_fixture_snapshot("threshold_rules", on=date(2027, 6, 1))
    lines = [line(tax_point=date(2027, 2, 10), value_gbp=Decimal("30000.00")),
             line(tax_point=date(2027, 5, 20), value_gbp=Decimal("20000.00"))]

    result = rules.backward_test(lines, ref, as_of=date(2027, 6, 1))

    assert result.outcome == "TRIGGERED"
    assert result.trigger_date == date(2027, 6, 1)
    assert result.total_gbp == Decimal("50000.00")
    assert result.rule_id == "R1-012.backward"
```

## Rules
- Name: `test_<req id with underscores>_<scenario id>_<what>`.
- Docstring: requirement ID, scenario ID, legal source + retrieval date, where every
  fixture number came from.
- Fixture reference data only (`tests/fixtures/refdata/`, `fixture: true`). When
  official values are published, add a second test against the official dataset;
  keep the fixture test.
- Explicit `as_of` / `FrozenClock`. No real "today".
- Exact `Decimal` equality. No `pytest.approx` for money, mass or emissions.
- Assert the decision metadata too (`rule_id`, dataset version IDs) — traceability is
  part of the requirement.
- Test both sides of every boundary (day before/after, threshold ±£0.01, rounding .499/.500).
- For locks (e.g. R3-014 default→actual), assert the action is refused **and** that no
  configuration/flag can enable it.
- Golden fixture (48.2 t Turkish EAF steel): assert the formula with fixture rate/default;
  mark the handbook £785.25 / £4,771.80 as illustrative.
