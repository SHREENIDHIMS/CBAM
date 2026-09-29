<!-- Text transcription of CBAM_Team_Handbook.pdf (image-only scan, 6 pages), made for search.
The PDF is the source of truth. Handwritten margin notes are not transcribed.
Where the handbook conflicts with the v1.4 spec, the spec wins (it corrects the handbook);
see docs/GAP_ANALYSIS.md §9. Do not edit. -->

# CBAM Platform — Team Handbook

Part 1: What CBAM is, from zero · Part 2: What we build, in what order, by when
VLookup Business Solutions · For the development team (no prior knowledge assumed) · 29 September 2026

**How to use this handbook:** Part 1 (Sections 1–6) teaches CBAM from nothing — read it fully before touching Part 2. Part 2 (Sections 7–12) is the development plan: releases, week-by-week schedule, team, and standing rules. Deep regulatory reference lives in the companion document `CBAM-Complete-Workflow.docx`; architecture and data model live in `CSorted-Platform-Technical-Specification.docx` (Parts A3, C3, D, E).

## PART 1 — CBAM explained from zero

**CBAM in one sentence:** From 1 January 2027, UK businesses that import certain carbon-heavy goods (steel, aluminium, cement, fertilisers, hydrogen) must pay a tax based on how much carbon dioxide was released when those goods were made in the overseas factory — and it is the IMPORTER's job to find out that number, prove it, calculate the tax, and pay HMRC.

### 1 — Why does this tax exist?
UK factories already pay for CO2 through the UK ETS. Overseas factories without a carbon charge can undercut them ("carbon leakage"). CBAM puts an equivalent carbon charge on imported goods at the border. Analogy: a visa fee based on behaviour — clean factory = small fee, dirty factory (or one that refuses to say) = big fee.

### 2 — Who is caught by it?
| Question | Answer |
|---|---|
| Which goods? | Only 5 sectors: aluminium, cement, fertilisers, hydrogen, iron & steel. Each good is identified by its customs CN code (8-digit). If the CN code is on HMRC's CBAM list, the good is in scope. |
| Which businesses? | Any UK importer whose CBAM goods are worth £50,000 or more — tested two ways: (a) looking back over any rolling 12 months, (b) looking forward: expected to cross £50k in the next 30 days. Cross either test → must register with HMRC within 30 days. |
| Who is liable? | The importer (the "liable person"). Not the overseas factory, not the shipping company. A named human at the importer — the Senior Accounting Officer (SAO) — signs the returns and is personally responsible for their accuracy. |
| When? | Tax applies to goods imported from 1 January 2027. First return covers the whole of 2027 and is due 31 May 2028. After that: quarterly returns. |

### 3 — The key idea: the tax depends on a number only the overseas factory knows
Embedded emissions = tonnes of CO2 released to make each tonne of product (modern EAF steel ≈ 0.4; old coal-fired ≈ 2.0+).

| Option | What it means | Consequence |
|---|---|---|
| A — Actual data | Ask the overseas factory for its real, measured emissions number (with evidence) | Usually a much lower tax. Also unlocks Carbon Price Relief |
| B — Default values | Use HMRC's published standard number for that product type | Deliberately set high. No relief allowed. Once a return is filed using defaults, it can never be corrected later |

**Single most important fact:** worked example — 48.2 tonnes of steel from a modern Turkish plant: £785.25 with actual verified data; £4,771.80 with HMRC defaults — six times more on one shipment. "Our platform exists to win this data race."

### 4 — How CBAM works, start to finish
1. **Goods arrive in the UK** — customs paperwork (CDS) records CN code, weight, value, origin, supplier. Platform imports the file and checks each CN code against HMRC's CBAM list. *(Importer / customs agent → platform reads the file.)*
   - **Decision:** CBAM goods and £50k crossed (either test)? YES → step 2. NO → keep monitoring the rolling total monthly; alert at 80%.
2. **Register with HMRC** — within 30 days of crossing; needs EORI, VAT number, company details, named SAO. Year-one grace: anyone liable during 2027 has until 31 January 2028. *(Client, guided by our checklist; platform tracks status.)*
3. **Ask the overseas factory for its emissions data** — per installation, structured request in the supplier's language: CO2 per tonne (Scope 1 / direct), production method, fuels used, monitoring year, any carbon tax paid at home. Auto-reminders Day 7, 14, 21. *(Platform, automatically; supplier answers via phone-friendly web form.)*
   - **Decision:** usable data within 28 days? YES → step 4. NO → HMRC defaults (punitive; relief blocked; cannot be amended once filed).
