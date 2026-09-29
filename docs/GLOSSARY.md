# Glossary

Plain meanings of the words used in this project. Legal meaning comes from the
sources in the regulatory source registry; this list is only a guide.

| Term | Meaning |
|---|---|
| **CBAM** | Carbon Border Adjustment Mechanism. A UK charge on the carbon emitted when making certain imported goods. Starts 1 Jan 2027. |
| **CBAM good** | An imported good whose commodity code is in the CBAM scope list (aluminium, cement, fertiliser, hydrogen, iron & steel). |
| **Commodity code** | The 8/10-digit customs classification of a good. Scope is decided from the code in force at the tax point. |
| **CDS** | Customs Declaration Service — HMRC's import declaration system. Our source of import data (as exports/uploads). |
| **Declaration / line** | One customs declaration, which has one or more goods lines. |
| **Importer** | The person liable for CBAM on the import. Not the same as the declarant. |
| **Declarant / customs agent / broker** | The party who submits the customs declaration, sometimes on the importer's behalf. Not liable just for declaring. |
| **Liable person** | The person legally responsible for CBAM on a good (R1-036). |
| **Tax agent** | A person authorised to prepare/submit CBAM returns for the liable person. Cannot register them and does not become liable. |
| **EORI** | Economic Operator Registration and Identification number. GB… for Great Britain, XI… for Northern Ireland. |
| **Tax point** | The legal moment CBAM is charged on a good — normally when it becomes subject to import duty (or would be), or when it enters the UK if no duty applies. Special procedures have their own triggers. |
| **Tax-point quarter** | The calendar quarter of the tax point. Needed in the 2027 annual return. |
| **Accounting period** | The period a return covers: calendar year 2027, then quarters. |
| **Special customs procedure** | Customs regimes that delay or change duty: storage/free zones (freeports, warehousing), inward processing, outward processing, authorised use (end-use), temporary admission. |
| **Registration threshold** | £50,000 of CBAM goods. **Forward test:** you expect ≥ £50k in the next 30 days (any day). **Backward test:** you had ≥ £50k in the previous 12 months (checked on the 1st of each month; 2027 look-back starts 1 Jan 2027). Earliest date wins. |
| **Registrable person** | Someone who has met the threshold, whether or not the HMRC service is open yet. Must keep records and return. |
| **Pre-registration mode** | Our mode from 1 Jan 2027 until registration: keep all records and deadlines even though HMRC's service may not be open. |
| **Non-preferential origin** | The customs "country of origin" used for CBAM (not the trade-deal preferential origin). UK-origin goods can be exempt with evidence. |
| **Installation** | A factory/plant that produces the good. One supplier can have many. |
| **Monitoring period** | The period over which the installation measured emissions. |
| **Embedded (embodied) emissions** | Greenhouse gas emitted making the good, in tonnes of CO2 equivalent (tCO2e). |
| **CO2e** | CO2 equivalent: other gases (N2O, CF4, C2F6) converted to CO2 with prescribed factors. |
| **Emissions intensity** | tCO2e per functional unit of good (usually per tonne). Reported to 5 decimal places. |
| **Functional unit** | The unit emissions are measured against — usually tonnes of good; clinker basis for some cement, nitrogen content for some fertilisers. |
| **Direct / indirect emissions** | Scope. Direct = from the production process. Indirect = from electricity used. UK CBAM 2027 covers direct only; indirect is modelled but inactive. |
| **Precursor** | An input good that is itself a CBAM good (e.g. crude steel used to make steel tubes). Its emissions are **upstream direct** emissions — a *source*, not a third scope. |
| **System boundary** | HMRC's definition of which processes and precursors count for a good (System Boundaries Document v1.00). |
| **Production route** | The method used (e.g. EAF vs blast furnace steel). Drives which data and boundary apply. |
| **Actual emissions** | Installation-measured, verifier-verified figures. |
| **Default values** | Treasury-published figures used when actual verified data is unavailable. |
| **Verifier** | Accredited independent body that checks the installation's emissions report. |
| **Verification report / good-specific verification summary** | Two distinct verifier evidence documents. Never merged into one type. |
| **CPR (Carbon Price Relief)** | Reduction in CBAM for carbon price already paid abroad under a qualifying scheme; per scheme; capped at liability. |
| **Carbon Pricing Verification Form** | The evidence document for a CPR claim; must cover one of the two calendar years before the import year. |
| **Qualifying carbon-pricing scheme** | A foreign carbon price HMRC accepts for CPR (reference data). |
| **Nil return** | A return showing no liability. Still required for registrable persons. |
| **Amendment** | Correction of an error in a filed return. Cannot replace default emissions with actual emissions (legal lock). |
| **SAO** | Senior Accounting Officer. The handbook names SAO as approver; whether this is a legal CBAM role is open (LEGAL-DEC-005). |
| **Force-of-law notice** | HMRC notices that carry legal effect once commenced (1 Jan 2027). Drafts must stay inactive. |
| **Effective-dated** | A value that has `effective_from` / `effective_to` dates, so the right version applies to each transaction date. |
| **Legal hold** | A block on deleting records because of an investigation, HMRC direction or dispute. |
| **Magic link** | A secure, expiring, single-case link that lets a supplier answer without an account. |
| **R1 / R2 / R3** | The three releases: Data Machine / Validation & Intelligence / Calculation & Filing. |
| **Pilot cut / Live cut** | The two R1 milestones: first real client vs ready for 1 Jan 2027. |
| **Golden fixture** | A fixed worked example (e.g. 48.2 t Turkish EAF steel) used as a permanent regression test. |
