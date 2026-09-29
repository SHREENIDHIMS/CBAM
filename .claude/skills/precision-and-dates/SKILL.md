---
name: precision-and-dates
description: Exact rules for money, mass, emissions, FX (Decimal/NUMERIC, scales, legal rounding) and for dates (UTC instants, Europe/London legal dates, quarters, injected clock) in CBAM. Use when writing any calculation, rounding, date, deadline or quarter logic, or reviewing it.
---

# Precision and dates (R1-043, R1-044)

## Numbers
- `Decimal` in Python, `NUMERIC` in PostgreSQL. **Never `float`** (CI grep fails).
- Parse from strings: `Decimal(row["net_mass"])`. Serialise to JSON as strings.
- Scales: GBP `NUMERIC(18,2)`; intermediate money `NUMERIC(24,8)`; mass kg
  `NUMERIC(20,6)`; tCO2e / intensity `NUMERIC(24,10)`; factors/FX `NUMERIC(18,8)`.
- Round **only** at the legally prescribed step, with an explicit mode from the rule's
  reference data:
  ```python
  from app.core.money import quantize
  relief_gbp = quantize(relief_gbp_raw, places=2, mode=ref.cpr_rounding_mode)  # ROUND_DOWN per R3-005
  ```
- `quantize()` has no default mode on purpose.
- Keep unrounded intermediates; store the rounded legal value separately.
- Units in names: `net_mass_kg`, `value_gbp`, `intensity_tco2e_per_t`.

## Dates
- Instants: timezone-aware UTC `datetime`, DB `timestamptz`.
- Legal dates: `date`, via `uk_date(instant)` (Europe/London). Never `.date()` on a UTC datetime.
- Business code gets time from the injected `Clock`; `rules.py` receives `as_of: date`.
- Quarter / accounting period from the **tax-point date**, through `core/dates.py`;
  the 2027-annual vs quarterly switch comes from transition reference data.
- Working days come from `ref_working_days`, never from `weekday()` alone.
- UI shows `14 March 2027`; APIs/files use `2027-03-14`.

## Tests you must include
- 31 Mar 23:30 UTC (BST in force) → UK date 1 Apr → Q2.
- 31 Dec 23:30 UTC (GMT) → UK date 31 Dec → Q4.
- Leap day 29 Feb 2028.
- Round-trip `Decimal` through the API unchanged.
- `hypothesis` property: quantize(ROUND_DOWN) never increases a value; sum of rounded
  lines vs rounded sum behaviour matches the rule.
