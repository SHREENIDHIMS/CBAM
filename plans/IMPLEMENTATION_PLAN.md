# Implementation plan — CBAM (single developer)

**How to read this plan**

- Phases are in **dependency order**. There are no durations. A phase is finished
  when every box in its **Exit gate** is ticked — not when time runs out.
- Each step names the requirement IDs it delivers. Full text and acceptance
  criteria: `docs/spec/CBAM_Spec_v1.4.md` and `docs/PRD.md` §6 (IDs R1-042+ ,
  R2-030+, R3-037), §6.1 (clarifications) and `docs/GAP_ANALYSIS.md` §9.3 (R1-053).
- Work one step at a time: `/plan <ID>` → failing test → `/implement` → `/test` →
  `/review` → tick the box → `plans/CHANGELOG.md` → PR.
- Legal dates are facts, not deadlines for this plan: CBAM starts 1 Jan 2027, so
  the **R1 Live** gate must be passed before then (see `docs/ROADMAP.md`).
- Tick boxes by changing `- [ ]` to `- [x]` in the PR that finishes the step.

**Standard exit criteria for every phase** (not repeated below):
all phase tests green in CI; lint + types clean; migrations up/down/up; no
hard-coded regulatory values; audit events on every state change; docs updated;
UI steps checked in a browser with Playwright; `/review` done (plus `security`
agent for auth/tenancy/files/links, `regulatory-analyst` for rules/reference data).

---

## Phase 0 — Groundwork (repo, tooling, understanding)

**Goal:** a running empty skeleton, CI, and the regulatory scenarios written down
before any business code.

1. - [ ] Read in full: `CLAUDE.md`, `docs/spec/CBAM_Team_Handbook.md` (Part 1 first),
   `docs/spec/CBAM_Spec_v1.4.md`, `docs/GAP_ANALYSIS.md`, `docs/GLOSSARY.md`.
   Handbook gate: you can explain the £50k two-test threshold and why default
   values are expensive, in your own words.
2. - [ ] Install tools: Python 3.12, `uv`, Node 22, Docker Desktop, Supabase CLI, `gh`.
3. - [x] `backend/`: `uv init`; add Phase-0 dependencies (`docs/TECHNICAL_SPEC.md` §3);
   `pyproject.toml` with ruff (E,F,I,B,UP,S,DTZ,RUF), mypy config, pytest config.
4. - [x] `backend/app/main.py` with `/health/live` and `/health/ready`; `app/core/config.py`
   reading env vars from `.env.example`.
5. - [x] `supabase init` → `supabase/config.toml`; set MFA (TOTP) on, leaked-password
   protection on, min password length 12; remove `cbam` from exposed schemas.
6. - [ ] `infra/docker-compose.yml` with Redis (and ClamAV under profile `scan`).
7. - [x] Alembic initialised for schema `cbam`; first migration creates schema, roles
   `cbam_owner` and `cbam_app`, and revokes `anon`/`authenticated` on `cbam`.
8. - [x] `frontend/`: Vite + React + TS; Tailwind + shadcn/ui; routes `ops/` and `portal/`;
   eslint, prettier, vitest, Playwright + axe; `/api` proxy to :8000.
9. - [x] Celery app (`app/core/jobs.py`) with one no-op task and beat entry, proving the
   worker and beat run locally.
10. - [x] Sentry wired (disabled when DSN empty) with PII scrubbing.
11. - [ ] GitHub Actions CI per `docs/TESTING.md` §5 (Supabase CLI in CI); float-ban grep;
    `gitleaks`; pre-commit hooks for ruff/prettier/gitleaks.
12. - [x] Write the threshold scenario catalogue TH-01…TH-11 as **failing, skipped**
    tests with inputs and expected outcomes in `backend/tests/scenarios/test_threshold.py`
    (spec R1-012 requires these written before implementation). The domain owner
    checks the hand calculations.
13. - [x] Ask the regulatory-analyst agent to re-check every source in spec §23/§30 and
    `docs/GAP_ANALYSIS.md` §10.3, including HMRC's autumn 2026 guidance and the October
    2026 webinar material, and record retrieval dates. Log any change. Repeat this
    re-check before the Pilot and Live releases.
14. - [ ] Review `docs/OPEN_DECISIONS.md` with the project owner; get answers where possible
    (brand BRAND-DEC-015, domain owner GOV-DEC-009, hosting OPS-DEC-010, stack TECH-DEC-011).

**Exit gate**
- [ ] `supabase start`, compose, api, worker, beat and frontend all run from `README.md` steps
- [ ] CI green on an empty PR
- [ ] TH-01…TH-11 exist as skipped tests with hand-checked expectations
- [ ] Open decisions reviewed and statuses updated

---

## Phase 1 — Platform foundations

