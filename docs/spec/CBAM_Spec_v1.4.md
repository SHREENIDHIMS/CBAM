<!-- Text copy of CBAM_Prioritised_Requirements_and_Build_Specification_v1.4_FINAL.docx, generated for search. The .docx is the source of truth. Do not edit. -->

UK CBAM PLATFORM

Prioritised Product Requirements & Build Specification — Revised Build Contract

Merged from the 29 September 2026 Team Handbook + September 2026 UK regulatory research + v1.1 gap review + v1.2 independent gap closure review + v1.3 final completeness audit

| Critical regulatory correction: The handbook describes HMRC registration as opening in Q4 2026. Current HMRC guidance says the CBAM registration service will open by 1 January 2028. The product therefore needs a pre-registration compliance mode from 1 January 2027: capture imports, threshold events and evidence before the registration service is available. |
|---|

| Important product interpretation: The handbook's Day 7 / 14 / 21 / 28 supplier chase is a product workflow/SLA, not the legal test for whether default emissions must be used. Legal default selection is driven by the emissions-data rules and verification/evidence requirements. Supplier readiness and the sector-aware form must be in place before the first formal request. |
|---|

Document status: Revised development build contract
Version: 1.4
Date: 30 September 2026

# 1. Executive summary

The uploaded Team Handbook is the product-management baseline: it defines the end-to-end journey from UK imports through supplier emissions collection, validation, Carbon Price Relief (CPR), calculation, return approval, filing and evidence retention, and it deliberately separates R1 Data Machine, R2 Validation & Intelligence and R3 Calculation & Filing. (Handbook, pp. 1–6)

This v1.3 revision keeps the handbook's R1 Data Machine / R2 Validation & Intelligence / R3 Calculation & Filing structure but closes the remaining regulatory, sequencing, product and operational gaps found in the v1.1 review. It adds explicit registration-service/deadline logic, a mandatory legal default-emissions amendment lock, production-route and system-boundary data, HMRC notices/assessment/review/appeal case handling, registration lifecycle continuity, special-procedure R3 value rules, exact weight rounding, payment/working-day logic, regulatory-source activation status, supplier contract/evidence responsibility, and a tighter pilot-versus-live prioritisation. Where law is not yet active (for example draft force-of-law notices), the product must retain source status and commencement metadata and must not activate draft rules prematurely.

| Central engineering principle: Law is data, not code. Commodity codes, defaults, rates, validation rules, deadlines, qualifying carbon-price schemes and other regulatory reference data must be versioned, effective-dated, source-linked and changeable without redeploying the application. |
|---|

# 2. Source baseline and what changed

| Area | Handbook baseline | Merged requirement |
|---|---|---|
| Product scope | Customs data → threshold → supplier outreach → validation → CPR → calculation → return → evidence. | Retain the lifecycle and make each stage a separately auditable module. |
| Registration | Q4 2026 portal assumption. (p. 4) | Replace with current HMRC position: registration service opens by 1 Jan 2028; pre-registration record-keeping begins 1 Jan 2027. |
| Threshold | £50k; rolling 12-month + forward 30-day. (pp. 1–2) | Implement legal cadence precisely: forward test can run daily; backward test runs on the first day of each month. Daily recalculation may run operationally as a superset. |
| Special customs procedures | Presented near scope/registration workflow. | Model tax-point lifecycle; do not use a permanent generic exemption flag. |
| Emissions | Handbook uses CO2 language and Scope 1. | Store CO2e; keep emission scope separate from source/provenance. Precursor emissions are upstream direct emissions, not a third scope category. |
| Defaults | Default values used where supplier data is missing. | Implement legal default-selection rules, including cases where defaults are mandatory and the restriction on mixing actual/default data across final goods and precursors. |
| CPR | Evidence + independent verification. | Add scheme-by-scheme CPR calculation, previous-quarter FX, two-year verification-form rule, free-allocation/threshold/compensation treatment and cap at liability. |
| Governance | Human approval / SAO wording. | Keep the handbook approver workflow, but make the statutory approver role configurable until tax advisers confirm the CBAM-specific governance interpretation. |
| Planning | R1/R2/R3 and weekly R1 gates. | Preserve gates and explicitly tag every capability R1/R2/R3; do not pull calculation/filing work forward into R1. |

# 3. Current regulatory baseline (30 Sep 2026)

| Rule / date | Current position used for product design | Product implication |
|---|---|---|
| CBAM start | 1 January 2027 | System must be operational before this date. |
| Initial sectors | Aluminium, cement, fertiliser, hydrogen, iron & steel | Scope engine is commodity-code driven; sector is derived/reference data. |
| Registration threshold | £50,000 | Maintain legal threshold events and the earliest trigger date. |
| Forward test | Expected £50,000 or more in the next 30 days; can be relevant on any day | Daily projection/monitoring workflow. |
| Backward test | £50,000 or more in prior 12 months; checked on the first day of each month | Monthly scheduled legal test; retain the test snapshot. |
| First accounting period | Calendar year 2027 | Quartering/reporting logic must distinguish first year from later quarters. |
| Registration service | HMRC guidance says the registration service will open by 1 January 2028 | Store an exact opening date as configurable/effective-dated regulatory data; do not assume the service cannot open earlier. |
| Registration deadline | Ordinarily 30 days from the day liability to register begins; first CBAM calendar year has a transitional 31 January 2028 deadline | Deadline engine supports 30-day rule and the first-year 31 January 2028 transitional deadline. |
| Emissions | Initial UK scope is direct emissions, including relevant precursor emissions; indirect emissions are effective-dated for future rules. CO2e uses prescribed gas factors; relevant intensity is rounded to 5 decimals. | Schema separates scope (DIRECT/INDIRECT) from source/provenance (OWN_INSTALLATION/PRECURSOR_GOOD) and uses versioned gas/functional-unit/boundary reference data. |
| Actual/default data | Actual data requires verification evidence; defaults apply where actual data is unavailable or cannot be evidenced as verified | Selection logic must be deterministic and audit-able. |
| Records | Six-year retention; net mass in kg; up to six decimal places for relevant weight records | Evidence archive and immutable audit history. |
| CPR | Calculated separately for each qualifying carbon-price scheme and cannot exceed CBAM liability | Dedicated CPR engine and scheme evidence model. |
| Returns | A registered or registrable person must return for each accounting period; first period is annual, later periods are quarterly; amendments are only for correcting errors and are legally restricted for default-emissions replacement. | Return engine supports nil returns, amendment versions, exact working-day deadlines, HMRC method/digital-facility constraints and historical reproducibility. |
| Penalties / assessments | HMRC has penalty and assessment powers | Compliance exception, penalty and interest tracking required. |
| Default-to-actual amendment | Finance Act 2026 Schedule 17 paragraph 8(2) expressly prohibits an amendment that replaces default-emissions information with actual-emissions information | Treat this as a mandatory legal lock, not a configurable business decision. |

Regulatory research basis: HMRC/GOV.UK policy summary and guidance, Finance Act 2026, the Carbon Border Adjustment Mechanism (Emissions and Verification) Regulations 2026 (SI 2026/995), the other CBAM secondary instruments, the HMRC force-of-law notices and System Boundaries Document, and current HMRC/legislation material checked on 30 September 2026. Important source-status rule: HMRC says the force-of-law notices published on GOV.UK are draft and do not have force of law until commenced on 1 January 2027; the system must store source status/commencement and must not load a draft notice as active regulatory data.

# 4. Product and architecture principles

- Compliance first: every user-facing result must be reproducible from source evidence, regulatory reference data and a deterministic calculation trail.

- Law is data, not code: all regulatory reference tables are versioned and effective-dated.

- Tax point first: the system determines when the legal CBAM tax point occurs before deciding reporting period or threshold contribution.

- Source → normalised → derived: do not overwrite source facts with calculated values.

- Human review is explicit: extraction and rules can flag; authorised users approve or reject. No silent auto-file.

- Multi-client by design: all business records are tenant-scoped; supplier data can be shared only where explicitly authorised.

- British English in user-facing UI, dates such as 14 March 2027, and GBP formatting consistent with the handbook. Tax-point quarter and non-preferential origin must be explicit in reporting data.

- Configuration over constants: thresholds, rates, defaults, validation tolerances, reminder schedules and qualifying schemes live in reference/configuration data.

- Keep R1 narrow: the first release proves the data machine; R2 proves evidence/validation; R3 proves calculation and filing.

# 5. R1 — Data Machine (target: 1 Dec 2026)

R1 is the operational foundation. It should ingest import data, establish scope, monitor thresholds, maintain client/supplier/installations, start outreach, capture documents and provide the operational dashboard. It should not calculate the final CBAM tax or build the final filing engine.

