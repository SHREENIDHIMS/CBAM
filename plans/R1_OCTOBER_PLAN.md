# R1 submission plan

The owner needs a running R1 for submission this month, earlier than `docs/ROADMAP.md`
assumes. This plan is a cut-down R1, ordered by phase and sub-step. It changes the order
and the depth of the work, not the rules: every CLAUDE.md §3 guarantee still applies (law is
data, Decimal only, UK legal dates, tenant isolation, audit, humans approve).

R1 is the data machine: import, scope, tax point, threshold, suppliers, outreach, documents,
dashboard. **It does not calculate CBAM tax and does not file returns** (that is R3).

## The golden rule: local with dummy data first, real data second

1. **Stage A — local, dummy data only.** Everything runs on this machine (`supabase start` +
   `docker compose` + API, worker, beat, frontend) against the **demo tenant** filled with
   synthetic data. No real client, supplier or customs data anywhere.
2. **Local gate.** The full R1 journey works end to end on dummy data (checklist below). If any
   box is open, we fix it and do **not** move on.
3. **Stage B — real data, still local.** Only after the local gate passes: run one real, masked
   "Get customs data" report on the local stack and have the domain owner activate the real
   reference data. Nothing real goes into the repo or tests.
4. **Stage C — hosted, only if hosting is decided (OPS-DEC-010).** If not, we submit the local run.

## Scope

| Area | In | Cut to after submission |
|---|---|---|
| Phase 4 Scope, origin, geography & tax point | Scope rule (step 1), **geography flags from GB/XI EORI context shown in the ledger (step 2, R1-009 light)**, **declared vs validated origin with an exception when evidence is missing; UK origin never accepted without evidence (step 3, R1-032 light)**, UK-origin / private-use / Returned Goods exclusions (4), tax-point state machine (5), special procedures flagged for manual review (6, flag + task only), decisions panel on line detail (8) | Full geography rule set for NI, Crown Dependencies, Overseas Territories and Continental Shelf; complex-good origin evidence; re-run on activation (7) |
| Phase 5 Threshold | Forward + backward tests with TH-01…TH-11 (1), snapshots/events (3), Celery beat runs (4), 80% warning + trigger tasks (5), threshold screen (6) | Forecast register beyond the minimal input (2) |
| Phase 10 Pre-registration (R1-013 light, pulled forward) | **Registration trigger date kept from the threshold event; deadline shown with its basis (first-year deadline from reference data, 30-day rule otherwise); service-opening date as configuration, never assumed; non-digital route flag** | Registration readiness pack (R1-014), status record (R1-033), change control (R1-030) |
| Phase 6 Suppliers & portal | Supplier/installation/contact master (1), sector forms as data for the 5 sectors (4), supplier cases (5), magic links (6), mobile portal: form, draft, upload, submit (7) | CSV onboarding wizard (2), readiness questionnaire (3), help & questions (7a), EU template upload (7b), ADR-0002 (7c) |
| Phase 7 Outreach & documents | Day 0/7/14/21/28 schedule in minutes-mode (2, 3), local mail catcher only (4, no Resend), document upload with allow-list, versions, signed URLs (5), English templates (1) | Other languages, Resend + webhooks, case timeline UI (6) |
| Phase 8 Dashboard | **Demo tenant script (5), built first**, per-client dashboard (1), task list (3) | Portfolio view (2), p95 load target |
| Phases 9–10 (rest) | — | Hosting, load test, UAT, the other Live-cut items |

## Build order

Every step ends with: tests → `/review` → PR. Merging stays the owner's call.

