# R1 October plan (submission by 31 October 2026)

The owner has a submission deadline of **Saturday 31 October 2026** for a running R1.
That is earlier than `docs/ROADMAP.md` assumes (1 January 2027). This plan is a cut-down R1
that fits about 3 weeks. It changes the order and the depth of the work, not the rules:
every CLAUDE.md §3 guarantee still applies (law is data, Decimal only, UK legal dates,
tenant isolation, audit, humans approve).

## The golden rule: local with dummy data first, real data second

1. **Stage A — local, dummy data only (11–27 Oct).** Everything runs on this machine
   (`supabase start` + `docker compose` + API, worker, beat, frontend) against the **demo
   tenant** filled with synthetic data. No real client, supplier or customs data anywhere.
2. **Local gate (27 Oct).** The full R1 journey works end to end on dummy data (checklist
   below). If any box is open, we fix it and do **not** move on.
3. **Stage B — real data, still local (29 Oct).** Only after the local gate passes: run one
   real, masked "Get customs data" report on the local stack and have the domain owner
   activate the real reference data. Nothing real goes into the repo or tests.
4. **Stage C — hosted (30 Oct), only if hosting is decided (OPS-DEC-010).** If not, we submit
   the local run.

## Scope for 31 October

| Area | In (must have) | Cut to after 31 Oct |
|---|---|---|
| Phase 4 Scope & tax point | Scope rule (step 1), tax-point state machine (5), UK-origin / private-use / Returned Goods exclusions (4), special procedures flagged for manual review (6, flag + task only), decisions panel on line detail (8) | Full geography rules (2), validated origin evidence (3), re-run on activation (7) |
| Phase 5 Threshold | Forward + backward tests with TH-01…TH-11 (1), snapshots/events (3), Celery beat runs (4), 80% warning + trigger tasks (5), threshold screen (6) | Forecast register beyond the minimal input (2) |
| Phase 6 Suppliers & portal | Supplier/installation/contact master (1), sector forms as data for the 5 sectors (4), supplier cases (5), magic links (6), mobile portal: form, draft, upload, submit (7) | CSV onboarding wizard (2), readiness questionnaire (3), help & questions (7a), EU template upload (7b), ADR-0002 (7c) |
| Phase 7 Outreach & documents | Day 0/7/14/21/28 schedule in minutes-mode (2, 3), local mail catcher only (4, no Resend), document upload with allow-list, versions, signed URLs (5), English templates (1) | Other languages, Resend + webhooks, case timeline UI (6) |
| Phase 8 Dashboard | **Demo tenant script (5) — built first, day 1**, per-client dashboard (1), task list (3) | Portfolio view (2), p95 load target |
| Phases 9–10 | — | All (hosting, load test, UAT, Live cut) |

## Day by day

Every build day ends with: tests → `/review` → PR. Merging stays the owner's call.

| Day | Date | Work | Done when |
|---|---|---|---|
| 1 | Sun 11 Oct | PR 15 + 16 fixed and pushed. Owner merges them. Start the demo tenant script (R1-058) | PRs merged |
| 2 | Mon 12 Oct | Demo tenant script: synthetic clients, EORIs, customs reports, lines; refuses to run outside local/dev. Local run checklist from `README.md` works from a clean start | `supabase start` → all services up → demo data loaded with one command |
| 3 | Tue 13 Oct | Phase 4: scope rule + tax-point state machine (rules.py, tests first) | Scope and tax-point scenario tests pass |
| 4 | Wed 14 Oct | Phase 4: exclusions + special-procedure flag and task | Each excluded line shows reason, rule version, evidence need |
| 5 | Thu 15 Oct | Phase 4: decisions panel and manual-review resolve form; regulatory-analyst review | Phase 4 PR open |
| 6 | Fri 16 Oct | Phase 5: un-skip TH-01…TH-11; forward/backward rules | All threshold scenarios pass (frozen clock) |
| 7 | Sat 17 Oct | Phase 5: snapshots, events, Celery beat schedule, warning/trigger tasks | Missing run raises an alert |
| 8 | Sun 18 Oct | Phase 5: threshold screen with "why" lines and coverage warning | Phase 5 PR open |
| 9 | Mon 19 Oct | Phase 6: supplier, installation, contact master + API + screens | CRUD works on demo tenant |
| 10 | Tue 20 Oct | Phase 6: sector forms as reference data (5 sectors) + supplier cases | Each sector renders its own questions |
| 11 | Wed 21 Oct | Phase 6: magic links (hash, expiry, scope, revoke, rate limit) + security review | Expired/revoked links fail closed |
| 12 | Thu 22 Oct | Phase 6: mobile portal — form, save draft, upload, submit | Phase 6 PR open |
| 13 | Fri 23 Oct | Phase 7: outreach schedule Day 0/7/14/21/28 in minutes-mode, English templates, local mail catcher | Full sequence seen in the mail catcher |
| 14 | Sat 24 Oct | Phase 7: documents — upload allow-list, versions, SHA-256, signed URLs | Renamed executable rejected |
| 15 | Sun 25 Oct | Phase 8: per-client dashboard (same queries as detail screens) | One screen shows a client's posture |
| 16 | Mon 26 Oct | Phase 8: task list (mine, overdue, complete with reason) | Phase 7 + 8 PRs open |
| 17 | Tue 27 Oct | **Local gate** — full journey on dummy data (checklist below) | Every box ticked |
| 18 | Wed 28 Oct | Buffer: fix whatever the local gate found | Local gate re-run green |
| 19 | Thu 29 Oct | **Stage B** — one real masked customs report on the local stack; domain owner activates real reference data | Real file imports cleanly; results checked by the owner |
| 20 | Fri 30 Oct | **Stage C** — hosted staging if OPS-DEC-010 is decided; otherwise prepare the local demo | App reachable, or local demo script rehearsed |
| 21 | Sat 31 Oct | Submit: release notes in `plans/CHANGELOG.md`, tag `r1-demo`, demo walkthrough | Submitted |

## Local gate checklist (Stage A exit, 27 Oct)

Run on a clean local stack with the demo tenant only:

- [ ] One command starts everything; one command loads the demo tenant
- [ ] Sign in with MFA; switching clients never shows another client's data
- [ ] Upload a synthetic customs report → lines, row exceptions, coverage gaps
- [ ] Every line has a scope result and a tax-point state; unresolved lines get no quarter
- [ ] Threshold screen shows both tests; a demo client crosses 80% and the trigger, with tasks
- [ ] A supplier case sends a magic link; the portal form is filled on a phone-sized screen
- [ ] The Day 0…28 reminders appear in the local mail catcher in minutes-mode
- [ ] A document uploads, gets a version and downloads only through a signed URL
- [ ] The dashboard and task list match the detail screens
- [ ] Full backend + frontend test suites, lint, types and Playwright are green
- [ ] Audit events exist for every state change in the journey

## Risks

- **Too much for 3 weeks.** Phase 6 is the largest. If it slips, the portal ships with one
  sector form and the other four follow after 31 Oct.
- **Real data (Stage B) depends on outside people:** a masked real report (DATA-DEC-002) and
  a named domain owner (GOV-DEC-009). Without them, the submission is the dummy-data run.
- **Hosting (OPS-DEC-010) is undecided.** Without it there is no hosted demo; the local run
  is the deliverable.
- **Open legal questions** (LEGAL-DEC-019, LEGAL-DEC-026, REG-DEC-023) stay as configuration
  hooks; nothing is guessed to save time.
