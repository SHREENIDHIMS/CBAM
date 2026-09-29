---
description: Implement an approved CBAM plan test-first, then verify
argument-hint: <requirement ID(s) or plan step>
---

Implement: **$ARGUMENTS** (the plan must already be approved in this conversation;
if not, run `/plan $ARGUMENTS` first).

1. Check `git status` is clean and you are on a feature branch (`feat/...` or `fix/...`),
   not `main`. Create the branch if needed.
2. Write the failing tests first (named with the requirement ID; regulatory tests cite
   the source and use fixture reference data and a frozen clock). Run them and show
   they fail for the right reason.
3. Implement the smallest change that passes, following `CLAUDE.md` §3 and §5 (use the
   `developer` agent for larger steps).
4. Run: targeted tests → full backend suite → `ruff check`, `ruff format --check`,
   `mypy app` → frontend lint/typecheck/tests if touched → Alembic up/down/up if a
   migration was added.
5. For UI changes, run the app and check the screen with Playwright (desktop and, for
   the portal, a mobile viewport); run axe.
6. Tick the step in `plans/IMPLEMENTATION_PLAN.md` and add a line to
   `plans/CHANGELOG.md` under Unreleased.
7. Commit with Conventional Commits including the ID (e.g. `feat(threshold): R1-012 backward test`).
   No AI attribution in commits.
8. Report: files changed, tests added, commands + results, anything not verified. Suggest `/review`.
