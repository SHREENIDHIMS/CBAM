# Technical specification

Rules for how code is written in this repo. `CLAUDE.md` §3 lists the compliance
rules; this file gives the exact engineering details behind them.

## 1. Languages and versions

| Item | Version / setting |
|---|---|
| Python | 3.12 (pinned in `backend/.python-version`) |
| Node | 22 LTS (pinned in `frontend/.nvmrc`) |
| PostgreSQL | Supabase-managed (match the local `supabase start` version) |
| Package managers | `uv` (lockfile `uv.lock` committed), `npm` (`package-lock.json` committed) |
| Formatting | `ruff format`, `prettier` |
| Linting | `ruff check` (rules: E, F, I, B, UP, S, DTZ, RUF), `eslint` |
| Types | `mypy --strict` for `app/core/` and every `rules.py`; `mypy` default elsewhere; `tsc --strict` |

`DTZ` (flake8-datetimez) is on so naive `datetime.now()` is a lint error.

## 2. Backend layout

```
backend/
├── pyproject.toml
├── app/
│   ├── main.py              # app factory, routers, middleware
│   ├── core/
│   │   ├── config.py        # pydantic-settings; reads env only
│   │   ├── db.py            # engine, session, SET LOCAL app.tenant_id
│   │   ├── auth.py          # Supabase JWT verification (JWKS), aal2 check, current user
│   │   ├── permissions.py   # role → permission map, require(...) dependency
│   │   ├── audit.py         # record(actor, action, obj, before, after, reason)
│   │   ├── clock.py         # Clock protocol; SystemClock (UTC) + FrozenClock for tests
│   │   ├── dates.py         # uk_date(instant), quarter(date), accounting_period(date)
│   │   ├── money.py         # Decimal context, quantize helpers, Money/Mass types
│   │   ├── decisions.py     # Decision dataclass, fingerprint(), save_decision()
│   │   ├── errors.py        # domain errors → problem+json
│   │   └── jobs.py          # Celery app, beat schedule, idempotency helper
│   └── modules/<module>/{models,schemas,rules,service,api}.py
├── refdata/<dataset>/<version>/{manifest.yaml, data.csv|yaml}
├── migrations/              # Alembic
└── tests/{unit,integration,scenarios,security,load,fixtures}/
```

## 3. Dependencies

Allowed without discussion: anything already in `pyproject.toml`/`package.json`.
Before adding a new one, answer in the PR: can the standard library, PostgreSQL or
an existing dependency do it? Is it maintained (release in last 12 months),
licence-compatible (MIT/BSD/Apache/PSF/ISC), free of known vulnerabilities
(`pip-audit`, `npm audit`)? What does it add to image/bundle size?

Planned core dependencies (Phase 0): `fastapi`, `uvicorn`, `pydantic-settings`,
`sqlalchemy`, `alembic`, `psycopg[binary]`, `celery[redis]`, `pyjwt[crypto]`,
`supabase` (storage client, server side only), `resend`, `sentry-sdk`,
`python-multipart`, `openpyxl`, `pyyaml`, `structlog`; dev: `pytest`,
`pytest-asyncio`, `hypothesis`, `ruff`, `mypy`, `locust`, `pip-audit`.
R2 adds `anthropic` (Claude API, under R2-030) and PDF/OCR libraries.
Frontend: `react`, `react-router`, `@tanstack/react-query`, `@supabase/supabase-js`
(auth only), `tailwindcss`, shadcn/ui components, `openapi-typescript`,
`@sentry/react`; dev: `vitest`, `@playwright/test`, `@axe-core/playwright`.

## 4. Dates and time (R1-043)

- The legal time zone is `Europe/London` (a constant in `core/dates.py`; it never changes).
- Instants: `timestamptz`, always UTC in Python (`datetime` with `tzinfo=UTC`).
- Legal dates: `date`. Convert with `uk_date(instant)` only.
- Business code gets time from `Clock` (dependency-injected). `rules.py` never
  gets a clock — it gets `as_of: date`.
- Quarter of a date: `Q1 = Jan–Mar` etc. Accounting period: 2027 → the year;
  from 2028 → the quarter. The switch-over is reference data
  (`transition_packages`, R3-036), not an `if year == 2027`.
- Working days (R3-022): from the `working_day_calendar` reference table, never
  computed from weekdays alone.
- Display: `14 March 2027` (UI); ISO `2027-03-14` in APIs and files.

## 5. Numbers and rounding (R1-044)

| Quantity | Python type | DB column | Rounding |
|---|---|---|---|
| Source money (as sourced) | `Decimal` + ISO currency | `NUMERIC(24,8)` + `char(3)` | none (as given) |
| GBP money for decisions/returns | `Decimal` | `NUMERIC(18,2)` | only where the rule says; CPR converted relief rounds **down** to 2 dp (R3-005) |
| Intermediate money | `Decimal` | `NUMERIC(24,8)` | none |
| Net mass | `Decimal` kg | `NUMERIC(20,6)` | reporting rounding per R3-003 fractional-kg rules, at the legal step only |
| Emissions (tCO2e), intensity internal | `Decimal` | `NUMERIC(24,10)` | intensity reported at 5 dp at the prescribed step (R2-004) |
| Gas factors, FX rates | `Decimal` | `NUMERIC(18,8)` | none |

- Decimal context: precision 38, `ROUND_HALF_EVEN` default; every legal rounding
  names its mode explicitly (`ROUND_DOWN`, `ROUND_HALF_UP`…) and the mode comes from
  the rule's reference data, not from the default context.
- Parse numbers from files as strings → `Decimal`. Never `float()`.
- JSON: decimals are serialised as **strings** in the API (`"48200.000000"`).
- CI check: `grep -rn "float" backend/app --include=*.py` must return nothing
  except in an allow-list file (e.g. metrics code).