| ID | Requirement | Release / Priority | What the system must do | Acceptance / evidence |
|---|---|---|---|---|
| R1-001 | Organisation / tenant setup | R1 / P0 | Create isolated client/organisation records, including business type, business address, business/contact details, GB/XI EORI context, VAT status and user memberships. Track whether the organisation is the liable person or acting only as an agent. | A test tenant cannot read another tenant's imports, suppliers, documents, tasks or audit events. |
| R1-002 | Role and permission model | R1 / P0 | Implement platform admin, operations user, client admin, reviewer, approver, supplier user and tax-agent-capable roles as configurable permissions. Tax-agent permissions may allow return preparation/submission when authorised, but must not allow the tax agent to register the liable person and must not transfer CBAM liability to the agent. | Permission matrix tests show least-privilege access; a tax agent cannot perform liable-person registration and is never shown as the liable person solely because the agent submits. |
| R1-003 | CDS import pipeline | R1 / P0 | Import a real/sample CDS export, preserve source rows, validate schema, reject malformed rows with actionable errors and make re-import idempotent. The ingestion boundary must support a future HMRC/CDS feed but must not assume a public historical API exists. | Same source file can be replayed without duplicate business records. |
| R1-004 | Manual import entry | R1 / P1 | Allow authorised users to create or correct an import when no CDS feed is available, with reason and audit event. | Manual entry has the same downstream fields and validations as imported data. |
| R1-005 | Import line ledger | R1 / P0 | Store declaration, line, tax point, tax-point quarter, commodity code, description, quantity/weight, customs value, non-preferential origin, importer/declarant relationships and source reference. Preserve the exact commodity code in force at the tax point. | Each in-scope line can be traced back to the exact source row/document. |
| R1-006 | Importer vs declarant | R1 / P0 | Represent importer, declarant, customs agent/broker and acting-on-behalf-of relationships separately. | Test case with freight forwarder as declarant retains importer as liable person where applicable. |
| R1-007 | Commodity-code scope engine | R1 / P0 | Classify every import line against versioned UK CBAM commodity-code data with effective dates and exclusions. | Scope result includes rule version and source; code changes do not require deployment. |
| R1-008 | Tax-point skeleton | R1 / P0 | Implement the tax-point state and a procedure-aware lifecycle. For normal imports, use the statutory tax-point rule (normally when the good becomes subject to import duty or would be, and where it is not subject to import duty, when it enters the UK); special procedures must resolve using their specific trigger rules. R1 must identify unresolved cases, avoid premature return-period assignment, and create a manual-review flag for threshold treatment where value rules are not yet implemented. | A line cannot be assigned to a return period solely from declaration date if the tax point is unresolved. |
| R1-009 | Geography handling | R1 / P0 | Store GB/XI EORI context and UK geographic/customs movement facts for Northern Ireland, Crown Dependencies, Overseas Territories and UK Continental Shelf movements. Apply geographic treatment through effective-dated regulatory data. | Geographic cases are visible in the import ledger and rules can act on them. |
| R1-010 | Customs-value basis | R1 / P1 | Capture customs value using the same valuation basis used for customs duty and preserve the source/override reason. | System records how customs value was derived and blocks unauthorised overwrite. |
| R1-011 | Exemption / exclusion assessment | R1 / P0 | Implement scope exclusions/exemptions as rule outcomes and capture supporting evidence. Cover private/non-business use, UK non-preferential origin, Returned Goods Relief (including Northern Ireland return conditions where applicable), and temporary admission with full relief. Model temporary admission partial/no relief and loss of full relief as tax-point events, not permanent exemptions; keep any linked-ETS jurisdiction list empty by default. | Each excluded line displays the reason, rule version and evidence requirement; returned-goods, UK-origin and temporary-admission cases preserve the evidence relied upon. |
| R1-012 | Threshold engine | R1 / P0 | Maintain £50k threshold snapshots/events with a daily forward 30-day operational check and a legally timed backward check on the first day of each month. Write down and automate the five handbook QA scenarios in Week 1: forward-only trigger, backward-only trigger, both-tests-earliest-date, below-threshold, and special-customs manual-review. Add weight/value and special-procedure variants. Preserve the earliest liability date and test type. | Hand-calculated scenarios from handbook pass; event shows earliest trigger date and test type. |
| R1-013 | Pre-registration compliance mode | R1 / P0 | From 1 Jan 2027, retain liable imports, threshold evidence, supplier/emissions evidence and the registration trigger date. Maintain the first-year registration deadline of 31 Jan 2028, ordinary 30-day deadline logic for other cases, a configurable service-opening date, and a non-digital registration path flag for users who meet HMRC exceptions. | A client can generate a registration-ready pack before service opening; system shows the exact deadline basis and never assumes an unannounced service date. |
| R1-014 | Registration readiness record | R1 / JAN-1 | Prepare the registration data pack: name/contact details, business address and business type, GB/XI EORI and VAT details, trigger date, estimated next-12-month weight for each CBAM sector, evidence of how each estimate was calculated, and the required completeness/correctness declaration. Keep the pack versioned and exportable. | Registration readiness record contains all required fields, declaration state, trigger date, deadline basis, sector estimates and the evidence/method used to derive those estimates. |
| R1-015 | Supplier master | R1 / P0 | Create suppliers, installations, contacts, country, product relationships, preferred language, monitoring readiness and verifier status. | One supplier can have multiple installations and products; data is not flattened. |
| R1-016 | Supplier readiness questionnaire | R1 / PILOT-P1 | Capture supplier readiness before formal emissions collection: monitoring status, verifier appointed, expected data year, preferred language, EU CBAM data availability, contractual evidence owner, and whether the installation can provide sector-specific data. Readiness must be visible before the request is sent. | Readiness status is visible before the first formal emissions request. |
| R1-017 | Supplier secure portal | R1 / P0 | Issue expiring, tenant-scoped magic links. The supplier flow must render a sector-aware form definition from reference data, including applicable gases, functional unit, production route/method and key questions (for example clinker basis for cement and nitrogen basis for fertiliser), plus document upload on mobile. The first supplier form must be completable on a phone in under 10 minutes for the handbook pilot test. | Unauthorised user cannot access a supplier case; link expiry and single-case scope are tested; a representative factory manager can complete the minimum form in under 10 minutes on a phone. |
| R1-018 | Supplier outreach engine | R1 / P0 | Generate multilingual outreach/reminders using a configurable Day 0 / 7 / 14 / 21 / 28 product SLA. The SLA is not itself the legal default-selection rule. All sends, failures and escalations are auditable. | A supplier case automatically moves through the schedule; each send is auditable. |
| R1-019 | Document intake | R1 / P0 | Upload/store PDFs, Excel and images against supplier/installation/import/case; retain versions and original file. | Every upload has immutable source metadata and is retrievable from the case. |
| R1-020 | Human review queue shell | R1 / JAN-1 | Provide the review-queue shell for missing data, supplier exceptions, special-procedure threshold lines and manual classifications. This is a January-live requirement unless a pilot blocker forces earlier delivery. | Operations can assign, resolve and reopen a queue item with reason. |
| R1-021 | Operations dashboard | R1 / P0 | Show imports, scope status, threshold status, outreach status, missing documents, upcoming deadlines and unresolved items per client. | A new pilot client can see its current compliance posture on one screen. |
| R1-022 | Task / deadline engine | R1 / P0 | Create tasks for threshold triggers, supplier follow-ups, registration readiness and missing evidence. | Tasks have due date, owner, status and escalation history. |
| R1-023 | Audit trail | R1 / P0 | Append-only audit events for every business state change with actor, timestamp, before/after and reason where applicable. | Update/delete tests confirm the business audit history cannot be silently rewritten. |
| R1-024 | Export / evidence index | R1 / JAN-1 | Export import register, supplier status, registration-readiness data and evidence inventory for client review, including source identifiers, regulatory versions and generated-at timestamp. | CSV/PDF export includes source identifiers and generated-at timestamp. |
| R1-025 | Data quality validation | R1 / P0 | Detect missing/invalid commodity code, weight, tax point, origin, value and supplier mapping before records enter downstream workflows. | Bad rows appear in an actionable exception report; valid rows continue. |
| R1-026 | Observability / resilience baseline | R1 / JAN-1 | Add the resilience baseline needed for January live operation: structured logs, metrics, idempotent/retryable jobs, backup/restore procedure, health checks and failure visibility. Pilot may use a lighter implementation but the controls must be present before 1 Jan live. | A failed import/job is visible, retryable and cannot silently disappear. |
| R1-027 | Special-procedure threshold review | R1 / PILOT-P0 | For storage/free zones, inward processing, outward processing, authorised use/Union end-use and other relevant special customs procedure lifecycles, capture the data needed to determine the tax point and value counted toward the threshold. Where an exported good is processed and re-enters, track whether the re-imported product is CBAM or non-CBAM and the applicable value/charge treatment. Until full R3 value rules exist, flag affected lines for manual review. | Test set covers storage/free zones, inward processing, outward processing, authorised use/Union end-use, export-before-tax-point, and partial/full temporary-admission outcomes; each flagged line shows procedure, tax-point state and value-basis reason. |
| R1-028 | Sector-aware supplier form definition | R1 / PILOT-P0 | Create the reference-driven form schema required before supplier outreach: sector, commodity-code applicability, gases, functional unit, monitoring period, product/production-method questions and evidence slots. R2 then implements deeper validation/extraction against the same definition. | A cement, fertiliser, aluminium, hydrogen and iron/steel sample supplier each receives an appropriate question set without collecting incompatible generic data. |
| R1-029 | Supplier contract / evidence responsibility | R1 / P1 | Store whether the supplier agreement assigns responsibility for monitoring, verification cost, evidence ownership, response deadlines and dispute escalation. Surface the assigned responsibility in outreach and review workflows; do not invent legal contract terms. | A supplier case identifies the current evidence owner and contractual responsibility state, with versioned change history. |
| R1-030 | Registration information change control | R1 / JAN-1 | Track material registration-profile changes (including business type, address, EORI/VAT and liable-person information) and create an HMRC notification task when registered information changes or becomes incorrect. Support the statutory window, evidence, acknowledgement and audit trail. | A changed EORI/contact/address/business-type fixture creates a dated notification task with the correct due-date rule and cannot be silently ignored. |
| R1-031 | CDS data acquisition workbench | R1 / P1 | Provide an operational path for CDS data from real exports, approved data-request routes or manual upload without assuming a public historical API. Preserve the acquisition method, source owner and date. | An import dataset can be loaded from a real/sample CDS export and its acquisition provenance is visible on the import batch. |
| R1-032 | Origin determination and evidence | R1 / P0 | Validate/capture the CBAM good’s country of origin using the applicable UK non-preferential customs origin basis. Link origin evidence and distinguish declared origin from validated origin. UK-origin goods must be routed to the applicable exemption outcome only when the required evidence supports it; complex-good/re-import origin evidence must be retained. | Origin conflicts or missing evidence create an exception; a UK-origin result cannot be silently accepted without the required evidence and rule version. |
| R1-033 | Registration account / status record | R1 / P1 | Maintain the post-registration record separately from readiness: registration application/submission status, HMRC registration identifier when issued, registration date, liable-person details, service route and status history. | A client can move from monitor → registrable → registration-ready → submitted/registered without overwriting prior states; status history is auditable. |
| R1-034 | Customs declaration amendment / reconciliation | R1 / P1 | Accept corrected/replaced customs declaration files or manual corrections after import. Preserve the original declaration state, link the amendment/replacement, re-run affected scope/tax-point/value/threshold classifications, and create an impact task when an approved downstream result changes. Never overwrite the original customs evidence. | A declaration amendment produces a versioned comparison, affected records are re-evaluated, and the original source remains immutable and auditable. |
| R1-035 | Import monetary precision / currency provenance | R1 / P1 | Store the customs value exactly as sourced, including source currency where applicable, conversion metadata and the GBP amount used for CBAM threshold/value logic. Keep source and derived monetary values separately and decimal-safe. | A non-GBP source-value fixture preserves original amount/currency and the exact GBP value/method used in threshold decisions. |

## 6. R1 acceptance gates

| Gate | Release acceptance |
|---|---|
| G1 – Readiness | Team can explain CBAM basics, current regulatory baseline and the product boundary; no unresolved blocker is hidden. |
| G2 – Import | A real CDS sample imports successfully; 10,000-record load test is completed as required by the handbook. |
| G3 – Scope | All pilot imports produce deterministic in/out-of-scope results with versioned commodity-code evidence. |
| G4 – Threshold | Five hand-calculated threshold scenarios pass; forward and backward tests use correct legal cadence. |
| G5 – Supplier | A supplier can complete the mobile flow; Day 7/14/21/28 orchestration is observable and auditable. |
| G6 – Documents | Supplier documents are stored, versioned and linked to the case; users can retrieve the originals. |
| G7 – Operations | A pilot client can see import, threshold, supplier and document status on the dashboard. |
| G8 – Hardening | Backup/restore, security checks, tenant isolation, UAT and pilot onboarding evidence are complete. |

# 7. R2 — Validation & Intelligence (target: 28 Feb 2027)

R2 turns collected supplier and document data into validated evidence. It should not silently calculate a final tax amount. The output of R2 is a set of trusted, approved inputs and explainable exceptions that R3 can consume.

