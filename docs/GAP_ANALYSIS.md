# Specification validation and gap analysis

**Baseline reviewed:** `CBAM_Prioritised_Requirements_and_Build_Specification_v1.4_FINAL.docx` (30 Sep 2026)
**Also compared:** the original draft, v1.1 and v1.3 ("FINAL") in `docs/spec/archive/`, and the
Team Handbook (`docs/spec/CBAM_Team_Handbook.pdf`, text copy `CBAM_Team_Handbook.md`)
**Result:** v1.4 is the correct baseline. It is regulatorily thorough. It is not yet a
complete *build* contract for one developer: it has editorial defects, sequencing
gaps and missing engineering requirements. All are fixed below and carried into
`docs/PRD.md` §6 and `plans/IMPLEMENTATION_PLAN.md`.

The `.docx` files are not edited. This document is the change record on top of them.

---

## 1. Version comparison

| Version | Requirement rows | What changed | Anything lost later? |
|---|---|---|---|
| Original | 60 | First merge of handbook + regulatory research | No |
| v1.1 | 65 | Pilot vs January cut, week-1 QA scenarios, reference-data completeness | R3-DEC-001 (default→actual "configurable") — **correctly** replaced in v1.2 by the legal lock R3-014 |
| v1.3 ("FINAL") | 92 | Registration lifecycle, origin, special procedures, HMRC cases, precursor allocation | No |
| v1.4 | 106 | Liable-person determination, forecast register, magic-link lifecycle, verifier standards, review/appeal timetable, retention anchor, transition packages | — |

Open-decision IDs `REG-DEC-002`, `DATA-DEC-003`, `BUS-DEC-004` in older versions were
only renumbered to `REG-DEC-001`, `DATA-DEC-002`, `BUS-DEC-003`. Nothing of substance
was dropped between versions.

## 2. Editorial defects in v1.4 (fixed in our docs)

| # | Where | Defect | Fix applied |
|---|---|---|---|
| D1 | §1 | Says "This v1.3 revision" in a v1.4 document | Treat as v1.4 |
| D2 | §24–§28 | Two sections numbered 24; no §27; §25 heading says "retained in v1.3" | Cite sections by title, not number, where ambiguous |
| D3 | §9 "Special customs procedures" | Behaviour text duplicated into the Release column | Release = R1 (flag) / R3 (value rules) |
| D4 | §9 "Importer vs declarant", "Future indirect emissions" | Release column contains behaviour text | Release = R1 / R2 schema, activation effective-dated |
| D5 | §9 | "Artificial business separation" and "Anti-avoidance / artificial separation" are the same row | One row, R3 (R3-024, R3-032) |
| D6 | R2-008 | Accreditation-body sentence repeated | Read once |
| D7 | §20 | "Statutory approver / SAO" duplicates LEGAL-DEC-005; "Supplier contract terms" duplicates PROD-DEC-006 | Merged in `docs/OPEN_DECISIONS.md` |
| D8 | R1-012, §18, §24.3 | Time-boxed wording ("Week 1", "Nine-week plan") | Replaced by ordered phases with exit gates (no durations) |
| D9 | §18, §19, §24.2 | Team of 3 developers + QA assumed | Replaced by the single-developer model in `CLAUDE.md` §2 |
| D10 | Priority labels | `P0`, `P1`, `JAN-1`, `PILOT-P0`, `PILOT-P1` are used but never defined | Legend in `docs/PRD.md` §4 |
| D11 | §24.2 | Pilot/January cut lists only R1-001…R1-033; R1-034…R1-041 (added later) are unassigned | Assigned in `docs/ROADMAP.md` §3 |
| D12 | §24 | Handbook PDF is cited but was not in the specification folder and is image-only | **Closed:** handbook added to `docs/spec/` with a text transcription; reconciled in §9 below |

## 3. Sequencing gaps (things needed earlier than the spec places them)

