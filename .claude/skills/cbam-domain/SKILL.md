---
name: cbam-domain
description: UK CBAM domain primer for this project - scope, tax point, £50k forward/backward threshold, registration deadlines, actual vs default emissions, precursors, verification, Carbon Price Relief, returns, amendments and the legal locks. Use before designing or reviewing any CBAM business logic, or when a CBAM term is unclear.
---

# UK CBAM domain primer

Short, build-oriented summary. Authority order: active law → commenced HMRC notices →
HMRC guidance → `docs/spec/CBAM_Spec_v1.4.md` → `docs/spec/CBAM_Team_Handbook.md`.
Definitions: `docs/GLOSSARY.md`.

## The flow (handbook §4)
Imports (CDS) → scope by commodity code at the tax point → £50k threshold →
registration → supplier emissions request → validation → CPR → calculation →
return + approval → filing + payment → six-year evidence.

## Facts the code relies on (all stored as reference data, never constants)
| Topic | Rule | Spec |
|---|---|---|
| Start | 1 Jan 2027 | §3 |
| Sectors | aluminium, cement, fertiliser, hydrogen, iron & steel; scope from commodity code | R1-007 |
| Threshold | £50,000. Forward: expected ≥ £50k in next 30 days, any day. Backward: ≥ £50k in prior 12 months, tested on the 1st of each month; 2027 look-back starts 1 Jan 2027. Earliest date wins | R1-012, §29.2 |
| Registration | Service opens "by 1 Jan 2028" (configurable). Deadline 30 days from liability; 2027 liability → 31 Jan 2028 | R1-013 |
| Accounting periods | 2027 annual; then quarterly. Handbook: 2027 return due 31 May 2028 (unconfirmed — REG-DEC-007) | §3 |
| Tax point | Normally when goods become (or would be) subject to import duty; if no duty, when they enter the UK. Special procedures have their own triggers | R1-008 |
| Liable person | Importer, not declarant/broker; agents may submit but never register or become liable | R1-006, R1-036, R1-002 |
| Emissions | Direct only from 2027 (indirect modelled, inactive). CO2e from gas components with prescribed factors; intensity 5 dp | R2-002, R2-004 |
| Precursor | Upstream **direct** emissions; a source type, not a scope | R2-003 |
| Actual vs default | Actual needs verification evidence; otherwise default. Day-28 chase is not the legal test | R2-005 |
| Verified result | Installation calculates, verifier verifies, importer reports the verified figure; our recompute is a plausibility check | R2-019 |
| CPR | Per qualifying scheme; evidence form covers one of the two calendar years before import year; FX = HMRC rate for the quarter before the tax point, converted relief rounded down to 2 dp; capped at liability | R2-009, R3-004–006 |
| Amendments | Only to correct errors; **cannot replace default with actual** (Finance Act 2026 Sch 17 para 8(2)) — hard lock | R3-013, R3-014 |
| Records | Six years from the legal anchor; net mass kg up to 6 dp; legal holds block deletion | R3-017, R3-035 |
| Penalties | e.g. £500 record-keeping; £500 + £40/day for certain notification failures — reference data | R3-016 |

## Open questions — never guess
REG-DEC-001 service opening date · REG-DEC-007 return/payment due dates ·
REG-DEC-013 whether defaults block CPR · LEGAL-DEC-005 SAO as legal approver ·
TECH-DEC-004 HMRC filing interface. See `docs/OPEN_DECISIONS.md`.

## Common traps
- Using the declaration date as the tax point.
- Running the backward test daily and emitting legal events on non-1st days.
- Treating special procedures as permanent exemptions (they are tax-point lifecycles).
- Treating "no data by Day 28" as permission to use defaults.
- Adding a `PRECURSOR` scope enum value.
- Aggregating different consignments with the same code into one return line.
- Using an "active" dataset whose source is still draft.
