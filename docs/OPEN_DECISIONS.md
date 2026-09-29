# Open decisions

Nobody — developer or Claude — may guess the answer to anything on this list.
Build a configuration hook or adapter boundary instead, and keep working.

**How to close one:** write the answer, who decided, the date, and the source
(link or document). Move the row to "Closed". If it changes behaviour, add an ADR
or a reference-data change, and a line in `plans/CHANGELOG.md`.

| Status values | `open` · `waiting-external` (only HMRC/Treasury can answer) · `closed` |
|---|---|

## Open

| ID | Question | Blocks | Owner | Workaround until closed | Status |
|---|---|---|---|---|---|
| REG-DEC-001 | Exact HMRC registration-service opening date (guidance says "by 1 Jan 2028") | R1-013, R1-040 | Domain owner (watch GOV.UK) | Effective-dated config `registration_service.opening_date`; pre-registration mode continues | waiting-external |
| DATA-DEC-002 | How will each client obtain CDS import history? (no public historical API assumed) | R1-003, R1-031, pilot data | Developer + client ops + HMRC software support | Upload of CDS export files; acquisition method recorded per batch | open |
| BUS-DEC-003 | Does our company act as an HMRC-authorised tax agent? Professional liability and insurance? | R3-011 live filing | Business owner + legal | Build filing-ready export; live submission stays disabled | open |
| TECH-DEC-004 | Final HMRC return schema/method; is HMRC's digital calculation facility mandatory? | R3-011, R3-023 | Waiting on HMRC | Adapter interface + filing-ready export; no endpoint called | waiting-external |
| LEGAL-DEC-005 | Is there a statutory CBAM approver role (handbook says SAO)? | R3-010 policy | Tax/legal adviser (written) | Approver role configurable per tenant; SAO not mandatory | open |
| PROD-DEC-006 | Supplier commercial terms: who pays verification, who owns evidence, response SLA, disputes | R1-029, outreach copy | Business owner | Store responsibility state per supplier case; never state commercial terms as HMRC requirements | open |
| REG-DEC-007 | Exact return and payment due-date rules. **Handbook states the 2027 return is due 31 May 2028, then quarterly**; the spec gives no date | R3-012, R3-009, §14 reminders | Domain owner | Confirm from the official source, then load `ref_compliance_calendar`; until then deadlines show "rule pending" | open |
| GOV-DEC-009 | Handbook names **Jenny + ops** as domain owner. Confirm Jenny signs off reference-data activation and legal interpretations, and whether a tax adviser backs her | Reference-data activation (R1-050), rule interpretations, UAT | Project owner | Development proceeds; nothing is *activated* in production without her approval | open |
| OPS-DEC-010 | Hosting region: handbook says Supabase "EU region". Choose London (eu-west-2) or an EU region, and where the API/worker containers run | Pilot deployment, DPA | Project owner | Proposed: Supabase London + containers in a UK region; see `docs/DEPLOYMENT.md` | open |
| TECH-DEC-011 | Confirm ADR-0001 (aligned with the handbook: FastAPI, Celery, Supabase, Resend, Sentry) against the missing tech-spec companion (DOC-DEC-014) | Phase 0 | Developer | Build with ADR-0001; change only by a new ADR | open |
| OPS-DEC-012 | Handbook names **Resend**; confirm it and set the sending domain with SPF/DKIM/DMARC | R1-046, supplier outreach in pilot | Project owner | Local mail catcher from the Supabase CLI; Resend adapter | open |
| REG-DEC-013 | Handbook: "defaults block CPR" (no relief on goods reported with default values). The spec does not state this. Is it law? | R3-004, R2-009 | Domain owner (legal source required) | CPR engine has a rule hook `cpr_allowed_with_default`, loaded as reference data only when a source confirms it | open |
| DOC-DEC-014 | Obtain the handbook's companions `CBAM-Complete-Workflow.docx` and `CSorted-Platform-Technical-Specification.docx` (Parts A3, C3, D, E) | Checking our architecture and data model against the team's | Project owner | `docs/ARCHITECTURE.md` + `docs/DATABASE.md` stand; reconcile when received | open |
| BRAND-DEC-015 | Product/brand name, email sending domain and portal URL | Outreach templates, R1-046, pilot | Project owner | Placeholder `cbam.example`; templates use a `{brand}` variable | open |

## Controlled external inputs (not decisions, but never invent them)

| Input | Where it goes when published |
|---|---|
| Default emissions values + methodology notices | `refdata/default_emissions/`, `refdata/default_methodology/` |
| Quarterly CBAM sector rates | `refdata/cbam_rates/` |
| Qualifying carbon-pricing scheme list (provisional list of 27 Aug 2026 exists) | `refdata/carbon_price_schemes/` |
| HMRC exchange rates | `refdata/exchange_rates/` |
| Carbon Pricing Verification Form fields | R2-009 data model |
| EU CBAM communication/template | R2-010 mapping |
| Two example verifier packages | R2-008 fixtures |
| Masked real CDS export | `backend/tests/fixtures/cds/` |

## Closed

| ID | Answer | Decided by | Date | Source |
|---|---|---|---|---|
| DOC-DEC-008 | Team Handbook PDF added to `docs/spec/` with a text copy | Project owner | 30 Sep 2026 | `docs/spec/CBAM_Team_Handbook.pdf` |
| R3-DEC-001 (v1.1) | Default → actual amendment is prohibited by law; not configurable | Spec v1.2 | 30 Sep 2026 | Finance Act 2026 Sch 17 para 8(2) |