| # | Gap | Why it matters | Fix |
|---|---|---|---|
| S1 | R1-007 (scope engine) needs versioned commodity-code data in R1, but the regulatory source registry (R2-020) and reference-data admin (R2-015) are R2 | R1 would either hard-code data (breaks "law is data") or be blocked | New **R1-050**: file-based, checksummed reference-data loader with minimal `draft`/`active` source status in R1. R2-020/R2-015 extend it. |
| S2 | R1-012 (threshold, pilot) creates tasks, but the task engine R1-022 sits later in the flat list | Threshold events would have nowhere to go | Task/deadline engine built in Phase 1 foundations |
| S3 | R1-008/R1-027 flag lines for manual review, but the review-queue shell R1-020 is a January item | Flags would be invisible in the pilot | Pilot uses a review flag + task on the line; the queue UI comes in the Live cut |
| S4 | Return and payment due-date rules are referenced (R3-012, §14) but never stated | Cannot build reminders or deadlines without inventing them | New open decision REG-DEC-007; due dates are reference data |

## 4. Missing requirements (added)

These are engineering and operational requirements a regulated multi-client system
needs, which v1.4 does not state. Full text with acceptance criteria is in
`docs/PRD.md` §6.

| New ID | Title | Release / priority | Gap it closes |
|---|---|---|---|
| R1-042 | Authentication, MFA and sessions for internal and client users | R1 / P0 | R1-002 defines roles but not login, MFA or session rules |
| R1-043 | UK legal-date and time-zone semantics | R1 / P0 | Tax point, threshold and deadlines are dates in UK law; BST/GMT boundaries can move a line into the wrong day or quarter |
| R1-044 | Numeric precision contract | R1 / P0 | §15 says "decimal-safe" but gives no scales; two developers (or two sessions) would choose differently |
| R1-045 | Concurrency control on reviewed and approved records | R1 / P0 | Two reviewers acting on stale data could both approve |
| R1-046 | Email delivery, bounce and complaint handling | R1 / P0 | R1-018 audits "failures" but no bounce processing or sender authentication is required |
| R1-047 | Outreach template translation governance | R1 / P1 | Multilingual outreach with no rule on who approves translations |
| R1-048 | File-upload safety and evidence storage | R1 / P0 | §15 says "safe file handling" without concrete controls |
| R1-049 | Privileged support access ("break-glass") | R1 / P1 | Platform admins can see every tenant with no justification or time limit |
| R1-050 | Versioned reference-data loader for R1 | R1 / P0 | Sequencing gap S1 |
| R1-051 | Client onboarding and bulk supplier/installation import | R1 / PILOT-P1 | No path to load a pilot client's existing supplier list |
| R1-052 | Identifier checks (EORI format/HMRC check, commodity-code validity) | R1 / P2 | Bad EORIs and codes caught only by humans |
| R2-030 | Third-party processing controls for extraction (OCR/LLM) | R2 / P0 | R2-001 may send supplier documents to external services without a data-protection rule |
| R2-031 | Regulatory source change watcher | R2 / P1 | Registry stores sources, but nothing notices when GOV.UK/legislation pages change |
| R3-037 | Tenant data export and offboarding | R3 / P1 | R3-025 reconciles closure but gives the client no copy of its records |

## 5. Missing non-functional targets (added to `docs/TECHNICAL_SPEC.md` §8)

| Area | v1.4 says | Added (proposed, confirm before Pilot) |
|---|---|---|
| Backup | "rehearsed before pilot" | RPO ≤ 15 min (point-in-time recovery), RTO ≤ 4 h, restore rehearsal before each release |
| Performance | "define p50/p95 before hardening" | Dashboard p95 ≤ 1.5 s; import of 10,000 lines ≤ 5 min end-to-end; supplier portal page p95 ≤ 1 s on 4G |
| Test clock | Not stated | All rule and job code takes an injected clock/`as_of` date |
| Data in non-prod | "separate credentials and data stores" | No real client data outside production; masked fixtures only |
| Audit tamper evidence | "append-only" | DB trigger + role grants block UPDATE/DELETE; per-tenant hash chain |
| Accessibility | "WCAG 2.2 AA objective" | axe-core checks in every Playwright run for portal and ops screens |

