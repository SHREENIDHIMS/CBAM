---
description: Run CBAM tests (targeted first, then full) and report honestly
argument-hint: [optional path, marker or requirement ID, e.g. R1-012 or tests/scenarios]
---

Run tests for: **$ARGUMENTS** (empty = everything relevant to the current diff).

1. Make sure the local stack is up (`supabase status`, Redis). If not, say so and give
   the start commands from `README.md`; do not guess results.
2. Targeted: if an ID was given, `uv run pytest -q -k "<id with _ instead of ->"`;
   if a path was given, run that path; otherwise run tests for files changed in
   `git diff main...HEAD`.
3. Full backend: `uv run pytest -q`, then `uv run ruff check .`,
   `uv run ruff format --check .`, `uv run mypy app`, the float-ban grep.
4. Frontend (if touched): `npm run lint`, `npm run typecheck`, `npm test`,
   `npx playwright test` (smoke) with axe.
5. Report a table: command | result | counts. Paste the exact failure output (trimmed)
   for anything red, the likely cause, and which acceptance criteria remain unproven.
   Never report a pass for a command you did not run.
