# CLAUDE.md — CBAM (UK Carbon Border Adjustment Mechanism platform)

Read this file before every change. It holds decisions that are **already settled**.
Do not re-open them unless the user asks. If a task seems to need breaking one of
these rules, stop and ask instead of working around it.

This file is the summary. The detail lives in:

| Need | Read |
|---|---|
| What we are building and why | `docs/PRD.md` |
| The team's original handbook (plain-English CBAM + build rules) | `docs/spec/CBAM_Team_Handbook.md` (text copy of the PDF) |
| Every requirement ID (R1-xxx, R2-xxx, R3-xxx) with acceptance criteria | `docs/spec/CBAM_Spec_v1.4.md` (text copy of the signed-off `.docx`) plus the additions in `docs/PRD.md` §6 |
| What was wrong or missing in the spec, and how it was fixed | `docs/GAP_ANALYSIS.md` |
| System shape, modules, patterns | `docs/ARCHITECTURE.md` |
| Stack, coding rules, numbers, dates | `docs/TECHNICAL_SPEC.md` |
| Endpoints and error format | `docs/API_SPEC.md` |
| Tables, constraints, row-level security | `docs/DATABASE.md` |
| Threat model and controls | `docs/SECURITY.md` |
| Test layers, fixtures, gates | `docs/TESTING.md` |
| Environments, CI/CD, backups | `docs/DEPLOYMENT.md` |
| Release order and external blockers | `docs/ROADMAP.md` |
| Step-by-step build phases (the work list) | `plans/IMPLEMENTATION_PLAN.md` |
| Open questions nobody may guess | `docs/OPEN_DECISIONS.md` |
| Words like "tax point", "CPR", "precursor" | `docs/GLOSSARY.md` |
| Why a big choice was made | `docs/adr/` |

---

## 1. What this project is

A multi-client web platform that helps UK importers comply with the UK CBAM, which
starts on **1 January 2027**. It takes customs import data, works out which goods are
in scope, watches the £50,000 registration threshold, collects emissions evidence from
overseas suppliers, validates it, calculates the CBAM liability and Carbon Price
Relief, prepares and files returns, and keeps a six-year evidence trail.

It ships in three releases, always in this order:

- **R1 — Data Machine**: imports, scope, tax point, threshold, registration readiness,
  suppliers, outreach, documents, dashboard. **No tax calculation. No filing.**
- **R2 — Validation & Intelligence**: extraction, emissions model, verification,
  CPR evidence, plausibility rules, human review, reference-data admin.
- **R3 — Calculation & Filing**: liability, CPR, returns, approval, HMRC submission,
  payments, amendments, repayments, penalties, HMRC cases, retention.

R1 is split into a **Pilot cut** and a **Live cut** (see `docs/ROADMAP.md`).

## 2. Who works on it

One developer builds the whole system, using the Claude agents in `.claude/agents/`
for design, review, testing and security. There is no second human coder, so:

- Every change gets an automated review (`/review`) before it is merged.
- Every regulatory interpretation is checked by the `regulatory-analyst` agent and,
  where the spec marks it as open, signed off by the **domain owner** (the handbook
  names Jenny + ops; see `docs/OPEN_DECISIONS.md` GOV-DEC-009). Claude never signs off law.
- Scope order is fixed: finish R1 before R2, R2 before R3. If time is short, R1
  scope holds and R2 slips. Never pull R3 work into R1.

## 3. Non-negotiable rules (the compliance guarantees)

Breaking any of these is a bug, even if tests pass.

1. **Law is data, not code.** Commodity codes, thresholds, rates, default values,
   gas factors, functional units, deadlines, qualifying carbon-price schemes,
   penalty amounts, working-day calendars and payment methods live in versioned,
   effective-dated reference tables with a source link. Never write a regulatory
   number or list as a Python/TypeScript constant. The only exception is test
   fixtures, which must say where the value came from.
2. **Draft law never drives decisions.** A rule may be used only when its source in
   the regulatory source registry has status `in_force` or `commenced` and the
   transaction date is inside its effective period. Being loaded is not being active.
3. **Tax point first.** Work out the legal tax point before assigning a return
   period, quarter or threshold contribution. Never use the declaration date as a
   stand-in. If the tax point is unresolved, the line waits for manual review.
4. **Source → normalised → derived.** Never overwrite a source fact (CDS row,
   uploaded file, supplier submission). Corrections create a new version linked
   to the old one. Every derived number stores its formula version, reference-data
   versions and input IDs.
5. **Decimal only.** No `float` anywhere in money, mass, emissions, rates or FX.
   Use Python `Decimal` and PostgreSQL `NUMERIC`. Round only at the legally
   prescribed step, with the prescribed rule (see `docs/TECHNICAL_SPEC.md` §5).
