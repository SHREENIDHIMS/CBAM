# ADR-0001: Technology stack and system shape

**Status:** Proposed — aligned with the Team Handbook §9–§10. Confirm under
TECH-DEC-011 once the tech-spec companion (DOC-DEC-014) is available.
**Date:** 30 Sep 2026

## Context

- One developer builds and runs the whole product.
- The handbook already names: FastAPI (Python) backend, Celery chase engine,
  Supabase (EU region) with Row Level Security, Resend for email, Sentry, and the
  Claude API for R2 document extraction.
- The core risks are correctness (decimal maths, legal dates, law-as-data),
  auditability and tenant isolation — not scale. The largest stated load is a
  10,000-line import.
- A managed platform that gives PostgreSQL, authentication with MFA, file storage
  and backups in one place removes a lot of work that one developer would
  otherwise have to build and secure.

## Decision

1. **Modular monolith.** One FastAPI service, one Celery worker, one Celery beat
   scheduler, one PostgreSQL database. Modules are folders with a fixed pattern
   (`rules.py` pure, `service.py`, `api.py`). No microservices.
2. **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, `uv`.
3. **Supabase** (London or EU region — OPS-DEC-010):
   - **PostgreSQL** is the system of record. Business tables live in a private
     schema `cbam` that is **not** exposed through Supabase's auto-generated
     Data API. Only FastAPI talks to it, connecting as a dedicated role `cbam_app`
     (never `postgres` or `service_role`). RLS isolates tenants.
   - **Supabase Auth** handles internal/client user login, password reset and
     TOTP MFA. FastAPI verifies the Supabase JWT and requires MFA level `aal2`
     for privileged roles. Our own tables hold memberships and roles.
   - **Supabase Storage** (private buckets) holds original documents and
     generated exports; downloads only through short-lived signed URLs issued by
     FastAPI after a permission check.
   - Point-in-time recovery enabled on the production project.
4. **Jobs:** Celery with Redis as broker; Celery beat for the schedules (daily
   forward test, 1st-of-month backward test, outreach chase, reminders).
5. **Email:** Resend, behind a small adapter so local development uses the
   Supabase CLI mail catcher.
6. **Errors:** Sentry for backend and frontend, with personal-data scrubbing on.
7. **Frontend:** React + TypeScript + Vite, one app with two route trees:
   `ops` (internal/client users, Supabase Auth) and `portal` (suppliers via magic
   link, no account, mobile-first). TanStack Query, Tailwind + shadcn/ui.
8. **Suppliers never get Supabase accounts.** Magic links are our own
   (hashed token, single case, expiry, revoke) — handbook rule "magic links, never
   passwords".
9. **R2 extraction:** Claude API, only under R2-030 (per-tenant opt-in, processor
   register, human review of every extracted value).
10. **API/worker hosting:** containers in a UK/EU region next to the Supabase
    project (provider chosen under OPS-DEC-010).

## Alternatives considered

| Option | Why not |
|---|---|
| Self-managed PostgreSQL + built-in auth + S3 | More to build and secure alone (auth, MFA, backups); nothing gained for this load |
| Supabase auto-generated Data API directly from the frontend | Business rules, audit and legal locks must sit in one place (FastAPI + DB constraints); a second path to the tables is a bypass risk |
| PostgreSQL-backed job queue instead of Celery | Would drop Redis, but the handbook standardises on Celery; not worth diverging |
| Java/Spring or Node full stack | Weaker document-extraction and decimal ecosystem for this domain; handbook chose Python |
| Microservices | One developer; one deploy, one database, one transaction is safer |

## Consequences

- Local development runs `supabase start` (Postgres, Auth, Storage, Studio, mail
  catcher) plus Redis from `infra/docker-compose.yml`.
- A decision, its audit event and its task are written in one database transaction.
- Supabase-specific code is limited to: JWT verification (`core/auth.py`), the
  storage adapter (`modules/documents/storage.py`) and project config. Moving off
  Supabase later means replacing those, not the domain code.
- Redis holds only the job queue; losing it loses queued work, not data — every
  job is idempotent and re-schedulable from database state.