| ID | Requirement | Release / Priority | What the system must do | Acceptance / evidence |
|---|---|---|---|---|
| R2-001 | Document extraction | R2 / P0 | Extract structured fields from PDF/Excel/image evidence with OCR fallback and preserve page/table coordinates where possible. | Each extracted value points to document + page/region; low-confidence or ambiguous results are reviewable. |
| R2-002 | Emissions data model | R2 / P0 | Store CO2e, gas components, monitoring period, production method, production route/process, product, installation, functional unit, unit, source/provenance, calculation basis and verification status. The reference layer determines gases, units, routes and system boundaries for each commodity/product. | CO2, N2O, CF4 and C2F6 components can be represented and converted using versioned regulatory factors; production route/process and system-boundary IDs are retained. |
| R2-003 | Scope/source separation | R2 / P0 | Separate emission scope (DIRECT/INDIRECT) from source/provenance (OWN_INSTALLATION/PRECURSOR_GOOD). | Precursor emissions are represented as upstream direct emissions, not as a third scope category. |
| R2-004 | GHG conversion | R2 / P0 | Read and validate the installation/verifier-reported gas components and calculate a platform-side CO2e recomputation for plausibility and arithmetic checks. Apply prescribed gas factors and 5-decimal emissions-intensity rounding where the regulation requires it. The legally reportable emissions-intensity figure remains the installation’s verified result (step 8), not a platform-generated substitute. | Known mixed-gas fixture reproduces CO2e arithmetic; intensity rounding is exactly 5 decimal places; any discrepancy with the verified result becomes a review exception. |
| R2-005 | Actual/default selection | R2 / P0 | Select actual or default emissions using the legal evidence rules. If actual data is unavailable or cannot be evidenced as satisfactorily verified, route to the applicable default. Store the reason, source rule and effective date. | Cases with missing or unverifiable actuals deterministically route to default. |
| R2-006 | Precursor compatibility rules | R2 / P0 | Enforce final-good/precursor actual/default compatibility rules and their legal direction. Allow default precursor data with actual final-good data where permitted; block actual precursor data when the final CBAM good uses a default value. Preserve the source rule for each component. | Invalid actual/default combinations are blocked with a rule reference. |
| R2-007 | Monitoring-data year selection | R2 / P0 | Implement Option 1 import-linked and Option 2 production-linked selection rules, including the 2027 transitional 2027/2026 choice under Option 1 and the production-year path. Store the selected monitoring period and legal option. | 2027 fixtures select the correct 2027/2026 or production-year data according to configured option. |
| R2-008 | Verifier validation | R2 / P0 | Capture verifier independence from the installation and qualifying carbon-pricing bodies, accreditation-body eligibility, sector scope, standards, materiality, physical site-visit evidence, verification date/conclusion and the verifier’s independent-reviewer evidence. Capture unresolved data gaps/misstatements and whether material issues remain. Capture accreditation-body eligibility, including any active requirement for accreditation through a Global ACI full-member body, from versioned verification reference data; do not hard-code the membership rule if the legal source changes. | A verifier package cannot pass when mandatory accreditation/scope/site-visit/independent-reviewer evidence or required conclusion data is absent; unresolved material issues block acceptance. |
| R2-009 | CPR evidence tracker | R2 / P0 | Track a Carbon Pricing Verification Form for each CBAM good claiming relief, the qualifying carbon-price year, scheme, installation, scheme elements, free allowances, thresholds, graduated pricing, removals, compensation and verifier evidence. Support separate relief calculations for separate qualifying schemes, including precursor-related schemes, and capture the factor source where indirect pricing requires an IPCC/IEA/UNFCCC-based emissions factor. Enforce the evidence-period rule that the Carbon Pricing Verification Form covers one of the two calendar years before the import year, using the active reference-data rule. Preserve the effective-price inputs and source evidence for each scheme. | Each relief claim has its own verification form/evidence chain, qualifying year and scheme; no form can be reused across unrelated goods without an explicit mapping rule. |
| R2-010 | EU CBAM evidence reuse | R2 / P1 | Allow controlled import/reuse of EU CBAM data/evidence, followed by UK-rule validation. | EU-origin evidence can be mapped into UK fields without being accepted as UK-valid automatically. |
| R2-011 | Plausibility rules | R2 / P0 | Validate units, product/method consistency, monitoring year, plausible ranges, missing fields and cross-document conflicts. | Rules yield PASS/WARNING/ERROR/HUMAN_REVIEW with source rule version. |
| R2-012 | Human evidence review | R2 / P0 | Provide review screen showing extracted value, source document, rule failures and approval/rejection action. | Reviewer can approve, reject or request correction; action is immutable in audit history. |
| R2-013 | Evidence lineage | R2 / P0 | Persist source-document lineage for each accepted field and every derived intermediate value. | Clicking an emissions value shows its source and validation history. |
| R2-014 | Supplier readiness dashboard | R2 / P1 | Track monitoring status, verifier appointment, expected data year, data received and defects per installation. | Operations can identify suppliers that will force default use before the return is due. |
| R2-015 | Regulatory reference data admin | R2 / P0 | Provide controlled admin screens/imports for defaults, validation rules, qualifying schemes and verifier rules with effective dates and sources. | Every active value has version, source, effective date and change audit event. |
| R2-016 | Compliance dashboard | R2 / P1 | Expose evidence completeness, default exposure, verification status, CPR readiness and open exceptions. | Dashboard reconciles to underlying cases and does not recalculate independently. |
| R2-017 | Verification report vs good-specific verification summary | R2 / P0 | Represent the two evidence forms distinctly and link each to installation, monitoring period, product and verifier. Do not collapse them to one generic “verification report” type. | A record identifies exactly which evidence type was supplied and why it satisfies the applicable rule. |
| R2-018 | Functional-unit and gas applicability validation | R2 / P0 | Validate that the supplier data uses the functional unit and gases prescribed for the commodity code/product, including cement/clinker and fertiliser/nitrogen handling and relevant PFC/N2O cases. | A wrong-unit or wrong-gas submission is blocked or sent to human review with a rule reference. |
| R2-019 | Verified-result boundary | R2 / P0 | Treat the verifier-approved installation result as the authoritative reportable intensity; platform arithmetic is only a plausibility/reconciliation control. | A discrepancy creates a review exception and never silently overwrites the verified result. |
| R2-020 | Regulatory source registry / activation gate | R2 / P0 | Maintain a registry of legislation, regulations, notices, system-boundary documents and official guidance with publication date, status (draft/laid/in-force/commenced/superseded), commencement date, effective period, retrieval timestamp, source URL and supersession links. Only active rules may drive production decisions. | A draft force-of-law notice remains non-active until its commencement condition is met; the active rule set for a calculation shows the source status and version. |
| R2-021 | Production route / process / boundary validation | R2 / P0 | Validate the production route and production process against the System Boundaries reference for the good and ensure the relevant precursor set and emissions boundary are selected before accepting actual data. | A supplier route that does not match the configured system boundary is blocked or routed to human review with the relevant source/version. |
| R2-022 | Data-gap and verification-package acceptance | R2 / P0 | Represent data gaps, measurement exceptions, estimates/standard factors and verifier conclusions as explicit states. Distinguish verification report, good-specific verification summary, Carbon Pricing Verification Form and other evidence. | A case with missing mandatory evidence cannot become “verified”; the reviewer can see the gap treatment and supporting rule. |
| R2-023 | CPR scheme/commodity evidence mapping | R2 / P1 | Map each relief claim to the exact CBAM good, installation, carbon-pricing scheme and qualifying emissions period. Record multiple schemes/currencies independently before aggregation/cap. | A multi-scheme fixture creates separate auditable relief components and uses the correct prior-quarter FX per currency. |
| R2-024 | Precursor attribution, aggregation and production allocation | R2 / P0 | Implement the regulatory treatment for precursor emissions where a complex good uses one or more precursor goods. Support precursor monitoring-period selection, multiple installations and periods, prescribed weighted averaging, isolation of relevant quantities, joint production processes and multifunctional production processes. Preserve the mass, emissions-intensity/default, allocation/weighting method and source for each precursor contribution. Include UK-origin treatment for relevant precursor contributions and keep any exemption/adjustment state tied to non-preferential-origin evidence and the applicable system-boundary rule. | A complex-good fixture with multiple precursor installations/periods reconciles to the prescribed weighted result; joint/multifunctional cases route to the correct reference rule and every contribution is traceable. |
| R2-025 | Verification team / independent reviewer evidence | R2 / P1 | Where supplied by the verifier package, retain lead-auditor/verification-team information and independent-reviewer identity, role and conclusion so the importer can demonstrate the verification process was completed by the qualifying body. | Reviewer identity/conclusion is linked to the verification record; missing required evidence is surfaced rather than inferred. |
| R2-026 | Emission evidence revision / correction workflow | R2 / P0 | Support supplier/verifier resubmission of corrected emissions data or evidence without deleting the prior submission. Preserve superseded documents, prior extracted values, reviewer decisions, reason for change and the rule/version that caused re-review. Re-open downstream approvals when an input changes. | A corrected supplier report creates a new version, preserves the old package, re-runs affected validations and blocks stale approval from remaining effective. |
| R2-027 | Coverage and completeness of monitoring data | R2 / P0 | Check that the submitted emissions package covers the required installation, product/good, monitoring period, production route and relevant precursor boundary. Identify missing periods/quantities, partial coverage and unsupported extrapolation before a verified result is accepted. | A partial-period fixture is rejected or sent to human review with the exact missing coverage and applicable rule/version. |

# 8. R3 — Calculation & Filing (target: 30 Sep 2027)

R3 consumes trusted R2 inputs and performs deterministic liability calculation, CPR, return preparation, approval, filing/payment tracking and evidence-pack generation.