## 6. New open decisions (see `docs/OPEN_DECISIONS.md`)

| ID | Question |
|---|---|
| REG-DEC-007 | Exact return and payment due-date rules for the first annual period and later quarters |
| DOC-DEC-008 | Add the Team Handbook PDF to the repo — **closed** (added) |
| GOV-DEC-009 | Who is the named domain owner / tax adviser who signs off regulatory interpretations? |
| OPS-DEC-010 | Hosting region and provider (proposed: AWS London) |
| TECH-DEC-011 | Confirm the proposed stack (ADR-0001) |
| OPS-DEC-012 | Email provider and sending domain (handbook names Resend) |
| REG-DEC-013 | Can CPR be claimed on goods reported with default emissions? (handbook: no; spec: silent) |
| DOC-DEC-014 | Obtain the handbook's companion documents (`CBAM-Complete-Workflow.docx`, `CSorted-Platform-Technical-Specification.docx`) |
| BRAND-DEC-015 | Product/brand name, email domain and portal URL |

## 7. Validation of the regulatory content

The regulatory positions in v1.4 §3 and §29.2 were checked for internal consistency
(they agree with each other and with the requirement rows). They were **not**
re-verified against GOV.UK in this review. Before Phase 2 (reference data), the
`regulatory-analyst` agent must re-check every source in spec §23 and §30, record
the retrieval date in the source registry, and raise any change as a new entry
here.

## 8. Things deliberately *not* added

| Idea | Why not |
|---|---|
| Billing/subscriptions | Commercial, not in any source; add when a pricing model exists |
| BI / forecasting beyond the 30-day test | Spec §22 non-goal |
| Native mobile app | Supplier portal is mobile-first web; enough for the <10-minute test |
| Microservices | One developer; a modular monolith keeps one deploy, one database, one transaction |
| Client notification preferences / digests | No requirement; add after pilot feedback |

## 9. Team Handbook reconciliation

The handbook (`docs/spec/CBAM_Team_Handbook.pdf`, 29 Sep 2026) is the product baseline
the spec was built from. Every handbook point was checked against v1.4.

### 9.1 Where the spec corrects the handbook (spec wins)

| Handbook says | v1.4 position | What we build |
|---|---|---|
| HMRC registration opens via Government Gateway in Q4 2026 | Service opens **by 1 Jan 2028**; exact date configurable | R1-013, R1-040 pre-registration mode |
| No usable data in 28 days → apply defaults | Day 28 is a product SLA; defaults follow the legal evidence rules | R1-018 escalates only; R2-005 selects |
| Nightly rolling-12-month test | Backward test is legally on the 1st of each month; forward any day | Daily run allowed operationally; legal event only on legal cadence |
| SAO signs returns and is personally liable | No CBAM-specific SAO duty confirmed | Approver role configurable (LEGAL-DEC-005) |
| CO2 / Scope 1 language | Store CO2e + gas components; scope separate from source | R2-002, R2-003 |
| "Scope 2 joins from 2029" | Indirect emissions effective-dated, no date asserted | Schema supports INDIRECT; activation only from an active source |
| Golden example £785.25 / £4,771.80 "runs in CI forever" | Useful only after official rates/defaults are frozen as fixtures | Test the formula; assert the £ amounts only with fixture reference data |
| Verifier ISO 17029 + 14065 | Adds ISO 14064-3 and ISO 14066 for CPR, via reference data | R2-028 |

### 9.2 Handbook details the spec left out (now added)