**Goal:** everything every module relies on: tenancy, auth, permissions, audit,
clock, money, decisions, tasks.
**Requirements:** R1-001, R1-002, R1-022 (engine), R1-023, R1-042, R1-043, R1-044, R1-045

1. - [ ] `core/dates.py`: `uk_date()`, `quarter()`, `accounting_period()` (via reference
   data hook); property tests incl. BST/GMT boundaries (R1-043).
2. - [ ] `core/clock.py`: `Clock` protocol, `SystemClock`, `FrozenClock`; FastAPI dependency.
3. - [ ] `core/money.py`: Decimal context, `quantize(value, places, mode)` where mode is
   required; JSON encoder that emits decimals as strings (R1-044).
4. - [ ] Tables `tenants`, `organisations`, `users` (profile), `memberships`,
   `approval_roles` with RLS; RLS coverage test that fails for any tenant table without
   forced RLS (R1-001).
5. - [ ] `core/db.py`: request-scoped transaction that sets `app.tenant_id` after the
   membership check; worker helper to run a job "as tenant".
6. - [ ] `core/auth.py`: verify Supabase JWT (JWKS, expiry, audience); `aal2` required for
   privileged roles; recent-auth check helper for sensitive actions (R1-042).
7. - [ ] `core/permissions.py`: roles `platform_admin`, `operations`, `client_admin`,
   `reviewer`, `approver`, `supplier`, `tax_agent`, `domain_owner`; permission map;
   `require("perm")` dependency; permission-matrix test incl. tax-agent restrictions (R1-002).
8. - [ ] `audit_events` table + append-only trigger + grants + hash chain; `core/audit.py`
   `record()`; nightly chain-verify task; tests: UPDATE/DELETE as `cbam_app` fail (R1-023).
9. - [ ] `core/decisions.py` + `decisions` table: canonical-JSON fingerprint, save, lookup.
10. - [ ] `row_version` mixin + `If-Match` handling → 409 on mismatch (R1-045).
11. - [ ] `core/errors.py`: problem+json handler, domain error types.
12. - [ ] `tasks` module: task model, owner, due date + `due_rule`, status machine,
    escalation history; API list/patch (R1-022 engine; UI later).
13. - [ ] Frontend: Supabase Auth sign-in, MFA enrolment + challenge, sign-out, password
    reset; app shell; `/me`; role-aware navigation; British English formatting helpers
    (`14 March 2027`, `£1,234.56`) with tests.
14. - [ ] Platform admin screens: create tenant, invite users, assign roles (R1-001).
15. - [ ] Structured logging (`structlog`) with request/tenant/user IDs, no PII.

**Exit gate**
- [ ] Automated test: a user of tenant A cannot read or write any tenant-B row via API or direct SQL as `cbam_app` (handbook "RLS proven")
- [ ] Privileged role without MFA is refused
- [ ] Audit rows cannot be changed; chain verifies
- [ ] Concurrent approval test returns one success and one 409

---

## Phase 2 — Reference data and regulatory sources (R1 level)

