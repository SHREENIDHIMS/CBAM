# Product Requirements Document — CBAM

**Baseline:** Build Specification v1.4 (`docs/spec/`) + additions in §6 of this file.
Where this document and the spec differ, this document's §6 additions win only for
the rows they add; every other spec row stands as written.

---

## 0. Sources

- Build contract: `docs/spec/CBAM_Spec_v1.4.md`
- Product baseline: VLookup Business Solutions *CBAM Platform — Team Handbook*
  (29 Sep 2026), `docs/spec/CBAM_Team_Handbook.md`. Its key message: **"The data
  race is the product. The calculator comes second."** A client that uses default
  values instead of verified supplier data pays roughly six times more
  (48.2 t Turkish EAF steel: £785.25 actual vs £4,771.80 default — illustrative).

## 1. Problem

From **1 January 2027** UK importers of aluminium, cement, fertiliser, hydrogen, and
iron & steel goods owe a carbon charge (UK CBAM) on the emissions embodied in those
goods. To comply they must:

1. know which imports are in scope and when each one's legal **tax point** occurs;
2. notice when they cross the **£50,000** registration threshold (forward 30-day
   test on any day; backward 12-month test on the first day of each month);
3. collect verified emissions data from overseas factories that are not obliged
   to answer, in many languages;
4. choose actual or default emissions under strict legal rules;
5. claim Carbon Price Relief (CPR) where a carbon price was already paid abroad;
6. file returns (annual for 2027, quarterly afterwards), pay, amend, and respond to
   HMRC — and prove every figure for six years.

Spreadsheets and email cannot do this reliably across many clients. The product is
the system of record and the workflow that makes each step auditable.

## 2. Users

| Persona | Who | Main goals | Role in system |
|---|---|---|---|
| Operations user | Our compliance team member serving many clients | See which clients need attention; chase suppliers; resolve exceptions | `operations` |
| Client admin | The importer's finance/compliance lead | See own posture; manage own users; supply data | `client_admin` |
| Reviewer | Person checking evidence and exceptions | Approve/reject evidence with the source in view | `reviewer` |
| Approver | Person authorised to approve a return (handbook: SAO; legal role configurable) | Approve returns with full traceability | `approver` |
| Supplier user | Factory/installation manager abroad (handbook: "a factory manager in Turkey") | Answer the emissions request on a phone in < 10 minutes without an account | `supplier` (magic link) |
| Tax agent | Authorised agent | Prepare/submit returns when authorised; never registers the liable person | `tax_agent` |
| Platform admin | Us | Tenants, reference data, support | `platform_admin` |
| Domain owner | Named tax/CBAM expert (GOV-DEC-009) | Approve reference-data changes and legal interpretations | `domain_owner` |

## 3. End-to-end journey (handbook eight-step flow)

| Step | What happens | Release |
|---|---|---|
| 1. Imports | CDS export or manual entry becomes an immutable, traceable import ledger | R1 |
| 2. Scope | Each line classified by versioned commodity-code rules, exclusions, origin, geography | R1 |
| 3. Tax point & threshold | Tax point resolved (special procedures flagged); £50k forward/backward tests; trigger date | R1 |
| 4. Registration readiness | Registration pack, deadline basis (30-day rule / 31 Jan 2028 transition), status record | R1 |
| 5. Supplier outreach | Readiness, sector-aware form via secure link, reminders, documents | R1 |
| 6. Validation | Extraction, emissions model, verification, plausibility, human review, actual/default selection | R2 |
| 7. CPR & calculation | Per-scheme CPR, FX, cap, embedded emissions, net liability | R2 evidence / R3 calculation |
| 8. Return, filing & evidence | Return lines, approval, submission, payment, amendments, cases, six-year evidence pack | R3 |

## 4. Releases and priority legend

| Label | Meaning |
|---|---|
| **P0** | Must exist in the release it is tagged with. Release cannot ship without it. |
| **P1** | Should exist in that release; may move to the next cut with a recorded reason. |
| **P2** | Nice to have; backlog. |
| **PILOT-P0** | Must be in the R1 **Pilot cut** (first client using real data). |
| **PILOT-P1** | Should be in the Pilot cut if the pilot client needs it; otherwise Live cut. |
| **JAN-1** | Must be in the R1 **Live cut**, which must be operating before CBAM starts on 1 Jan 2027. |

