# Changelog

All notable changes to this project. Newest first. Format based on
[Keep a Changelog](https://keepachangelog.com/). Every entry names the requirement
IDs it touches. Releases are tagged `r1-pilot`, `r1-live`, `r2.0`, `r3.0`.

## [Unreleased]

### Added
- Phase 3 step 2 (R1-003): migration 0009 adds `documents`, `document_versions` (immutable) and `import_batches` (declared details fixed; status forward-only, terminal batches locked, by trigger and by `modules/imports/rules.py`; unique per tenant on file SHA-256 and idempotency key). `core/storage.py` (`ObjectStore`; Supabase Storage over httpx with the backend-only service-role key; in-memory store for tests; content-addressed key `{tenant_id}/{sha256}`). `POST /tenants/{t}/import-batches` streams the upload through a size cap while hashing and sniffing (UTF-8 CSV text only), takes an advisory lock per tenant and hash, answers 202 for a new batch, 200 `replayed: true` for the same file, 409 for the same file with different declared details; `GET` list and detail. New settings `IMPORT_MAX_FILE_BYTES`, `SUPABASE_STORAGE_BUCKET_IMPORTS`; `python-multipart` added; private bucket `customs-imports` in `supabase/config.toml`. No Celery job yet (batches stay `received`). Open decisions LEGAL-DEC-019 (liable person for indirect representation, s.144(5), overseas importer, express/postal, XI) and DATA-DEC-020 (valuation-method values that equal the customs-duty basis); both source status unverified.
- Phase 2 (R1-050): migrations 0007 and 0008 add `regulatory_sources`, `ref_datasets`, `ref_dataset_versions`, `platform_domain_owners` and thirteen dataset tables (`ref_cbam_commodity_codes`, `ref_threshold_rules`, `ref_registration_rules`, `ref_service_state`, `ref_exclusion_rules`, `ref_origin_rules`, `ref_geography_rules`, `ref_tax_point_rules`, `ref_working_days`, `ref_sector_forms`, `ref_cds_report_layouts`, `ref_customs_monthly_exchange_rates`, `ref_compliance_calendar`) with `v_active_*` views that apply the source activation rule; triggers keep loaded rows immutable and let only a domain owner activate a version or move a source forward. `modules/refdata`: loader CLI (`python -m app.modules.refdata.load`; checksum, idempotent, same-version-different-content refused, manifest cannot claim a source in force, fixtures refused in production), `get()`, longest-prefix lookup, `snapshot()` with version IDs, dry-run impact report (diff, coverage gaps, warnings, pluggable affected-records provider), activation that retires the previous version, and `/platform` sources/datasets/versions/impact/activate routes. `python -m app.cli.bootstrap_domain_owner` registers an approver (ADR-0003). Real data loaded as `pending` only: the HMRC goods list (`cbam_commodity_codes` 2027.1, 54 rows, source `draft`, REG-DEC-018) and the policy-summary compliance calendar (REG-DEC-007). Frontend: `/ops/reference-data` screens (datasets, sources, versions, impact report, activate). `/me` gains `domain_owner`. Review fixes: only platform-mode sessions can write the new tables; the database requires a sealed, version-specific impact report, a non-empty version and a domain owner to activate; source status is one-way with `superseded` keeping earlier dates replayable; activation needs a reason and acknowledged warnings; short commodity codes are refused; the goods list now cites FA 2026 Sch 16 as its (laid, pending) source (REG-DEC-018); domain owners can be revoked. Fixture data for every dataset in `backend/tests/fixtures/refdata/`.
- Phase 1 step 14 (R1-001), frontend half: platform administration screens (`/ops/platform`: clients with status and UK dates, add a client, suspend/reactivate/close with a reason, people with role labels, invite with roles, edit roles, remove with confirmation; roles that need two-step verification are flagged). 61 vitest tests and axe checks on the signed-in screens (session injected, API mocked). Backend half: `modules/platform_admin` with `GET/POST /platform/tenants`, `PATCH /platform/tenants/{id}` (suspend, reactivate, close; reason and `If-Match` required; closed is terminal), `GET .../members`, `POST .../invitations` (invites through the Supabase Auth admin API using the backend-only service-role key, behind an interface), `PATCH/DELETE .../members/{user_id}`. Every write needs a recent login and is recorded in the platform audit chain. `python -m app.cli.bootstrap_platform_admin` creates the first platform admin. `platform_admin` can never be assigned as a tenant role.
- Phase 1 step 13 (R1-042): frontend sign-in, password reset, TOTP enrolment and challenge (Supabase Auth only), `/me`-driven app shell with role-aware navigation, tenant picker, sign-out, British formatting helpers (`14 March 2027`, `£1,234.56`, UK time, decimal strings only), problem+json API client. 46 vitest tests; axe checks on sign-in, reset and portal pages. Not yet exercised against a real Supabase (none in the cloud environment): smoke-test sign-in and MFA locally.
- Phase 1 step 12 (R1-022): migration 0006 `tasks` + immutable `task_events`; `modules/tasks` (pure status machine with reasons required to block, cancel, reopen or move a due date; escalation levels from days overdue; service writes task, history and audit in one transaction); `GET /tenants/{t}/tasks`, `GET .../{id}`, `GET .../{id}/history`, `PATCH .../{id}` with `If-Match`; daily `escalate_overdue_tasks` job. Escalation thresholds (7, 14, 28 days overdue) are a product setting, not law. `core/pagination.py` for cursor paging.
- Phase 1 steps 5, 6, 7 (R1-002, R1-042): `core/auth.py` (Supabase JWT via JWKS: signature, expiry, audience, issuer; asymmetric algorithms only, no `none`, key-confusion refused; `aal2` for operations/reviewer/approver/domain_owner/platform_admin; recent-login check from the `amr` claim, 15 minutes), `core/permissions.py` (starting least-privilege matrix; tax agent can never register the liable person), `core/tenancy.py` (token -> membership -> MFA -> tenant session; `require(permission, recent_auth=...)`, `require_platform(...)`), `GET /api/v1/me`, migration 0005 (`platform_admins` table; `platform_admin` is no longer a tenant role). `require()` lives in `core/tenancy.py` rather than `core/permissions.py` to avoid a circular import.
- Phase 1 steps 9, 10 (R1-045): migration 0004 `decisions` (immutable, superseding history, tenant RLS) with `core/decisions.py` (canonical-JSON fingerprint, idempotent save, current/history lookup); `core/versioning.py` (`row_version`, `If-Match` parsing, `update_versioned` -> 409 on stale, 404 across tenants) and the concurrent-approval test.
- Phase 1 step 8 (R1-023): migration 0003 `audit_events` (append-only trigger for everyone including the owner, no UPDATE/DELETE/TRUNCATE for `cbam_app`, per-tenant SHA-256 hash chain computed in the database under an advisory lock, `audit_verify_chain`), `core/audit.record()`, nightly `verify_audit_chains` task that fails loudly. Tests: tamper detection, concurrent writers, tenant isolation.
- Phase 1 step 4 (R1-001): migration 0002 with `tenants`, `users`, `organisations`, `memberships`, `approval_roles`, forced row-level security (fail closed), platform mode limited to tenants/users/memberships, cross-tenant tests as `cbam_app`, and a test that every `cbam` table has forced RLS. `core/db.py` `tenant_session` / `run_as_tenant` (step 5 is finished when step 6 adds the membership check). Later migrations run as `cbam_owner`.
- Phase 1 steps 1, 2, 3, 11, 15 (R1-043, R1-044): `core/dates.py` (UK dates, quarters, data-driven accounting periods), `core/clock.py`, `core/money.py` (Decimal, mandatory rounding mode, decimals as JSON strings), `core/errors.py` (problem+json), `core/logging.py` (structlog, PII scrubbing, request IDs). Tenant and user IDs are bound to logs when auth lands (steps 5, 6).
- Phase 0 backend skeleton (steps 3, 4, 10, 12; steps 6, 7, 11 written but not yet run
  against Docker/Postgres/GitHub): `backend/` uv project, FastAPI health endpoints,
  settings, Sentry with PII scrubbing, Celery heartbeat task, Alembic with schema/roles
  migration, Redis compose, CI workflow, float-ban script, pre-commit config.
- Phase 0 steps 5, 7 (migration run up/down/up on Postgres 16), 9 and most of 8 (shadcn/ui: `cn` helper and Button added by hand because ui.shadcn.com is not reachable from the cloud environment; `components.json` is set up so `npx shadcn add` works locally): `supabase/config.toml` (TOTP MFA on, min password 12, `cbam`
  not exposed), `frontend/` (Vite, React, TS, Tailwind, `ops/` and `portal/` routes,
  eslint, prettier, vitest, Playwright + axe) and a Celery worker + beat run against
  local Redis. shadcn/ui components are not initialised yet. Leaked-password protection
  is a hosted Supabase setting still to be switched on.
- Migration 0001 now works for Supabase's non-superuser `postgres` role (found on first Windows run): grants itself membership in `cbam_owner` and gives it CREATE on the database.
- R1-012: skipped threshold scenario catalogue TH-01..TH-11 awaiting domain-owner check.

### Added
- Research update (`docs/GAP_ANALYSIS.md` §10): official-source findings F1–F9 and
  clarifications to R1-003/031, R1-011, R1-012/037, R1-035, R3-005, R3-009/012,
  R3-017/035 (`docs/PRD.md` §6.1).
- New requirements R1-054 ("Get customs data" importer + coverage tracker), R1-055 (EU
  template upload), R1-056 (portal help, save-and-return), R1-057 (shared installation
  network, design in Phase 6), R1-058 (demo tenant), R1-059 and R1-060 (backlog).

### Changed
- Primary-source re-check 3 Oct 2026 in `docs/GAP_ANALYSIS.md` §12: SI 2026/830 and FA 2026 Sch 17 paras 2, 6, 7, 8, 9, 14 read in full; C1, C2, C3, C6, C7, C9, C10, C12 confirmed; penalties (paras 33–40), SI 994/995, scheme list and newer HMRC publications checked in §12.1. Phase 0 step 13 done; re-check again before Pilot and Live.
- Source re-check 2 Oct 2026 recorded in `docs/GAP_ANALYSIS.md` §11 (search snippets only; no primary source fetched; step 13 still open). New open decisions REG-DEC-016, REG-DEC-017; notes added to REG-DEC-001/007/013, TECH-DEC-004, LEGAL-DEC-005, GOV-DEC-009.
- R2-031 source change watcher moved to the R1 Live cut.
- Open decisions DATA-DEC-002, REG-DEC-007 and REG-DEC-013 updated with research evidence.

### Earlier
- Project set-up: `CLAUDE.md`, Claude agents/commands/skills, documentation set
  (`docs/`), implementation plan (`plans/IMPLEMENTATION_PLAN.md`).
- Specification baseline v1.4 and Team Handbook stored under `docs/spec/` with
  searchable text copies; earlier spec versions in `docs/spec/archive/`.
- Gap analysis (`docs/GAP_ANALYSIS.md`): editorial fixes D1–D12, sequencing fixes
  S1–S4, handbook reconciliation, new requirements R1-042 … R1-053, R2-030, R2-031,
  R3-037, and open decisions REG-DEC-007, GOV-DEC-009 … BRAND-DEC-015.
- ADR-0001: stack aligned with the Team Handbook (FastAPI, Supabase, Celery,
  Resend, Sentry, React).
