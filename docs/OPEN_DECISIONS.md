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
| REG-DEC-001 | Exact HMRC registration-service opening date (guidance says "by 1 Jan 2028") | R1-013, R1-040 | Domain owner (watch GOV.UK) | Effective-dated config `registration_service.opening_date`; pre-registration mode continues | waiting-external **Re-check 2 Oct 2026 (search snippets only, not primary text):** no official opening date found; secondary 'Q4 2026' claims are not authority. |
| DATA-DEC-002 | **Narrowed:** the route is HMRC's "Get customs data" service (CSV reports, 31 days each, 4 years back, no API; client grants us third-party access in the service). Still open: confirm each pilot client will grant access, and whether any client also has broker-supplied exports | R1-003, R1-031, R1-054, pilot data | Project owner + client ops | R1-054 importer + coverage tracker; manual upload of other CDS exports | open |
| BUS-DEC-003 | Does our company act as an HMRC-authorised tax agent? Professional liability and insurance? | R3-011 live filing | Business owner + legal | Build filing-ready export; live submission stays disabled | open |
| TECH-DEC-004 | Final HMRC return schema/method; is HMRC's digital calculation facility mandatory? | R3-011, R3-023 | Waiting on HMRC | Adapter interface + filing-ready export; no endpoint called | waiting-external **Re-check 2 Oct 2026 (search snippets only, not primary text):** no CBAM API on the HMRC Developer Hub; the draft force-of-law notice points to a Government Gateway web service for amendments. |
| LEGAL-DEC-005 | Is there a statutory CBAM approver role (handbook says SAO)? | R3-010 policy | Tax/legal adviser (written) | Approver role configurable per tenant; SAO not mandatory | open **Re-check 2 Oct 2026 (search snippets only, not primary text):** no source found creating a CBAM-specific approver/SAO duty. |
| PROD-DEC-006 | Supplier commercial terms: who pays verification, who owns evidence, response SLA, disputes | R1-029, outreach copy | Business owner | Store responsibility state per supplier case; never state commercial terms as HMRC requirements | open |
| REG-DEC-007 | **Narrowed:** HMRC policy summary (9 Sep 2026) gives: 2027 → 31 May 2028; Q1 2028 → 31 Jul 2028; Q2 → 29 Sep 2028; Q3 → 30 Nov 2028; Q4 → 28 Feb 2029 (returns and payments). Still open: the legal provision these come from, and the rule for 2029 onwards | R3-012, R3-009, §14 reminders | Domain owner | Seeded as a `pending` `ref_compliance_calendar` version citing the policy summary; activated only after the domain owner confirms the legal source | open **Re-check 2 Oct 2026 (search snippets only, not primary text):** candidate source is SI 2026/830 (Transitory Provision) Regs 2026 plus a general rule 'last working day of the second month after the period ends'. Q3/Q4 2028 fit the rule; Q1/Q2 2028 (31 Jul, 29 Sep) look like transitional overrides. Stay `pending` until the SI text is read. See GAP_ANALYSIS §11. **3 Oct 2026 primary text:** legal source found: FA 2026 Sch 17 paras 6(3), 7(2) (last working day of second month after period end) and SI 2026/830 (31 May / 31 Jul / 29 Sep 2028). 2029 onwards follows the general rule. Domain owner to confirm and name the working-day calendar. See GAP_ANALYSIS §12. |
| GOV-DEC-009 | Handbook names **Jenny + ops** as domain owner. Confirm Jenny signs off reference-data activation and legal interpretations, and whether a tax adviser backs her | Reference-data activation (R1-050), rule interpretations, UAT | Project owner | Development proceeds; nothing is *activated* in production without her approval | open **Re-check 2 Oct 2026 (search snippets only, not primary text):** primary-source retrieval was blocked from the agent environment; the domain owner (or an allow-listed fetch) must do it. |
| OPS-DEC-010 | Hosting region: handbook says Supabase "EU region". Choose London (eu-west-2) or an EU region, and where the API/worker containers run | Pilot deployment, DPA | Project owner | Proposed: Supabase London + containers in a UK region; see `docs/DEPLOYMENT.md` | open |
| TECH-DEC-011 | Confirm ADR-0001 (aligned with the handbook: FastAPI, Celery, Supabase, Resend, Sentry) against the missing tech-spec companion (DOC-DEC-014) | Phase 0 | Developer | Build with ADR-0001; change only by a new ADR | open |
| OPS-DEC-012 | Handbook names **Resend**; confirm it and set the sending domain with SPF/DKIM/DMARC | R1-046, supplier outreach in pilot | Project owner | Local mail catcher from the Supabase CLI; Resend adapter | open |
| REG-DEC-013 | Handbook: "defaults block CPR" (no relief on goods reported with default values). The spec does not state this, and HMRC's CPR guidance (16 Jul 2026) does not say it either; relief requires a Carbon Pricing Verification Form from a qualifying verifier. Is it law? | R3-004, R2-009 | Domain owner (legal source required) | CPR engine has a rule hook `cpr_allowed_with_default`, loaded as reference data only when a source confirms it | open **Re-check 2 Oct 2026 (search snippets only, not primary text):** secondary commentary asserts defaults preclude CPR; no official text found; check SI 2026/809 relief conditions. Hook unchanged. **3 Oct 2026 primary text:** still no official text found in SI 2026/809 or the CPR guidance; stays open. |
| DOC-DEC-014 | Obtain the handbook's companions `CBAM-Complete-Workflow.docx` and `CSorted-Platform-Technical-Specification.docx` (Parts A3, C3, D, E) | Checking our architecture and data model against the team's | Project owner | `docs/ARCHITECTURE.md` + `docs/DATABASE.md` stand; reconcile when received | open |
| BRAND-DEC-015 | Product/brand name, email sending domain and portal URL | Outreach templates, R1-046, pilot | Project owner | Placeholder `cbam.example`; templates use a `{brand}` variable | open |
| REG-DEC-016 | Does SI 2026/830 set the 31 Jan 2028 registration deadline and the 31 May / 31 Jul / 29 Sep 2028 return and payment dates (give regulation numbers)? Which provision sets the permanent "last working day of the second month" rule, and which working-day calendar applies (England & Wales or UK-wide)? | R1-013, R3-009, R3-012, §14 reminders | Domain owner (legal source required) | Effective-dated `return_due_rule` + working-day calendar as reference data; generated dates stay `pending` until confirmed | open **3 Oct 2026 primary text:** answered from primary text (SI 2026/830 regs 2, 3; Sch 17 paras 2(4), 6, 7); only the working-day calendar and domain-owner sign-off remain. |
| REG-DEC-017 | Is the amendment window 3 years from the end of the accounting period (Sch 17 para 8 or only the draft force-of-law notice)? Is retention counted from the day after period end (SI 2026/802), with repayment-claim records 6 years from the claim date? | R3-013, R3-035 | Domain owner (legal source required) | Reference-data rows with status `draft` until confirmed; draft law never drives decisions | open **3 Oct 2026 primary text:** amendment window is only in the draft notice (Sch 17 para 8(3) delegates it); retention is 6 years from the day after period end (SI 802 reg 6); repayment-claim 6-year anchor is in guidance only. |
| REG-DEC-018 | What is the legal basis and status of the CBAM goods list? HMRC publishes it as guidance (five sector pages, updated 16 Jul 2026); which provision of FA 2026 Sch 17 or regulations defines the scope, and is the list on those pages the whole list (for example, is aluminium waste in 7602 really outside it)? The loaded dataset also stores `Except 7204` within heading 72, which HMRC does not state | R1-007, R1-008, R1-050, R1-012 | Domain owner (legal source required, checks the transcription: handbook "CN code list accuracy") | `cbam_commodity_codes` 2027.1 is loaded `pending` against source `HMRC-CBAM-GOODS-SCOPE` in status `draft`; nothing is activated and the source is not set in force until the domain owner decides | open **3 Oct 2026:** transcribed by script from the GOV.UK content API (54 rows); see `backend/refdata/cbam_commodity_codes/2027.1/manifest.yaml`. |