Release order is fixed: **R1 Pilot → R1 Live → R2 → R3.** See `docs/ROADMAP.md`.

## 5. Requirement catalogue (index)

Full text and acceptance criteria: `docs/spec/CBAM_Spec_v1.4.md` (spec §5, §7, §8, §29.1)
and §6 below. Build phase for each ID: `plans/IMPLEMENTATION_PLAN.md` Appendix A.

| Module | R1 | R2 | R3 |
|---|---|---|---|
| Organisations, users, roles, auth | 001, 002, 036, 042, 045, 049, 051, 058 | — | 037 |
| Customs imports | 003, 004, 005, 006, 010, 025, 031, 034, 035, 038, 054, 059 | — | — |
| Scope, origin, geography, exclusions | 007, 009, 011, 032, 052 | — | — |
| Tax point & special procedures | 008, 027 | — | 021 |
| Threshold | 012, 037 | — | 024, 032 |
| Registration | 013, 014, 030, 033, 040 | — | 020, 026 |
| Suppliers & portal | 015, 016, 017, 028, 029, 039, 041, 055, 056, 057 | 014 | — |
| Outreach & email | 018, 046, 047, 053 | — | — |
| Documents & evidence | 019, 048 | 001, 012, 013, 017, 022, 026, 030 | 017 |
| Tasks, review, dashboard, export | 020, 021, 022, 024, 060 | 016 | — |
| Reference data & sources | 050, 043, 044 | 015, 020, 031 | 001, 022, 036 |
| Emissions | — | 002, 003, 004, 005, 006, 007, 011, 018, 019, 021, 024, 027, 029 | 002, 003 |
| Verification | — | 008, 025, 028 | — |
| CPR | — | 009, 010, 023 | 004, 005, 006 |
| Liability & returns | — | — | 007, 008, 009, 010, 013, 014, 018, 029 |
| Filing & payment | — | — | 011, 012, 022, 023, 030 |
| Compliance cases & penalties | — | — | 015, 016, 019, 027, 028, 031, 033, 034 |
| Retention & closure | — | — | 017, 025, 035 |
| Audit & observability | 023, 026 | — | — |

## 6. Additional requirements (v1.5 gap closure)

Same format as the spec. Reason for each: `docs/GAP_ANALYSIS.md` §3–§4.

