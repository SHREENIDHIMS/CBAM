---
description: Whole-repo CBAM compliance and quality audit (report only, no changes)
argument-hint: [optional focus: compliance | security | tests | traceability | all]
---

Audit the repository. Focus: **$ARGUMENTS** (default: all). Report only; change nothing.

1. **Compliance rules** (`CLAUDE.md` §3): search for regulatory numbers in code
   (e.g. `50000`, `50_000`, `0.8`, `31`, dates like `2028-01-31`, rate/default values),
   `float` in `backend/app`, `datetime.now(`/`date.today(` in business code, tables
   with `tenant_id` lacking forced RLS, state changes without `audit.record`, one-way
   states without a DB guard, frontend calls to Supabase tables.
2. **Traceability**: for each requirement ID marked done in
   `plans/IMPLEMENTATION_PLAN.md`, find at least one test named with that ID. List
   IDs marked done without tests, and tests referencing unknown IDs.
3. **Reference data**: every dataset in `backend/refdata/` has a manifest with source,
   status, checksum; checksums match; no draft source marked active.
4. **Security**: run the `security` agent over the whole backend/frontend; run
   `pip-audit`, `npm audit --audit-level=high`, `gitleaks detect`.
5. **Tests**: coverage report vs gates in `docs/TESTING.md` §4; skipped tests; tests
   depending on real time.
6. **Docs drift**: endpoints in code vs `docs/API_SPEC.md`; tables vs `docs/DATABASE.md`;
   open decisions referenced in code vs `docs/OPEN_DECISIONS.md`.

Output a report grouped by area with severity and `path:line`, then a short
prioritised fix list. Offer to write it to `docs/releases/audit-<date>.md`.
