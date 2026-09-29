# Roadmap

No calendar durations. Work is ordered by **dependency**; each milestone ends at a
gate, not a date. The only dates here are legal facts that the product must respect.

## 1. Legal dates that constrain the order

| Legal date | What must already work |
|---|---|
| 1 Jan 2027 — CBAM starts | **R1 Live cut**: import capture, scope, tax point, threshold, pre-registration record-keeping, supplier collection, evidence storage, audit |
| When HMRC registration opens (by 1 Jan 2028, REG-DEC-001) | Registration readiness pack, status record |
| 31 Jan 2028 — 2027 registration deadline | Registration lifecycle |
| First return due (REG-DEC-007) | **R3** calculation, return, approval, filing-ready export |

R2 must be complete early enough that verified emissions evidence for 2027 imports
is ready before R3 returns are prepared.

## 2. Milestones

```
Phase 0 ─► Phase 1–8 ─► Phase 9 ═► R1 PILOT ─► Phase 10 ═► R1 LIVE
      ─► Phase 11–15 ═► R2 ─► Phase 16–21 ═► R3
```

| Milestone | Meaning | Gate |
|---|---|---|
| **R1 Pilot** | First real client uses the data machine | Spec gates G1–G8 + all PILOT-P0 items |
| **R1 Live** | Ready to operate from 1 Jan 2027 | Every JAN-1 item + resilience + restore rehearsal |
| **R2** | Evidence is trusted and explainable | Every accepted value has lineage; R2 P0 items done |
| **R3** | Liability, returns, filing, payments, enforcement | Fixture returns reproduce exactly; no duplicate filing; historical replay stable |

## 3. R1 cut assignment (fixes spec §24.2 gap D11)

| Cut | Requirement IDs |
|---|---|
| **Pilot** | R1-001, 002, 003, 004, 005, 006, 007, 008, 009, 010, 011, 012, 015, 016*, 017, 018, 019, 021, 022, 023, 025, 027, 028, 032, 036, 041, 042, 043, 044, 045, 046, 048, 050, 051*, 053, 054, 055*, 056*, and the five pilot-language templates of R1-047 (*PILOT-P1: in pilot if the pilot client needs it) |
| **Live** | R1-013, 014, 020, 024, 026, 029, 030, 031, 033, 034, 035, 037, 038, 039, 040, 047, 049, 057, 058, and R2-031 (moved earlier) |
| **Backlog** | R1-052, 059, 060 |

R2 and R3 contents: `docs/PRD.md` §5 and `plans/IMPLEMENTATION_PLAN.md` Appendix A.

## 4. External blockers and when they bite

| Blocker (spec §20 + handbook §12) | Needed by | If still open |
|---|---|---|
| Real "Get customs data" reports from a pilot client, and the client's third-party access grant (DATA-DEC-002) | Phase 3 mapping freeze | Build against the published report descriptions + synthetic files; freeze mapping when real (masked) reports arrive, before Pilot |
| Sample EU CBAM Communication Template (handbook §12) | Phase 6 (R1-055) | Portal works without it; pre-fill added when the template is available |
| Domain owner named (GOV-DEC-009) | Phase 2 activation, Pilot UAT | Develop with fixture data; nothing activated in production |
| Email provider/domain (OPS-DEC-012, BRAND-DEC-015) | Phase 7 real sends, Pilot | Local mail catcher; pilot cannot start outreach |
| Brand name, portal URL (BRAND-DEC-015) | Phase 7 templates | `{brand}` placeholder; changing it after outreach means re-sending to suppliers |
| 2–3 pilot clients recruited (handbook §12) | Phase 9 UAT | UAT with synthetic data only; Pilot gate cannot pass |
| Verifier bodies contacted (Bureau Veritas, SGS) | Phase 14 | Model from published standards; real certificates needed before R2 release |
| Companion docs (DOC-DEC-014) | Phase 0 review | Our architecture stands; reconcile on arrival |
| Hosting (OPS-DEC-010) | Phase 9 | Pilot cannot go live |
| Registration opening date (REG-DEC-001) | Live | Configurable; no change needed |
| Carbon Pricing Verification Form fields, verifier examples, EU template | Phases 13–14 | Build model from the published form; fixtures when examples arrive |
| Default values, CBAM rates, exchange rates | Phases 16–17 | Formula tests with fixture data; re-base when published |
| HMRC return schema / digital facility (TECH-DEC-004) | Phase 19 | Filing-ready export only |
| Agent model (BUS-DEC-003) | Live filing | Filing stays disabled |
| Return/payment due dates (REG-DEC-007) | Phase 18–19 | Deadlines shown as "rule pending" |

## 5. Single-developer scope rule

If the work does not fit, cut in this order: P2 → P1 in the current release → the
next release slips. Never move R3 work earlier, never ship R1 Live without its
JAN-1 items, never skip the scenario tests to save time.
