# API specification

The live contract is the OpenAPI schema FastAPI generates at `/api/v1/openapi.json`.
This document fixes the conventions and the resource map so endpoints are designed
the same way every time. Update it when you add a resource.

## 1. Conventions

| Topic | Rule |
|---|---|
| Base path | `/api/v1` |
| Format | JSON, UTF-8. Field names `snake_case`. |
| Tenancy | Tenant is in the path: `/api/v1/tenants/{tenant_id}/…`. Server checks membership, then sets RLS. Platform endpoints: `/api/v1/platform/…`. Supplier portal: `/api/v1/portal/…`. |
| Auth (users) | `Authorization: Bearer <Supabase access token>`. FastAPI verifies the JWT against the project JWKS, checks expiry/audience, and requires `aal2` for MFA-required roles. No cookies, so no CSRF token. |
| Auth (suppliers) | Magic link `/{portal_base}/l/{token}` → `POST /api/v1/portal/sessions` exchanges the token for a portal session cookie scoped to one supplier case; the token is then removed from the URL. |
| Decimals | Strings: `"48200.000000"`. Currency always alongside money: `{"amount": "1234.56", "currency": "GBP"}`. |
| Dates | Legal dates `YYYY-MM-DD`; instants ISO-8601 UTC `2027-01-04T09:30:00Z`. |
| IDs | UUIDv7 strings. |
| Pagination | `?limit=50&cursor=…` → `{"items": [...], "next_cursor": "…" \| null}`. Max limit 200. |
| Filtering/sorting | Explicit query params per resource (`?status=open&sort=-due_date`). No generic query language. |
| Create idempotency | `Idempotency-Key` header required on POST that creates business records; same key + same body → same response; same key + different body → 422. |
| Concurrency | Responses include `row_version`; updates/approvals send `If-Match: <row_version>`; mismatch → 409 (R1-045). |
| Errors | `application/problem+json` (RFC 9457): `type`, `title`, `status`, `detail`, `instance`, plus `rule_id`, `source_id`, `errors[]` where relevant. |
| Reason | State changes that the spec says need a reason take `"reason": "…"` (required, non-empty). |
| Versioning | Breaking change → `/api/v2`. Additive changes are fine in v1. |

### Error example

```json
{
  "type": "https://cbam.example/errors/rule-blocked",
  "title": "Amendment blocked by law",
  "status": 422,
  "detail": "An amendment cannot replace default-emissions information with actual-emissions information.",
  "rule_id": "R3-014",
  "source_id": "FA2026-SCH17-P8-2"
}
```

## 2. Resource map

R = requirement IDs. Only R1 resources are designed in detail now; R2/R3 are
listed so names stay consistent.

### Auth and users (R1-042, R1-002, R1-049)

Sign-in, MFA enrolment/challenge, sign-out and password reset are done by the
frontend with `supabase-js` directly against Supabase Auth. Our API only consumes
the resulting token.

| Method | Path | Purpose |
|---|---|---|
| GET | `/me` | Current user, memberships, roles, permissions, whether MFA is required/passed |
| GET/POST | `/tenants/{t}/users` | List/invite users |
| PATCH | `/tenants/{t}/users/{id}` | Roles, disable |
| POST | `/platform/support-access` | Start break-glass access (reason, tenant, expiry) |