6. **Legal dates are UK dates.** Store instants as UTC `timestamptz`. Store legal
   dates (tax point, deadlines, trigger dates) as `date` computed in
   `Europe/London`. Business logic never calls `now()` directly; it receives an
   `as_of` date from the injected clock so tests and historical replays work.
7. **Tenant isolation.** Every business row has `tenant_id`. PostgreSQL Row Level
   Security enforces it; the app also filters. A cross-tenant read is a P0 bug.
8. **Append-only audit.** Every business state change writes an audit event (actor,
   time, before, after, reason). The audit table cannot be updated or deleted by the
   application database role.
9. **Humans approve; the system never auto-files.** Rules can flag, suggest and
   block. Only an authorised user can approve evidence, a return or a filing.
10. **The verified result is authoritative.** The platform may recompute CO2e and
    intensity only as a plausibility check. A mismatch creates a review exception;
    it never replaces the verifier-approved figure.
11. **Default → actual amendment is legally blocked.** Finance Act 2026 Sch 17
    para 8(2). This lock is not configurable by any tenant, admin or flag.
12. **Precursor is a source, not a scope.** Emission scope is `DIRECT`/`INDIRECT`.
    Source is `OWN_INSTALLATION`/`PRECURSOR_GOOD`. Never add a third scope.
13. **Supplier SLA ≠ law.** The Day 0/7/14/21/28 chase is a product workflow. Day 28
    does not by itself make default values apply.
14. **Tax agent ≠ liable person.** An agent may prepare/submit when authorised, but
    can never register the liable person or become liable by submitting.
15. **No invented HMRC behaviour.** No guessed API endpoints, due dates, rates or
    defaults. If it is not in an active source, it is an open decision
    (`docs/OPEN_DECISIONS.md`) and the code uses a configuration hook.
16. **Legal hold beats retention.** Nothing covered by statutory retention, a legal
    hold or an HMRC preservation direction can be deleted. Deletions are audited.
17. **Legal state transitions are one-way and enforced twice** (handbook §11): a
    filed return locks, an approved decision cannot be edited. Enforce with a
    database constraint or trigger **and** an application check — never only by
    hiding a button.
18. **One path to the data.** The frontend never reads or writes business tables
    through Supabase's auto-generated API. Everything goes through FastAPI.

## 4. Stack (ADR-0001 — follows the Team Handbook)

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic |
| Database | Supabase PostgreSQL; business tables in private schema `cbam` (not exposed via the Supabase Data API); RLS per tenant; app connects as role `cbam_app` |
| Auth | Supabase Auth (email + password, TOTP MFA) for internal/client users; FastAPI verifies the JWT. Suppliers use our own magic links, never accounts |
| Files | Supabase Storage, private buckets, signed URLs issued by FastAPI |
| Background jobs | Celery + Redis; Celery beat for schedules |
| Email | Resend (adapter; local mail catcher from the Supabase CLI) |
| Errors | Sentry (PII scrubbing on) |
| Frontend | React + TypeScript + Vite, TanStack Query, React Router, Tailwind + shadcn/ui |
| R2 extraction | Claude API, only under R2-030 and always human-reviewed |
| Python tooling | `uv`, `ruff`, `mypy --strict` on `app/core` and every `rules.py`, `pytest`, `hypothesis` |
| Frontend tooling | `npm`, `eslint`, `tsc`, `vitest`, Playwright, axe-core |
| Local run | `supabase start` + `docker compose` (Redis) |
| Hosting | Supabase (London/EU region) + API/worker containers in a UK/EU region — OPS-DEC-010 |

Do not add a dependency without checking the rules in `docs/TECHNICAL_SPEC.md` §3.

## 5. Repository layout

```
CBAM/
├── CLAUDE.md                  ← this file
├── README.md                  ← how to run it
├── .env.example               ← every config variable, no secrets
├── .claude/
│   ├── settings.json          ← shared permissions for Claude in this repo
│   ├── agents/                ← architect, researcher, developer, reviewer, tester,
│   │                            security, devops, regulatory-analyst
│   ├── commands/              ← /plan /implement /test /review /audit /refdata /status
│   └── skills/                ← cbam-domain, reference-data, precision-and-dates,
│                                regulatory-tests
├── docs/
│   ├── spec/                  ← signed-off spec + Team Handbook (.docx/.pdf = truth, .md = search copies). Read-only.
│   ├── adr/                   ← architecture decision records
│   └── *.md                   ← PRD, architecture, specs, security, testing, deployment…
├── plans/
│   ├── IMPLEMENTATION_PLAN.md ← phases, steps, exit gates
│   └── CHANGELOG.md
├── backend/                   ← created in Phase 0
│   ├── app/
│   │   ├── core/              ← config, db, tenancy, auth, audit, clock, money, errors
│   │   └── modules/<name>/    ← models.py, schemas.py, rules.py, service.py, api.py
│   ├── refdata/               ← versioned reference-data seed files with source metadata
│   ├── migrations/            ← Alembic
│   └── tests/                 ← unit/, integration/, scenarios/, security/, load/, fixtures/
├── frontend/                  ← created in Phase 0
│   └── src/{ops,portal,shared}/
├── supabase/                  ← Supabase CLI project config (created in Phase 0)
└── infra/                     ← docker-compose.yml (Redis), deployment config
```

