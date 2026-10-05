# Database design

Supabase PostgreSQL. Business tables live in schema `cbam` (not exposed through the
Supabase Data API). Supabase owns the `auth` and `storage` schemas; we never write
to them directly. Migrations with Alembic (schema `cbam` only). This document fixes the conventions and the
minimum table set (spec §10, §21). Table names are final once migrated; column
lists here are the minimum — add columns as requirements need them.

## 1. Conventions

| Topic | Rule |
|---|---|
| Keys | `id uuid primary key` (UUIDv7 generated in app) |
| Tenancy | `tenant_id uuid not null references tenants` on every business table; first column of most indexes |
| Timestamps | `created_at timestamptz not null default now()`, `created_by uuid`; `updated_at` only on mutable rows |
| Concurrency | `row_version integer not null default 1` on mutable/reviewable rows (R1-045) |
| Versioned facts | `supersedes_id uuid null references <same table>`; current = not superseded (partial unique index) |
| Effective dating | `effective_from date not null`, `effective_to date null` (exclusive) + exclusion constraint on `daterange` |
| Money / numbers | See `docs/TECHNICAL_SPEC.md` §5. Never `real`/`double precision` |
| Enums | `text` + `CHECK` constraint (easier to extend than PG enums) |
| One-way states | Legal transitions (e.g. return `filed`, decision `approved`) are guarded by a trigger that rejects changes to locked rows, in addition to the app check (handbook §11) |
| Soft delete | Not used for business records. Records are superseded or closed, never hidden |
| Naming | `snake_case`, plural tables, `<table>_id` foreign keys, units in column names |
| JSON | `jsonb` only for raw source rows, before/after audit snapshots, and form answers; queried fields get real columns |

## 2. Row Level Security

```sql
alter table import_lines enable row level security;
alter table import_lines force row level security;
create policy tenant_isolation on import_lines
  using (tenant_id = current_setting('app.tenant_id')::uuid)
  with check (tenant_id = current_setting('app.tenant_id')::uuid);
```

- The app connects as role `cbam_app` (no `BYPASSRLS`, not table owner, no access to
  `auth`/`storage` schemas). Never as `postgres` or with the `service_role` key.
- Migrations run as `cbam_owner`.
- The `cbam` schema is removed from Supabase's "exposed schemas" list, and
  `anon`/`authenticated` roles get no privileges on it (tested).
- A test iterates every table with a `tenant_id` column and fails if RLS is not
  enabled + forced (so a new table cannot forget it).

## 3. Audit table (append-only)

```sql
create table audit_events (
  id uuid primary key,
  tenant_id uuid,                      -- null for platform events
  occurred_at timestamptz not null default now(),
  actor_type text not null check (actor_type in ('user','supplier','system','job')),
  actor_id uuid,
  action text not null,                -- e.g. 'import_line.scope_decided'
  object_type text not null,
  object_id uuid not null,
  before jsonb, after jsonb,
  reason text,
  request_id text,
  prev_hash bytea, hash bytea not null
);
create function audit_block_change() returns trigger language plpgsql as
$$ begin raise exception 'audit_events is append-only'; end $$;
create trigger audit_no_update before update or delete on audit_events
  for each row execute function audit_block_change();
revoke update, delete, truncate on audit_events from cbam_app;
```

`hash = sha256(prev_hash || canonical_json(row without hash))`, chained per tenant.

## 4. Tables by domain

### Organisation & access (R1)
- `tenants` (id, name, status)
- `organisations` (tenant_id, legal_name, business_type, address jsonb, gb_eori, xi_eori, vat_number, vat_status, acts_as: `liable_person|agent`)
- `users` (id = Supabase `auth.users.id`, email, display_name, status) — profile only; passwords and MFA secrets stay in Supabase Auth
- `memberships` (user_id, tenant_id, roles text[])
- `support_access_grants` (platform_user_id, tenant_id, reason, starts_at, expires_at)
- `approval_roles` (tenant_id, role_name, permissions) — configurable approver (LEGAL-DEC-005)
- `liable_person_determinations` (tenant_id, declaration_id, candidate_party_id, rule_version, evidence)