| ID | Requirement | Release / Priority | What the system must do | Acceptance / evidence |
|---|---|---|---|---|
| R3-001 | CBAM rate reference | R3 / P0 | Store quarterly sectoral CBAM rates as versioned reference data with publication/source metadata. | A historical import always uses the rate applicable to its tax point/sector under the active rules. |
| R3-002 | Embedded-emissions calculator | R3 / P0 | Calculate embodied emissions from applicable weight, emissions intensity and precursor components. | Calculation output exactly reproduces approved fixture results and shows each operand. |
| R3-003 | Weight and rounding | R3 / P0 | Apply legal weight measurement/evidence rules. Store source net mass in kg with up to 6 decimal places where needed; for reporting/calculation apply the prescribed rounding thresholds, including the fractional-kg rules, only at the legally mandated step. Retain source evidence and whether the figure was HMRC-determined/estimated. | Fixtures cover <1kg, >1kg with fractional .001-.499 and .500-.999, exact integers, source overrides and HMRC-determined/estimated weight; importer responsibility remains explicit. |
| R3-004 | CPR calculation engine | R3 / P0 | Calculate CPR per qualifying carbon-price scheme, applying free allowances/thresholds and unpriced emissions or removals as required, then scheme-level pricing and compensation treatment in the prescribed order. Support precursor-related schemes separately. Use the effective carbon price for the qualifying emissions year, then apply scheme-specific compensation in the prescribed stage after the effective-price calculation; all component values must remain traceable to the same scheme/evidence package. | Each scheme produces an independently traceable relief result and the order of operations is visible in the calculation trace. |
| R3-005 | FX calculation | R3 / P0 | Apply the HMRC exchange rate for the calendar quarter before the CBAM good’s tax point for each non-GBP carbon-price amount and round the converted relief down to two decimal places. | Multi-currency fixture uses the correct prior-quarter rate per scheme and produces the exact mandated round-down. |
| R3-006 | CPR cap / no unconverted relief | R3 / P0 | Prevent CPR exceeding CBAM liability and reject relief that lacks required currency conversion/evidence. | System blocks over-relief and records the reason. |
| R3-007 | Net liability | R3 / P0 | Calculate gross liability less eligible CPR using only approved R2 inputs and active regulatory reference data. | Every pound of liability is traceable to import, emissions, rate and relief inputs. |
| R3-008 | Return line builder | R3 / P0 | Create return lines at required consignment/goods granularity with 8-digit commodity code in force at tax point, tax point, first-period tax-point quarter where applicable, net weight in kg, emissions intensity/default in tCO2e per functional unit, non-preferential origin, and carbon price/CPR in GBP. Do not aggregate separate consignments merely because the goods share a code. | Return preview reconciles to import ledger and calculation totals. |
| R3-009 | Nil returns | R3 / P0 | Support nil returns where required and maintain reminder tasks. | A nil return can be drafted, approved and tracked without being treated as “no return needed”. |
| R3-010 | Approval workflow | R3 / P0 | Implement configurable client approval workflow; the handbook names SAO, but the statutory CBAM approver role remains configurable until legally confirmed. | Approval requires an authorised user, timestamp and immutable audit event; the approver role can be changed by controlled configuration. |
| R3-011 | HMRC submission adapter | R3 / P0 | Integrate with the confirmed HMRC digital submission mechanism once its interface/specification is available. Support the possibility that HMRC requires use of an HMRC digital facility to calculate the return amount. Until the final interface is confirmed, provide filing-ready payload/export without inventing an API. Store receipt/acknowledgement/rejection references. | Adapter is versioned; submission status transitions are auditable; no unsupported endpoint is called; a confirmed HMRC method or digital-calculation requirement can be activated through configuration. |
| R3-012 | Payment tracking | R3 / P1 | Track payment amount, date, method, reference, status and reconciliation for supported HMRC methods. Compute due dates using the legally applicable last-working-day rule and support payments arising from returns, amendments and HMRC assessments. | Payment ledger reconciles to approved liability and an authoritative working-day calendar; payment methods are configurable and sourced from HMRC notices/guidance. |
| R3-013 | Amendments | R3 / P0 | Create versioned amendments only for correction of an error within the statutory amendment window, preserving the original return and reason. Enforce the Finance Act 2026 rule that an amendment must not replace default-emissions information with actual-emissions information. | Original cannot be overwritten; a default-emissions line is hard-blocked from being amended to actual emissions; the legal rule/version is shown to the reviewer. |
| R3-014 | Default-emissions amendment lock | R3 / P0 | Implement the Finance Act 2026 Schedule 17 paragraph 8(2) prohibition as a mandatory legal rule: a return amendment cannot replace emissions embodied determined using default values with emissions determined under the actual-emissions regulations. The rule is source-versioned, but not user-configurable. | Unit test proves the blocked transition; no tenant or admin setting can switch the legal lock off. |
| R3-015 | Repayment claims | R3 / P1 | Support repayment requests for overpayments caused by return errors, the three-year claim window, unjust-enrichment restrictions and reimbursement arrangements. Store claim reason, error-discovery date, accounting period, affected goods/return, original payment date and HMRC decision. Where reimbursement is made/planned, retain each person’s name/address, amount, interest amount and reimbursement date, with the applicable six-year retention rule. Respect the claim method and supporting information specified by the active HMRC repayment notice/form. | Claim cannot proceed without eligibility/evidence; reimbursement records contain the required person, amount, interest and date fields and are retained under the correct retention anchor. |
| R3-016 | Penalty and interest ledger | R3 / P1 | Track penalty and interest events including failure to notify liability or registration changes, failure to return/pay, the £500 record-keeping penalty, the £500 fixed notification penalty and applicable daily penalty (£40 where prescribed), information-notice failures, return/document errors, tax-avoidance disclosure/serial-avoidance events, assessments, reasonable-excuse state, double-jeopardy checks and late-payment interest. Do not hard-code changing rates or statutory amounts; load them as effective-dated legal reference data. | Penalty fixtures include the £500 record-keeping case and applicable £500 + daily notification-penalty case; every event has type, statutory basis, notice date, amount, due date, interest method, payment/review/appeal state and evidence. |
| R3-017 | Evidence pack | R3 / P0 | Generate a six-year auditable evidence pack containing source docs, calculations, approvals, filings and reference-data versions. Retention must be anchored to the legally applicable retention start date and support legal hold before destruction. | One click produces a deterministic pack; retention metadata records the anchor date, due date and any active legal hold. |
| R3-018 | Historical reproducibility | R3 / P0 | Recalculate/view a historical result using the exact regulatory versions and approved source inputs that were used at the time. | Changing today's rules does not alter a previously approved return result. |
| R3-019 | HMRC notices, assessments, reviews and appeals | R3 / P0 | Create a compliance case layer for HMRC information notices, requests for records/preservation directions, best-judgment/default and supplementary assessments, compulsory-registration actions, penalty notices, review requests and appeals. Track notice date, response/payment date, amount, legal basis, evidence, review/appeal outcome and any payment/deposit/hardship condition. Separate case management from any criminal-law determination. | A simulated HMRC assessment can be linked to a return/import, assigned a response deadline, reviewed/appealed and closed with an immutable outcome history. |
| R3-020 | Registration lifecycle, succession, insolvency and deregistration | R3 / P0 | Handle changes/incorrect registration data, voluntary/mandatory deregistration, death/incapacity successor handling, insolvency office-holder continuity, final-return obligations and historical retention. For death/incapacity, capture the 21-day notification, authority evidence and six-month successor treatment (including extension state where applicable). For insolvency, distinguish liabilities arising before and after the insolvency procedure and the office-holder’s controlled role. | Fixtures cover ordinary change notification, 21-day successor notification with six-month continuity state, insolvency handover with pre/post liability treatment, deregistration with outstanding returns and final close-out without deleting history. |
| R3-021 | Special-procedure final value / liability rules | R3 / P0 | Complete the calculation/tax-point/value rules for storage/free zones, inward processing, authorised use/Union end-use and outward processing. Model: (a) CBAM good processed to non-CBAM good—chargeable portion of original good; (b) CBAM good processed to another CBAM good—new processed CBAM good; (c) non-CBAM processed into CBAM—new CBAM good; (d) outward processing re-imported as CBAM—new CBAM good and only the legally specified value difference contributes to threshold where applicable; (e) outward processing re-imported as non-CBAM—no CBAM liability; and (f) export before tax point—no liability/no threshold contribution. Include UK-origin/carbon-price treatment where legally applicable. For Northern Ireland / EU movement variants, preserve the applicable customs route, origin and re-import facts so the active tax-point and carbon-price treatment can be selected from effective-dated rules. | At least five special-procedure fixtures reproduce the legal value/tax-point outcomes and every operand is traceable. |
| R3-022 | Working-day calendar and payment channels | R3 / P0 | Use an effective-dated working-day calendar based on the statutory definition: the relevant day is not a Saturday, Sunday or bank holiday in any part of the United Kingdom, where that definition applies. Maintain the HMRC-authorised payment-channel catalogue from current notices/guidance. | Calendar tests cover month ends/weekends/holidays; payment records reject unsupported methods and reconcile to the correct due date. |
| R3-023 | Submission response / HMRC calculation-facility compatibility | R3 / P1 | Persist HMRC submission receipt, acknowledgement, rejection/error payload, retry state and the calculation/return method used, including HMRC-provided digital calculation facility requirements when applicable. | A submission simulation preserves full request/response lineage and can be replayed without duplicating the filing. |
| R3-024 | Artificial-separation risk controls | R3 / P1 | Maintain connected-business/related-entity relationships and a review workflow for potential artificial separation intended to avoid the registration threshold or liability. Keep evidence and human decision notes. | A connected-entity scenario raises a review case and records the resolution without automatically asserting an offence. |
| R3-025 | Final closure / deregistration reconciliation | R3 / P1 | Before client/account closure, reconcile all imports, returns, payments, repayments, penalties, assessments, evidence-retention obligations and open HMRC cases. Block destructive deletion where statutory retention or legal hold applies. | Closure checklist cannot complete while required returns/cases/evidence are unresolved. |
| R3-026 | Registrable-person return/payment obligation | R3 / P0 | Enforce the rule that once a person is registrable, they must account for CBAM, submit the required return for each accounting period and pay tax due until they meet deregistration conditions. The workflow must not treat “not yet registered” as “no return obligation” where the law makes the person registrable. | A fixture where the person becomes registrable before formal service registration creates the correct accounting-period obligations and does not lose the affected imports. |
| R3-027 | Tax-avoidance disclosure and deliberate-misstatement incident controls | R3 / P1 | Provide configurable compliance-case types for relevant tax-avoidance disclosure/serial-avoidance matters and deliberate-misstatement/fraudulent-evasion concerns. The system records facts, notices, evidence and escalation; it must not automatically conclude that an offence has occurred. | A test event creates the correct compliance case, preserves evidence and routes it to authorised human/legal review without asserting criminal liability. |
| R3-028 | HMRC record-preservation / information-response workflow | R3 / P1 | Track HMRC directions/notices requiring production or preservation of CBAM records, including response date, requested records, delivery status, evidence of response and legal hold. Prevent retention automation from deleting records covered by a notice. | An information request can be linked to exact evidence, assigned, responded to, closed and retained with a complete audit trail. |
| R3-029 | Return-to-ledger reconciliation and change propagation | R3 / P0 | Reconcile every return line and total to the import ledger, approved emissions/CPR inputs and calculation outputs. When an upstream approved fact changes before filing or through a permitted correction, identify all affected return lines, totals, approvals and evidence-pack contents. | A changed weight/emissions/CPR input creates a deterministic impact list and no stale total can remain approved. |
| R3-030 | Filing idempotency and resubmission controls | R3 / P0 | Prevent duplicate HMRC submissions for the same return/version while allowing controlled retry after transport failure or HMRC rejection. Persist idempotency key, submission attempt, request fingerprint, response/receipt and operator action. | A retry after a simulated timeout cannot create a duplicate filing; a true rejection can be corrected and resubmitted as a new controlled attempt. |

# 9. Regulatory edge cases the product must explicitly model

| Topic | Required behaviour | Release |
|---|---|---|
| Special customs procedures | Do not treat as a permanent exemption. Track the tax-point lifecycle; goods exported before the relevant tax point may fall outside UK CBAM, while later release can create liability. | Do not treat as permanent exemption. Track tax-point lifecycle and the value basis that will count, including special rules for inward/outward processing and release from warehousing/freeports. R1 flags for manual threshold review; R3 completes calculation rules. |
| Northern Ireland / Crown Dependencies | Store jurisdiction and customs movement facts; apply scope/tax rules via reference data. | R1 |
| Importer vs declarant | Keep importer legally separate from customs declarant/agent. | Keep importer, declarant and customs agent legally separate. A tax agent may submit returns once authorised but may not register the liable person on their behalf. |
| Artificial business separation | Maintain connected-entity/business structure and an alert/review path for potential artificial separation intended to avoid CBAM. | R3 |
| Deregistration | Support eligibility review, outstanding-return/block flags and historical retention. | R3 |
| Death/incapacity/insolvency | Support controlled handover to successor/office-holder and keep filing/audit continuity. | R3 |
| Compulsory registration / HMRC assessment | Provide case status and notice tracking for HMRC-initiated actions. | R3 |
| Repayment / unjust enrichment | Store claim period, reimbursement evidence and HMRC decision. | R3 |
| Nil return reminders | Generate reminders even when liability is nil. | R3 |
| Verifier rules | Store accreditation body, scope, standard, materiality and site visit; CPR has additional standards. | R2 |
| Qualifying carbon-price schemes | Seed a current reference list, allow changes, and keep effective dates/source. | R2 |
| Future indirect emissions | Model DIRECT/INDIRECT at schema level; make applicability effective-dated so indirect can be enabled when law requires. | Model DIRECT/INDIRECT at schema level. Precursor is a source/provenance relationship, not a scope category. Indirect applicability is effective-dated and must not be activated in 2027 without the applicable law. |
| Weight evidence and HMRC assessment | Store source evidence for net mass and a flag for HMRC-determined/estimated weight; the importer remains responsible for the figure reported. | R1/R3 |
| Tax-point quarter | Persist the tax point date and derive the relevant quarter from tax-point rules, not declaration date. | R1/R3 |
| Anti-avoidance / artificial separation | Maintain connected-business relationships and an alert/review path for potential artificial separation intended to avoid registration/liability. | R3 |
| Penalties / interest / assessment | Track notice type, legal basis, amount, due date, payment status, interest basis, review/appeal status and evidence. | R3 |
| Registration changes | A registered person must notify HMRC when registration information changes/becomes incorrect within the statutory window. | R1/R3; notification task due-date is legal/config data. |
| HMRC reviews / appeals | Track assessment, penalty, review and appeal rights, deadlines, outcomes and any payment/deposit/hardship conditions. | R3 |
| Regulatory source status | Draft force-of-law notices are reference inputs but are not active law until commencement; the product must prevent draft data from becoming active by accident. | R2 |
| Tax-agent registration | Tax agent may prepare/submit returns when authorised but cannot register the liable person and does not assume CBAM liability. | R1/R3 |
| Registration service opens earlier than 1 Jan 2028 | Use effective-dated configuration; do not assume the service is closed until the actual opening date is published. | R1 |
| Registrable before registration service opens | Continue record keeping and create registration-ready/return obligations without inventing a filing route. | R1/R3 |
| Return reporting granularity | Separate every consignment and separate different CBAM goods within one shipment. | R3 |
| Precursor multiple installations/periods | Apply prescribed weighted/allocated precursor treatment and preserve every component. | R2/R3 |
| Verifier independent reviewer | Record independent reviewer evidence/conclusion where required by the verification framework. | R2 |
| HMRC preservation direction | Legal hold overrides normal destruction and response is tracked as a compliance case. | R3 |
| Tax avoidance / deliberate misstatement concern | Create a human/legal review case; never auto-label a criminal offence. | R3 |