Module pattern (every backend module follows it):

- `rules.py` — **pure functions only**. No database, no clock, no network. Inputs:
  facts + reference-data snapshot + `as_of`. Output: a decision object with
  `rule_id`, `rule_version`, `source_ids`, `outcome`, `reason`. This is where the law lives.
- `service.py` — loads facts and reference data, calls `rules.py`, saves results and
  audit events in one transaction.
- `api.py` — FastAPI routes. Thin. Permission check, call service, return schema.
- `models.py` / `schemas.py` — SQLAlchemy tables / Pydantic request-response shapes.

## 6. Commands

Run from the repo root once Phase 0 exists (exact commands live in `README.md`):

```bash
supabase start                                           # postgres, auth, storage, studio, mail
docker compose -f infra/docker-compose.yml up -d        # redis
cd backend && uv sync && uv run alembic upgrade head
uv run pytest -q                                         # all backend tests
uv run pytest tests/scenarios -q                         # regulatory scenario fixtures
uv run ruff check . && uv run ruff format --check . && uv run mypy app
cd frontend && npm ci && npm run lint && npm run typecheck && npm test
npx playwright test                                      # E2E + accessibility
```

## 7. How to work (every task)

1. Find the requirement ID(s). No ID → ask, or add it to `docs/PRD.md` §6 first.
2. Read the requirement text and acceptance criteria in the spec, plus the phase in
   `plans/IMPLEMENTATION_PLAN.md`.
3. `/plan <ID>` → short plan: files, rules, reference data, tests, open decisions hit.
4. Write the failing test first. Regulatory tests name the requirement ID and the
   legal source (see skill `regulatory-tests`).
5. `/implement <ID>` → smallest change that passes. Follow the module pattern.
6. `/test` → targeted tests, then the full suite, lint and types.
7. `/review` → reviewer agent; add `security` agent when touching auth, tenancy,
   files, magic links or exports; add `regulatory-analyst` when touching `rules.py`
   or reference data.
8. Tick the step in `plans/IMPLEMENTATION_PLAN.md`, add a line to
   `plans/CHANGELOG.md`, open a PR.

**Definition of done:** acceptance criteria from the spec pass as automated tests;
lint, types and full suite green; migrations run up and down; audit events written
for every state change; no hard-coded regulatory values; docs updated if behaviour
changed; UI changes checked in a browser with Playwright.

## 8. Git

- Default branch `main`. One branch per requirement group: `feat/r1-012-threshold`,
  `fix/r1-017-link-expiry`. Conventional Commits with the ID:
  `feat(threshold): R1-012 backward monthly test`.
- Open a PR; never merge it, never push to `main`, never force-push, unless the user
  says so for that PR.
- **No AI attribution anywhere** (commits, PRs, comments, docs). No Co-Authored-By
  trailers, no "generated with" footers. This includes footers the GitHub tooling adds
  to a PR body: check the body after opening the PR and remove any footer.
- **Delete the branch after its PR is merged.** Once the user merges (or tells Claude to
  merge) a PR, delete its head branch on the remote and locally so the repository stays
  clean. Start the next piece of work from a fresh branch cut from the updated `main`.
  Never delete `main`, and never delete a branch that has an open PR or unmerged commits.
- `docs/spec/` is read-only. Spec changes go into `docs/PRD.md` §6 and
  `docs/GAP_ANALYSIS.md`, never into the signed-off files.

## 9. Secrets and data

- Never read `.env` or print secrets. Config comes from environment variables listed
  in `.env.example`.
- No real client or supplier data in the repo, in tests or in local databases. CDS
  samples must be masked before they enter `backend/tests/fixtures/`.
- Supplier contacts are personal data (UK GDPR). Do not log names, emails or phone
  numbers; log IDs.
- Do not send document contents to any third-party service (OCR, LLM) unless the
  tenant setting allows it (R2-030) and the domain owner approved the processor.

## 10. When unsure

- A legal point is unclear → do not guess. Add or update an entry in
  `docs/OPEN_DECISIONS.md`, build a configuration hook, and tell the user.
- A spec row seems wrong → note it in `docs/GAP_ANALYSIS.md` and ask.
- Two docs disagree → the order of precedence is: this file's §3 rules → the v1.4
  spec + `docs/PRD.md` §6 additions → the Team Handbook → the other docs. The spec
  corrects the handbook in several places (`docs/GAP_ANALYSIS.md` §9). Report the conflict.