### Reference data & sources (R1-050, R2-020)
- `regulatory_sources` (source_id text unique, title, source_type, url, publication_date, status `draft|laid|in_force|commenced|superseded`, commencement_date, effective_from/to, retrieved_at, checksum, supersedes_source_id, notes)
- `ref_datasets` (name unique) · `ref_dataset_versions` (dataset_id, version, source_id, checksum, status `pending|active|retired`, loaded_at, activated_by, activated_at, impact_report jsonb)
- `platform_domain_owners` (user_id) — the people who may activate reference data or put a source in force (ADR-0003). Granted by an operator on the database, never through the app. Like every `cbam` table these have forced RLS; the policies are open, and the guard is the grants plus triggers: data rows only enter a `pending` version and never change; a version leaves `pending` only for a domain owner; a source is registered `draft`/`laid` unless a domain owner says otherwise; nothing is deleted.
- One table per dataset, each with `dataset_version_id`, `effective_from`, `effective_to` + business columns, e.g.:
  - `ref_cbam_commodity_codes` (code_prefix, listing_text, sector, description, greenhouse_gases, in_scope, exclusion_within) — listed headings and sub-headings, longest-prefix lookup; `in_scope=false` rows are HMRC's "Except" entries
  - `ref_threshold_rules` (threshold_gbp, forward_days, backward_months, backward_test_day, lookback_floor_date)
  - `ref_registration_rules` (rule `ordinary_30_day|first_year_transitional`, days, fixed_deadline)
  - `ref_service_state` (service, opening_date)
  - `ref_tax_point_rules`, `ref_exclusion_rules`, `ref_origin_rules`, `ref_geography_rules`
  - `ref_sector_forms` (sector, code_pattern, gases, functional_unit, routes, questions jsonb, evidence_slots)
  - `ref_working_days` (jurisdiction, day, is_working_day)
  - `ref_cds_report_layouts` (report_type, column, maps_to, required) — HMRC "Get customs data" layouts (R1-054)
  - `ref_customs_monthly_exchange_rates` (currency, month, rate) — customs value conversion only (R1-035)
  - `ref_eu_template_mappings` (template_version, sheet, cell_or_column, maps_to_field) (R1-055)
  - `ref_linked_ets_jurisdictions` (jurisdiction, exemption basis) — empty until an agreement commences
  - `ref_compliance_calendar` (period, return_due, payment_due) — seeded `pending` from the policy summary (REG-DEC-007)
  - R2/R3: `ref_gas_factors`, `ref_functional_units`, `ref_production_routes`, `ref_system_boundaries`, `ref_default_emissions`, `ref_default_methodology`, `ref_validation_rules`, `ref_verification_rules`, `ref_evidence_types`, `ref_carbon_price_schemes`, `ref_exchange_rates`, `ref_cbam_rates`, `ref_compliance_calendar`, `ref_penalty_rules`, `ref_interest_rules`, `ref_retention_rules`, `ref_payment_methods`, `ref_precursor_allocation_rules`, `ref_transition_packages`, `ref_enforcement_case_types`

Exclusion constraint (as built: only one version of a dataset is active, so non-overlap within a version is enough; `btree_gist` is required):

```sql
alter table ref_cbam_commodity_codes add constraint ref_cbam_commodity_codes_no_overlap
  exclude using gist (dataset_version_id with =, code_prefix with =,
                      daterange(effective_from, effective_to) with &&);
```

### Decisions (all releases)
- `decisions` (tenant_id, subject_type, subject_id, rule_id, rule_version, dataset_version_ids uuid[], input_fingerprint bytea, outcome text, reason text, details jsonb, as_of date, supersedes_id)