## Controlled external inputs (not decisions, but never invent them)

| Input | Where it goes when published |
|---|---|
| Default emissions values + methodology notices | `refdata/default_emissions/`, `refdata/default_methodology/` |
| Quarterly CBAM sector rates | `refdata/cbam_rates/` |
| Qualifying carbon-pricing scheme list (provisional list of 27 Aug 2026 exists) | `refdata/carbon_price_schemes/` |
| HMRC **CBAM** exchange rates for CPR (quarterly; not the monthly customs rates) | `refdata/cbam_cpr_exchange_rates/` |
| HMRC monthly customs exchange rates (customs value conversion only) | `refdata/customs_monthly_exchange_rates/` |
| UK–EU ETS linking agreement (if concluded and commenced) | `refdata/linked_ets_jurisdictions/` |
| HMRC autumn 2026 CBAM guidance and October 2026 webinar material | regulatory source registry; re-check before Phase 2 |
| Carbon Pricing Verification Form fields | R2-009 data model |
| EU CBAM communication/template | R2-010 mapping |
| Two example verifier packages | R2-008 fixtures |
| Masked real CDS export | `backend/tests/fixtures/cds/` |

## Closed

| ID | Answer | Decided by | Date | Source |
|---|---|---|---|---|
| DOC-DEC-008 | Team Handbook PDF added to `docs/spec/` with a text copy | Project owner | 30 Sep 2026 | `docs/spec/CBAM_Team_Handbook.pdf` |
| R3-DEC-001 (v1.1) | Default → actual amendment is prohibited by law; not configurable | Spec v1.2 | 30 Sep 2026 | Finance Act 2026 Sch 17 para 8(2) |
