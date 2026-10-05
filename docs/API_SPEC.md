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
| POST | `/tenants/{t}/import-batches` | Upload CDS file (multipart `file` + `acquisition_method`, optional `cds_report_type`, `eori`, `window_start`, `window_end`, `source_owner`, `acquired_on`); `imports:write`; optional `Idempotency-Key`. **202** new batch (`status: received`, queued for processing after it is saved; a replay is queued again only if its batch is still `received`/`queued` and older than `IMPORT_STALE_BATCH_MINUTES`, a beat task `imports.sweep_stale_batches` (every 5 minutes) re-queues batches still `received`/`queued` after `IMPORT_STALE_BATCH_MINUTES`, and a broker outage leaves the batch `received` rather than failing the upload), **200** `replayed: true` when the same SHA-256 and details were already received, **409** same file with different declared details, or an `Idempotency-Key` already used for a different file, **413** over `IMPORT_MAX_FILE_BYTES`, **415** not UTF-8 CSV text (binary, NUL bytes), **422** bad details, empty file or no header row, **429** too many uploads in flight for this client (`Retry-After`; cap `IMPORT_MAX_CONCURRENT_UPLOADS_PER_TENANT`, per API process), **503** storage not configured. Replay rules: the same bytes replay whatever `Idempotency-Key` is sent (a different key for a file already received is ignored and not stored); a batch in `failed` or `rejected` is history and does not count, so the same bytes after one of those create a new batch (202) while the old batch stays as it was; after `completed` or `completed_with_errors` they replay (200). The `Idempotency-Key` header must be 1 to 200 visible ASCII characters (422 otherwise). `failure_reason` on a batch is a short code (`^[a-z0-9_]{1,64}$`), never parser text |
| GET | `/tenants/{t}/import-batches` · `/{id}` | Status, counts, provenance (`imports:read`); list is newest first with `status`, `limit`, `cursor`; another tenant's batch is 404. After validation (`validating`), an `import_item` batch moves to `normalising`: every row with no error-severity exception (warning-only rows are valid) becomes a declaration, a line and parties, grouped per MRN under a lock, in resumable chunks. New facts make version 1; identical facts seen again (an overlapping file) add only a `duplicate_seen` source link and count in `lines_unchanged`; changed facts make a new version that supersedes the old one (`change_reason: source_changed`); stale data never supersedes: a row equal to ANY earlier version is only a sighting, a current version that was corrected or keyed by hand (`entry_method`/`value_source` `correction` or `manual`) is never superseded by a file (`SOURCE_CONFLICTS_WITH_CORRECTION`), and a report older than the one the current version came from (acquired date, else window end, else received date) is not applied (`OLDER_EXTRACT_CONFLICT`; equal dates let the later-loaded report win); rows of one file that disagree about a line key or a declaration are ALL rejected before any is applied (`LINE_CONFLICT_IN_FILE`, `DECLARATION_FACTS_CONFLICT`). `entry_method` is `gcd` for Get customs data and `cds` for CDS exports, data requests and manual uploads (provisional, DATA-DEC-025); `manual` is reserved for human-keyed entry. `lines_created` counts lines made by the batch. An item report whose layout does not map the mandatory line fields is `rejected` with `COLUMN_MISSING` for each field; other report types are joined by the adapter (step 8a) |
| GET | `/tenants/{t}/import-batches/{id}/exceptions` | Exception report of a batch (`imports:read`; a tax agent can read). JSON is ascending by row number, with `severity=error\|warning`, `status=open\|resolved\|waived`, `limit` (max 200) and `cursor` (422 for a bad value or cursor, including a row number out of range). `format=csv` streams every matching row with a header row `row_number,field,code,severity,message,status`, `Content-Disposition: attachment`, `nosniff`, and escapes every cell that starts with `=`, `+`, `-`, `@`, tab or CR with a leading apostrophe. `field` is a canonical field name (`line.commodity_code`) or, for a missing column, the layout's column name; `row_number` counts CSV records (data rows after the header), not file lines, so a quoted newline stays one row; 0 means a problem with the whole file; `code` is `^[A-Z0-9_]{1,64}$`; `message` is fixed text per code and never contains a cell value. Another tenant's batch is 404 |
| POST | `/tenants/{t}/import-batches/{id}/retry` | Retry a `failed` batch (`imports:write`, `If-Match` row version: 428 without, 409 if stale). `failed` is final and locked, so this creates a NEW batch (202, `Location`, `status: received`) for the same stored file and declared details and queues it; the failed batch stays as history. Processing is capped per file by `IMPORT_MAX_COLUMNS`, `IMPORT_MAX_HEADING_CHARS`, `IMPORT_MAX_CELL_CHARS`, `IMPORT_MAX_ROW_CHARS` (which applies to the raw CSV record as read, quoted newlines included, before any trimming) and the chunk budget `IMPORT_CHUNK_MAX_BYTES`; a file over a limit is `rejected` with a file-level code (`HEADER_TOO_MANY_COLUMNS`, `HEADER_TOO_LONG`, `ROW_TOO_LARGE`, `FILE_UNREADABLE`) and rows saved before the problem stay with their counters. A NUL character in the stored file is `FILE_UNREADABLE`. A running job holds a lease (`IMPORT_LEASE_SECONDS`) with an owner token (`lease_owner`): it is renewed after every chunk and on a time basis (every third of the lease) while a resumed job skips rows already saved, and only the token holder renews or releases it; a job that finds another token stops and leaves the batch alone. After a handled failure the lease is handed back and expires after the task's retry back-off, so the sweeper and the retry do not both take over. A duplicate job inside a fresh lease returns at once and does not count; only a first start or a takeover of a lost worker's expired lease is an attempt (a start after a clean hand-back is not; the hand-back lasts the retry back-off plus `IMPORT_RETRY_MARGIN_SECONDS`), and a batch started more than `IMPORT_MAX_ATTEMPTS` times becomes `failed` with `worker_crash_loop`. The sweeper also re-queues `parsing`/`validating` batches whose lease has expired (a killed worker). A record that hides newlines inside quotes is bounded by the row and column caps (`ROW_TOO_LARGE`, `HEADER_TOO_LONG`, `HEADER_TOO_MANY_COLUMNS`). A file whose scan state is `infected` is `rejected` with `FILE_INFECTED`; `pending`/`not_scanned` still process until Phase 7 gates on `clean`. A resumed batch keeps the layout version it started with, even if that version is later retired or withdrawn. The layout is chosen for the batch's `acquired_on` (else its received date), and a layout with a date column but no `date_format`, or two columns mapped to one field, is `rejected` with `LAYOUT_INVALID`. 409 if the batch is not `failed` or the file already has a live batch |
| GET | `/tenants/{t}/customs-data/coverage?eori=&from=&to=` | Coverage calendar: loaded windows, gaps, overlaps (R1-054) |
| GET/PUT | `/tenants/{t}/customs-data/access` | Third-party access status per EORI (R1-054) |
| GET | `/tenants/{t}/import-lines` | Ledger (`imports:read`; a tax agent can read, a supplier cannot: 403): cursor-paginated (`limit` max 200, `cursor`), newest first, CURRENT versions only unless `include_superseded=true`. Filters: `commodity_code` (prefix, 1 to 10 digits), `origin` (2 capitals), `from`/`to` (the acceptance date as reported, inclusive; NOT a tax point), `batch_id`, `entry_method=cds\|gcd\|manual\|correction`, `has_open_exceptions`. 422 for a bad filter or cursor. Each item has the line, `mrn`, `version`, `is_current` and `open_exceptions`, and the declaration facts of the CURRENT declaration version for its MRN (`acceptance_date`, `current_declaration_id`); `declaration_superseded` is true when the line's own `declaration_id` is no longer the current version (a later file corrected the header); amounts are decimal strings. There are no scope, tax-point, quarter or threshold fields (Phase 4 adds a separate decision view). Scope, tax-point state, quarter and supplier filters arrive with their phases |
| GET | `/tenants/{t}/import-lines/{id}` | Line detail (`imports:read`): the line; its declaration with importer, declarant and representative parties and `representation_type` as reported; EVERY source row it came from through `import_line_sources` (role `primary` or `duplicate_seen`, report type, row number, the raw cell text and its SHA-256, and the batch it came from); the batch; the stored file's `filename`, `sha256` and `size_bytes` (NOT a download); the whole version chain; and the open exceptions of its source rows. Another tenant's line is 404 |
| GET | `/tenants/{t}/declarations/{id}` | One declaration with its parties (`imports:read`); 404 for another tenant's |
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