# 10. Recommended domain model

The system should be relational and modular. Avoid a single giant “CBAM case” record. The following is the minimum domain shape; table names are indicative.

| Domain | Core entities | Important relationships |
|---|---|---|
| Organisation | tenants, clients, users, roles, permissions, approval_roles, registration_profiles, lifecycle_events | All business records tenant-scoped. |
| Customs | imports, declarations, import_lines, shipment_lines | Declaration → many lines; line → supplier/installations. |
| Reference data | commodity_codes, cbam_scope_rules, exemptions, rates, defaults, validation_rules, regulatory_versions, regulatory_sources, exchange_rates, working_day_calendar, payment_methods | All effective-dated; source status/commencement controls activation; every decision stores the rule/source version used. |
| Supplier | suppliers, installations, supplier_contacts, readiness | Supplier 1→N installations; installation 1→N products/monitoring periods. |
| Emissions | emission_records, gas_components, precursor_links, monitoring_periods, production_routes, system_boundaries, default_methodologies | Scope is separate from source/provenance; route/process/boundary determine the applicable data collection and validation. |
| Verification | verifiers, accreditations, verifier_scope, verification_records | Evidence ties to installation, period and product. |
| Documents | documents, document_versions, document_extractions, evidence_links | Document is immutable source; extracted values are derived records. |
| CPR | carbon_pricing_schemes, carbon_price_evidence, cpr_calculations, cpr_components | CPR calculated separately by qualifying scheme and precursor where required. |
| Returns | returns, return_lines, return_versions, submissions, amendments | Historical versions preserved. |
| Compliance ops | tasks, notifications, deadlines, exceptions, penalties, interest, assessments, compliance_cases, payments, repayments, reviews, appeals | All events auditable and actionable; statutory deadlines are source-driven and separate from product SLAs. |
| Audit | audit_events, change_reasons, evidence_hashes | Append-only business audit trail; retain six years or longer if legal hold applies. |
| Registration lifecycle | registration_profiles, registration_events, readiness_packs | Trigger date, first-year deadline, 30-day rule, service-opening configuration, sector estimates/evidence, HMRC registration identifier/status, changes and notifications. |
| Origin | origin_records, origin_evidence, origin_rule_versions | Non-preferential origin, declared/validated status, UK-origin exemption evidence and re-import/complex-good evidence. |

## 11. Emissions data structure — important correction

Do not model PRECURSOR as a third emissions scope. The correct conceptual split is:

| Field | Examples | Purpose |
|---|---|---|
| Emission scope | DIRECT / INDIRECT | What regulatory emissions category the component belongs to. |
| Emission source type | OWN_INSTALLATION / PRECURSOR_GOOD | Where the emissions arise in the production chain. |
| Gas | CO2 / N2O / CF4 / C2F6 | Stores gas-specific quantity before CO2e conversion. |
| Conversion factor | Regulatory factor for gas | Versioned factor used to produce tCO2e. |
| Monitoring basis | IMPORT_DATE / PRODUCTION_YEAR | Defines which legal data-selection option is applied. |
| Verification status | VERIFIED / NOT_VERIFIED / EVIDENCE_MISSING | Drives actual/default eligibility. |
| Precursor allocation | WEIGHTED_AVERAGE / ISOLATED_QUANTITY / JOINT_PROCESS / MULTIFUNCTIONAL_PROCESS | Prescribed precursor attribution/allocation method with rule/version lineage. |

# 12. Data lineage and traceability

The application should implement a three-layer trace that makes an auditor able to reproduce every derived number:

| Layer | Example | Rule |
|---|---|---|
| 1. Source truth | CDS row, supplier report, verifier certificate, CPR verification form | Never mutate the original file/record; preserve source metadata. |
| 2. Normalised facts | net_mass_kg = 48.200000; intensity = 0.12345 tCO2e/t | Every normalised fact stores origin, extraction/manual-entry method, validation status and source location. |
| 3. Derived values | embodied emissions, CPR, net liability, return total | Store formula/version/reference-data IDs plus input IDs; never store a result with no provenance. |

# 13. Application screens / UX structure

| Area | Primary screens | Key user outcome |
|---|---|---|
| Portfolio / clients | Client list, compliance health, threshold state | Operations can see which clients require attention. |
| Imports | Import register, import detail, scope decision, tax-point timeline | Every import line is understandable and traceable. |
| Threshold | Threshold dashboard, trigger event, registration readiness | User sees why the £50k trigger was or was not reached. |
| Suppliers | Supplier list, installation profile, readiness, outreach timeline | User can chase missing data without email spreadsheets. |
| Supplier portal | Mobile profile, emissions form, document upload, submission confirmation | Supplier can complete requests without creating an account if secure-link design is used. |
| Documents / evidence | Evidence library, document viewer, field lineage | Reviewer can inspect source evidence alongside extracted values. |
| Review | Exceptions queue, emissions review, verification review, CPR review | Humans approve only what needs approval. |
| Returns | Return workspace, calculation view, approval, filing/payment status | Client has one controlled workflow from draft to filed. |
| Admin / rules | Commodity codes, defaults, rates, schemes, validators, calendars | Regulatory updates can be loaded without code changes. |
| Audit | Timeline, object history, export evidence pack | Audit response is fast and reproducible. |

# 14. Notifications and task events

| Event | Trigger | Default action |
|---|---|---|
| Threshold warning | Projected/actual threshold approaches configured warning point | Notify operations/client; create task. |
| Threshold trigger | Legal threshold test becomes true | Create registration-readiness event and task. |
| Supplier request | New installation requires data | Send secure multilingual request. |
| Supplier Day 7 / 14 / 21 | No complete response | Send reminder and update status. |
| Supplier Day 28 | Product escalation SLA reached | Escalate to operations; do not assume legal default solely because SLA expired. |
| Verification missing | Actual value supplied but verification evidence absent | Route to review/default decision per law. |
| Default exposure | Applicable rule requires/defaults data | Flag likely liability impact. |
| Return ready | All required inputs approved | Create approval task. |
| Return deadline approaching | Calendar engine reaches reminder window | Notify responsible users. |
| Payment overdue | Due date passed | Create interest/penalty case. |
| Document expiring | Verifier certificate / supporting evidence needs refresh | Create renewal task. |
| Registration information change | Registered profile becomes incorrect/changed | Create statutory notification task with the applicable due date; notify owner and log acknowledgement. |
| HMRC assessment / information notice | Notice received | Create compliance case, response/payment task and evidence link. |
| Review / appeal deadline | Reviewable decision issued | Create configurable legal deadline tasks and preserve notice/source. |
| Death / incapacity / insolvency event | Successor/office-holder evidence received | Create statutory continuity task; restrict unauthorised filing changes. |
| Retention / legal hold | Record reaches destruction eligibility or hold is placed | Block destruction where retained/held; notify owner. |

# 15. Non-functional requirements

| Area | Requirement |
|---|---|
| Security | Tenant isolation, least privilege, secure magic links, secret management, encryption in transit/at rest, audit of privileged actions, safe file handling and malware-scanning boundary where available. |
| Privacy / GDPR | Supplier contacts are personal data. Record purpose, lawful basis/process ownership, retention, access, deletion/DSAR handling and contractual/data-processing responsibilities. Legal retention for CBAM evidence overrides ordinary deletion only where applicable. |
| Hosting | Choose and document hosting region(s) before pilot, including data residency, backups and disaster-recovery location. UK/EU customer requirements should be configurable rather than assumed. |
| Reliability | Scheduled jobs must be idempotent, retryable and observable. Backup and restore must be rehearsed before pilot. |
| Auditability | Audit log is append-only; business evidence is versioned and linked. Legal hold support should be available before deletion/retention automation is enabled. |
| Performance | R1 must pass the handbook's 10,000-import load test. Define target p50/p95 budgets for import, dashboard and supplier workflows before hardening. |
| Accessibility | Supplier portal should be mobile-first and accessible; target WCAG 2.2 AA for the customer-facing UI as a product quality objective. |
| Observability | Metrics, structured logs, queue/job status, import counts, failed validations, notification delivery and submission state must be searchable by client/case. |
| Data integrity | All monetary and emissions calculations use decimal-safe types; units are explicit; rounding occurs only at legally prescribed steps. |
| Environment separation | Local/staging/prod have separate credentials and data stores; production regulatory data changes require controlled change management. |
| Regulatory source integrity | Every active rule set must show source status, publication date, commencement date, effective period, retrieval timestamp and version. Draft/uncommenced notices cannot silently become active. |
| Compliance case management | HMRC notices, assessments, reviews, appeals and penalty cases require deadline-safe storage, immutable evidence and role-based access. |
| Supplier usability | Minimum supplier questionnaire must pass a mobile usability test in under 10 minutes using the handbook pilot scenario, without requiring account creation beyond the secure link. |
| Audit / legal hold | Evidence deletion is blocked by statutory retention or legal hold; destruction events themselves are audited. |

# 16. Test strategy

The handbook already mandates a permanent worked example and weekly release gates. The merged test strategy expands this into four layers.

| Test layer | Examples |
|---|---|
| Unit | Commodity-code scope, threshold cadence, tax point, weight rounding, gas conversion, default-selection rules, verifier rules, CPR components, FX rounding. |
| Integration | CDS CSV → import lines → scope; supplier portal → document → extraction; reference-data update → historical result reproducibility. |
| Golden fixtures | Keep the handbook's 48.2t Turkish EAF steel example as a regression fixture, but do not hard-code its final tax as a legal truth until official rate/default fixtures are frozen. Test the formula and re-base once published values are available. |
| Scenario / UAT | Threshold crossed forward; threshold crossed backward; special customs tax-point; missing/unverified actuals; mixed actual/default precursor; CPR multiple schemes; nil return; amendment; repayment; penalty/interest; supplier non-response. |
| Security | Cross-tenant access, magic-link abuse, document access, privilege escalation, audit-log tampering and unsafe file upload. |
| Load / recovery | 10,000 imports, long supplier list, bulk document ingestion, failed queue retry, backup restore and partial outage recovery. |
| Regulatory activation | Draft force-of-law notice remains inactive; commencement activates the correct version. |
| Registration lifecycle | 30-day registration, 31 Jan 2028 first-year transition, registration changes, successor 21-day notification, deregistration and compulsory registration/assessment fixtures. |
| Default amendment lock | Attempt to replace default-emissions return data with actual data is rejected by legal rule. |
| Special-procedure value | Inward processing, outward processing, freeport and warehousing value/tax-point scenarios. |
| HMRC enforcement / appeals | Assessment, notice, penalty, review and appeal lifecycle with deadlines and evidence. |
| Weight rounding | All legal fractional-kg/reporting rounding cases and HMRC-determined weight representation. |

## 17. Golden fixture rules

| Handbook fixture: 48.2 tonnes of Turkish EAF steel is the permanent worked-example target in the handbook (p. 2/5). The handbook quotes example liabilities of £785.25 on actual data and £4,771.80 using default data. These are useful regression targets only after the official rate/default inputs are captured as versioned fixtures. Never bake those tax amounts into production code. |
|---|

