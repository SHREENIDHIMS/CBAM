# CBAM

A multi-client platform that helps UK importers comply with the **UK Carbon Border
Adjustment Mechanism** (starts 1 January 2027): import capture, scope and tax point,
the £50,000 registration threshold, supplier emissions collection, validation,
Carbon Price Relief, returns and a six-year evidence trail.

> **Status:** specification and planning complete; code starts at Phase 0 of
> [`plans/IMPLEMENTATION_PLAN.md`](plans/IMPLEMENTATION_PLAN.md).

## Start here

| If you want to… | Read |
|---|---|
| Understand CBAM from zero | [`docs/spec/CBAM_Team_Handbook.md`](docs/spec/CBAM_Team_Handbook.md) (Part 1) |
| Know the rules for working in this repo | [`CLAUDE.md`](CLAUDE.md) |
| See what we are building | [`docs/PRD.md`](docs/PRD.md) |
| See every requirement with acceptance criteria | [`docs/spec/CBAM_Spec_v1.4.md`](docs/spec/CBAM_Spec_v1.4.md) + [`docs/PRD.md`](docs/PRD.md) §6 |
| See what was missing in the spec and how it was fixed | [`docs/GAP_ANALYSIS.md`](docs/GAP_ANALYSIS.md) |
| Know what to build next | [`plans/IMPLEMENTATION_PLAN.md`](plans/IMPLEMENTATION_PLAN.md) |
| See unanswered questions | [`docs/OPEN_DECISIONS.md`](docs/OPEN_DECISIONS.md) |

## Releases

**R1 Data Machine** (Pilot cut → Live cut) → **R2 Validation & Intelligence** →
**R3 Calculation & Filing**. Order is fixed. See [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Stack

FastAPI (Python 3.12) · Supabase (PostgreSQL, Auth, Storage) · Celery + Redis ·
React + TypeScript + Vite · Resend · Sentry. Reasons: [`docs/adr/0001-tech-stack.md`](docs/adr/0001-tech-stack.md).

## Run locally (after Phase 0)

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), Node 22, Docker Desktop,
[Supabase CLI](https://supabase.com/docs/guides/cli).

```bash
cp .env.example .env                               # fill in local values
supabase start                                     # Postgres, Auth, Storage, Studio, mail
docker compose -f infra/docker-compose.yml up -d   # Redis

cd backend
uv sync
uv run alembic upgrade head
uv run python -m app.modules.refdata.load tests/fixtures/refdata   # fixture reference data
uv run uvicorn app.main:app --reload               # API  http://localhost:8000
uv run celery -A app.core.jobs worker -l info      # worker (new terminal)
uv run celery -A app.core.jobs beat -l info        # scheduler (new terminal)

cd ../frontend
npm ci
npm run dev                                        # UI   http://localhost:5173
```

## Checks

```bash
cd backend  && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest -q
cd frontend && npm run lint && npm run typecheck && npm test && npx playwright test
```

## Repository layout

```
CLAUDE.md          working rules for this repo (read before any change)
.claude/           assistant agents, slash commands, skills, shared settings
docs/              PRD, architecture, specs, security, testing, deployment, roadmap, ADRs
docs/spec/         signed-off specification + Team Handbook (read-only)
plans/             implementation plan and changelog
backend/           FastAPI app (Phase 0)
frontend/          React app: ops + supplier portal (Phase 0)
supabase/          Supabase CLI config (Phase 0)
infra/             docker-compose (Redis), deployment config
```

## Contributing (single developer)

One branch per requirement group (`feat/r1-012-threshold`), Conventional Commits with
the requirement ID, PR into `main`, reviewed with `/review` before merge. See
`CLAUDE.md` §7–§8.

This software supports compliance work; it is not legal or tax advice.
