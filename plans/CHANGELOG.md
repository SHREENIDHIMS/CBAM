# Changelog

All notable changes to this project. Newest first. Format based on
[Keep a Changelog](https://keepachangelog.com/). Every entry names the requirement
IDs it touches. Releases are tagged `r1-pilot`, `r1-live`, `r2.0`, `r3.0`.

## [Unreleased]

### Added
- Phase 0 backend skeleton (steps 3, 4, 10, 12; steps 6, 7, 11 written but not yet run
  against Docker/Postgres/GitHub): `backend/` uv project, FastAPI health endpoints,
  settings, Sentry with PII scrubbing, Celery heartbeat task, Alembic with schema/roles
  migration, Redis compose, CI workflow, float-ban script, pre-commit config.
- Phase 0 steps 5, 9 and most of 8 (shadcn/ui still open): `supabase/config.toml` (TOTP MFA on, min password 12, `cbam`
  not exposed), `frontend/` (Vite, React, TS, Tailwind, `ops/` and `portal/` routes,
  eslint, prettier, vitest, Playwright + axe) and a Celery worker + beat run against
  local Redis. shadcn/ui components are not initialised yet. Leaked-password protection
  is a hosted Supabase setting still to be switched on.
- R1-012: skipped threshold scenario catalogue TH-01..TH-11 awaiting domain-owner check.

### Added
- Research update (`docs/GAP_ANALYSIS.md` §10): official-source findings F1–F9 and
  clarifications to R1-003/031, R1-011, R1-012/037, R1-035, R3-005, R3-009/012,
  R3-017/035 (`docs/PRD.md` §6.1).
- New requirements R1-054 ("Get customs data" importer + coverage tracker), R1-055 (EU
  template upload), R1-056 (portal help, save-and-return), R1-057 (shared installation
  network, design in Phase 6), R1-058 (demo tenant), R1-059 and R1-060 (backlog).

### Changed
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