## 6. Reference data files (R1-050)

```
backend/refdata/cbam_commodity_codes/2027.1/
├── manifest.yaml
└── data.csv
```

`manifest.yaml`:

```yaml
dataset: cbam_commodity_codes
version: "2027.1"                # quoted text
source_id: HMRC-CBAM-GOODS-SCOPE
source_title: "Check which goods are in scope of Carbon Border Adjustment Mechanism (CBAM)"
source_type: guidance            # legislation | regulation | notice | system_boundary | guidance
source_url: https://www.gov.uk/government/publications/check-which-goods-are-in-scope-of-carbon-border-adjustment-mechanism-cbam
publication_date: 2026-07-16     # optional
commencement_date: null          # optional; the source is not usable before it
retrieved_at: 2026-10-03
source_status: draft             # draft | laid ONLY (see below)
effective_from: 2027-01-01
effective_to: null
checksum_sha256: <of data.csv>
fixture: false                   # true = test data; refused in production
notes: "Transcribed by <name>; checked by domain owner <name> on <date>"
```

- `data.csv` is UTF-8 with exactly the dataset's columns (`app/modules/refdata/datasets.py`,
  mirrors the migration). Optional `effective_from` / `effective_to` columns per row default
  to the manifest's period. Empty cells are NULL only for optional columns. YAML data files
  are not supported yet.
- **The manifest never declares a source in force.** The loader registers a new source as
  `draft` or `laid` only, and a manifest claiming `in_force`, `commenced` or `superseded` is
  refused. A domain owner moves the source forward in the registry
  (`POST /platform/sources/{id}/status`, with a reason). For a source that already exists, the
  registry is the authority and the manifest's `source_status` is ignored, so reloading a
  folder is always a no-op.
- A dataset version only drives decisions when it is `active` **and** its source is
  `in_force`/`commenced` on the transaction date, or `superseded` for dates before its
  `effective_to` (`v_active_*` views). Activating a version needs a current impact report, a
  reason, and an acknowledgement when the report has warnings; the previous active version is
  retired, never deleted. Row periods must lie inside the manifest's period.
- `get_by_prefix` refuses a code that is too short to decide (listed codes below it differ).
  The loader refuses a prefix list whose exceptions do not sit under a listed in-scope code.
- `cbam_commodity_codes` lists headings and sub-headings exactly as HMRC publishes them
  (`code_prefix` = digits only). Everything below a listed code is covered, so the lookup is the
  longest matching prefix (`refdata.get_by_prefix`); "Except" rows have `in_scope=false`.

- Loader command: `uv run python -m app.modules.refdata.load <folder> [<folder> ...]`.
- Same version + different checksum → refused. New content = new version folder.
- Loaded versions start `pending`. Activation needs `domain_owner` approval after a
  dry-run impact report (R1-050).
- Tests use their own fixture datasets under `tests/fixtures/refdata/` and say so.

## 7. API conventions

See `docs/API_SPEC.md`. Short form: REST under `/api/v1`, JSON, decimals as
strings, `problem+json` errors, cursor pagination, `Idempotency-Key` on creates,
`If-Match: <row_version>` on approvals/updates.

## 8. Non-functional targets

| Area | Target | Checked by |
|---|---|---|
| Import | 10,000 CDS lines imported, validated, scoped ≤ 5 min | `tests/load/` (locust / timed job) |
| Dashboard | p95 ≤ 1.5 s for a client with 10,000 lines | load test |
| Supplier portal | p95 page ≤ 1 s on throttled 4G; form done < 10 min by a real user | Playwright throttling + usability test |
| Availability | Business hours target 99.5 % (single region) | uptime check |
| Backup | RPO ≤ 15 min (PITR), RTO ≤ 4 h | restore rehearsal per release |
| Accessibility | WCAG 2.2 AA, zero axe "serious/critical" | Playwright + axe |
| Security | No high/critical findings from `pip-audit`, `npm audit`, `gitleaks`, OWASP ZAP baseline | CI + pre-release |
| Retention | 6 years from legal anchor; legal hold blocks deletion | R3-035 tests |

## 9. Logging and observability

- `structlog` JSON logs: timestamp, level, request_id, tenant_id, user_id, job_id,
  event. **No personal data** (names, emails, phones) and no document content.
- Metrics (Prometheus format at `/metrics`, internal only): import rows by status,
  job failures, email events, magic-link failures, request latency.
- Health: `/health/live` (process up), `/health/ready` (DB + storage + Redis reachable).
- Sentry for exceptions (backend + frontend) with `send_default_pii=False` and a
  scrubber for emails/names in breadcrumbs.
- Failed jobs appear in the ops UI with a retry button (R1-026).

## 10. Error handling

- Domain errors (`RuleBlocked`, `StaleVersion`, `NotPermitted`, `TenantMismatch`,
  `SourceNotActive`) map to problem+json with a stable `type` URI and, where legal,
  the `rule_id` and `source_id`.
- Never swallow an exception in a job; let it retry and surface.
- Validation errors on import rows are data (exception report), not exceptions.

## 11. Code style

- Names follow the domain (`tax_point_date`, `net_mass_kg`, `liable_person_id`).
  Units in names where they matter (`_kg`, `_gbp`, `_tco2e`).
- Small functions; one rule per function in `rules.py`, named after the rule.
- Comments explain *why* and cite the source (`# Finance Act 2026 Sch 17 para 8(2)`).
- No speculative abstractions: no interface with one implementation, except the
  HMRC filing adapter and email/storage adapters, which have a real second
  implementation (local fake vs provider).
