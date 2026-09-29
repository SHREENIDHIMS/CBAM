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
- One table per dataset, each with `dataset_version_id`, `effective_from`, `effective_to` + business columns, e.g.:
  - `ref_cbam_commodity_codes` (code, sector, description, in_scope, exclusion_note)
  - `ref_threshold_rules` (threshold_gbp, forward_days, backward_months, backward_test_day, lookback_floor_date)
  - `ref_registration_rules` (rule `ordinary_30_day|first_year_transitional`, days, fixed_deadline)
  - `ref_service_state` (service, opening_date)
  - `ref_tax_point_rules`, `ref_exclusion_rules`, `ref_origin_rules`, `ref_geography_rules`
  - `ref_sector_forms` (sector, code_pattern, gases, functional_unit, routes, questions jsonb, evidence_slots)
  - `ref_working_days` (jurisdiction, day, is_working_day)
  - R2/R3: `ref_gas_factors`, `ref_functional_units`, `ref_production_routes`, `ref_system_boundaries`, `ref_default_emissions`, `ref_default_methodology`, `ref_validation_rules`, `ref_verification_rules`, `ref_evidence_types`, `ref_carbon_price_schemes`, `ref_exchange_rates`, `ref_cbam_rates`, `ref_compliance_calendar`, `ref_penalty_rules`, `ref_interest_rules`, `ref_retention_rules`, `ref_payment_methods`, `ref_precursor_allocation_rules`, `ref_transition_packages`, `ref_enforcement_case_types`

Exclusion constraint example:

```sql
alter table ref_cbam_commodity_codes add constraint no_overlap
  exclude using gist (code with =, daterange(effective_from, effective_to) with &&)
  where (dataset_version_status = 'active');   -- via a generated/denormalised column
```

### Decisions (all releases)
- `decisions` (tenant_id, subject_type, subject_id, rule_id, rule_version, dataset_version_ids uuid[], input_fingerprint bytea, outcome text, reason text, details jsonb, as_of date, supersedes_id)

### Customs (R1)
- `import_batches` (tenant_id, file_sha256 unique per tenant, filename, document_id (file in Supabase Storage), acquisition_method `cds_export|data_request|manual_upload|feed`, source_owner, acquired_on, status, row_counts)
- `source_rows` (batch_id, row_number, raw jsonb, row_sha256) — immutable
- `row_exceptions` (batch_id, row_number, field, code, message)
- `declarations` (tenant_id, mrn, version, supersedes_id, acceptance_at, procedure_code, importer_party_id, declarant_party_id, agent_party_id, representation_type)
- `parties` (tenant_id, name, eori, role hints)
- `import_lines` (tenant_id, declaration_id, line_no, commodity_code, description, net_mass_kg NUMERIC(20,6), supplementary_qty, customs_value_source NUMERIC(24,8), customs_value_currency, customs_value_gbp NUMERIC(18,2), fx_method, valuation_basis, country_of_origin_declared, origin_validated, geography, tax_point_state, tax_point_date, tax_point_quarter, source_row_id, entry_method `cds|manual`, supersedes_id, row_version)
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
- `supplier_submissions` (case_id, version, supersedes_id, answers jsonb, form_definition_version, submitted_at)
- `outreach_templates` (key, language, version, body, status `draft|approved|retired`, approved_by)
- `outreach_messages` (case_id, template_version_id, contact_id, scheduled_for, sent_at, provider_message_id, status) · `email_events` (message_id, type, at, payload) · `email_suppressions` (email_hash, reason, at)
- `documents` (tenant_id, current_version_id) · `document_versions` (document_id, version, storage_key, sha256, size, mime_detected, original_filename, uploaded_by_type/id, scan_state, supersedes_id)
- `evidence_links` (document_version_id, object_type, object_id, purpose)

### Operations (R1)
- `tasks` (tenant_id, type, subject_type/id, title, due_date, due_rule, owner_id, status, escalation_level, row_version)
- `review_items` (tenant_id, kind, subject, status `open|assigned|resolved|reopened`, assignee, resolution, reason, row_version)
- `job_failures` (job_name, idempotency_key, tenant_id, error, attempts, last_at, resolved_at)
- `exports` (tenant_id, kind, params, status, document_id, generated_at)

### R2 / R3 (tables named now, detailed when their phase starts)
R2: `document_extractions`, `extracted_values` (page, bbox, confidence, processor), `processors`, `emission_records`, `gas_components`, `precursor_links`, `monitoring_periods`, `verifiers`, `accreditations`, `verification_records`, `verification_gaps`, `carbon_price_evidence`, `cpr_components_evidence`, `field_lineage`, `source_watch_results`.
R3: `calculations`, `calculation_operands`, `cpr_calculations`, `cpr_components`, `returns`, `return_versions`, `return_lines`, `approvals`, `submissions`, `submission_attempts`, `amendments`, `payments`, `repayment_claims`, `reimbursements`, `compliance_cases`, `case_deadlines`, `penalties`, `interest_charges`, `legal_holds`, `retention_schedules`, `connected_entities`, `closure_checklists`, `tenant_exports`.

## 5. Source activation rule (as a query)

A reference row may be used for a transaction on legal date `d` only if:

```
dataset_version.status = 'active'
AND source.status IN ('in_force','commenced')
AND (source.commencement_date IS NULL OR source.commencement_date <= d)
AND row.effective_from <= d AND (row.effective_to IS NULL OR d < row.effective_to)
```

This lives in one SQL view per dataset (`v_active_<dataset>`), and services read only
from those views.

## 6. Migrations

- One Alembic revision per PR at most; message names the requirement ID.
- Every migration has a working `downgrade` (tested in CI: up → down → up).
- Production changes use expand → migrate data → contract across separate releases.
- Never edit a merged migration.
- Reference data is **not** loaded by migrations; it is loaded by the refdata loader.

## 7. Indexing starting points

- `import_lines (tenant_id, tax_point_date)`, `(tenant_id, commodity_code)`, `(tenant_id, tax_point_state)`
- `decisions (tenant_id, subject_type, subject_id)`
- `tasks (tenant_id, status, due_date)`
- `audit_events (tenant_id, object_type, object_id, occurred_at)`
- `magic_links (token_hash)` unique
Check with `EXPLAIN ANALYZE` in the 10,000-line load test before adding more.