4. **Check the data is believable** — AI extracts numbers from uploads; rules check: CO2 figure present? Monitoring year matches import year? Within plausible range (±50% of sector benchmark)? Production method valid? Anything odd → human specialist. *(Platform AI + rules → human review queue.)*
5. **Carbon Price Relief** — if the factory paid carbon tax at home (e.g. Turkey's ETS), deduct it — only with two proofs: an official certificate of carbon price paid (naming exact factory and year) and an independent ISO-accredited verifier certificate. No proofs = no discount.
6. **Calculate the tax** — per import line: Embedded CO2 = (CO2 per tonne) × (shipment tonnes). Tax = Embedded CO2 × (CBAM rate − CPR). CBAM rate published by HMRC each quarter per sector (derived from UK carbon market prices). Never below £0. Calculated separately for every customs declaration × CN code × factory — never lumped. *(Every number traceable to its source document.)*
7. **Prepare and approve the return** — one line per declaration/CN/factory with weight, emissions, rate, relief, tax, each linked to evidence. Client's SAO reviews and personally approves — a human click, always.
8. **File with HMRC and pay** — first period all of 2027, due 31 May 2028; then quarterly. Evidence kept 6 years; full evidence pack in one click. *(Client files — platform produces exactly what to enter; platform archives everything.)*

Then the cycle repeats every shipment and quarter.

### 5 — Jargon translator
CBAM; HMRC; CN code (8-digit product code); CDS (Customs Declaration Service — main data source); EORI; Installation (the specific overseas factory — tax is per factory); Embedded emissions; Scope 1 (direct; the only emissions taxed from 2027; "electricity-related Scope 2 joins from 2029"); Default values; CBAM rate (£ per tCO2, per sector per quarter); CPR; Verifier (e.g. Bureau Veritas, SGS; accredited to ISO 17029 + ISO 14065); SAO; Liable person.

### 6 — What our tool automates
| Manual reality | Platform |
|---|---|
| Re-typing customs paperwork into spreadsheets | Imports the CDS file; every line classified automatically |
| Nobody notices £50k until HMRC writes | Rolling total recalculated nightly, both tests; alert at 80%, alarm at breach with the 30-day clock |
| Emailing 30 factories in 6 countries | Multilingual requests, phone-friendly form, Day 7/14/21 chasing, Day 28 escalation |
| Squinting at a Turkish PDF | AI extracts numbers; rules check plausibility; humans review flagged ones |
| Untouchable spreadsheet formula | Tested calculation engine; worked example is a permanent automated test |
| Shoebox of PDFs at audit | Every figure linked to its source; 6-year evidence pack in one click |

## PART 2 — Development kickoff plan

**The one thing to understand:** CBAM goes live 1 January 2027, but the first return is not due until 31 May 2028. The tax calculator is not needed in January. What is needed on 1 January is the DATA CAPTURE MACHINE: imports logged, £50k threshold monitored, supplier outreach firing. 2027 emissions data cannot be collected retroactively. "The data race is the product. The calculator comes second."

### 7 — Regulatory status check (Sept 2026)
- Three SIs laid 13 July 2026 (Administrative Provisions; Rate Calculation & CPR — SI 2026/809; Transitory Provisions), in force 1 Jan 2027. HMRC guidance published August 2026.
- "HMRC registration opens via Government Gateway in Q4 2026." *(Superseded by spec v1.4: by 1 Jan 2028.)*
- HMRC has issued a Carbon Price Verification Form for CPR (installation, scheme, emissions data). Supplier portal fields must map onto this form.
- Rate = average UK ETS auction price for the preceding quarter minus a free-allowance adjustment, per sector, published quarterly. Store as reference data per sector per quarter.
- Still draft: Emissions & Verification Regulations. Build validation rules as configurable data.

### 8 — Build order: three releases, dated by law
| Release | What ships | Why |
|---|---|---|
| R1 — Data Capture | Imports register (CSV import of CDS + manual entry) · CN-code scope checker · rolling £50k monitor (backward 12-month and forward 30-day) · client registration checklist (EORI, VAT, SAO) · supplier + installation register · outreach engine with Day 7/14/21/28 chase · tokenised supplier portal (form mirrors the EU template + HMRC Carbon Price Verification Form) · document upload + storage · ops dashboard · audit log | Outreach must fire to every supplier before 1 Jan |
| R2 — Validation & Intelligence | Claude API document extraction (monitoring reports, ETS certificates, verifier certs → structured JSON) · validation rules engine (~10 rules from step 4: Scope 1 present, period matches, ±50% plausibility, method valid, cert names installation, verifier ISO 17029 + 14065, precursor consistency) · human review queue · RAG (red/amber/green) compliance dashboard per client · CPR evidence tracker | Supplier responses arrive Jan–Mar in volume |
| R3 — Calculation & Filing | Calculation engine (pure function: embedded × (rate − CPR), floor £0, per declaration × CN × installation) · quarterly rate reference admin · liability forecasts per client · return generator with SAO approval workflow · evidence pack generator · the hard locks (defaults filed = permanent, defaults block CPR) | A full quarter of dry-runs before the first return is due |

**Rule:** nothing from R3 gets built during R1.

### 9 — Plan to R1 (gates, durations removed)
| Workstream | Deliverable / gate |
|---|---|
| Setup + reading | Handbook + companion docs read; repos (app, api), CI/CD, Supabase project (EU region), envs (local/staging/prod), Sentry. GATE: everyone can explain the £50k two-test threshold and why defaults are poison |
| Foundations | Schema per tech-spec Part C (shared core + `cbam_` tables), Row Level Security policies + tests, auth (ops/client roles), INSERT-only `audit_log`, seed data: CBAM CN codes list, sectors. GATE: RLS proven — client A cannot read client B in an automated test |
| Imports register | CSV import of CDS export format (real sample from a freight forwarder), field validation, CN scope check against seeded list, manual entry form, imports list UI. GATE: 500-row CDS file imports cleanly with errors reported per row |
| Threshold monitor + client onboarding | Nightly rolling-12-month value per client + 30-day forward test, alert at 80% and at breach, registration checklist UI (EORI/VAT/SAO). GATE: threshold maths verified against 5 hand-calculated scenarios |
| Supplier outreach + portal | Supplier/installation register, data_request creation, multilingual templates (EN/TR/ZH/HI/DE first), Resend integration, chase scheduler (Celery), tokenised portal: structured form + file upload, mobile-first. GATE: full Day 7/14/21/28 sequence runs in staging (minutes-mode) end to end |
| Ops dashboard + documents | Per-client view: imports, threshold status, outreach status per supplier, documents received, deadline list. Document storage with versioning. GATE: ops can answer "where is client X?" in one screen |
| Hardening + pilot onboarding | Pen-test basics, backup/restore drill, load test (10k imports), UAT with Jenny + ops using the worked example as the test script. GATE: R1 sign-off — a real pilot client's data loaded and outreach sent |

### 10 — Team shape
Tech lead; Backend dev (Python: FastAPI, Celery chase engine, threshold calc, CSV import); Frontend dev (ops dashboard, client portal, supplier portal mobile-first); QA (threshold-maths suite, RLS tests, chase-sequence simulation, UAT scripts); Domain owner — Jenny + ops (CN code list accuracy, email template wording, HMRC form mapping, UAT, supplier language review; first task: obtain a real CDS export sample, the HMRC Carbon Price Verification Form, the EU Communication Template). Minimum viable team: 3 devs + QA + Jenny. If fewer, R1 scope holds and R2 slips — never the reverse.

### 11 — Standing rules
- The law is data, not code. Rates, defaults, CN codes, validation thresholds, chase schedules — all reference tables editable by ops, never constants in code.
- Legal state transitions are one-way. A filed return locks. Build these as database constraints AND application checks — not UI disablement.
- Every state change writes to the INSERT-only audit log with actor, before/after, timestamp. Six-year retention.
- The worked example (48.2 t Turkish EAF steel: £785.25 actual vs £4,771.80 default) is the permanent golden test; it runs in CI forever.
- Suppliers get magic links, never passwords. If a factory manager in Turkey can't complete the form on a phone in under 10 minutes, the portal has failed — test exactly that.
- Nothing auto-files, ever. AI extracts, rules validate, humans approve.
- Demo against the gates, not task lists. A gate not met = talk scope, not extend dates.
- British English in all user-facing text. Dates "14 March 2027". Currency £ with thousands separators.

### 12 — Parallel (non-dev) blockers
| Action | Why it blocks dev |
|---|---|
| Obtain a real CDS export file, the HMRC Carbon Price Verification Form, the EU Commission Communication Template (Excel) | Import parser and portal form fields are designed from real artefacts, not guesses |
| Decide product/brand name | Needed for email domain, portal URL, templates |
| Chamber briefing + recruit 2–3 pilot clients | UAT needs a real client's import data |
| Contact 2 verifier bodies (Bureau Veritas, SGS) | R2 CPR validation needs real verifier certificates |
| Onboard pilot clients on R1; load supplier lists; queue outreach | The entire January value proposition |

Companion documents: `CBAM-Complete-Workflow.docx` (regulatory detail) · `CSorted-Platform-Technical-Specification.docx` (architecture & data model).