| Handbook detail | Added as |
|---|---|
| First return (all of 2027) due **31 May 2028**; then quarterly | Recorded in REG-DEC-007 as the handbook's statement; loaded into `ref_compliance_calendar` only after the domain owner confirms the official source |
| Threshold alert at **80%** and alarm at breach | R1-012 default warning point = 80% (reference data `threshold_warning_ratio`, editable) |
| First outreach languages **EN, TR, ZH, HI, DE** | R1-047: these five templates are required for the pilot |
| Chase schedule testable in staging in **"minutes-mode"** | New **R1-053**: outreach time-scale setting for non-production environments |
| **500-row** CDS file imports cleanly with per-row errors | Phase 3 exit gate (before the 10,000-row load test) |
| R2 rule set: CO2 figure present, period matches import year, **±50% of sector benchmark**, method valid, certificate names the installation, verifier ISO standards, precursor consistency | R2-011 initial rule catalogue; the ±50% band and benchmarks are reference data |
| **RAG (red/amber/green)** compliance dashboard per client | R2-016 shows RAG status per client |
| "Defaults block CPR" hard lock | New open decision **REG-DEC-013** — the spec does not state this; must be confirmed from law before it becomes a rule |
| Return lines per **declaration × CN code × installation**, never lumped; tax never below £0 | Matches R3-008 granularity and R3-006 cap |
| Legal state transitions one-way, enforced by **database constraints AND application checks** | `CLAUDE.md` §3 rule 17 and `docs/DATABASE.md` §1 |
| Domain owner: **Jenny + ops** | GOV-DEC-009 updated: Jenny named; confirm she signs off reference data |
| Stack: FastAPI, Celery, **Supabase (EU region)**, Resend, Sentry; R2 extraction via Claude API | ADR-0001 aligned with the handbook; Claude API extraction governed by R2-030 |
| Parallel blockers: brand name, pilot clients, verifier bodies (Bureau Veritas, SGS), CDS sample, CPR form, EU template | `docs/ROADMAP.md` §4 and `docs/OPEN_DECISIONS.md` |
| Companion documents referenced but not supplied | DOC-DEC-014 |

### 9.3 New requirement from the handbook

| ID | Requirement | Release / Priority | What the system must do | Acceptance / evidence |
|---|---|---|---|---|
| R1-053 | Outreach time-scale for testing | R1 / PILOT-P0 | A non-production setting (`OUTREACH_TIME_SCALE_SECONDS_PER_DAY`) makes the Day 0/7/14/21/28 schedule run in minutes instead of days, so the full sequence can be exercised end to end. The app refuses to start in production with any value other than the real day length. | In staging the full sequence runs end to end in minutes and every send is audited; production start-up fails if the setting is changed. |

## 10. Research update (30 Sep 2026)

Official sources were re-checked after the handbook reconciliation. Findings and
what changed:

| # | Finding | Source | Action taken |
|---|---|---|---|
| F1 | Return and payment deadlines: 2027 → 31 May 2028; Q1 2028 → 31 Jul 2028; Q2 → 29 Sep 2028; Q3 → 30 Nov 2028; Q4 → 28 Feb 2029. Irregular pattern | HMRC CBAM policy summary (updated 9 Sep 2026) | REG-DEC-007 narrowed; dates seeded into `ref_compliance_calendar` for domain-owner confirmation (Phase 2); PRD §6.1 |
| F2 | HMRC "Get customs data": free, CSV, 4 report types, ≤ 31 days per report, 4 years back, last 2 days unavailable, up to 72 h, third-party access granted by the client in the service, GB or XI EORI, no API | GOV.UK "Get customs data for import and export declarations" (updated 25 Mar 2026) | DATA-DEC-002 narrowed; new **R1-054**; forward-test clarification |
| F3 | Records kept 6 years after the end of the accounting period the goods are attributed to | Policy summary | R3-035 anchor clarified |
| F4 | CPR uses an HMRC-published rate for the quarter before the point of import; HMRC's existing API publishes **monthly/spot/average customs** rates | "Work out your carbon price relief" (16 Jul 2026); HMRC exchange-rate API docs | Two separate datasets; R3-005 clarified |
| F5 | Official CPR guidance does not state that default values block relief; relief needs a Carbon Pricing Verification Form from a qualifying verifier | "What you need to work out carbon price relief" (16 Jul 2026) | REG-DEC-013 stays open with this evidence |
| F6 | Second tranche of regulations + interest SI laid 9 Sep 2026; more guidance "in the autumn"; HMRC webinars in October 2026 | GOV.UK CBAM collection | Regulatory re-check steps added before Phase 2, Pilot and Live |
| F7 | UK–EU ETS linking negotiations began Jan 2026, not concluded; may create mutual CBAM exemptions | ICAP; law-firm briefings | Linked-ETS list stays empty; activation scenario test added |
| F8 | Returned Goods Relief: re-import within 3 years, same state; NI Union-goods variant | "Goods that may not contribute towards the threshold" (16 Jul 2026) | R1-011 fields clarified |
| F9 | Default values not yet published; one global default per good; country-specific defaults revisited after 2027 | Industry briefings on the draft regulations | No change: defaults stay reference data; do not populate geography rules until defined |

