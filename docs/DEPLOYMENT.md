# Deployment and operations

Stack follows ADR-0001 (Team Handbook): Supabase for PostgreSQL, Auth and Storage;
Celery + Redis for jobs; Resend for email; Sentry for errors. Where the API/worker
containers run is OPS-DEC-010; the controls below apply whichever host is chosen.

## 1. Environments

| Env | Purpose | Data | Deploys |
|---|---|---|---|
| `local` | Development on the developer's machine | Synthetic + masked fixtures only | `supabase start` + `docker compose` |
| `ci` | Automated checks | Throwaway (Supabase CLI in CI) | Every PR |
| `staging` | Release candidate, UAT, security scan, restore rehearsal, outreach "minutes-mode" (R1-053) | Synthetic; pilot client may use masked data | On merge to `main` |
| `production` | Clients | Real | Manual promotion of a tagged staging build |

Separate Supabase projects (and separate keys) for staging and production.
No production data is ever copied down (spec §15).

## 2. Local setup

| Piece | How | Port |
|---|---|---|
| Supabase stack (Postgres, Auth, Storage, Studio, mail catcher) | `supabase start` (config in `supabase/config.toml`) | 54321 API, 54322 DB, 54323 Studio, 54324 mail |
| Redis | `infra/docker-compose.yml` | 6379 |
| ClamAV (optional) | `infra/docker-compose.yml` profile `scan` | 3310 |

Steps (also in `README.md`):

```bash
cp .env.example .env                        # fill local values printed by `supabase start`
supabase start
docker compose -f infra/docker-compose.yml up -d
cd backend && uv sync && uv run alembic upgrade head
uv run python -m app.modules.refdata.load tests/fixtures/refdata   # fixture data only
uv run uvicorn app.main:app --reload        # api :8000
uv run celery -A app.core.jobs worker -l info
uv run celery -A app.core.jobs beat -l info
cd ../frontend && npm ci && npm run dev     # ui :5173 (proxies /api)
```

## 3. Configuration

All config from environment variables; full list in `.env.example`. Secrets live
in the host's secret store (never in the repo). Changing regulatory values is
**not** configuration — it goes through reference data (R1-050).

## 4. Production shape (proposed)

| Piece | Service |
|---|---|
| Database, Auth, Storage | Supabase project in London (eu-west-2) or an EU region (OPS-DEC-010); Pro plan or higher with **point-in-time recovery**; SSL enforced; network restrictions to the API/worker egress IPs; `cbam` schema not exposed via the Data API |
| API | FastAPI container(s), 2 instances behind HTTPS load balancer, UK/EU region |
| Worker / beat | Celery worker (1–2) + exactly one beat |
| Redis | Managed Redis (TLS, auth) in the same region — broker only |
| Email | Resend with verified sending domain (SPF, DKIM, DMARC — BRAND-DEC-015) and webhook for delivery/bounce/complaint |
| Errors | Sentry (EU data region), PII scrubbing |
| Logs/metrics | Host's log service (JSON), uptime check on `/health/ready` |
| Backups beyond Supabase | Nightly logical dump (`pg_dump` of `cbam` schema) + storage bucket copy to a separate account/region, encrypted |

## 5. CI/CD

1. PR → CI pipeline (`docs/TESTING.md` §5). Must be green.
2. Merge to `main` (by the user) → build image tagged with commit SHA → push to the
   container registry → run Alembic migrations as a one-off job on staging → deploy
   staging → smoke tests.
3. Release: tag `r1-pilot`, `r1-live`, `r2.0`, … → promote the same image to
   production → one-off migration task → deploy → smoke tests → release notes in
   `plans/CHANGELOG.md`.

Rules: the same image goes staging → production; migrations are backward-compatible
with the previous app version (expand/contract); no manual changes in the console.

## 6. Reference-data deployment

Reference data is data, not code: a new dataset version is loaded on staging,
impact report reviewed, activated by the domain owner, then loaded and activated
the same way on production. The loader is idempotent and checksum-verified, so
staging and production end up byte-identical.

## 7. Backups and restore

| Item | How | Target |
|---|---|---|
| Database | Supabase PITR + daily backups; nightly `pg_dump` of `cbam` kept off-platform (monthly copies kept 7 years) | RPO ≤ 15 min |
| Files | Nightly copy of Storage buckets to separate encrypted storage | no loss of evidence |
| Restore rehearsal | Restore latest snapshot to a scratch instance, run integrity checks (row counts, audit hash chain verify, sample file SHA-256) | Before every release; RTO ≤ 4 h |

The restore log is saved in `docs/releases/<release>/restore.md`.

## 8. Monitoring and alerts

| Alert | Condition |
|---|---|
| API down | `/health/ready` failing 3 min |
| Job failures | Any job in `job_failures` unresolved > 1 h |
| Scheduled legal job missed | Backward test not recorded by 06:00 UK on the 1st; forward daily test missing |
| Email | Bounce rate > 5 % in 24 h; webhook errors |
| Audit chain | Nightly verify fails |
| Security | Spike in failed logins / magic-link failures |
| DB | Supabase CPU/disk alerts; disk < 20 % free |
| Redis / Celery | Queue length growing 30 min; beat heartbeat missing |

## 9. Release checklist (every release)

- [ ] All phase exit gates ticked in `plans/IMPLEMENTATION_PLAN.md`
- [ ] CI green on the release commit
- [ ] Load test and restore rehearsal done, evidence saved
- [ ] ZAP baseline clean (no high)
- [ ] Reference data on production matches staging (checksums)
- [ ] Feature flags set for this release only
- [ ] Rollback plan: previous image tag + migration compatibility confirmed
- [ ] `plans/CHANGELOG.md` updated

## 10. Rollback

Redeploy the previous image tag. Because migrations are expand/contract, the
previous version runs against the new schema. Never roll back a migration that
dropped data in production; restore from PITR only as a last resort, with the
domain owner informed (audit/evidence implications).
