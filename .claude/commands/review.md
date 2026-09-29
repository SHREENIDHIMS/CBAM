---
description: Review the current CBAM branch diff with the right agents before a PR
argument-hint: [optional base branch or PR number; default main]
---

Review the changes on this branch against **$ARGUMENTS** (default: `main`).

1. Show `git status` and `git diff --stat <base>...HEAD`. Identify the requirement IDs
   from commit messages and the plan.
2. Run the `reviewer` agent on the diff.
3. If the diff touches auth, tenancy/RLS, Supabase config, magic links, files, exports,
   webhooks, secrets or personal data → also run the `security` agent.
4. If it touches any `rules.py`, reference data (`backend/refdata/`, `ref_*` tables),
   deadlines or legal state machines → also run the `regulatory-analyst` agent.
5. Merge the findings into one list by severity (Blocker/Critical first), removing
   duplicates, each with `path:line` and a fix.
6. Check no AI attribution appears: `git log <base>..HEAD --format=%B | grep -ci "claude\|anthropic\|co-authored"` must be 0.
7. Verdict: ready for PR / changes required. Do not push or open the PR unless the user asks.