# 18. Nine-week R1 build plan

| Week | Workstream | Exit criteria |
|---|---|---|
| W1 | Setup + reading | Repos/environments ready; team passes handbook/regulation walkthrough; blockers logged. |
| W2–3 | Foundations | Schema, tenant/security baseline, reference tables, audit and test harness ready. |
| W3–4 | Imports register | CDS sample imported; parser validation and scope classification working. |
| W4–5 | Threshold + onboarding | Forward/backward tests pass; trigger event, registration readiness and 5 hand-calculated scenarios pass. |
| W5–7 | Supplier outreach + portal | Supplier/installations loaded; mobile form; multilingual messages; Day 7/14/21/28 sequence observable. |
| W7–8 | Ops dashboard + docs | Per-client import/threshold/outreach/document view and document storage complete. |
| W8–9 | Hardening + pilot | Pen test basics, backup/restore, 10k import load test, UAT and pilot onboarding complete. |

# 19. Team allocation

| Role | Suggested R1 ownership |
|---|---|
| Tech lead | Architecture, database/security review, code quality, releases, reference-data change control. |
| Backend 1 | CDS/import pipeline, scope engine, threshold/tax-point foundation. |
| Backend 2 | Supplier/installations, outreach jobs, documents, notifications. |
| Frontend | Operations dashboard, import views, client views, supplier portal shell. |
| QA (part-time acceptable) | Threshold scenarios, R1 gates, UAT scripts, tenant/security and load tests. |
| Domain owner | Interpretation of forms, reference-data mapping, HMRC workflow, UAT and supplier-language review. |

| Capacity rule: The handbook says the minimum viable team is 3 developers + QA + domain owner and that if the team has fewer people, R1 scope holds and R2 slips rather than reversing the order. Treat this as a governance rule. |
|---|

# 20. External dependencies and open decisions

| Item | Why it blocks design | Decision / action |
|---|---|---|
| Real CDS export sample | R1 import mapping, scope and UAT depend on real field shapes. | Obtain a masked/sample export and freeze mapping fixture. |
| HMRC Carbon Price Verification Form | R2 CPR data model depends on the actual form fields. | Obtain form and map fields before R2 form implementation. |
| EU Commission Communication / template | Supplier evidence interoperability and form mapping. | Obtain latest document; define controlled EU-to-UK mapping. |
| Verifier examples | R2 verifier validation needs real certificate/report shapes. | Obtain two example verifier packages and validate mandatory fields. |
| HMRC return submission interface | R3 cannot promise direct filing API behaviour until interface is published/confirmed. | Build payload adapter boundary + filing-ready export first. |
| Default values | Exact values not safely hard-coded until official publication/final fixtures. | Create versioned reference-data loader and re-base golden fixtures once published. |
| Illustrative/actual CBAM rates | Rate values are reference data and may change. | Seed only authoritative published values; keep formula tests independent. |
| Statutory approver / SAO interpretation | Handbook names SAO; official CBAM material does not establish a CBAM-specific SAO filing duty. | Keep approver role configurable; get written tax/legal confirmation. |
| MRV / verifier detailed guidance | Verifier screens need exact field/exception rules. | Track official updates and treat guidance as versioned reference material. |
| Supplier contract terms | Who pays for verification and who owns evidence affects outreach and dispute workflow. | Add a supplier contract/evidence-responsibility field and workflow before pilot. |
| REG-DEC-001 — Exact registration-service opening date | HMRC wording is “by 1 Jan 2028”; the exact service opening could be earlier. | Store opening date as effective-dated configuration and update from official HMRC announcement. |
| DATA-DEC-002 — CDS data acquisition route | The product needs real import-history data but must not assume a public self-serve historical API. | Confirm with HMRC software/support and client operational team; support export/upload + approved data-request/manual route. |
| BUS-DEC-003 — HMRC agent / professional-liability model | Return preparation/submission may make the service an HMRC-facing professional activity. | Decide whether the company acts as an authorised tax agent, who signs/approves, and the required contractual/insurance position before live filing. |
| TECH-DEC-004 — HMRC return schema / calculation facility | Finance Act allows HMRC to specify the return method and, potentially, use of an HMRC digital facility to calculate the amount. | Obtain the final HMRC return schema/method and digital-facility requirement; keep an adapter boundary and filing-ready export until confirmed. |
| LEGAL-DEC-005 — Final statutory approver role | The handbook names an SAO, while the CBAM-specific legal material used for the current build contract does not establish a bespoke SAO filing duty. | Keep the approver role configurable; obtain written tax/legal confirmation before making SAO mandatory in product policy. |
| PROD-DEC-006 — Supplier commercial terms | Who pays for verification, who owns source evidence and what service level is contracted affects supplier workflow and dispute handling. | Confirm contract model and encode only agreed commercial policy; do not present commercial assumptions as HMRC requirements. |

# 21. Regulatory/reference-data tables to make editable

| Reference table | Minimum fields |
|---|---|
| CBAM commodity codes | code, sector, product description, scope flag, exclusion, effective_from, effective_to, source, version |
| Default emissions | good, default_value, unit, methodology_version, geography/portion applicability, effective_from/to, publication/notice, version, source; supports Treasury-set values that may vary by where emissions occurred or apply to a portion. Do not populate non-existent geography/portion rules until officially defined. |
| CBAM sector rates | sector, quarter, rate_gbp_per_tco2e, effective_from/to, publication, version |
| Validation rules | rule_id, condition, message, severity, sector/code applicability, effective dates, source |
| Verification rules | standard, accreditation requirement, scope, materiality, site_visit requirement, conclusion/opinion fields, evidence types, effective dates, source; stores the legal verifier package and acceptance conditions, including unresolved-gap/uncorrected-misstatement handling. |
| Carbon-price schemes | scheme, jurisdiction, qualifying status, effective dates, source, evidence type |
| Exchange rates | currency, quarter, GBP rate, source, publication/effective date |
| Compliance calendar | event, accounting period, due date, reminder windows, legal source, effective date |
| Tax-point rules | customs procedure, trigger event, condition, effect, effective dates |
| Penalty/interest rules | type, trigger, rate/method, effective dates, source |
| GHG applicability by commodity | commodity_code, sector, applicable_gases, effective_from, effective_to, source, version; Defines whether CO2, N2O and/or PFCs apply to a specific commodity code. |
| Functional units and conversion rules | commodity_code/sector, functional_unit, composition_basis, conversion_equation, rounding, effective dates, source, version; Supports general tonne-of-good cases plus cement/clinker and fertiliser/nitrogen conversion rules. |
| Gas conversion factors | gas, factor_to_tco2e, source, effective_from/to, version; Versioned conversion factors for relevant non-CO2 gases. |
| Precursor / system boundaries | complex_good, precursor_good, production_process, boundary_definition, method_source, effective dates, version; Defines relevant precursors and system boundaries for actual monitoring and default methodology. |
| Default-value methodology | good, methodology_version, value_definition, population/basis, publication_notice, effective dates, amendment_history; Stores not only the value but the Treasury notice/method used to produce it and its version history. |
| Evidence document types | document_type, applicable_sector/rule, mandatory_fields, verifier_role, effective dates; Distinguishes verification report, good-specific verification summary, CPR verification form and other supporting evidence. |
| Regulatory source registry | source_id, title, source_type, publication_date, status, commencement_date, effective_from/to, URL, retrieved_at, supersedes, checksum/identifier, notes; status controls whether source can activate a rule. |
| Working-day calendar | jurisdiction, date, is_working_day, source, version, effective dates; used for last-working-day deadlines and statutory response/payment dates. |
| Payment methods | method_code, description, legal/operational availability, source, effective dates; supports HMRC-authorised methods without hard-coding a permanent list. |
| Production routes / processes | sector, commodity_code/product, route, process, system_boundary_id, applicable_gases, relevant_precursors, effective dates, source/version; ties supplier forms and validation to System Boundaries. |
| Compliance / enforcement cases | case_type, notice/assessment id, linked return/import, issue date, response/payment due, amount, legal basis, review/appeal state, evidence, outcome, source/version; supports HMRC notices, assessments, penalties and appeals. |
| Non-preferential origin rules | commodity/route, origin rule, evidence type, effective dates, source/version |
| Precursor aggregation/allocation rules | precursor, complex good, installation/period, weighting/allocation method, joint/multifunctional flag, effective dates, source/version |
| Registration requirements | field, required/conditional, evidence, deadline rule, effective dates, source/version |
| Enforcement / offence case types | case_type, statutory_basis, trigger, notice/response rule, penalty/assessment linkage, effective dates, source |
| Record-preservation rules | record_type, retention_anchor, duration, HMRC-direction condition, legal-hold rule, source/version |
| Interest rules | event_type, start/end basis, rate/reference, compounding/rounding method, effective dates, source |
| Tax-point trigger rules | normal import trigger, duty-liability condition, no-duty entry trigger, special-procedure trigger, processed-good rule, export-before-tax-point effect, effective dates, source/version |
| Supplier submission versions | installation, product, submission id, supersedes, monitoring period, submitted values, evidence links, verifier state, review state, reason, created/effective timestamps |
| Customs amendment/reconciliation rules | declaration id, original version, amended version, amendment date/reason, affected fields, recalculation triggers, source/version |

# 22. Explicit R1 non-goals

- No production-grade CBAM liability calculator in R1.

- No final HMRC filing integration in R1.

- No complex BI/forecasting layer in R1.

- No autonomous approval or auto-filing.

- No hard-coded regulatory rates/defaults as business constants.

- No assumption that the Day 28 supplier chase itself legally authorises default use.

- No interpretation of SAO as a statutory CBAM role until confirmed.

# 23. Official research sources used

- HMRC – Carbon Border Adjustment Mechanism (CBAM) policy summary — https://www.gov.uk/government/publications/carbon-border-adjustment-mechanism-cbam-policy-summary/carbon-border-adjustment-mechanism-cbam-policy-summary

- HMRC – Check which goods are in scope of CBAM — https://www.gov.uk/government/publications/check-which-goods-are-in-scope-of-carbon-border-adjustment-mechanism-cbam

- HMRC – Work out the date you will need to register for CBAM — https://www.gov.uk/guidance/work-out-the-date-youll-need-to-register-for-carbon-border-adjustment-mechanism-cbam

- HMRC – Keeping records for CBAM — https://www.gov.uk/guidance/keeping-records-for-carbon-border-adjustment-mechanism-cbam

- HMRC – Imported CBAM goods that may not contribute towards the registration threshold — https://www.gov.uk/guidance/imported-carbon-border-adjustment-cbam-goods-that-may-not-contribute-towards-the-registration-threshold

- HMRC – Work out carbon price relief — https://www.gov.uk/guidance/work-out-your-carbon-price-relief

- HMRC – Get a carbon pricing verification form — https://www.gov.uk/guidance/get-a-carbon-pricing-verification-form

- HMRC – CBAM collection / registration service updates — https://www.gov.uk/government/collections/check-if-youll-need-to-register-for-carbon-border-adjustment-mechanism-cbam

- HMRC – Carbon Border Adjustment Mechanism: factsheet — https://www.gov.uk/government/publications/factsheet-carbon-border-adjustment-mechanism-cbam/factsheet-carbon-border-adjustment-mechanism

- Legislation.gov.uk – Finance Act 2026 — https://www.legislation.gov.uk/ukpga/2026/11/contents

- Legislation.gov.uk – The Carbon Border Adjustment Mechanism (Emissions and Verification) Regulations 2026 (SI 2026/995) — https://www.legislation.gov.uk/uksi/2026/995/contents