### Customs (R1)
- `import_batches` (built in migration 0009: tenant_id, file_sha256 `char(64)` null for manual entry, document_version_id, filename, acquisition_method `get_customs_data|cds_export|data_request|manual_upload|manual_entry|feed`, cds_report_type `import_item|import_header|import_tax_lines|export_item|null`, eori `^(GB|XI)[0-9]{12}$`, window_start, window_end, source_owner, acquired_on, idempotency_key, request_fingerprint `bytea` (SHA-256 of the declared details), status `received|queued|parsing|validating|normalising|completed|completed_with_errors|failed|rejected`, rows_total/rows_processed/rows_valid/rows_rejected, lines_created/lines_unchanged, failure_reason, row_version). Unique per tenant on `file_sha256` and on `idempotency_key` (partial: non-null and status not `failed`/`rejected`, so a failed or rejected batch never blocks sending the same bytes again). `failure_reason` is a code (`^[a-z0-9_]{1,64}$`). `(tenant_id, document_version_id)` is a composite foreign key, so a batch cannot point at another tenant's file. A trigger lets only status, counters, `failure_reason`, `row_version` and `updated_at` change; status moves forward only and terminal batches are locked (`modules/imports/rules.py` `batch_transition` is the matching application rule); no delete. Migration 0010 adds `report_layout_version_id` (foreign key to `ref_dataset_versions`; the layout version the batch was read with; once set it cannot change) and `layout_status` (`matched|not_active|columns_missing|unreadable|invalid`), an `attempts` counter (incremented on a first start or a takeover of a LOST worker's expired lease, never by a duplicate delivery or by a start after a lease was handed back cleanly after a handled failure; it can never go down, by trigger; above `IMPORT_MAX_ATTEMPTS` the batch is failed as a crash loop) and `lease_expires_at` (renewed by the job after every chunk; an expired lease lets the sweeper take the batch over), and a unique `(tenant_id, id)` key for composite foreign keys.
- `customs_data_coverage` (tenant_id, eori, report_type, covered_from, covered_to, batch_id) — drives the coverage calendar and gap detection (R1-054)
- `customs_data_access` (tenant_id, eori, third_party_access_granted, granted_on, checked_on, notes) (R1-054)
- `source_rows` (built in migration 0010: tenant_id, batch_id, row_number >= 1 (data rows, the header is not a row), raw jsonb header -> cell text exactly as read (extra cells under `__extra_cells__`), row_sha256, created_at; unique `(batch_id, row_number)`; composite foreign key `(tenant_id, batch_id)`; forced RLS; immutable by trigger (also for the owner and TRUNCATE) and with UPDATE/DELETE/TRUNCATE revoked from `cbam_app`)
- `row_exceptions` (migration 0010: tenant_id, batch_id, source_row_id null = whole-file problem, row_number (0 = file), field, code `^[A-Z0-9_]{1,64}$`, severity `error|warning`, fixed-text message (never a cell value), status `open|resolved|waived`, resolved_by/at, resolution_reason, row_version; unique `(batch_id, row_number, field, code)` so a retried job cannot insert twice; composite foreign keys to the batch and the source row; forced RLS; a trigger allows only the resolution columns to change and only away from `open`; no delete; `cbam_app` has UPDATE only on the resolution columns)
- `ref_cds_report_layouts` gains an optional `date_format` (strptime pattern for a date column) in migration 0010; its `v_active_` view is rebuilt
- `parties` (migration 0011: tenant_id, `eori` null or `^(GB|XI)[0-9]{12}$`, `name` null (a business name can be personal data: never logged), created_at; partial unique `(tenant_id, eori)` where eori is not null; append-only). A party is identified by its EORI; the platform creates one only when a report gives an EORI (no names are mapped yet).
- `declarations` (0011: tenant_id, mrn (1 to 100 characters), version, `supersedes_id` (unique, composite foreign key; a trigger checks the chain), `acceptance_date` date AS THE REPORT GAVE IT (not a tax point), acceptance_at, procedure_code, additional_procedure_codes text[], importer_party_id, declarant_party_id, representative_party_id (composite foreign keys to `parties`), `representation_type` `self|direct|indirect|unknown` (`unknown` unless the file says; never inferred), `eori_context` `GB|XI` (prefix of the importer EORI), entry_method `cds|gcd|manual|correction`, batch_id, content_sha256, created_at; unique `(tenant_id, mrn, version)`). Party roles are facts as reported; the liable-person determination is Phase 3 step 6.
- `import_lines` (0011: tenant_id, declaration_id, item_no, version, `supersedes_id` (unique, chain-checked by trigger), `commodity_code` `^[0-9]{8,10}$` exactly as given, description, `net_mass_kg` NUMERIC(20,6) >= 0, supplementary_qty NUMERIC(20,6) + supplementary_unit (not mapped yet), `customs_value_source` NUMERIC(24,8) + `customs_value_currency` char(3), `customs_value_gbp` NUMERIC(18,2) set ONLY when the currency is GBP and needs no rounding (check constraint), `customs_value_gbp_note` short code (`non_gbp_no_fx`, `gbp_more_than_2dp`), fx_method (null until Phase 10, R1-035), valuation_basis as declared, `value_source` `declared|manual|correction` (R1-010: how the value was derived; anything but `declared` needs `value_override_reason`, and `correction` needs `supersedes_id`), country_of_origin_declared char(2), cpc, batch_id, `source_row_id` NOT NULL (composite foreign key to `source_rows`), entry_method, change_reason (short code, required from version 2), content_sha256; unique `(tenant_id, declaration_id, item_no, version)`; indexes `(tenant_id, commodity_code)`, `(tenant_id, declaration_id)`, `(tenant_id, batch_id)`). NO tax point, scope, quarter or threshold column: those are decided in Phase 4 and stored in their own tables, never on this one.
- `import_line_sources` (0011, lineage: tenant_id, import_line_id, source_row_id, report_type, `role` `primary|header|tax_line|duplicate_seen`; unique `(import_line_id, source_row_id, role)`; a source row has at most one `primary`/`duplicate_seen` link, by partial unique index). `primary` = the row the line was built from; `duplicate_seen` = an overlapping file showed the same facts again (kept as evidence, no new line); `header`/`tax_line` are for the report adapter (step 8a).
- **Current declaration.** A line keeps the `declaration_id` it was created under, which a later file may have superseded (a corrected header creates declaration version 2 and only the lines that file carries move to it). Anything that needs declaration facts must resolve the CURRENT declaration by MRN (the version nothing supersedes) and never read `declaration_id` directly: the ledger does this (`modules/imports/ledger.py` `current_declaration`) and returns `declaration_superseded` when they differ. Phase 4 tax-point logic must do the same. Rows rejected for file conflicts are not lines: Phase 5 must list them for human resolution and show the threshold as incomplete while they are open (REG-DEC-023).
- `hash_version` (0011, on `declarations` and `import_lines`) records the schema of the content hash (`rules.HASH_VERSION`, also mixed into the hash). Changing which fields are hashed needs a version bump AND a migration plan for the stored hashes, otherwise every row would look changed: `reconcile_version` does not compare `hash_version`. A CHECK allows known versions only, so a bump also changes the constraint. `row_exceptions` gains an index `(tenant_id, source_row_id)` for the ledger's open-exception filter.
- All four tables (0011) are append-only: forced row-level security, UPDATE/DELETE/TRUNCATE revoked from `cbam_app`, and a trigger blocks them for every role including the owner. A correction is a new version that supersedes the old one; the old one is kept. "Current" means no row supersedes it. `import_batches` also gains `lease_owner` (uuid token of the job that holds the lease; only that job may renew or release it).
- `cbam.impact_line_counts_by_code_prefix(prefixes text[])` (0011): SECURITY DEFINER, `set search_path = cbam, pg_temp`, owned by the NOLOGIN role `cbam_impact_reader` (only SELECT on `import_lines`, through a policy `impact_reader_select` for that role alone), execute revoked from public and granted to `cbam_app`; raises unless `cbam.is_platform()` is set and for more than 1000 prefixes; returns `(prefix, tenant_id, line_count)` for CURRENT lines whose commodity code starts with one of the digit-only prefixes: counts only, no ids or values. The role and the owner's membership of it are cluster-level and not dropped by the downgrade. See docs/SECURITY.md.
- `special_procedure_events` (import_line_id, procedure, event_type, event_date, value_basis, notes)
- `reconciliation_events` (tenant_id, kind `duplicate|amendment|missing_line|orphan|conflict`, refs, resolution)
- `forecasts` (tenant_id, expected_tax_point, expected_value_gbp, source `order|forecast|manual`, confidence, evidence_document_id, supersedes_id)
- `origin_records` (import_line_id, declared, validated, basis, evidence_document_ids, rule_version)

