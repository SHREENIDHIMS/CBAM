# Security and privacy

The platform holds commercial customs data, supplier personal data and tax records
for many clients. The worst outcomes are: one client seeing another's data, a
tampered figure in a return, or evidence lost before six years.

## 1. Assets

| Asset | Sensitivity |
|---|---|
| Import ledger, customs values, supplier lists | Commercially confidential per client |
| Supplier contact details | Personal data (UK GDPR) |
| Emissions evidence, verifier reports | Confidential; legal evidence |
| Returns, payments, HMRC correspondence | Tax records; 6-year retention |
| Audit log | Integrity-critical |
| Reference data | Integrity-critical (wrong data → wrong tax for everyone) |
| Credentials, session tokens, magic-link tokens, MFA secrets | Secret |

## 2. Threat model (short STRIDE)

| Threat | Example | Controls |
|---|---|---|
| Spoofing | Stolen password; forged JWT; guessed magic link | Supabase Auth with TOTP MFA (`aal2` required for privileged roles), JWT signature/expiry/audience checks (R1-042); 256-bit random link tokens, stored hashed, expiry, single-case scope, revoke on resend (R1-041) |
| Tampering | Edit a customs value or audit row; swap a document | Versioned facts, RLS, audit trigger + grants + hash chain, SHA-256 on every file, object versioning, `row_version` checks |
| Repudiation | "I never approved that return" | Audit events with actor, request ID, before/after; approvals need MFA-passed session |
| Information disclosure | Cross-tenant read; link leaks in referrer/logs; PII in logs | RLS + app filter + tests; token swapped for cookie and removed from URL; `Referrer-Policy: no-referrer`; no PII in logs; signed URLs ≤ 5 min |
| Denial of service | Huge upload; import flood | Size limits, content-type allow-list, per-tenant job concurrency, request rate limits |
| Elevation of privilege | Supplier reaches ops API; agent registers liable person | Separate portal API surface and session type; permission per route; permission-matrix tests; tax-agent restrictions (R1-002) |
| Wrong law | Draft notice activated; bad reference file | Source activation rule, domain-owner approval (platform-level grant, ADR-0003), dry-run impact report sealed to the version, reason and warning acknowledgement, checksums (R1-050, R2-020). Residual: a stolen `cbam_app` credential can spoof `app.user_id`; a separate loader/approver credential is an open item |

## 3. Controls by area

### Authentication (R1-042)
- Supabase Auth: minimum password length 12, leaked-password protection on,
  email confirmation on, rate limits on.
- MFA: TOTP. FastAPI refuses privileged roles unless the JWT is `aal2`; approvals,
  reference-data activation, role changes and support access also need a token
  issued within the last 15 minutes (re-authenticate).
- Tokens: short-lived access tokens, refresh rotation on. The Supabase
  `service_role` key exists only in the backend secret store, never in the
  frontend, never in logs.
- The Supabase Data API does not expose the `cbam` schema, so a stolen user token
  cannot read business tables except through FastAPI's permission checks.

### Supplier magic links (R1-017, R1-041)
- Token: 32 random bytes (URL-safe), only the SHA-256 is stored.
- Scope: one supplier case. Expiry configurable (default 7 days). Resend creates
  a new token and revokes the old one. Revoke is immediate.
- First use exchanges the token for a portal session cookie (short idle timeout);
  the SPA replaces the URL so the token is not kept in history.
- Rate limit link attempts per IP; all issue/use/expire/revoke events audited.
- Portal shows no other case, supplier, installation or client data.

### Tenant isolation
- RLS forced on every tenant table; app role without BYPASSRLS.
- Tests: for every list/detail endpoint, a user of tenant A gets 404 for tenant B IDs.
- Background jobs set tenant explicitly; object storage keys are prefixed
  `tenants/{tenant_id}/` and the download endpoint re-checks the DB record.

### Files (R1-048)
- Content-sniffed allow-list, size limit, randomised storage keys, private Supabase
  Storage bucket (encrypted at rest), no public URLs. Files are never overwritten:
  each version gets a new key and the database keeps the SHA-256. The nightly
  off-platform copy (DEPLOYMENT §7) is the second line of defence for evidence.
- Malware scan hook (ClamAV container locally/at pilot, or provider service);
  `pending` files are not downloadable by others; `infected` quarantined.
- Office files are never rendered server-side with macros; Excel parsed with
  `openpyxl` read-only, formulas not evaluated.
- CSV exports escape leading `= + - @` to prevent formula injection.

### Web
- HTTPS only, HSTS. Bearer tokens (no auth cookies, so no CSRF); the portal
  session cookie is Secure/httpOnly/SameSite=Strict.
- Because supabase-js keeps the session in browser storage, XSS is the main token
  risk: strict CSP `default-src 'self'` (+ the Supabase and Sentry origins), no
  inline scripts, `frame-ancestors 'none'`, no `dangerouslySetInnerHTML`.
- CORS: none needed (same origin).
- Input validation with Pydantic at every boundary; SQL only through SQLAlchemy
  parameters.
- Outbound HTTP (source watcher, HMRC, EORI check) only to allow-listed hosts (SSRF).

### Secrets
- Environment variables from the platform secret store (AWS Secrets Manager in
  prod). `.env` only locally, never committed. `gitleaks` in CI and pre-commit.
- MFA secrets live in Supabase Auth, not in our tables.

### Privileged access (R1-049)
- Platform admins see tenant business data only through a time-boxed, reasoned
  support grant, visible to the tenant.

## 4. Privacy (UK GDPR)

| Topic | Rule |
|---|---|
| Roles | Our company is processor for client data, controller for platform accounts (confirm in contracts) |
| Personal data held | User accounts; supplier contacts (name, email, phone, language); verifier/reviewer names in evidence |
| Lawful basis | Recorded per supplier contact (`lawful_basis` field) |
| Minimisation | Only contact data needed to request emissions data |
| Retention | Account data: while active + 1 year. Supplier contacts: while supplier relationship active; evidence records follow the 6-year CBAM rule |
| Rights | DSAR export and erasure for personal data, except where CBAM retention or legal hold requires keeping it (record the reason) |
| Processors | Register of sub-processors (Supabase, container host, Redis host, Resend, Sentry, malware scan, Anthropic/Claude API for R2) with region and DPA; OCR/LLM only under R2-030 |
| Breach | 72-hour ICO notification process in the incident runbook |

## 5. Security testing

- Unit/integration: permission matrix, RLS coverage test, `cbam` schema not reachable
  by `anon`/`authenticated`, JWT tampering/expiry/`aal` checks, magic-link lifecycle,
  upload type spoofing, signed-URL expiry, audit immutability (UPDATE/DELETE
  as app role must fail).
- CI: `pip-audit`, `npm audit --audit-level=high`, `gitleaks`, `ruff` S-rules.
- Before Pilot and each release: OWASP ZAP baseline scan against staging; the
  `security` agent reviews the release diff; manual check of spec §16 security
  tests (cross-tenant, link abuse, document access, privilege escalation, audit
  tampering, unsafe upload).
- Before Live: independent basic pen test if budget allows (spec G8).

## 6. Incident response (short)

1. Contain (revoke sessions/links, disable account, block IP).
2. Preserve evidence (legal hold on affected records; export logs).
3. Assess personal-data impact → ICO within 72 h if required; tell affected clients.
4. Fix root cause with a regression test; record in `plans/CHANGELOG.md` and the
   lessons file.
