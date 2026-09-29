# Architecture

Stack and reasons: `docs/adr/0001-tech-stack.md` (follows the Team Handbook). Coding rules: `docs/TECHNICAL_SPEC.md`.

## 1. System context

```
            ┌──────────────┐        ┌───────────────────────┐
 CDS export │ Client ops / │  HTTPS │                       │  API        ┌───────────┐
 files ───► │ our ops team │ ─────► │   CBAM platform       │ ──────────► │ Resend    │
            └──────────────┘        │  (modular monolith)   │ ◄────────── │ (email)   │
            ┌──────────────┐ magic  │                       │  bounces    └───────────┘
            │ Supplier on  │ link   │  api + worker + beat  │
            │ phone/laptop │ ─────► │        │              │  (R3, when   ┌───────────┐
            └──────────────┘        │  Supabase (DB, Auth,  │  confirmed)  │ HMRC      │
                                    │  Storage) + Redis     │ ───────────► │ services  │
 GOV.UK / legislation ─ (R2 watcher,│                       │              └───────────┘
 read-only fetch)  ───────────────► └───────────────────────┘
```

## 2. Runtime components

| Component | What it is | Scales by |
|---|---|---|
| `api` | FastAPI app serving `/api/v1` and the built frontend | More containers (stateless) |
| `worker` | Celery worker: imports, threshold jobs, outreach sends, scans, exports | More containers; jobs are idempotent |
| `beat` | Celery beat: daily forward test, 1st-of-month backward test (UK date), outreach chase, deadline reminders, retention scan | Exactly one instance |
| Redis | Celery broker only (no business data) | Managed |
| Supabase PostgreSQL | All business state (schema `cbam`) | Vertical (Supabase plan) |
| Supabase Auth | Internal/client user identities, MFA | Managed |
| Supabase Storage | Original files, generated exports/evidence packs | Managed |
| Resend | Outbound mail + delivery/bounce/complaint webhooks | Managed |
| Sentry | Error tracking (PII scrubbed) | Managed |

## 3. Module map (backend `app/modules/`)

Modules are built in release order. A module may call another module's `service.py`
functions; it must never read another module's tables directly.

| Module | Owns | Requirements | Release |
|---|---|---|---|
| `core` (not a module; `app/core/`) | config, db session, tenancy/RLS, auth, permissions, audit, clock, money/decimal types, errors, feature flags | R1-002, 023, 042–045 | R1 |
| `organisations` | tenants, organisations, users, memberships, roles, liable person, onboarding, support access | R1-001, 036, 049, 051 | R1 |
| `refdata` | regulatory sources, datasets, versions, activation, lookups, impact dry-run | R1-050 → R2-015, R2-020, R2-031 | R1→R2 |
| `tasks` | tasks, deadlines, escalation, working-day calendar lookups | R1-022 | R1 |
| `imports` | batches, source rows, declarations, lines, parties, amendments, reconciliation, forecasts, currency | R1-003–006, 010, 025, 031, 034, 035, 037, 038 | R1 |
| `scope` | commodity scope decisions, exclusions, origin, geography, identifier checks | R1-007, 009, 011, 032, 052 | R1 |
| `taxpoint` | tax-point state machine, special-procedure lifecycle, manual-review flags | R1-008, 027 → R3-021 | R1→R3 |
| `threshold` | snapshots, forward/backward tests, trigger events | R1-012 | R1 |
| `registration` | readiness pack, deadlines, service switch, status record, change control | R1-013, 014, 030, 033, 040 → R3-020, 026 | R1→R3 |
| `suppliers` | suppliers, installations, contacts, readiness, contract responsibility, evidence-source parties, sector form definitions | R1-015, 016, 028, 029, 039 | R1 |
| `portal` | magic links, portal sessions, form rendering/submission | R1-017, 041 | R1 |
| `outreach` | templates, translations, schedules (incl. test time-scale), sends, email events, suppression | R1-018, 046, 047, 053 | R1 |
| `documents` | uploads, versions, scanning, signed URLs, evidence links | R1-019, 048 | R1 |
| `review` | review queue items, assignment, resolution | R1-020 → R2-012 | R1→R2 |
| `dashboard` / `exports` | read models, CSV/PDF exports | R1-021, 024 → R2-016 | R1→R2 |
| `extraction` | extraction jobs, extracted values with coordinates, processor register | R2-001, 030 | R2 |
| `emissions` | emission records, gas components, precursors, monitoring periods, routes, boundaries, selection | R2-002–007, 011, 018, 019, 021, 024, 027, 029 | R2 |
| `verification` | verifiers, accreditation, verification records, evidence types, gaps | R2-008, 017, 022, 025, 028 | R2 |
| `cpr` | schemes, CPR evidence (R2) and CPR calculation (R3) | R2-009, 010, 023 → R3-004–006 | R2→R3 |
| `calculation` | embedded emissions, weight rounding, liability, historical replay | R3-001–003, 007, 018, 036 | R3 |
| `returns` | returns, lines, versions, approval, nil, amendments, reconciliation | R3-008–010, 013, 014, 026, 029 | R3 |
| `filing` | HMRC adapter, filing-ready export, attempts, idempotency | R3-011, 023, 030 | R3 |
| `payments` | payments, channels, repayments | R3-012, 015, 022 | R3 |
| `compliance` | HMRC cases, notices, assessments, penalties, interest, reviews/appeals, avoidance, preservation | R3-016, 019, 024, 027, 028, 031–034 | R3 |
| `retention` | retention anchors, legal holds, closure, tenant export | R3-017, 025, 035, 037 | R3 |

## 4. The core patterns

### 4.1 Functional core, imperative shell

`rules.py` holds the law as pure functions:

```python
def backward_test(lines: list[ThresholdLine], ref: ThresholdRef, as_of: date) -> TestResult: ...
```

- Inputs: plain facts, a reference-data snapshot (with version IDs), `as_of`.
- Output: a frozen dataclass with `outcome`, `rule_id`, `rule_version`,
  `source_ids`, `reason`, and any computed values.
- No database, no clock, no I/O. So every legal scenario is a fast unit test and
  historical replay is "call the same function with the old snapshot".

`service.py` does the I/O: load facts, load the active reference snapshot for the
right date, call the rule, save a `decision` row + audit event + tasks in **one
transaction**.

### 4.2 Effective-dated reference data

Every regulatory table has `dataset_version_id`, `effective_from`, `effective_to`
(exclusive, nullable). A lookup is always `get(key, on=<legal date>)`, never "latest".
Non-overlap is enforced by a PostgreSQL exclusion constraint. A dataset version is
usable only if its source is active (see `docs/DATABASE.md` §5).

### 4.3 Decision records

Every rule outcome that matters (scope, exclusion, tax point, threshold test,
actual/default selection, CPR, liability) is stored in `decisions`:
subject type/id, rule ID, rule version, dataset version IDs, input fingerprint
(SHA-256 of canonical JSON inputs), outcome, reason, `as_of`, created_at.
Re-running with the same inputs gives the same fingerprint and outcome — this is
how R3-018 historical reproducibility is proven.

### 4.4 Versioned facts (never overwrite)

Source rows, documents, supplier submissions, declarations and returns are
versioned with `supersedes_id`. The current version is the one nothing supersedes.
A change upstream creates an **impact record** listing every downstream decision,
approval and return line that must be re-evaluated (R1-034, R2-026, R3-029).

### 4.5 Tenancy

- `tenant_id` column on every business table.
- FastAPI verifies the Supabase JWT, loads the user's membership for the tenant in
  the path, then sets `SET LOCAL app.tenant_id = '<uuid>'` at the start of each request
  transaction after checking membership; RLS policies filter on it.
- Platform-level tables (reference data, sources) have no `tenant_id` and are
  read-only to tenant users.
- Workers set the tenant per job. A job without a tenant runs only
  platform-level work.

### 4.6 Audit

`audit_events` is append-only (trigger rejects UPDATE/DELETE; app role has INSERT
and SELECT only). Each row has actor, action, object type/id, before/after JSON,
reason, request ID, and `prev_hash`/`hash` forming a per-tenant chain. A nightly job
verifies the chain.

### 4.7 State machines

Status fields with legal meaning (tax-point state, supplier case, review item,
registration status, return, submission, compliance case) are explicit state
machines: allowed transitions are listed in code next to the model, every
transition writes an audit event, and illegal transitions raise an error.

### 4.8 Jobs (Celery)

Every job has an idempotency key (e.g. `threshold:backward:<tenant>:<yyyy-mm-01>`),
retries with backoff, and writes failures to a visible `job_failures` read model.
Nothing fails silently (R1-026).

### 4.9 Feature flags per release

`FEATURE_R2_ENABLED`, `FEATURE_R3_ENABLED` hide unfinished release areas in
production. They are release switches, not legal switches — law never sits
behind a feature flag.

## 5. Key flows

### 5.1 CDS import → scope → threshold

```
upload file ─► import_batch (sha256, acquisition method)   [idempotent on sha256]
          ─► source_rows (raw, immutable)
          ─► validate rows ─► exceptions report (bad rows) │ good rows continue
          ─► normalise ─► declarations / import_lines / parties / values (GBP + source)
          ─► reconcile vs earlier batches (duplicates, amendments)
          ─► scope decision (commodity code @ tax-point date, exclusions, origin)
          ─► tax-point decision (resolved | unresolved → manual review flag + task)
          ─► threshold job (daily forward, monthly backward) ─► trigger event ─► tasks
```

### 5.2 Supplier outreach

```
installation needs data ─► readiness check ─► form definition (sector/code/route)
  ─► magic link issued (hash stored, expiry) ─► Day 0 email (template version)
  ─► Day 7/14/21 reminders if incomplete ─► Day 28 escalation to operations (not a legal default)
supplier opens link ─► token exchanged for portal session cookie ─► form + uploads
  ─► submission version ─► documents scanned ─► review / R2 validation
```

### 5.3 R3 return (later)

```
approved R2 inputs ─► calculation (rates, weight rounding, CPR per scheme, FX, cap)
  ─► return lines (per consignment) ─► reconciliation to ledger ─► approval (row_version)
  ─► filing adapter (idempotency key) ─► receipt/rejection ─► payment ledger ─► evidence pack
```

## 6. Frontend structure

```
frontend/src/
├── ops/            internal + client app (desktop-first)
│   ├── clients/  imports/  threshold/  registration/  suppliers/
│   ├── documents/  review/  tasks/  dashboard/  admin/   (R2/R3 areas added later)
├── portal/         supplier magic-link app (mobile-first, no account)
│   ├── Landing  Form (sector-aware, rendered from form definition)  Upload  Done
├── shared/         api client (generated from OpenAPI), ui components, i18n, formatting
```

- British English, dates like `14 March 2027`, GBP as `£1,234.56`.
- Portal text is translated from versioned, approved templates (R1-047).
- The API OpenAPI schema generates the TypeScript client (`openapi-typescript`),
  so types never drift.

## 7. What is deliberately not in the architecture

- No cache layer, no search engine, no microservices. Redis is only the Celery broker.
- No use of Supabase's auto-generated Data API or Realtime for business data.
- No LLM in any decision path. R2 extraction may use a processor only under
  R2-030 and every value is human-reviewed.
- No direct HMRC API calls until TECH-DEC-004 closes.