### Threshold & registration (R1)
- `threshold_snapshots` (tenant_id, test `forward|backward`, as_of, window_start, window_end, total_gbp, included_line_ids hash, result, decision_id)
- `threshold_events` (tenant_id, test_type, trigger_date, earliest_liability_date, decision_id)
- `registration_profiles` (tenant_id, status `monitor|registrable|registration_ready|submitted|registered|deregistered`, trigger_date, deadline, deadline_rule, hmrc_registration_id, registered_on, row_version)
- `registration_events` (profile_id, from_status, to_status, at, reason, evidence)
- `readiness_packs` (tenant_id, version, content jsonb, sector_estimates jsonb, estimate_method, declaration_state, declared_by, declared_at, document_id)
- `registration_changes` (tenant_id, field, old, new, detected_at, notification_due, notified_at, acknowledgement_ref)

### Suppliers, portal, outreach, documents (R1)
- `suppliers` (tenant_id, name, country, preferred_language, notes) · `installations` (supplier_id, name, country, address, identifier, monitoring_status, verifier_status)
- `supplier_contacts` (supplier_id, name, email, phone, language, lawful_basis) — personal data
- `installation_products` (installation_id, commodity_code, production_route)
- `readiness_answers` (installation_id, version, answers jsonb)
- `supplier_cases` (tenant_id, installation_id, products, monitoring_period, status, day0_at, evidence_owner, responsibility jsonb, row_version)
- `evidence_source_parties` (tenant_id, party kind `installation|supply_chain_party|verifier`, name, links)
- `magic_links` (case_id, token_hash, issued_at, expires_at, revoked_at, replaced_by_id, last_used_at)
- `portal_sessions` (magic_link_id, case_id, expires_at)
- `supplier_submissions` (case_id, version, supersedes_id, answers jsonb, answer_provenance jsonb (`SUPPLIER|EU_TEMPLATE`), form_definition_version, eu_template_document_id, submitted_at) — "not known yet" is an explicit answer state (R1-055, R1-056)
- `portal_help_texts` (sector, question_key, language, version, body, status `draft|approved|retired`) (R1-056)
- `supplier_questions` (case_id, question, asked_at, task_id, answer, answered_at) (R1-056)
- `outreach_templates` (key, language, version, body, status `draft|approved|retired`, approved_by)
- `outreach_messages` (case_id, template_version_id, contact_id, scheduled_for, sent_at, provider_message_id, status) · `email_events` (message_id, type, at, payload) · `email_suppressions` (email_hash, reason, at)
- `documents` (tenant_id, current_version_id) · `document_versions` (document_id, version, storage_key, sha256, size, mime_detected, original_filename, uploaded_by_type/id, scan_state, supersedes_id)
  - As built in migration 0009 (minimal, Phase 7 extends): `documents` (id, tenant_id, created_at, created_by) and `document_versions` (id, tenant_id, document_id, version, storage_key `tenants/{tenant_id}/{random uuid}` (random per version, not derived from the content; the SHA-256 is a column), sha256, size_bytes, mime_detected, original_filename, uploaded_by_type/id, scan_state `not_scanned|pending|clean|infected`, uploaded_at). Both are immutable (trigger plus no UPDATE/DELETE for `cbam_app`); versions reference documents by composite `(tenant_id, document_id)` keys; the current version is the highest `version` until `current_version_id` and `supersedes_id` arrive.
