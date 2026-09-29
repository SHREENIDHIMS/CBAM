---
description: Plan one CBAM requirement or plan step before coding (no code changes)
argument-hint: <requirement ID(s) or plan step, e.g. R1-012 or "Phase 5 step 1">
---

Plan the work for: **$ARGUMENTS**

Do not change any source files.

1. Read the requirement row(s) with acceptance criteria from `docs/spec/CBAM_Spec_v1.4.md`
   or `docs/PRD.md` §6 / `docs/GAP_ANALYSIS.md` §9.3, and the matching step in
   `plans/IMPLEMENTATION_PLAN.md`. Confirm earlier phases it depends on are done.
2. Search the code for what already exists and can be reused.
3. If the work adds tables, cross-module flows or a state machine, use the
   `architect` agent. If it touches legal logic or reference data, use the
   `regulatory-analyst` agent.
4. Produce the plan:
   - Requirement IDs and each acceptance criterion → the test that will prove it
   - Files to create/change (module pattern: `rules.py`, `service.py`, `api.py`, models, migration, UI)
   - Reference datasets/versions needed (fixture vs official)
   - Open decisions hit (`docs/OPEN_DECISIONS.md`) and the configuration hook used instead
   - Checks against `CLAUDE.md` §3 rules that apply
   - Branch name (`feat/r1-xxx-short-name`) and commit breakdown
5. Stop and wait for approval.