| ID | Requirement | Release / Priority | What the system must do | Acceptance / evidence |
|---|---|---|---|---|
| R1-042 | Authentication, MFA and sessions | R1 / PILOT-P0 | Supabase Auth (email + password) for internal and client users. TOTP MFA mandatory for `platform_admin`, `operations`, `reviewer`, `approver`, `domain_owner`; optional for others, tenant-enforceable. FastAPI verifies every Supabase JWT (signature, expiry, audience) and rejects MFA-required roles unless the token is `aal2`. Short access-token lifetime, refresh rotation, inactivity sign-out in the UI (config, default 30 min). Supabase rate limits on login/reset kept on; failed logins and MFA events copied into our audit log. | A token without `aal2` is refused for MFA-required roles; an expired or tampered JWT gets 401; sign-in events appear in the audit log. |
| R1-043 | UK legal-date semantics | R1 / PILOT-P0 | Store instants as UTC `timestamptz`. Store every legal date (tax point, trigger date, deadline, effective date) as `date` derived in `Europe/London`. All rules take an explicit `as_of` date from an injected clock; no rule calls the system clock. Quarter and accounting period derive from the tax-point date. | Fixtures at 23:30 UTC on 31 Mar (BST) and 31 Dec (GMT) land in the correct UK date and quarter; a frozen-clock test replays a past month's backward test exactly. |
| R1-044 | Numeric precision contract | R1 / PILOT-P0 | Use `Decimal`/`NUMERIC` only (no float) for money, mass, emissions, rates and FX. Column scales: source money as sourced + currency; GBP money `NUMERIC(18,2)`; intermediate money `NUMERIC(24,8)`; net mass kg `NUMERIC(20,6)`; tCO2e and intensity internal `NUMERIC(24,10)`, reported intensity rounded to 5 dp at the prescribed step; FX `NUMERIC(18,8)`. Rounding modes are named per rule in reference data. CI fails if `float` appears in domain code. | Property tests show no precision loss through import → threshold; CI float check fails on a planted `float(`. |
| R1-045 | Concurrency control | R1 / PILOT-P0 | Every reviewable or approvable record has a `row_version`. Updates, approvals and rejections must send the version they saw; a mismatch returns HTTP 409 and nothing changes. Scheduled jobs that change the same record take a row lock. | Two simulated reviewers approving the same item: one succeeds, one gets 409; audit shows one approval. |
| R1-046 | Email delivery and bounce handling | R1 / PILOT-P0 | Send through a provider adapter. Store message ID, status (queued/sent/delivered/bounced/complained/failed), provider response. Process bounce/complaint webhooks; hard bounces and complaints add the address to a suppression list and create an operations task. Sending domain has SPF, DKIM and DMARC before the pilot. | A simulated hard bounce stops further sends to that address, marks the supplier case, and creates a task; all sends are visible in the outreach timeline. |
| R1-047 | Translation governance | R1 / P1 (the five pilot languages are PILOT-P0) | Outreach and portal templates are versioned per language. First languages (handbook): **English, Turkish, Chinese, Hindi, German**. A machine-translated draft cannot be used until a named reviewer approves it. English is the fallback. The template version used is stored on every send. | Unapproved language falls back to English and logs why; each sent message shows its template version. |
| R1-048 | Upload safety and evidence storage | R1 / PILOT-P0 | Allow-list file types by content (magic bytes), not extension: PDF, XLSX, XLS, CSV, PNG, JPEG, HEIC. Max size configurable (default 25 MB). Store in a private bucket with server-side encryption and object versioning; the database keeps SHA-256, size, type, uploader, source. Files are served only through short-lived signed URLs after a permission check. A malware-scan hook marks files `pending`/`clean`/`infected`; infected files are quarantined and never served. | A renamed `.exe` is rejected; a file cannot be fetched without a valid permission + signed URL; SHA-256 recorded for every file. |
| R1-049 | Privileged support access | R1 / P1 | Platform-admin access to a tenant's business data requires a reason and an expiry (default 60 min). The session is flagged, every read and write is audited, and the tenant's client admin can see the access log. | Access without a reason is refused; access log visible to the tenant; access ends at expiry. |
| R1-050 | Versioned reference-data loader | R1 / PILOT-P0 | Load reference data from files in `backend/refdata/` (YAML/CSV) with a manifest: dataset, version, source ID, source URL, retrieved date, checksum, effective dates, status (`draft`/`active`). Loading is idempotent; a changed file with the same version is refused. Activation of a new version requires `domain_owner` approval and shows a dry-run impact report (which records would change outcome). Every decision stores the dataset version it used. R2-015/R2-020 extend this into full admin screens and the full status model. | Loading the same file twice changes nothing; a `draft` dataset cannot drive a scope decision; the impact report lists affected import lines before activation. |
| R1-051 | Client onboarding | R1 / PILOT-P1 | A guided onboarding flow: organisation details, EORI/VAT, liable-person vs agent, users and roles, and bulk CSV upload of suppliers, installations and contacts with row-level validation and a preview before commit. | A pilot client with 50 suppliers and 80 installations can be onboarded from one CSV; bad rows are reported, good rows load, re-upload does not duplicate. |
| R1-052 | Identifier checks | R1 / P2 | Validate EORI format (GB/XI + 12 digits) on entry; optionally check GB EORIs against the HMRC "Check EORI number" API. Validate that a commodity code exists on the UK tariff for the tax-point date as a warning only — CBAM scope still comes only from CBAM reference data. | Malformed EORI refused; an unknown commodity code creates a warning, not a scope decision. |
| R1-053 | Outreach time-scale for testing | R1 / PILOT-P0 | Non-production setting `OUTREACH_TIME_SCALE_SECONDS_PER_DAY` makes the Day 0/7/14/21/28 schedule run in minutes (handbook "minutes-mode"). App refuses to start in production with any other value than a real day. | Full sequence runs end to end in staging in minutes, all sends audited; production start-up fails if changed. |
| R2-030 | Third-party processing controls | R2 / P0 | OCR/LLM (including the Claude API named in the handbook) or any external processing of documents is off by default, enabled per tenant by a `client_admin` and approved by `platform_admin`, only for processors listed in the processor register (with DPA, region and retention). Extracted values from any automated method are never accepted without human review (R2-012). | With the tenant setting off, no document byte leaves our infrastructure (verified by network-mock test); every extraction records the processor used. |
| R2-031 | Source change watcher | R1 Live / P1 (moved earlier, see §6.1) | Daily job fetches each registered source URL, stores a content checksum, and creates a `regulatory_review` task when it changes. It never activates or edits reference data itself. | A changed page fixture creates one review task with old/new checksums; no reference-data row changes. |
| R1-054 | HMRC "Get customs data" import adapter and coverage tracker | R1 / PILOT-P0 | Parse the four official HMRC "Get customs data" CSV reports (import item, import header, import tax lines; export item stored but not used for CBAM) and join them by declaration into import lines, keeping every source row. Each report is linked to the EORI (GB or XI) and the date window it covers (max 31 days). A per-client coverage calendar shows which days are loaded for each EORI and highlights gaps and overlaps. On the 1st of each month an operations task asks for last month's reports. Coverage accounts for HMRC's data lag (last 2 days never available; reports up to 72 h). Whether the client has granted us third-party access in the HMRC service is recorded per client. Report layouts are versioned reference data, so a changed HMRC column layout is a data change, not a code change. | A year of fixture reports loads with no duplicates; a missing 31-day window shows as a gap and creates a task; a threshold view warns when coverage for its window is incomplete. |
| R1-055 | EU CBAM Communication Template upload | R1 / PILOT-P1 | In the supplier portal a supplier can upload the EU Commission CBAM Communication Template (Excel) they already complete for EU customers. We read the supported template versions (mapping stored as versioned reference data), pre-fill the UK sector form, and ask the supplier to confirm or correct each value before submitting. Pre-filled values are marked `source = EU_TEMPLATE` and are never treated as UK-valid; R2-010 performs the UK-rule validation. Unknown template versions are stored as a document and fall back to manual entry. | A fixture EU template pre-fills the form; confirmed values keep their EU provenance; an unknown template version does not break the form. |
| R1-056 | Supplier portal help and save-and-return | R1 / PILOT-P1 | Per-sector, per-question help text in the supplier's language (versioned and approved like outreach templates, R1-047); an explicit "not known yet" answer that is stored as such (never as zero or blank); an "Ask a question" button that creates an operations task linked to the case and answers back through the portal; drafts saved automatically and resumed through the same (unexpired) link. | A supplier can stop and resume without losing answers; a question creates a task visible in the case timeline; "not known yet" is distinguishable from 0 in the data. |
| R1-057 | Shared installation network (supplier consent) | R1 / P1 (design in Phase 6, build in Live cut) | One installation that supplies several of our clients answers once. A platform-level installation identity links the same real installation across tenants (matched by operator identifier/address, confirmed by operations). The supplier explicitly grants, per importer, which submissions and documents that importer may see; grants are revocable, time-stamped and audited. A tenant sees only granted data, through a read-only link to the shared submission; it never sees other importers, volumes or prices. Design recorded as ADR-0002 and reviewed by the `security` agent before build. | Without a grant a tenant sees nothing of another tenant's case; granting shares exactly the chosen submissions; revoking stops future access and is audited; RLS tests cover the shared tables. |
| R1-058 | Demo tenant and synthetic data | R1 / P1 | A script creates (and resets) a demo tenant with synthetic imports, suppliers, installations, cases and documents covering the main scenarios (below/above threshold, special procedure, bounced email, submitted supplier). It is blocked from running in production. Used for UAT, training and sales demos. | The reset script is idempotent; production start-up refuses it; the demo tenant contains no real data. |
| R1-059 | CBAM exposure check (prospect report) | R1 / P2 | In a sandbox tenant, a prospect's "Get customs data" CSV produces a report: in-scope lines by sector, total value, threshold status and date, and the installations to contact first. No tax calculation. The sandbox data is deleted after a configurable period unless the prospect becomes a client. | A fixture CSV produces the report; no liability figure appears; sandbox data is deleted on schedule. |
| R1-060 | Client monthly digest | R1 / P2 | A monthly email to each client admin: threshold position, supplier responses, missing documents and upcoming deadlines, with links into the app (no personal data of suppliers in the email body). Opt-out per user. | Digest content matches the dashboard for the same date; opted-out users receive nothing. |
| R3-037 | Tenant data export and offboarding | R3 / P1 | A client admin can request a full export of their tenant (imports, decisions, evidence files, returns, audit events) as a signed archive with a manifest. Export is audited. After closure (R3-025), data stays under retention/legal hold rules; export does not delete anything. | Export of a fixture tenant contains every table's rows and every file with matching SHA-256s; no other tenant's data is present. |