| Step | Phase | Sub-step | Done when |
|---|---|---|---|
| 1 | Phase 3 | PR 15 + 16 review fixes | ✅ Fixed and pushed |
| 2 | Phase 8.5 | Demo tenant loader (R1-058) + local demo business date (local only, refused in production) + local run check from `README.md` | One command loads dummy data; all services start from a clean stack |
| 3 | Phase 4.1 + 4.5 | Scope rule + tax-point state machine | Scope and tax-point scenario tests pass |
| 4 | Phase 4.2 + 4.3 | Geography flags (R1-009 light) + declared vs validated origin (R1-032 light) | Geography visible in the ledger; missing origin evidence raises an exception |
| 5 | Phase 4.4 + 4.6 | Exclusions + special-procedure flag and task | Each excluded line shows reason, rule version, evidence need |
| 6 | Phase 4.8 | Decisions panel + manual-review resolve form; regulatory-analyst review | Phase 4 PR open |
| 7 | Phase 5.1 | Un-skip TH-01…TH-11; forward/backward rules | All threshold scenarios pass (frozen clock) |
| 8 | Phase 5.3–5.5 | Snapshots, events, Celery beat schedule, warning/trigger tasks | Missing run raises an alert |
| 9 | Phase 5.6 + 10.2 | Threshold screen with "why" lines and coverage warning + pre-registration mode (R1-013 light) | Trigger date and deadline basis shown; Phase 5 PR open |
| 10 | Phase 6.1 | Supplier, installation, contact master + API + screens | CRUD works on the demo tenant |
| 11 | Phase 6.4 + 6.5 | Sector forms as reference data (5 sectors) + supplier cases | Each sector renders its own questions |
| 12 | Phase 6.6 | Magic links (hash, expiry, scope, revoke, rate limit) + security review | Expired/revoked links fail closed |
| 13 | Phase 6.7 | Mobile portal: form, save draft, upload, submit | Phase 6 PR open |
| 14 | Phase 7.1–7.4 | Outreach schedule Day 0/7/14/21/28 in minutes-mode, English templates, local mail catcher | Full sequence seen in the mail catcher |
| 15 | Phase 7.5 | Documents: upload allow-list, versions, SHA-256, signed URLs | Renamed executable rejected |
| 16 | Phase 8.1 | Per-client dashboard (same queries as detail screens) | One screen shows a client's posture |
| 17 | Phase 8.3 | Task list (mine, overdue, complete with reason) | Phase 7 + 8 PRs open |
| 18 | Local gate | Full journey on dummy data (checklist below) | Every box ticked |
| 19 | Stage B | One real masked customs report on the local stack; domain owner activates real reference data | Real file imports cleanly; results checked by the owner |
| 20 | Stage C | Hosted staging if OPS-DEC-010 is decided; otherwise rehearse the local demo | App reachable, or local demo rehearsed |
| 21 | Submit | Release notes in `plans/CHANGELOG.md`, tag `r1-demo`, demo walkthrough | Submitted |

## Local gate checklist (Stage A exit)

Run on a clean local stack with the demo tenant only:

- [ ] One command starts everything; one command loads the demo tenant
- [ ] Sign in with MFA; switching clients never shows another client's data
- [ ] Upload a synthetic customs report → lines, row exceptions, coverage gaps
- [ ] Every line has a scope result and a tax-point state; unresolved lines get no quarter
- [ ] Geography flags show in the ledger; a line without origin evidence has an exception
- [ ] Threshold screen shows both tests; a demo client crosses 80% and the trigger, with tasks
- [ ] The trigger date and registration deadline basis show; no service-opening date is assumed
- [ ] A supplier case sends a magic link; the portal form is filled on a phone-sized screen
- [ ] The Day 0…28 reminders appear in the local mail catcher in minutes-mode
- [ ] A document uploads, gets a version and downloads only through a signed URL
- [ ] The dashboard and task list match the detail screens
- [ ] Full backend + frontend test suites, lint, types and Playwright are green
- [ ] Audit events exist for every state change in the journey

## Risks

- **Too much for the time left.** Phase 6 is the largest. If it slips, the portal ships with one
  sector form and the other four follow after submission.
- **Real data (Stage B) depends on outside people:** a masked real report (DATA-DEC-002) and
  a named domain owner (GOV-DEC-009). Without them, the submission is the dummy-data run.
- **Hosting (OPS-DEC-010) is undecided.** Without it there is no hosted demo; the local run
  is the deliverable.
- **Open legal questions** (LEGAL-DEC-019, LEGAL-DEC-026, REG-DEC-023, REG-DEC-001) stay as
  configuration hooks; nothing is guessed to save time.
