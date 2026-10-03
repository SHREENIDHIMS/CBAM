# ADR-0003: Who approves reference data, and how the database enforces it

**Status:** Accepted for Phase 2 (3 Oct 2026). Revisit under GOV-DEC-009.
**Requirement:** R1-050 (extends to R2-015, R2-020)

## Context

Reference data is law as data (CLAUDE.md rule 1). One wrong row changes the tax for every
client, so activating it is the most sensitive action in the platform. The permission matrix
already names a `domain_owner` role with `refdata:activate`, but that role is a **tenant**
membership, and a client admin may hand out any tenant role inside their own client
(`TENANT_ASSIGNABLE_ROLES`). Reference data is platform-wide (no `tenant_id`), so a client admin
could otherwise make themselves an approver of global law.

## Decision

1. Reference-data approval is a **platform-level** grant: the table `platform_domain_owners`.
   Only an operator with the owner database URL can add a row (`python -m
   app.cli.bootstrap_domain_owner`, audited). The application role cannot insert into it.
2. The API checks that table, not a client role. Platform admins may read reference data but
   cannot generate impact reports, activate or change a source status; domain owners can,
   with an `aal2` token and a login within 15 minutes.
3. The database enforces the same rules, so a bug or a hidden button is never the only guard:
   - a dataset version is always inserted `pending` and its rows only enter a `pending`
     version; rows never change and nothing is deleted;
   - a version leaves `pending`, or is retired, only for a domain owner, and an activation must
     record the same user as `activated_by`;
   - a source is registered `draft` or `laid` unless a domain owner says otherwise, and only a
     domain owner can change one.
4. A dataset version drives decisions only when it is `active` **and** its source is
   `in_force`/`commenced` on the date. The loader cannot put a source in force: a manifest may
   declare `draft` or `laid` only. So the same file can sit loaded and active while its source is
   still `draft`, and `get()` returns nothing until the domain owner sets the source status.
5. Activation needs a stored impact report made against the version that is active right now;
   if the active version changes first, the report must be generated again.

## Consequences

- One more table and a CLI to run once per approver. The tenant `domain_owner` role still exists
  for tenant-level review work; it grants no access to `/platform` reference-data routes.
- The impact report lists the dataset diff and coverage gaps. The list of **affected import
  lines** comes from a provider that Phase 3 registers (`register_impact_provider`); until then
  the report says so. A provider must not read across tenants (CLAUDE.md rule 7).
- Fixture datasets (`fixture: true`) cannot be loaded or activated in production.