### 6.1 Clarifications to existing requirements (research update, 30 Sep 2026)

These do not add scope; they make existing rows precise. Source list: `docs/GAP_ANALYSIS.md` §10.

| Requirement | Clarification |
|---|---|
| R1-003, R1-031 | The primary data route is HMRC's "Get customs data" service (CSV, 31-day reports, 4-year history, no API). See R1-054. |
| R1-012, R1-037 | Customs data is always at least 2 days (up to ~5 days) behind, so the forward 30-day test must use the forecast register, never "latest CDS data" alone. The threshold view shows data coverage for its window. |
| R1-011 | Returned Goods Relief needs: original export date, re-import within 3 years of export, "same state" evidence, and the Northern Ireland Union-goods variant. Store these fields and evidence links. |
| R1-011 (linked ETS) | The linked-ETS exemption list stays empty. UK–EU ETS linking talks began Jan 2026 and are not concluded; if an agreement commences, it is added as reference data with its source, never as code. |
| R1-035 | Customs value in a foreign currency is converted with the customs (monthly) exchange rate from the declaration data. This dataset is **separate** from the CBAM Carbon Price Relief rates. |
| R3-005 | CPR conversion uses the rate HMRC publishes for CBAM for the calendar quarter before the tax point. Do **not** use HMRC's monthly customs exchange rates or their API for CPR. Dataset `cbam_cpr_exchange_rates` is loaded only from the CBAM publication. |
| R3-009, R3-012 | Return and payment deadlines (policy summary, 9 Sep 2026): 2027 period → 31 May 2028; Q1 2028 → 31 Jul 2028; Q2 → 29 Sep 2028; Q3 → 30 Nov 2028; Q4 → 28 Feb 2029. The pattern is irregular, so dates come only from `ref_compliance_calendar`; never computed. |
| R3-017, R3-035 | Records are kept for 6 years **after the end of the accounting period the goods are attributed to** (policy summary). This is the retention anchor to confirm against the legislation. |
| R2-031 | Moved earlier to the R1 Live cut (P1): the law is still changing (second tranche of regulations laid 9 Sep 2026; more HMRC guidance promised for autumn 2026). |