**Goal:** law-as-data machinery before any rule uses it.
**Requirements:** R1-050 (and the R1 subset of R2-020's status model)

1. - [ ] Tables `regulatory_sources`, `ref_datasets`, `ref_dataset_versions` (`docs/DATABASE.md` §4).
2. - [ ] Loader CLI `app.modules.refdata.load`: manifest schema validation, checksum,
   idempotency, "same version different checksum" refusal.
3. - [ ] Activation workflow: dry-run impact report → `domain_owner` approval (recent MFA)
   → `active`; audit; previous version `retired` without deleting.
4. - [ ] `v_active_<dataset>` view pattern implementing the source activation rule
   (`docs/DATABASE.md` §5); generic `get(dataset, key, on=date)` service.
5. - [ ] First datasets (schemas + **fixture** data in `tests/fixtures/refdata/`):
   `ref_cbam_commodity_codes`, `ref_threshold_rules` (threshold £, forward days,
   backward months, backward test day, 2027 look-back floor, **warning ratio 80%**),
   `ref_registration_rules`, `ref_service_state`, `ref_exclusion_rules`,
   `ref_origin_rules`, `ref_geography_rules`, `ref_tax_point_rules`,
   `ref_working_days`, `ref_sector_forms` (schema only for now),
   `ref_cds_report_layouts` (column layouts of the HMRC "Get customs data" reports, R1-054),
   `ref_customs_monthly_exchange_rates` (customs value conversion, R1-035).
   Keep `cbam_cpr_exchange_rates` a **separate** dataset (R3 phase; PRD §6.1).
6a. - [ ] Seed `ref_compliance_calendar` as a `pending` version from the HMRC policy summary
   (31 May 2028; 31 Jul, 29 Sep, 30 Nov 2028; 28 Feb 2029) for domain-owner
   confirmation (REG-DEC-007). Not activated until the legal source is confirmed.
6. - [ ] Real CBAM commodity-code list transcribed from the HMRC source into
   `backend/refdata/cbam_commodity_codes/<version>/` by the developer, checked by the
   domain owner (handbook: "CN code list accuracy" is Jenny's).
7. - [ ] Platform screens (read-only list + activate button): sources, datasets, versions,
   impact report.

**Exit gate**
- [ ] A `draft` source's data cannot be returned by any `get()` (test)
- [ ] Reloading the same folder changes nothing; tampered file refused
- [ ] Impact report lists affected lines for a changed code list (fixture)
- [ ] Real commodity-code dataset loaded on local, pending domain-owner activation

---

## Phase 3 — Customs import pipeline

**Goal:** CDS data in, immutable and traceable.
**Requirements:** R1-003, R1-004, R1-005, R1-006, R1-010, R1-025, R1-036, R1-054

1. - [ ] Freeze the column mapping from real (masked) HMRC "Get customs data" reports
   (DATA-DEC-002); if not yet available, from HMRC's published report descriptions +
   synthetic files, marked provisional. Mapping lives in `ref_cds_report_layouts`.
2. - [ ] `import_batches` + upload endpoint: store original file in Storage, SHA-256
   idempotency, acquisition method (R1-003).
3. - [ ] `source_rows` (raw, immutable) + row validation → `row_exceptions` (missing/invalid
   commodity code, weight, tax point inputs, origin, value, supplier mapping) (R1-025).
4. - [ ] Normalise into `declarations`, `import_lines`, `parties` with exact commodity code,
   net mass kg (6 dp), customs value + valuation basis, origin as declared (R1-005, R1-010).
5. - [ ] Importer / declarant / agent / acting-on-behalf relationships (R1-006).
6. - [ ] Liable-person determination rule + decision record; fixtures for direct importer,
   broker/declarant, acting-on-behalf (R1-036).
7. - [ ] Manual import entry with reason; same validation and downstream fields (R1-004).
8. - [ ] Celery job for large files with progress; replay safety test (same file twice →
   no duplicates).
8a. - [ ] "Get customs data" adapter (R1-054): parse import item, header and tax-lines
   reports; join by declaration; record EORI (GB/XI) and the report's date window.
8b. - [ ] Coverage tracker (R1-054): per-client, per-EORI calendar of loaded days; gap and
   overlap detection; monthly ops task on the 1st to fetch last month; record whether the
   client granted us third-party access; account for the 2-day / 72-hour HMRC lag.
9. - [ ] UI: import batch list/detail, exception report (view + CSV), import ledger with
   filters, line detail showing source row.

**Exit gate**
- [ ] **500-row CDS file imports cleanly with errors reported per row** (handbook gate)
- [ ] A year of fixture "Get customs data" reports loads without duplicates and a missing window shows as a gap with a task
- [ ] Replaying a file creates no duplicate business records
- [ ] Every line links to its exact source row and file
- [ ] Freight-forwarder-as-declarant fixture keeps importer liable

---

## Phase 4 — Scope, origin, geography, exclusions, tax point

**Goal:** every line has a deterministic, versioned scope and tax-point state.
**Requirements:** R1-007, R1-008, R1-009, R1-011, R1-027, R1-032

1. - [ ] Scope rule: commodity code at tax-point date against active code list →
   in/out + rule/dataset version (R1-007).
2. - [ ] Geography facts: GB/XI EORI context, NI, Crown Dependencies, Overseas Territories,
   UK Continental Shelf; rules via `ref_geography_rules` (R1-009).
3. - [ ] Origin: declared vs validated origin, evidence links, UK-origin exemption only with
   evidence; conflicts → exception (R1-032).
4. - [ ] Exclusions as rule outcomes: private/non-business use, UK origin, Returned Goods
   Relief (export date, re-import within 3 years, same-state evidence, NI Union-goods
   variant), temporary admission full relief; evidence requirement per outcome; the
   linked-ETS exemption list exists but is empty (R1-011, PRD §6.1).
5. - [ ] Tax-point state machine: `unresolved → resolved` (normal import rule) or
   `special_procedure_pending`; no return-period assignment while unresolved (R1-008).
6. - [ ] Special-procedure lifecycle capture: storage/free zones, inward processing, outward
   processing, end-use, temporary admission partial/none/lost, export before tax point,
   re-import CBAM vs non-CBAM; every affected line flagged for manual threshold review with
   procedure, state and value-basis reason; a task is created (R1-027; queue UI comes in Phase 10).
7. - [ ] Re-run scope/tax point when reference data version is activated (via impact report).
8. - [ ] UI: decisions panel on line detail; tax-point timeline; "manual review" resolve form.

**Exit gate**
- [ ] Scenario tests for every case in `docs/TESTING.md` §3 "Scope, origin, tax point" pass
- [ ] No line gets a quarter while its tax point is unresolved
- [ ] Each excluded line shows reason, rule version and evidence requirement

---

## Phase 5 — Threshold engine

**Goal:** legally timed £50k tests with an earliest-date trigger.
**Requirements:** R1-012

1. - [ ] Un-skip TH-01…TH-11; implement `threshold/rules.py`: forward test (any day, 30 days
   ahead, uses forecast inputs), backward test (1st of month, prior 12 months, 2027
   floor), earliest-date combination, exclusions of out-of-scope / excluded / flagged lines.
2. - [ ] Minimal forecast input (expected tax point + value + source) to feed the forward test
   (full versioned register is R1-037 in Phase 10).
3. - [ ] `threshold_snapshots` + `threshold_events` with decision IDs; snapshot stores the
   set of included lines (hash) and totals.
4. - [ ] Celery beat: daily forward run; backward run on the 1st (UK date); operational
   daily recompute never creates a legal backward event on other days (TH-07).
5. - [ ] Warning at the configured ratio (80% fixture/default) and trigger → notifications +
   tasks; trigger moves registration profile to `registrable` with trigger date.
6. - [ ] UI: threshold dashboard (rolling totals, both tests, warning/trigger history,
   "why" explanation listing contributing lines, and a warning when customs-data
   coverage for the test window is incomplete — R1-054).

**Exit gate**
- [ ] All ten threshold scenarios pass with frozen clock (handbook: "5 hand-calculated scenarios" + extras)
- [ ] Event records the earliest liability date and test type
- [ ] Missing scheduled run raises an alert

---

## Phase 6 — Suppliers, sector-aware forms, secure portal

**Goal:** a supplier can answer on a phone without an account.
**Requirements:** R1-015, R1-016, R1-017, R1-028, R1-041, R1-051, R1-055, R1-056 (and design of R1-057)

1. - [ ] Supplier master: suppliers, installations (1→N), contacts (personal data, lawful
   basis), installation products/routes, preferred language (R1-015).
2. - [ ] Client onboarding: organisation wizard + suppliers/installations/contacts CSV with
   preview, row errors, idempotent commit (R1-051).
3. - [ ] Readiness questionnaire per installation (monitoring status, verifier appointed,
   expected data year, EU CBAM data, evidence owner, sector-specific capability) — visible
   before the first request (R1-016).
4. - [ ] `ref_sector_forms` data for cement (clinker basis), fertiliser (nitrogen basis),
   aluminium (PFCs), hydrogen, iron & steel: gases, functional unit, routes, questions,
   evidence slots; fields mapped to the HMRC Carbon Price Verification Form and EU template
   where known (R1-028).
5. - [ ] Supplier cases (installation + products + monitoring period) with status machine.
6. - [ ] Magic links: 32-byte token, hash stored, expiry, single-case scope, resend revokes
   prior, revoke; token → portal session cookie exchange; URL cleaned; rate limiting;
   all events audited (R1-017, R1-041).
7. - [ ] Portal UI (mobile-first): landing, sector form rendered from definition, save draft,
   upload (camera/photo friendly), submit → `supplier_submissions` version; language switch.
7a. - [ ] Portal help and save-and-return (R1-056): per-question help text in the supplier's
   language (versioned, approved), "not known yet" answer state, "Ask a question" →
   operations task + reply in the portal, autosaved drafts resumed through the same link.
7b. - [ ] EU CBAM Communication Template upload (R1-055): parse supported template versions
   (mapping in reference data), pre-fill the sector form, supplier confirms each value,
   provenance `EU_TEMPLATE`; unknown versions stored as a document with manual entry.
7c. - [ ] Design the shared installation network (R1-057) as ADR-0002: platform installation
   identity, matching and confirmation, supplier consent grants per importer, read-only
   links, RLS model, audit. Review with the `architect` and `security` agents. Design only;
   the build happens in Phase 10.
8. - [ ] Accessibility pass (axe) and 4G-throttled performance check.

**Exit gate**
- [ ] Five sector fixtures each render the correct question set; no incompatible generic data collected
- [ ] Expired/revoked/replaced links fail closed; cross-case access denied (tests)
- [ ] Minimum form completable on a phone in < 10 minutes (script ready for real test in Phase 9)
- [ ] A draft can be left and resumed; a supplier question creates a task
- [ ] ADR-0002 (shared installation network) written and reviewed

---

## Phase 7 — Outreach engine, email, documents

**Goal:** requests and reminders go out automatically; evidence is stored safely.
**Requirements:** R1-018, R1-019, R1-046, R1-048, R1-053, R1-047 (five pilot languages)

1. - [ ] Outreach templates (versioned, per language) with `{brand}` placeholder; approval
   state; **EN, TR, ZH, HI, DE** approved for pilot; English fallback (R1-047 subset).
2. - [ ] Schedule engine: Day 0 / 7 / 14 / 21 reminders while incomplete, Day 28 escalation
   to operations (no default decision); schedule from `ref`/config, not constants (R1-018).
3. - [ ] Test time-scale `OUTREACH_TIME_SCALE_SECONDS_PER_DAY`; production start-up refuses
   non-real value (R1-053).
4. - [ ] Resend adapter + local mail catcher adapter; message records with template version;
   webhook endpoint (signature verified) for delivered/bounced/complained; suppression list;
   hard bounce → task (R1-046).
5. - [ ] Documents: upload to Storage (content-sniffed allow-list, size limit), versions,
   SHA-256, scan hook states, signed download URLs after permission check, evidence links to
   supplier/installation/line/case (R1-019, R1-048).
6. - [ ] Timeline UI per supplier case: sends, email events, link events, submissions, documents.

**Exit gate**
- [ ] **Full Day 0/7/14/21/28 sequence runs end to end in staging "minutes-mode"**, every send audited (handbook gate)
- [ ] Hard bounce stops sends and creates a task
- [ ] Renamed executable rejected; no file retrievable without permission + signed URL

---

## Phase 8 — Operations dashboard

**Goal:** "where is client X?" answered on one screen.
**Requirements:** R1-021 (R1-022 UI), R1-058

1. - [ ] Per-client dashboard: imports (by scope/tax-point state), threshold status + warning,
   registration status, outreach status per supplier, documents received/missing, upcoming
   deadlines, unresolved items.
2. - [ ] Portfolio view for operations: all clients with health indicators and filters.
3. - [ ] Task list UI: my tasks, overdue, by client; assign, complete with reason.
4. - [ ] Dashboard numbers come from the same queries as detail screens (no second calculation).
5. - [ ] Demo tenant script (R1-058): creates/resets a tenant with synthetic data covering
   the main scenarios; refuses to run in production. Used in Phase 9 UAT and demos.

**Exit gate**
- [ ] A pilot client's full posture visible on one screen (handbook gate)
- [ ] Dashboard p95 ≤ 1.5 s on the 10,000-line fixture

---

## Phase 9 — Hardening and R1 PILOT release

**Goal:** a real pilot client uses the system. Spec gates G1–G8.

1. - [ ] Hosting set up per OPS-DEC-010: staging + production Supabase projects, containers,
   Redis, Resend domain, Sentry, secrets, backups (`docs/DEPLOYMENT.md`).
2. - [ ] Load test: 10,000-line import ≤ 5 min; dashboard p95; bulk document upload.
3. - [ ] Backup/restore drill on staging; restore log saved.
4. - [ ] Security: ZAP baseline, `security` agent review of R1, manual checks (cross-tenant,
   link abuse, document access, privilege escalation, audit tampering, unsafe upload).
5. - [ ] Real mobile usability test with a representative factory manager (< 10 min).
6. - [ ] UAT with the domain owner + ops using the handbook worked example and pilot data;
   issues fixed or logged.
7. - [ ] Domain owner activates production reference data (commodity codes, threshold, etc.).
8. - [ ] Pilot client onboarded: organisation, users with MFA, supplier list, installations;
   imports loaded; outreach sent.
9. - [ ] Tag `r1-pilot`; release notes in `plans/CHANGELOG.md`; evidence in `docs/releases/r1-pilot/`.

**Exit gate (spec §6)**
- [ ] G1 Readiness — CBAM basics, baseline and product boundary understood; blockers visible
- [ ] G2 Import — real CDS sample imported; 10,000-record load test done
- [ ] G3 Scope — deterministic, versioned in/out-of-scope results for all pilot imports
- [ ] G4 Threshold — hand-calculated scenarios pass with legal cadence
- [ ] G5 Supplier — mobile flow completed; Day 7/14/21/28 observable and audited
- [ ] G6 Documents — stored, versioned, linked, originals retrievable
- [ ] G7 Operations — pilot client posture on the dashboard
- [ ] G8 Hardening — backup/restore, security checks, tenant isolation, UAT, pilot onboarding evidence

---

## Phase 10 — R1 LIVE cut (operational foundation for 1 January 2027)

**Goal:** everything legally needed from 1 Jan 2027.
**Requirements:** R1-013, R1-014, R1-020, R1-024, R1-026, R1-029, R1-030, R1-031, R1-033,
R1-034, R1-035, R1-037, R1-038, R1-039, R1-040, R1-047 (rest), R1-049, R1-057, R2-031

1. - [ ] Registration service switch: effective-dated opening date, UI service-state messages,
   pre-registration capture continues (R1-040).
2. - [ ] Pre-registration compliance mode: deadline engine with 30-day rule and 31 Jan 2028
   first-year rule, storing which rule produced each date; non-digital route flag (R1-013).
3. - [ ] Registration readiness pack: all fields, sector 12-month weight estimates with method
   and evidence, declaration, versioned, PDF/CSV export (R1-014).
4. - [ ] Registration status record: monitor → registrable → registration-ready →
   submitted/registered, HMRC ID, history (R1-033).
5. - [ ] Registration change control: detect material changes, notification task with due-date
   rule, acknowledgement (R1-030).
6. - [ ] Review queue shell: assign, resolve, reopen with reason; special-procedure flags,
   supplier exceptions, missing data, manual classifications appear here (R1-020).
7. - [ ] Exports: import register, supplier status, readiness data, evidence inventory with
   source IDs, regulatory versions, generated-at; CSV formula-injection safe (R1-024).
8. - [ ] Resilience: retryable idempotent jobs, `job_failures` UI with retry, metrics, alerts,
   backup/restore procedure documented (R1-026).
9. - [ ] Customs amendments/replacements: versioned declarations, comparison, re-run of
   affected decisions, impact task when approved results change (R1-034).
10. - [ ] Currency provenance: source amount/currency, conversion method, GBP used (R1-035).
11. - [ ] Forecast register: versioned forecasts with confidence and evidence; changes create
    threshold impact records (R1-037).
12. - [ ] Customs-source reconciliation: duplicates, missing lines, orphans, conflicts across
    batches/manual entries (R1-038).
13. - [ ] CDS acquisition workbench: acquisition method, source owner, date on every batch (R1-031).
14. - [ ] Supplier contract/evidence responsibility state, versioned, shown in outreach and
    review (R1-029).
15. - [ ] Delegated evidence source party (installation / supply-chain party / verifier) (R1-039).
16. - [ ] Translation governance for any further languages (R1-047 remainder).
17. - [ ] Privileged support access grants, visible to tenant (R1-049).
17a. - [ ] Shared installation network build per ADR-0002 (R1-057); `security` agent review
    and cross-tenant tests before release.
17b. - [ ] Source change watcher (R2-031, moved earlier): daily checksum of registered source
    URLs → `regulatory_review` task; never edits reference data.
18. - [ ] Repeat load test, restore drill, security review; tag `r1-live`.

**Exit gate**
- [ ] Every JAN-1 item done and its acceptance test passing
- [ ] A registration-ready pack can be generated for any registrable fixture client
- [ ] Changing the service opening date changes the UI without deployment and keeps history
- [ ] Restore rehearsal passed on the release candidate

---

## Phase 11 — R2a: Evidence foundation

**Requirements:** R2-002, R2-003, R2-013, R2-015, R2-017, R2-020, R2-022, R2-026, R2-030

1. - [ ] Full regulatory source registry statuses (draft/laid/in_force/commenced/superseded),
   supersession links; admin screens for all reference datasets with change audit (R2-020, R2-015).
2. - [ ] Emissions data model: records, gas components, monitoring periods, production route,
   functional unit, source/provenance, verification status; scope (DIRECT/INDIRECT) separate
   from source (OWN_INSTALLATION/PRECURSOR_GOOD) (R2-002, R2-003).
3. - [ ] Evidence document types: verification report, good-specific verification summary,
   Carbon Pricing Verification Form, others — never merged (R2-017, R2-022).
4. - [ ] Data gaps, estimates, verifier conclusions as explicit states (R2-022).
5. - [ ] Field lineage: every accepted field and derived intermediate links to document +
   location + validation history (R2-013).
6. - [ ] Revision workflow: resubmissions create versions; downstream approvals reopen (R2-026).
7. - [ ] Processor register + per-tenant third-party processing setting (R2-030).

**Exit gate**
- [ ] Clicking any emissions value shows its source and history
- [ ] A corrected submission creates a new version and blocks stale approvals
- [ ] With third-party processing off, no document leaves our infrastructure (test)

## Phase 12 — R2b: Extraction and human review

**Requirements:** R2-001, R2-011, R2-012

1. - [ ] Extraction pipeline: PDF text/tables, Excel, images/OCR; Claude API extraction only
   when R2-030 allows; values stored with page/region/confidence/processor (R2-001).
2. - [ ] Plausibility rule engine from `ref_validation_rules` with PASS/WARNING/ERROR/HUMAN_REVIEW;
   initial rules from handbook: CO2 present, period matches import year, ±50% of sector
   benchmark, method valid, certificate names installation, verifier standards, precursor
   consistency (R2-011).
3. - [ ] Review screen: source document beside extracted values, rule failures, approve /
   reject / request correction, immutable audit (R2-012).

**Exit gate**
- [ ] No automated value can be accepted without a human action
- [ ] Every rule result shows its rule version

## Phase 13 — R2c: Emissions rules

**Requirements:** R2-004, R2-005, R2-006, R2-007, R2-018, R2-019, R2-021, R2-024, R2-027, R2-029

1. - [ ] GHG recomputation with versioned gas factors, 5-dp intensity rounding; mismatch with
   verified result → review exception (R2-004, R2-019).
2. - [ ] Functional-unit and gas applicability validation (clinker, nitrogen, PFC, N2O) (R2-018).
3. - [ ] Production route/process/boundary validation against System Boundaries data (R2-021).
4. - [ ] Monitoring-data year selection: Option 1 (incl. 2027/2026 choice) and Option 2 (R2-007).
5. - [ ] Coverage completeness and coverage compatibility with the import population (R2-027, R2-029).
6. - [ ] Actual/default selection with reason, rule, effective date (R2-005).
7. - [ ] Precursor compatibility rules and precursor attribution/aggregation/allocation
   (weighted, isolated, joint, multifunctional) (R2-006, R2-024).

**Exit gate**
- [ ] Every R2 scenario in `docs/TESTING.md` §3 for these IDs passes

## Phase 14 — R2d: Verification and CPR evidence

**Requirements:** R2-008, R2-009, R2-010, R2-023, R2-025, R2-028

1. - [ ] Verifier model: independence, accreditation body eligibility, sector scope, standards
   (ISO/IEC 17029, ISO 14065; CPR: ISO 14064-3, ISO 14066), materiality, site visit,
   conclusion, independent reviewer (R2-008, R2-025, R2-028).
2. - [ ] CPR evidence tracker: Carbon Pricing Verification Form per good, qualifying year
   (two years before import year), scheme, free allowances, thresholds, compensation,
   factor source; multi-scheme/multi-currency components (R2-009, R2-023).
3. - [ ] EU CBAM evidence import mapped to UK fields, never auto-accepted (R2-010).
4. - [ ] Fixtures from two real verifier packages (external blocker).

**Exit gate**
- [ ] An incomplete verifier or CPR package cannot be accepted

## Phase 15 — R2e: Dashboards, source watcher, R2 release

**Requirements:** R2-014, R2-016

1. - [ ] Supplier readiness dashboard: who will force defaults before the return is due (R2-014).
2. - [ ] Compliance dashboard with **RAG** status per client: evidence completeness, default
   exposure, verification status, CPR readiness, open exceptions; reconciles to cases (R2-016).
3. - [ ] Load/restore/security checks; tag `r2.0`.

**Exit gate**
- [ ] All R2 P0 acceptance tests pass; zero unreviewed automated values accepted

---

## Phase 16 — R3a: Calculation core

**Requirements:** R3-001, R3-002, R3-003, R3-005, R3-018, R3-022, R3-036

1. - [ ] CBAM rate reference per sector per quarter (R3-001).
2. - [ ] Transition-rule packages (first annual period, quarters, payment windows) (R3-036).
3. - [ ] Working-day calendar + payment channel catalogue (R3-022).
4. - [ ] Weight and rounding rules incl. fractional-kg cases and HMRC-determined weight (R3-003).
5. - [ ] Embedded-emissions calculator with operand trace; golden fixture (formula) (R3-002).
6. - [ ] FX: HMRC **CBAM** rate for the quarter before the tax point per currency, round down
   2 dp, from `cbam_cpr_exchange_rates` only — never the monthly customs rates (R3-005).
7. - [ ] Historical replay: recompute with stored versions; unchanged after a rule change (R3-018).

## Phase 17 — R3b: CPR and net liability

**Requirements:** R3-004, R3-006, R3-007

1. - [ ] CPR per scheme in the prescribed order; precursor schemes separate; effective price;
   compensation stage; hook for REG-DEC-013 (defaults and CPR) (R3-004).
2. - [ ] CPR cap at liability; reject unconverted/unevidenced relief (R3-006).
3. - [ ] Net liability from approved R2 inputs only; floor £0 (R3-007).

## Phase 18 — R3c: Returns

**Requirements:** R3-008, R3-009, R3-010, R3-013, R3-014, R3-021, R3-026, R3-029

1. - [ ] Return line builder per consignment/declaration × code × installation (R3-008).
2. - [ ] Special-procedure final value/liability rules (a)–(f) (R3-021).
3. - [ ] Registrable-person obligations even before service registration (R3-026).
4. - [ ] Nil returns and reminders (R3-009); due dates from REG-DEC-007 data.
5. - [ ] Approval workflow with configurable approver role (SAO per tenant policy), MFA,
   row_version, immutable approval; filed/approved rows locked by DB trigger + app (R3-010).
6. - [ ] Amendments only for errors within the window; **default→actual lock** (not
   configurable) (R3-013, R3-014).
7. - [ ] Return-to-ledger reconciliation and change propagation (R3-029).

## Phase 19 — R3d: Filing and payments

**Requirements:** R3-011, R3-012, R3-023, R3-030

1. - [ ] Filing adapter boundary + filing-ready export ("exactly what to enter", handbook §4.8);
   live submission disabled until TECH-DEC-004 and BUS-DEC-003 close (R3-011).
2. - [ ] Submission lineage: receipt, acknowledgement, rejection, calculation method (R3-023).
3. - [ ] Idempotency keys, request fingerprint, controlled retry (R3-030).
4. - [ ] Payment ledger with due dates from working-day rules and authorised methods (R3-012).

## Phase 20 — R3e: Compliance cases and enforcement

**Requirements:** R3-016, R3-019, R3-024, R3-027, R3-028, R3-031, R3-032, R3-033, R3-034

1. - [ ] Compliance case layer: notices, assessments, compulsory registration, penalties,
   reviews, appeals (R3-019).
2. - [ ] Review/appeal timetable engine (R3-031).
3. - [ ] Penalty and interest ledger from reference data (£500 record-keeping; £500 + £40 daily
   notification) and penalty defence workflow (R3-016, R3-034).
4. - [ ] Artificial separation review + HMRC direction workflow (R3-024, R3-032).
5. - [ ] Tax-avoidance / deliberate-misstatement case types, never auto-concluding (R3-027).
6. - [ ] Record-preservation directions and information requests with legal hold (R3-028, R3-033).

## Phase 21 — R3f: Lifecycle, retention, closure, R3 release

**Requirements:** R3-015, R3-017, R3-020, R3-025, R3-035, R3-037

1. - [ ] Registration lifecycle: changes, succession (21-day, six-month), insolvency,
   deregistration, final returns (R3-020).
2. - [ ] Repayment claims with three-year window, unjust enrichment, reimbursement records (R3-015).
3. - [ ] Retention-anchor calculation and legal holds (R3-035).
4. - [ ] Evidence pack: one click, deterministic, six-year, with reference-data versions (R3-017).
5. - [ ] Closure reconciliation checklist (R3-025) and tenant export (R3-037).
6. - [ ] Dry-run returns with real client data for a full period; load/restore/security; tag `r3.0`.

**Exit gate (R3)**
- [ ] Approved fixture returns reproduce exactly; historical replay unchanged after rule updates
- [ ] Default→actual amendment rejected by the legal lock (cannot be switched off)
- [ ] Retry after timeout never creates a duplicate filing
- [ ] Evidence pack regenerates byte-identical for the same inputs

---

## Appendix A — Requirement → phase

| Phase | Requirement IDs |
|---|---|
| 1 | R1-001, R1-002, R1-022, R1-023, R1-042, R1-043, R1-044, R1-045 |
| 2 | R1-050 |
| 3 | R1-003, R1-004, R1-005, R1-006, R1-010, R1-025, R1-036, R1-054 |
| 4 | R1-007, R1-008, R1-009, R1-011, R1-027, R1-032 |
| 5 | R1-012 |
| 6 | R1-015, R1-016, R1-017, R1-028, R1-041, R1-051, R1-055, R1-056 |
| 7 | R1-018, R1-019, R1-046, R1-048, R1-053 (+ R1-047 pilot languages) |
| 8 | R1-021, R1-058 |
| 10 | R1-013, R1-014, R1-020, R1-024, R1-026, R1-029, R1-030, R1-031, R1-033, R1-034, R1-035, R1-037, R1-038, R1-039, R1-040, R1-047, R1-049, R1-057, R2-031 |
| Backlog | R1-052, R1-059, R1-060 |
| 11 | R2-002, R2-003, R2-013, R2-015, R2-017, R2-020, R2-022, R2-026, R2-030 |
| 12 | R2-001, R2-011, R2-012 |
| 13 | R2-004, R2-005, R2-006, R2-007, R2-018, R2-019, R2-021, R2-024, R2-027, R2-029 |
| 14 | R2-008, R2-009, R2-010, R2-023, R2-025, R2-028 |
| 15 | R2-014, R2-016 |
| 16 | R3-001, R3-002, R3-003, R3-005, R3-018, R3-022, R3-036 |
| 17 | R3-004, R3-006, R3-007 |
| 18 | R3-008, R3-009, R3-010, R3-013, R3-014, R3-021, R3-026, R3-029 |
| 19 | R3-011, R3-012, R3-023, R3-030 |
| 20 | R3-016, R3-019, R3-024, R3-027, R3-028, R3-031, R3-032, R3-033, R3-034 |
| 21 | R3-015, R3-017, R3-020, R3-025, R3-035, R3-037 |

## Backlog (P2, after the Live cut or when capacity allows)

- [ ] R1-052 Identifier checks (EORI format / HMRC "Check an EORI number" API; tariff validity warning)
- [ ] R1-059 CBAM exposure check for prospects (sandbox tenant; no tax figure)
- [ ] R1-060 Client monthly digest email