### Organisations and onboarding (R1-001, R1-036, R1-051)

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/platform/tenants` | Tenants (platform admin) |
| GET/PATCH | `/tenants/{t}/organisation` | Business details, EORI/VAT, liable-person vs agent |
| POST | `/tenants/{t}/onboarding/suppliers-csv` | Upload → preview with row errors |
| POST | `/tenants/{t}/onboarding/suppliers-csv/{upload_id}/commit` | Commit good rows |

### Imports (R1-003–006, 010, 025, 031, 034, 035, 037, 038)

| Method | Path | Purpose |
|---|---|---|
| POST | `/tenants/{t}/import-batches` | Upload CDS file (multipart `file` + `acquisition_method`, optional `cds_report_type`, `eori`, `window_start`, `window_end`, `source_owner`, `acquired_on`); `imports:write`; optional `Idempotency-Key`. **202** new batch (`status: received`), **200** `replayed: true` when the same SHA-256 and details were already received, **409** same file with different declared details, or an `Idempotency-Key` already used for a different file, **413** over `IMPORT_MAX_FILE_BYTES`, **415** not UTF-8 CSV text (binary, NUL bytes), **422** bad details, empty file or no header row, **429** too many uploads in flight for this client (`Retry-After`; cap `IMPORT_MAX_CONCURRENT_UPLOADS_PER_TENANT`, per API process), **503** storage not configured. Replay rules: the same bytes replay whatever `Idempotency-Key` is sent (a different key for a file already received is ignored and not stored); a batch in `failed` or `rejected` is history and does not count, so the same bytes after one of those create a new batch (202) while the old batch stays as it was; after `completed` or `completed_with_errors` they replay (200). The `Idempotency-Key` header must be 1 to 200 visible ASCII characters (422 otherwise). `failure_reason` on a batch is a short code (`^[a-z0-9_]{1,64}$`), never parser text |
| GET | `/tenants/{t}/import-batches` · `/{id}` | Status, counts, provenance (`imports:read`); list is newest first with `status`, `limit`, `cursor`; another tenant's batch is 404 |
| GET | `/tenants/{t}/import-batches/{id}/exceptions` | Row-level exception report (JSON/CSV) |
| GET | `/tenants/{t}/customs-data/coverage?eori=&from=&to=` | Coverage calendar: loaded windows, gaps, overlaps (R1-054) |
| GET/PUT | `/tenants/{t}/customs-data/access` | Third-party access status per EORI (R1-054) |
| GET | `/tenants/{t}/import-lines` | Ledger with filters: scope, tax-point state, quarter, supplier |
| GET | `/tenants/{t}/import-lines/{id}` | Line detail: source row, parties, decisions, timeline |
| POST | `/tenants/{t}/import-lines` | Manual entry (reason required) |
| POST | `/tenants/{t}/import-lines/{id}/corrections` | Correction → new version (reason required) |
| GET | `/tenants/{t}/reconciliation-events` | Duplicates, amendments, conflicts |
| GET/POST | `/tenants/{t}/forecasts` | Forward-test forecast register (versioned) |

### Scope, tax point, threshold (R1-007–009, 011, 012, 027, 032)

| Method | Path | Purpose |
|---|---|---|
| GET | `/tenants/{t}/import-lines/{id}/decisions` | Scope/exclusion/origin/tax-point decisions with rule + source versions |
| POST | `/tenants/{t}/import-lines/{id}/manual-review` | Resolve a flagged line (outcome, reason, evidence IDs) |
| GET | `/tenants/{t}/threshold` | Current state, latest snapshots |
| GET | `/tenants/{t}/threshold/events` | Trigger events (test type, earliest date) |
| POST | `/tenants/{t}/threshold/recalculate` | Operator-triggered run (idempotent per as_of) |

### Registration (R1-013, 014, 030, 033, 040)

| Method | Path | Purpose |
|---|---|---|
| GET | `/tenants/{t}/registration` | Status record, deadline + basis, service state |
| GET/POST | `/tenants/{t}/registration/readiness-packs` | Generate/list versioned packs |
| POST | `/tenants/{t}/registration/readiness-packs/{id}/declaration` | Completeness declaration |
| GET | `/tenants/{t}/registration/readiness-packs/{id}/export` | PDF/CSV |
| POST | `/tenants/{t}/registration/status-transitions` | Record submitted/registered + HMRC reference |
| GET | `/tenants/{t}/registration/changes` | Change-control notifications |

### Suppliers, portal, outreach, documents (R1-015–019, 028, 029, 039, 041, 046–048)

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/tenants/{t}/suppliers` · `/{id}` | Supplier master |
| GET/POST | `/tenants/{t}/suppliers/{id}/installations` | Installations |
| GET/PUT | `/tenants/{t}/installations/{id}/readiness` | Readiness questionnaire |
| GET/PUT | `/tenants/{t}/supplier-cases/{id}/responsibility` | Contract/evidence responsibility (versioned) |
| POST | `/tenants/{t}/supplier-cases` | Open a data request for installation + products + period |
| POST | `/tenants/{t}/supplier-cases/{id}/links` | Issue/resend link (invalidates prior) |
| DELETE | `/tenants/{t}/supplier-cases/{id}/links/{link_id}` | Revoke |
| GET | `/tenants/{t}/supplier-cases/{id}/timeline` | Sends, email events, submissions |
| POST | `/portal/sessions` | Exchange magic-link token |
| GET | `/portal/case` | Case summary + rendered form definition (language) |
| PUT | `/portal/case/draft` | Save draft answers |
| POST | `/portal/case/documents` | Upload evidence |
| POST | `/portal/case/submit` | Submit → submission version |
| POST | `/portal/case/eu-template` | Upload EU Communication Template → pre-filled draft for confirmation (R1-055) |
| GET | `/portal/help?question_key=` | Help text in the case language (R1-056) |
| POST | `/portal/case/questions` · GET `/portal/case/questions` | Ask a question / read answers (R1-056) |
| POST | `/webhooks/email/resend` | Delivery/bounce/complaint events (Resend webhook signature verified) |
| POST | `/tenants/{t}/documents` | Upload against supplier/installation/line/case |
| GET | `/tenants/{t}/documents/{id}` | Metadata, versions, scan state |
| POST | `/tenants/{t}/documents/{id}/download-url` | Short-lived signed URL (permission-checked) |
| GET/POST | `/platform/outreach-templates` | Template versions + translation approval |
| GET/POST | `/platform/help-texts` | Portal help text versions + approval (R1-056) |
| POST | `/platform/demo-tenant/reset` | Recreate the demo tenant (R1-058; refused in production) |
| GET/POST | `/portal/share-grants` · DELETE `/portal/share-grants/{id}` | Supplier grants/revokes importer access (R1-057, per ADR-0002) |