## 7. Explicit non-goals

Carried from spec §22, plus:

- No tax calculation or filing in R1. No autonomous approval or auto-filing, ever.
- No hard-coded regulatory values.
- No assumption that Day 28 of the supplier chase makes defaults legal.
- No treatment of SAO as a statutory CBAM role until LEGAL-DEC-005 is closed.
- No invented HMRC API. Filing is an adapter + filing-ready export until TECH-DEC-004 closes.
- No billing, BI, native mobile app or microservices (see `docs/GAP_ANALYSIS.md` §8).

## 8. Success measures

| Release | Measure |
|---|---|
| R1 Pilot | Gates G1–G8 pass (spec §6); a pilot client sees its full posture on one screen; a supplier completes the form on a phone in < 10 min; 10,000-line import passes |
| R1 Live | Every JAN-1 item done; restore rehearsed; registration pack can be generated for any registrable client |
| R2 | Every accepted emissions value is clickable back to its source page/region and rule version; zero unreviewed automated values accepted |
| R3 | Approved fixture returns reproduce exactly; historical replay after a rule change gives the original result; no duplicate filing under retry |

## 9. Regulatory hard dates (legal facts, not a schedule)

| Date | Fact | Source |
|---|---|---|
| 1 Jan 2027 | UK CBAM starts; pre-registration record-keeping required; draft force-of-law notices commence | Spec §3, §26 |
| Calendar 2027 | First accounting period (annual) | Spec §3 |
| By 1 Jan 2028 | HMRC registration service opens (exact date configurable — REG-DEC-001) | Spec §3 |
| 31 Jan 2028 | Transitional registration deadline for 2027 liability | Spec §3 |
| From 2028 | Quarterly accounting periods | Spec §3 |

## 10. Assumptions

- The spec (not legal advice) is the build contract; legal interpretation is the
  domain owner's call.
- CDS data arrives as exports/uploads until DATA-DEC-002 confirms another route.
- Clients are UK businesses; supplier users are anywhere and may use any language.