- `evidence_links` (document_version_id, object_type, object_id, purpose)

### Operations (R1)
- `tasks` (tenant_id, type, subject_type/id, title, due_date, due_rule, owner_id, status, escalation_level, row_version)
- `review_items` (tenant_id, kind, subject, status `open|assigned|resolved|reopened`, assignee, resolution, reason, row_version)
- `job_failures` (job_name, idempotency_key, tenant_id, error, attempts, last_at, resolved_at)
- `exports` (tenant_id, kind, params, status, document_id, generated_at)
- `digest_preferences` (user_id, monthly_digest_enabled) (R1-060, backlog)

### Shared installation network (R1-057 — detailed in ADR-0002)
- `platform_installations` (no tenant_id; platform-level identity: operator identifier, name, country, address hash)
- `installation_links` (tenant_id, installation_id → platform_installation_id, confirmed_by, confirmed_at)
- `share_grants` (platform_installation_id, grantee_tenant_id, submission_ids, granted_by_contact, granted_at, revoked_at)
  Tenants read shared submissions only through a view that joins active `share_grants`
  for `app.tenant_id`; RLS tests cover every path.

### R2 / R3 (tables named now, detailed when their phase starts)
R1 Live: `source_watch_results` (R2-031, moved earlier).
R2: `document_extractions`, `extracted_values` (page, bbox, confidence, processor), `processors`, `emission_records`, `gas_components`, `precursor_links`, `monitoring_periods`, `verifiers`, `accreditations`, `verification_records`, `verification_gaps`, `carbon_price_evidence`, `cpr_components_evidence`, `field_lineage`, `ref_cbam_cpr_exchange_rates` (quarterly CBAM rates; never the monthly customs rates).
R3: `calculations`, `calculation_operands`, `cpr_calculations`, `cpr_components`, `returns`, `return_versions`, `return_lines`, `approvals`, `submissions`, `submission_attempts`, `amendments`, `payments`, `repayment_claims`, `reimbursements`, `compliance_cases`, `case_deadlines`, `penalties`, `interest_charges`, `legal_holds`, `retention_schedules`, `connected_entities`, `closure_checklists`, `tenant_exports`.

