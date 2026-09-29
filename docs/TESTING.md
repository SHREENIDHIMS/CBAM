# Testing strategy

"Done" means an automated test proves the spec's acceptance criterion. With one
developer, tests are the second pair of eyes.

## 1. Layers

| Layer | Folder | What | Speed | Runs |
|---|---|---|---|---|
| Unit | `backend/tests/unit/` | `rules.py` functions, `core/` helpers (dates, money, fingerprint) | ms | every save / pre-commit |
| Scenario (regulatory) | `backend/tests/scenarios/` | Named legal scenarios end-to-end through services with a real DB and fixture reference data | s | every PR |
| Integration | `backend/tests/integration/` | API + DB + storage + jobs: import pipeline, portal flow, exports, RLS | s | every PR |
| Security | `backend/tests/security/` | Permission matrix, cross-tenant, links, uploads, audit immutability | s | every PR |
| Frontend unit | `frontend/src/**/*.test.tsx` | Components, formatting (dates, GBP), form rendering from definitions | ms | every PR |
| E2E + a11y | `frontend/e2e/` | Playwright journeys + axe | min | every PR (smoke), full before release |
| Load / recovery | `backend/tests/load/` | 10,000-line import, dashboard p95, bulk documents, job retry, restore | min | before each release |
| Usability | manual script | Supplier form on a phone < 10 min (R1-017) | — | before Pilot |

## 2. Rules for writing tests

1. **Test name carries the requirement ID**:
   `test_r1_012_backward_test_runs_on_first_of_month_only`.
2. **Regulatory tests cite the source** in the docstring (act/SI/notice/guidance +
   section) and state where each fixture number came from.
3. **Freeze time.** Pass `as_of` to rules; use `FrozenClock` in services. No test
   depends on today's date.
4. **Fixture reference data** lives in `tests/fixtures/refdata/` and is clearly
   marked as fixture, not official. When official values are published, re-base.
5. **Decimals as strings** in fixtures: `Decimal("48200.000000")`.
6. **Property tests** (`hypothesis`) for rounding, date/quarter mapping, threshold
   window arithmetic and idempotent import replay.
7. **No mocks of our own database.** Integration tests use the real local Supabase
   PostgreSQL (`supabase start`, separate test database), each test in a rolled-back
   transaction or a fresh schema. External services (Resend, HMRC, Claude API,
   Storage in unit tests) use fakes. Auth tests mint JWTs with the local project's
   signing key, including `aal1` vs `aal2` tokens.
8. **Every bug fix** starts with a failing regression test.
9. Tests are independent and can run in any order (`pytest -p randomly`).

## 3. Mandatory scenario catalogue

These are written **before** the matching implementation (spec R1-012, §16, §24.3).

### Threshold (R1-012) — write in Phase 0
| ID | Scenario | Expected |
|---|---|---|
| TH-01 | Forward-only: expected imports reach £50,000 within the next 30 days | Trigger; test type `forward`; trigger date = that day |
| TH-02 | Backward-only: on the 1st of the month the prior 12 months reach £50,000; 2027 look-back starts 1 Jan 2027 | Trigger on the 1st; no earlier than the 1st |
| TH-03 | Both tests met | Earliest liability date chosen and test type recorded |
| TH-04 | Below threshold | No trigger; client stays `monitor` |
| TH-05 | Special customs procedure line | Held for manual review with tax-point and value-basis reason; not counted or exempted silently |
| TH-06 | Weight evidence | Source net mass kept; manual override needs reason and evidence |
| TH-07 | Backward test on a day other than the 1st | Not run as a legal test (daily operational run may compute, but no legal event) |
| TH-08 | Look-back crossing 1 Jan 2027 | Lines before 1 Jan 2027 excluded |
| TH-09 | Forecast revised down after a forward trigger | New forecast version; original trigger event kept |
| TH-10 | Excluded / out-of-scope / UK-origin-evidenced lines | Not counted |

### Dates and numbers (R1-043, R1-044)
BST/GMT boundary (31 Mar 23:30 UTC → 1 Apr UK), quarter mapping, leap day,
Decimal round-trips through API as strings, float-ban check.

### Scope, origin, tax point (R1-007–011, 027, 032, 036)
Code in scope/out of scope at the tax-point date; code changes effective mid-year;
draft source ignored; private use; UK origin with/without evidence; returned goods
(incl. NI conditions); temporary admission full / partial / lost relief; storage,
free zone, inward processing, outward processing, end-use, export before tax point;
freight forwarder as declarant keeps importer liable; broker acting on behalf.

### Registration (R1-013, 014, 030, 033, 040)
Liability in 2027 → deadline 31 Jan 2028; liability outside first year → 30 days;
service opening date changed → UI state changes, history kept; readiness pack
complete/incomplete; EORI change creates notification task.

### Supplier (R1-017, 041, 046, 047, 053)
Link expiry, revoke, resend invalidates prior, cross-case access denied, hard
bounce suppresses, Day 7/14/21/28 transitions with frozen clock, Day 28 escalates
but does **not** set default; full sequence in staging "minutes-mode" (R1-053);
templates exist and are approved for EN, TR, ZH, HI, DE.

### Import (R1-003, 025)
A 500-row CDS file imports cleanly with errors reported per row (handbook gate),
then the 10,000-row load test.

### R2 / R3 (spec §16 list — written at their phase)
Mixed-gas CO2e; 5-dp intensity; verified result wins over recompute; actual/default
selection; precursor compatibility; monitoring year options (2027/2026); verifier
package completeness; CPR per scheme, prior-quarter FX per currency, round down,
cap at liability; weight rounding (<1 kg, .001–.499, .500–.999, integers,
HMRC-determined); **default→actual amendment blocked (R3-014)**; nil return;
repayment window; penalties (£500 record-keeping; £500 + £40 daily notification);
review/appeal timetable; retention anchor; filing retry without duplicate;
historical replay unchanged after a rule change; special-procedure value outcomes
(a)–(f).

### Golden fixture
48.2 t Turkish EAF steel (handbook §3, §11). Keep as a regression test of the **formula**.
The handbook liabilities (£785.25 actual, £4,771.80 default) are recorded as
*illustrative* and asserted only with fixture reference data; never used as
production constants. Re-base when official rates/defaults are published.

## 4. Coverage and gates

| Gate | Threshold |
|---|---|
| `rules.py` modules | ≥ 95 % branch coverage |
| `app/core/` | ≥ 90 % branch coverage |
| Whole backend | ≥ 80 % line coverage |
| Scenario catalogue for the phase | 100 % present and passing |
| E2E smoke | pass |
| axe | zero serious/critical |

Coverage is a floor, not a goal: a rule without a scenario test is not done even
at 100 % coverage.

## 5. CI pipeline (GitHub Actions)

1. `ruff check`, `ruff format --check`, `mypy`, float-ban grep
2. `supabase start` in CI, then `pytest tests/unit tests/scenarios tests/integration tests/security`
3. Alembic `upgrade head` → `downgrade base` → `upgrade head`
4. `pip-audit`, `gitleaks`
5. Frontend: `npm ci`, `lint`, `typecheck`, `vitest`, `build`, `npm audit --audit-level=high`
6. Playwright smoke + axe against the local stack (Supabase CLI + api + worker)
7. Coverage gates

## 6. Release acceptance

R1 Pilot = spec gates G1–G8 (see `plans/IMPLEMENTATION_PLAN.md` Phase 9).
Each release gate has a checklist in the implementation plan; evidence (test run
links, load-test output, restore log, usability notes) is saved under
`docs/releases/<release>/`.