### 10.1 Features added from the research

| ID | Feature | Release | Why |
|---|---|---|---|
| R1-054 | "Get customs data" importer + coverage tracker | Pilot (P0) | It is the realistic data route; a missing month would silently understate the threshold |
| R1-055 | EU CBAM Communication Template upload + pre-fill | Pilot (P1) | Many installations already fill it for EU customers; fewer questions = faster answers |
| R1-056 | Portal help, "not known yet", ask-a-question, save-and-return | Pilot (P1) | Protects the < 10-minute target and reduces abandoned forms |
| R1-057 | Shared installation network with supplier consent | Design Phase 6, build Live (P1) | One answer serves several clients; the spec allowed consented sharing but never defined it |
| R1-058 | Demo tenant + synthetic data | Live (P1) | UAT, training and pilot demos without real data |
| R1-059 | CBAM exposure check for prospects | Backlog (P2) | Helps recruit pilot clients; no tax calculation |
| R1-060 | Client monthly digest | Backlog (P2) | Keeps clients engaged; cheap |
| R2-031 | Source change watcher | Moved to Live (P1) | The law is still changing before go-live |

### 10.2 Considered and not added

| Idea | Why not now |
|---|---|
| Liability estimator in R1 | Breaks the "no calculator in R1" rule; rates and defaults are not published |
| WhatsApp/SMS reminders | New vendor and more personal data; revisit after pilot feedback |
| Automatic feed via HMRC "Customs Declarations Information" API | Not designed for bulk history; needs software registration; revisit after DATA-DEC-002 |
| HMRC Agent Authorisation API | Only if BUS-DEC-003 decides we act as a tax agent |

### 10.3 Sources checked (30 Sep 2026)

- HMRC CBAM policy summary — https://www.gov.uk/government/publications/carbon-border-adjustment-mechanism-cbam-policy-summary/carbon-border-adjustment-mechanism-cbam-policy-summary
- Get customs data — https://www.gov.uk/guidance/get-customs-data-for-import-and-export-declarations
- Work out your carbon price relief — https://www.gov.uk/guidance/work-out-your-carbon-price-relief
- What you need to work out carbon price relief — https://www.gov.uk/guidance/what-you-need-to-work-out-carbon-price-relief
- Work out the date you'll need to register — https://www.gov.uk/guidance/work-out-the-date-youll-need-to-register-for-carbon-border-adjustment-mechanism-cbam
- Goods that may not contribute towards the threshold — https://www.gov.uk/guidance/imported-carbon-border-adjustment-cbam-goods-that-may-not-contribute-towards-the-registration-threshold
- CBAM registration collection — https://www.gov.uk/government/collections/check-if-youll-need-to-register-for-carbon-border-adjustment-mechanism-cbam
- HMRC exchange rates (monthly) — https://www.trade-tariff.service.gov.uk/exchange_rates/monthly ; API — https://developer.service.hmrc.gov.uk/api-documentation/docs/api/xml/Exchange%20rates%20from%20HMRC
- HMRC Developer Hub API list — https://developer.service.hmrc.gov.uk/api-documentation/docs/api
- UK–EU ETS linking — https://icapcarbonaction.com/en/news/eu-and-uk-commit-linking-emissions-trading-systems-landmark-cooperation-agreement