## 5. Source activation rule (as a query)

A reference row may be used for a transaction on legal date `d` only if:

```
dataset_version.status = 'active'
AND source.status IN ('in_force','commenced','superseded')   -- superseded needs effective_to; see below
AND (source.commencement_date IS NULL OR source.commencement_date <= d)
AND row.effective_from <= d AND (row.effective_to IS NULL OR d < row.effective_to)
```

This lives in one SQL view per dataset (`v_active_<dataset>`), and services read only
from those views. A view cannot take the date, so it exposes `usable_from` / `usable_to`
(the row's period narrowed by the source's commencement and effective period) and the
lookup filters `usable_from <= d AND (usable_to IS NULL OR d < usable_to)`. The source
effective period is applied in addition to the rule above. A test runs the SQL view and
the pure rule in `refdata/rules.py` against the same cases.

## 6. Migrations

- One Alembic revision per PR at most; message names the requirement ID.
- Every migration has a working `downgrade` (tested in CI: up → down → up).
- Production changes use expand → migrate data → contract across separate releases.
- Never edit a merged migration.
- Reference data is **not** loaded by migrations; it is loaded by the refdata loader.

## 7. Indexing starting points

- `import_lines (tenant_id, commodity_code)`, `(tenant_id, declaration_id)`, `(tenant_id, batch_id)` (built); tax-point indexes belong to the Phase 4 tax-point table
- `decisions (tenant_id, subject_type, subject_id)`
- `tasks (tenant_id, status, due_date)`
- `audit_events (tenant_id, object_type, object_id, occurred_at)`
- `magic_links (token_hash)` unique
Check with `EXPLAIN ANALYZE` in the 10,000-line load test before adding more.