- Legislation.gov.uk – The Carbon Border Adjustment Mechanism (Calculation and Carbon Price Relief) Regulations 2026 (SI 2026/809) — https://www.legislation.gov.uk/uksi/2026/809/contents

- Legislation.gov.uk – The Carbon Border Adjustment Mechanism (Administrative Provisions) Regulations 2026 (SI 2026/802) — https://www.legislation.gov.uk/uksi/2026/802/contents

# 24. Handbook cross-reference

The six-page uploaded handbook remains the product-management baseline. Page 1 explains the reason and scope; pages 2–3 show the eight-step business flow and glossary/automation; page 4 defines the three release plan; page 5 sets the R1 weekly gates and standing rules; page 6 lists parallel blockers and companion documents. (Handbook, pp. 1–6)

| Source limitation: The uploaded PDF is image-based and has no machine-readable text layer. This document therefore uses the rendered page content as the source for handbook-derived requirements. Regulatory corrections and expansions in this specification are explicitly based on external official research, not silently inferred from the handbook. |
|---|

# 24. v1.1 REVISION HISTORY — SUPERSEDED BY §25

24.1 Regulatory and build-contract overrides

- Registration: the product must treat the HMRC service opening as configurable because official guidance says it will open “by 1 January 2028”. For first-year 2027 liability, the registration deadline is 31 January 2028; outside that transitional year, the ordinary rule is 30 days from the day liability to register begins.

- Threshold: forward test is considered on any day; backward test is applied on the first day of each month. During 2027 the backward look-back begins on 1 January 2027. If both tests are met, the earliest liability date applies.

- Tax point: declaration date is not a substitute for the legal tax point. Special customs procedures are lifecycle events and may require a manual threshold-review flag in R1 until the full R3 value rules are implemented.

- Emissions: store tCO2e and gas components. Precursor is source/provenance, not a third scope category. The platform may recompute CO2e for plausibility, but the verified installation result is the authoritative reportable emissions intensity.

- Defaults: default use is driven by the legal data/verification rules, not the supplier Day-28 SLA. The v1.1 text treated default-to-actual amendment as an open decision; §25 corrects this because Finance Act 2026 Schedule 17 paragraph 8(2) expressly prohibits replacing default-emissions return information with actual-emissions information by amendment.

24.2 R1 delivery cut — 1 December 2026 pilot vs 1 January 2027 live baseline

| Cut | Must be included | May follow by 1 Jan | Explicitly R2/R3 |
|---|---|---|---|
| 1 Dec pilot | R1-001/002/003/004/005/006/007/008/009/010/011/012/015/017/018/019/021/022/023/025/027/028/032; sector-aware supplier form; five threshold scenarios including special-procedure manual review; origin evidence test; mobile supplier usability test; acquisition provenance. | R1-013/014; R1-016; R1-020; R1-024; R1-026; R1-029/030/031/033 may follow the pilot unless a real pilot client requires them. Registration-service opening date remains configurable. | All R2 requirements and all R3 requirements. |
| 1 Jan live baseline | Everything required for pilot plus registration-ready data, registration declaration, sector-estimate evidence, registration-change tasking, registration status record, origin controls, review queue, export, resilience controls and complete operational audit/retention controls. | None of the legally necessary R1 data-machine capabilities may be deferred beyond this gate. | R2/R3 remain separate releases. |

Capacity rule: with 3 developers + QA + domain owner, the team should not attempt to finish the R1 table as a flat 31-item list. The pilot cut is the minimum demonstrable system; the January cut completes the operational foundation. R2 may slip rather than pulling R3 work into R1.

24.3 Week-1 QA scenario set (must be written down before implementation)

- Forward-only trigger: projected CBAM value reaches £50,000 within the next 30 days.

- Backward-only trigger: first-day-of-month look-back reaches £50,000; 2027 look-back starts at 1 January 2027.

- Both tests trigger: verify the earlier registration-liability date is selected.

- Below threshold: both tests remain false and the client remains unregistered/monitor-only.

- Special customs procedure: affected line is held for manual review with tax-point and value-basis evidence rather than silently counted or exempted.

- Weight evidence: source net mass is retained, and any manual override requires reason/source evidence.

24.4 Reference-data completeness required before R2

- GHG applicability by commodity code, including PFCs for relevant aluminium products and N2O for relevant fertiliser products.

- Functional unit and conversion equations, including clinker for cement and nitrogen for fertilisers where applicable.

- Gas-to-CO2e conversion factors and version/effective-date metadata.

- Precursor and System Boundaries definitions from the official reference material.

- Default-value methodology and Treasury notice/version metadata, separate from the value itself.

- Distinct document types for verification report, good-specific verification summary and Carbon Pricing Verification Form.

24.5 Registration and return data fields that are now mandatory in the build contract

- Registration: trigger date, business/contact details, EORI/VAT information and estimated next-12-month sector weights.

- Import line: importer, declarant, tax point, derived quarter, 8-digit commodity code in force at the tax point, customs value, net mass kg, non-preferential origin, procedure and source evidence.

- Return line (first annual period): explicit tax-point quarter where applicable, plus weight, emissions intensity/default, origin, carbon-price/relief information and source/regulatory versions.

24.6 Official sources checked for this revision

- HMRC CBAM Policy Summary (updated 9 September 2026): https://www.gov.uk/government/publications/carbon-border-adjustment-mechanism-cbam-policy-summary/carbon-border-adjustment-mechanism-cbam-policy-summary

- HMRC registration timing guidance: https://www.gov.uk/guidance/work-out-the-date-youll-need-to-register-for-carbon-border-adjustment-mechanism-cbam

- HMRC registration collection/service updates: https://www.gov.uk/government/collections/check-if-youll-need-to-register-for-carbon-border-adjustment-mechanism-cbam

- HMRC Carbon Price Relief: https://www.gov.uk/guidance/work-out-your-carbon-price-relief

- HMRC imported goods / threshold exemptions: https://www.gov.uk/guidance/imported-carbon-border-adjustment-cbam-goods-that-may-not-contribute-towards-the-registration-threshold

- HMRC importer definition: https://www.gov.uk/guidance/check-if-youre-classed-as-the-importer-for-carbon-border-adjustment-mechanism-cbam

- HMRC force-of-law notices and reference document: https://www.gov.uk/government/publications/carbon-border-adjustment-mechanism-force-of-law-notice-and-reference-document

- HMRC System Boundaries Document v1.00: https://www.gov.uk/government/publications/carbon-border-adjustment-mechanism-force-of-law-notice-and-reference-document/carbon-border-adjustment-mechanism-system-boundaries-document-version-100

- Legislation.gov.uk — Finance Act 2026: https://www.legislation.gov.uk/ukpga/2026/11/contents

- Legislation.gov.uk — Carbon Border Adjustment Mechanism (Emissions and Verification) Regulations 2026, SI 2026/995: https://www.legislation.gov.uk/uksi/2026/995/contents

# 25. v1.2 GAP CLOSURE OVERRIDES — RETAINED IN v1.3 BUILD

## 25.1 Registration service and deadlines

The service opening date is configurable because HMRC guidance says registration will open “by 1 January 2028”. The first-year 2027 transitional registration deadline is 31 January 2028. Outside that first-year transition, the ordinary registration deadline is 30 days from the day liability to register begins. The deadline engine must store which rule produced each due date.

## 25.2 Default-emissions amendment is a legal lock

Finance Act 2026 Schedule 17 paragraph 8(2) prohibits an amendment replacing default-emissions information with actual-emissions information. This is not an open decision and must not be switchable by tenant/admin configuration. All previous v1.1 references to R3-DEC-001 are superseded.

## 25.3 Verified emissions boundary

The installation calculates the prescribed emissions methodology and the verifier checks it. The platform may recompute CO2e and intensity as a plausibility/reconciliation control, but the verified result is the authoritative reportable value. Intensity is stored/reportable at the prescribed five-decimal precision.

## 25.4 R1 supplier collection must already be sector-aware

The R1 supplier-form schema must know commodity/sector, applicable gases, functional unit, production route/process, monitoring period and evidence slots before Day-0 outreach. R2 adds extraction and deeper validation; R1 must not collect structurally incompatible generic data.

## 25.5 R1 threshold handling for special customs

Where final R3 value rules are not yet implemented, R1 must flag inward processing, outward processing, freeport/free-zone and warehousing lines for manual review. QA must include the value-attributable/difference scenarios so the threshold engine cannot silently miscount them.

## 25.6 Regulatory-source activation status

The active rule set must distinguish draft, laid, in-force, commenced and superseded materials. HMRC states the published force-of-law notices are draft and do not yet have force of law; they are to commence on 1 January 2027. Draft rules must never silently drive production decisions before activation.

## 25.7 HMRC enforcement and appeal lifecycle

The product must treat assessment, information notices, penalties, reviews and appeals as first-class compliance cases with statutory deadlines, amounts, evidence, outcomes and immutable audit history.

## 25.8 Registration continuity

Registration is not a one-time record. The product must model changes/incorrect information, compulsory registration, succession after death/incapacity, insolvency handover and deregistration/final close-out with statutory deadlines and history.

## 25.9 Evidence and retention

Every reportable input must retain source lineage. Six-year retention is anchored to the legally applicable record-retention start date; legal holds block destruction. Verification report, good-specific verification summary and Carbon Pricing Verification Form are distinct evidence types.

## 25.10 What remains open

Exact service opening date, CDS acquisition method, HMRC return/digital calculation interface, agent/professional-liability model, statutory approver/SAO interpretation, supplier commercial terms, exact default values and final published rates remain controlled external inputs. None should be invented or hard-coded.

# 26. OFFICIAL SOURCE STATUS NOTES — v1.3 BASELINE

HMRC Carbon Border Adjustment Mechanism: force of law notices and reference document (published 13 July 2026; updated document set includes a draft Administrative Provisions/Carbon Price Relief notice and a draft Emissions and Verification notice). HMRC explicitly states these notices are draft and do not yet have force of law, with commencement on 1 January 2027. The same page identifies the System Boundaries Document v1.00 and Carbon Pricing Verification Form. Source: https://www.gov.uk/government/publications/carbon-border-adjustment-mechanism-force-of-law-notice-and-reference-document

Finance Act 2026, Schedule 17 paragraph 8: returns can be amended only to correct an error, and paragraph 8(2) expressly forbids replacing default-emissions information with information determined under the actual-emissions regulations. Source: https://www.legislation.gov.uk/ukpga/2026/11/schedule/17/paragraph/8/2026-08-17

Finance Act 2026, Schedule 17 paragraph 7 also allows HMRC to specify the return method and, where applicable, require an HMRC digital facility to calculate the amount. Payment is by a method specified by HMRC. Source: https://www.legislation.gov.uk/ukpga/2026/11/schedule/17/part/3/2026-08-17

Finance Act 2026 penalty provisions include a £500 fixed penalty plus £40 daily penalties for failure to notify certain registration/death/incapacity changes, a £500 record-keeping penalty, and reasonable-excuse/double-jeopardy provisions. Source: https://www.legislation.gov.uk/ukpga/2026/11/pdfs/ukpga_20260011_en.pdf

Document status: v1.4 authoritative revised build contract. This document is intended to be the development baseline, not legal advice. Regulatory reference data, HMRC interfaces, published rates/defaults and draft/uncommenced materials must remain versioned and subject to formal change control.

Implementation rule: presence in the regulatory-source registry is not activation. A source becomes eligible to drive production only when its status and commencement/effective dates satisfy the applicable rule. This prevents draft force-of-law material from becoming operative through an ingestion mistake.

Residual-gap closure applied in v1.3: customs-declaration amendment/reconciliation, monetary currency provenance, emissions-evidence revision control, monitoring-data coverage checks, return-to-ledger impact propagation and filing idempotency/resubmission controls. These safeguards prevent stale, duplicated or non-reproducible compliance records when customs or supplier evidence changes.