### Tasks, review, dashboard, exports (R1-020–022, 024)

| Method | Path | Purpose |
|---|---|---|
| GET | `/tenants/{t}/tasks` · PATCH `/{id}` | Tasks (assign, status, reason) |
| GET | `/tenants/{t}/review-items` · POST `/{id}/resolve` · `/{id}/reopen` | Review queue |
| GET | `/tenants/{t}/dashboard` | Posture summary |
| GET | `/platform/portfolio` | All-client health (operations) |
| POST | `/tenants/{t}/exports` · GET `/{id}` | Async export jobs (import register, supplier status, readiness, evidence index) |

### Reference data (R1-050 → R2-015, R2-020)

| Method | Path | Purpose |
|---|---|---|
| GET | `/platform/sources` · `/{id}` | Regulatory source registry |
| GET | `/platform/datasets` · `/{id}/versions` | Datasets and versions |
| GET | `/platform/datasets/{name}/versions/{v}` | One version with its stored impact report |
| POST | `/platform/datasets/{name}/versions/{v}/impact` | Dry-run impact report; seals the version (domain owner, recent login) |
| POST | `/platform/datasets/{name}/versions/{v}/activate` | Activate (domain owner, recent login, `If-Match`); body `{reason, acknowledge_warnings}`; needs a current impact report |
| POST | `/platform/sources/{id}/status` | Move a source forward, e.g. `laid` → `in_force`, with a reason; `superseded` also needs `effective_to` (domain owner, recent login, `If-Match`) |

Reference data is platform-wide. Reads need a platform admin or a registered **domain owner**;
impact reports, activation and source status need a domain owner (the `platform_domain_owners`
table, ADR-0003), not a client's `domain_owner` role. All need an `aal2` token.

### Later releases (names reserved)

R2: `/tenants/{t}/extractions`, `/emission-records`, `/verification-records`,
`/cpr-evidence`, `/evidence-lineage/{field_id}`, `/platform/processors`.
R3: `/tenants/{t}/returns`, `/returns/{id}/lines`, `/returns/{id}/approvals`,
`/returns/{id}/submissions`, `/amendments`, `/payments`, `/repayments`,
`/compliance-cases`, `/evidence-packs`, `/legal-holds`, `/tenant-export`.

## 3. Permissions

Each route declares one permission (`imports:write`, `review:resolve`,
`refdata:activate`, …). The role → permission map lives in `app/core/permissions.py`
and is tested as a matrix (R1-002). A tax agent never has `registration:submit_as_liable_person`.