# 28. v1.3 FINAL COMPLETENESS AUDIT — ADDITIONS APPLIED

Audit result: The specification has been re-audited against the uploaded Team Handbook plus the current official UK CBAM material checked on 30 September 2026. The identified regulatory, product, data-model, operational and delivery gaps from the second-pass review are now represented as requirements, acceptance criteria, edge cases or controlled open decisions.

v1.3 closes the remaining gaps by adding:

- Registration: business type, evidence-backed sector weight estimates, post-registration account/status record, and the distinction between becoming registrable and the later service opening.

- Geography/origin: Overseas Territories and UK Continental Shelf coverage, non-preferential origin validation, UK-origin evidence, and re-import/complex-good origin evidence.

- Special customs: storage/free zones and authorised use/Union end-use in R1, with explicit outward/inward processing, export-before-tax-point and processed-good outcomes in R3.

- Emissions/verification: precursor aggregation and allocation across multiple installations/periods, joint/multifunctional production, and independent-reviewer verification evidence.

- Returns/enforcement: explicit registrable-person filing/payment obligation, exact return granularity, HMRC record-preservation workflow, tax-avoidance/misstatement compliance cases, and reference-driven penalty/interest treatment.

- Repayments: required reimbursement person, amount, interest and date fields plus the correct retention anchor.

- Reference data: origin, precursor allocation, registration requirements, enforcement/offence case types, record preservation and interest rules.

- Testing/acceptance: added edge cases for origin, service-opening timing, registrable-before-registration, precursor aggregation, verifier independent review, preservation notices, tax-avoidance incidents and return granularity.

The remaining open decisions are intentionally not converted into invented requirements: exact registration-service opening date; CDS acquisition route; final HMRC return/submission method and any HMRC digital calculation facility; agent/professional-liability model; statutory approver/SAO interpretation; supplier commercial terms; exact published default values; exact quarterly CBAM rates; and detailed future guidance/notices not yet operative. The application must be built so these inputs can be activated through versioned reference data or controlled configuration without restructuring core workflows.

Regulatory-status rule: final/laid secondary legislation, draft notices, published guidance and future amendments must remain separately versioned. A rule may drive production only when its source status, commencement and effective dates make it legally applicable to the transaction or accounting period.

# 29. v1.4 COMPLETENESS AUDIT — FINAL GAP CLOSURE

Audit date: 30 September 2026. The current build contract was re-checked against the uploaded Team Handbook and the official UK CBAM material reviewed for this project. No additional material product-domain gap was identified beyond the items below. These additions close the remaining implementation ambiguities and are now part of the build baseline. The document remains subject to future HMRC publications, notices, rates, defaults and interface specifications; these are explicitly handled as versioned external dependencies.

## 29.1 Additional requirements added in v1.4

| ID | Requirement | Release / Priority | What the system must do | Acceptance / evidence |
|---|---|---|---|---|
| R1-036 | Statutory liable-person determination | R1 / P0 | Determine and persist the legally liable person from importer/customs facts rather than inferring liability from the declarant, broker or agent. Store the relevant declaration context, person-on-whose-behalf relationship and rule version. | Fixtures for direct importer, broker/declarant and acting-on-behalf-of cases produce the correct liable-person candidate and retain the evidence. |
| R1-037 | Forward-looking import forecast register | R1 / P1 | Maintain the inputs used for the 30-day expectation test: expected tax point, expected value, source (order/forecast/manual), confidence, created/updated time and link to supporting evidence. Keep forecast revisions auditable. | A changed forecast creates a versioned threshold impact record without overwriting the prior forecast. |
| R1-038 | Customs-source reconciliation | R1 / P1 | Reconcile repeated or amended source rows across CDS batches, manual entries and replacements. Detect duplicates, missing declaration lines, orphan records and source conflicts before downstream classification. | A duplicate import batch produces one business record plus a reconciliation event, not duplicate liability. |
| R1-039 | Supplier delegated evidence source | R1 / P1 | Allow emissions/evidence to originate from the installation, another supply-chain party, or a verifier acting on the installation’s behalf. Preserve the evidence-source party separately from the importer/supplier master. | A precursor document supplied by an upstream party remains linked to the correct installation/product and is not misattributed. |
| R1-040 | Registration service readiness switch | R1 / JAN-1 | Represent HMRC registration-service availability as an effective-dated configuration and expose service-state messaging to users. When service is unavailable, the platform must continue pre-registration record capture and deadline tracking. | Changing the configured opening date changes UI workflow without code deployment and does not delete pre-registration history. |
| R1-041 | Supplier magic-link lifecycle | R1 / P0 | Support issue, expiry, revocation, resend and single-case scope for supplier magic links; never expose cross-client or cross-installation data. | Expired/revoked links fail closed; resend invalidates the prior token; all token events are audited. |
| R2-028 | Explicit verifier standards and independence rules | R2 / P0 | Store and validate the exact verifier standards/accreditation conditions applicable to the evidence type, including ISO/IEC 17029:2019, ISO 14065:2020, and where required for CPR, ISO 14064-3:2019 and ISO 14066. Enforce independence from installation/importer/jurisdiction and required sector scope through reference data. | A CPR verifier package missing a required standard, independence condition or accreditation scope cannot be accepted as compliant. |
| R2-029 | Supplier data coverage compatibility | R2 / P0 | Check that installation/product/monitoring-period coverage is compatible with the import population before associating a verified result with a consignment. Detect stale, partial, overlapping or ambiguous coverage. | A verified report covering only part of an import population cannot silently satisfy all linked imports. |
| R3-031 | Statutory review and appeal timetable engine | R3 / P0 | Model HMRC review/appeal rights and deadlines as versioned legal events, including notice date, acceptance window, review request window, review outcome, appeal window, extension state and evidence. Do not hard-code one generic 30-day workflow where the active provision differs. | A review/appeal fixture calculates each deadline from the applicable notice/event and preserves every state transition. |
| R3-032 | Artificial-separation direction workflow | R3 / P1 | Model an HMRC direction treating connected persons as a single taxable person, including effective date, named/nominee person, joint-and-several liability state, 14-day response/nomination requirement where applicable, and add/remove changes. | An artificial-separation direction can be recorded and propagated to threshold/registration/liability views without automatically accusing a client of avoidance. |
| R3-033 | Record-preservation direction controls | R3 / P1 | Represent HMRC record-preservation directions with specified record categories, issue date, maximum preservation period, response instructions and legal hold. The retention scheduler must defer destruction while the direction applies. | A preservation direction prevents eligible evidence from being purged and the system shows the legal basis and expiration/continuation state. |
| R3-034 | Penalty defence workflow | R3 / P1 | Track reasonable-excuse assertions, when the excuse ceased, remedial action timing, double-jeopardy checks, supporting evidence and reviewer decision. Separate legal defence evaluation from simple penalty status. | A penalty case can be marked disputed with evidence and an explicit human/legal decision without silently waiving the penalty. |
| R3-035 | Retention-anchor calculation | R3 / P0 | Calculate the six-year retention end date from the legally applicable anchor, including the later-of-date-created/end-of-accounting-period rule where applicable, and preserve legal holds/directions. | Fixtures prove the retention date is deterministic and cannot be shortened by an application user. |
| R3-036 | Transition-rule/version package | R3 / P0 | Represent transitional and commencement overrides separately from permanent rules, including first-year annual return timing, later quarterly periods, payment windows and any commencement conditions. | An active calculation/return states which transition package was applied and remains reproducible after future rule updates. |

## 29.2 Regulatory items that are explicitly confirmed and must not be left as assumptions

- The registration service opening date must remain configurable because HMRC currently uses the wording “by 1 January 2028”; the first-year 2027 deadline is 31 January 2028 and the ordinary rule is 30 days from becoming liable to register.

- The £50,000 forward test applies on any day; the £50,000 backward test is applied on the first day of each month. For 2027 the look-back cannot include dates before 1 January 2027. If both tests trigger, the earliest liability date governs.

- The installation/operator calculates the prescribed emissions methodology; the verifier verifies it; the liable person reports the verified result. Platform recomputation is only a plausibility/reconciliation check.

- Precursor emissions are upstream direct emissions. The data model must separate emissions scope from source/provenance.

- Actual/default emissions selection is a legal rule and is distinct from the supplier Day-28 product SLA. The default-to-actual amendment prohibition under Finance Act 2026 Schedule 17 paragraph 8(2) is a legal lock.

- Carbon Price Relief is calculated separately for each qualifying scheme, uses the required previous-quarter exchange-rate basis, respects the verification-period rule, free-allocation/threshold/removal/compensation adjustments and cannot exceed the CBAM liability.

- Verification evidence must preserve the exact evidence type: verification report, good-specific verification summary and Carbon Pricing Verification Form are not interchangeable document classes.

- Current official HMRC source material contains a provisional qualifying-carbon-pricing-scheme list; this list must be seeded as reference data with source date/status and updated when HMRC changes it.

## 29.3 Remaining external/open items

- Exact HMRC registration-service opening date and service/API behaviour.

- Exact operational CDS data acquisition route for the target clients; support export/upload and approved data-request routes without assuming an undocumented public historical API.

- Final HMRC return submission schema and whether/how HMRC’s digital calculation facility must be used.

- Final Treasury/HMRC default emissions values and quarterly CBAM rates when published; test the formula independently of those fixtures until then.

- Commercial/legal decision on whether the product provider acts as an HMRC tax agent and the associated professional-liability/insurance model.

- Any future indirect-emissions commencement/change and future regulatory updates; activate only from versioned authoritative source data.

## 29.4 v1.4 completeness statement

Within the current published legal/policy baseline reviewed on 30 September 2026, the build contract now covers the complete operational lifecycle: organisation and liable-person determination, customs ingestion and reconciliation, scope/exclusion/tax-point logic, threshold and registration lifecycle, supplier readiness/outreach/sector-aware collection, emissions and verification evidence, document lineage, validation, Carbon Price Relief, deterministic calculation, returns, payment, amendment, repayment, assessments, penalties, reviews/appeals, artificial-separation directions, record-preservation, audit/retention, security, operations and regulatory reference-data management. No undocumented regulatory behaviour should be invented in implementation; where a point is not yet published or confirmed, the product must use the open-decision/configuration mechanism.

# 30. v1.4 OFFICIAL SOURCE UPDATES

| Source | Date | Build use | URL |
|---|---|---|---|
| HMRC – Current qualifying carbon pricing schemes | 27 Aug 2026 | Provisional QCPS list; effective-date/reference-data seed only. | https://www.gov.uk/government/publications/uk-cbam-current-qualifying-carbon-pricing-schemes |
| HMRC – System Boundaries Document v1.00 | 10 Jul 2026 | Defines aggregated goods categories, GHGs, functional units, precursors and system boundaries. | https://www.gov.uk/government/publications/carbon-border-adjustment-mechanism-force-of-law-notice-and-reference-document/carbon-border-adjustment-mechanism-system-boundaries-document-version-100 |
| HMRC – Force of law notices/reference document | 13 Jul 2026 | Tracks notice status/commencement and the Carbon Pricing Verification Form/System Boundaries references. | https://www.gov.uk/government/publications/carbon-border-adjustment-mechanism-force-of-law-notice-and-reference-document |
| Legislation.gov.uk – Interest (Appointed Day) Order 2026, SI 2026/994 | 2026 | Reference for CBAM interest commencement. | https://www.legislation.gov.uk/uksi/2026/994/contents |
| Legislation.gov.uk – Emissions and Verification Regulations 2026, SI 2026/995 | 2026 | Statutory emissions/verification rules. | https://www.legislation.gov.uk/uksi/2026/995/contents |
