/** Import API shapes (backend: app/modules/imports/schemas.py). */
export type BatchStatus =
  | 'received'
  | 'queued'
  | 'parsing'
  | 'validating'
  | 'normalising'
  | 'completed'
  | 'completed_with_errors'
  | 'failed'
  | 'rejected'

/** Same set as TERMINAL_STATES in the backend imports/rules.py. */
export const FINAL_STATUSES: readonly BatchStatus[] = [
  'completed',
  'completed_with_errors',
  'rejected',
  'failed',
]

export const ALL_STATUSES: readonly BatchStatus[] = [
  'received',
  'queued',
  'parsing',
  'validating',
  'normalising',
  ...FINAL_STATUSES,
]

export interface ImportBatch {
  id: string
  status: BatchStatus
  file_sha256: string | null
  document_version_id: string | null
  filename: string | null
  acquisition_method: string
  cds_report_type: string | null
  eori: string | null
  window_start: string | null
  window_end: string | null
  source_owner: string | null
  acquired_on: string | null
  rows_total: number
  rows_processed: number
  rows_valid: number
  rows_rejected: number
  lines_created: number
  lines_unchanged: number
  failure_reason: string | null
  report_layout_version_id: string | null
  layout_status: string | null
  created_at: string | null
  created_by: string | null
  row_version: number
}

export interface Page<T> {
  items: T[]
  next_cursor: string | null
}

export interface RowException {
  id: string
  row_number: number
  field: string
  code: string
  severity: 'error' | 'warning'
  message: string
  status: 'open' | 'resolved' | 'waived'
  row_version: number
}

export interface ExceptionFilters {
  severity: '' | 'error' | 'warning'
  status: '' | 'open' | 'resolved' | 'waived'
}

export type EntryMethod = 'cds' | 'gcd' | 'manual' | 'correction'

/** backend: ImportLineOut. Masses and amounts are decimal STRINGS: never convert them. */
export interface ImportLine {
  id: string
  declaration_id: string
  mrn: string
  current_declaration_id: string
  declaration_superseded: boolean
  acceptance_date: string
  item_no: number
  version: number
  supersedes_id: string | null
  is_current: boolean
  commodity_code: string
  description: string | null
  net_mass_kg: string
  customs_value_source: string
  customs_value_currency: string
  customs_value_gbp: string | null
  customs_value_gbp_note: string | null
  valuation_basis: string | null
  value_source: string
  value_override_reason: string | null
  country_of_origin_declared: string
  cpc: string | null
  batch_id: string
  source_row_id: string
  entry_method: EntryMethod
  change_reason: string | null
  created_at: string | null
  open_exceptions: number
}

export interface Party {
  id: string
  eori: string | null
  name: string | null
}

export interface Declaration {
  id: string
  mrn: string
  version: number
  supersedes_id: string | null
  is_current: boolean
  acceptance_date: string
  acceptance_at: string | null
  procedure_code: string | null
  additional_procedure_codes: string[] | null
  importer: Party | null
  declarant: Party | null
  representative: Party | null
  representation_type: 'self' | 'direct' | 'indirect' | 'unknown'
  eori_context: 'GB' | 'XI' | null
  entry_method: EntryMethod
  batch_id: string
  created_at: string | null
}

export interface SourceRow {
  source_row_id: string
  role: 'primary' | 'header' | 'tax_line' | 'duplicate_seen'
  report_type: string | null
  batch_id: string
  row_number: number
  raw: Record<string, unknown> | null
  row_sha256: string
}

export interface ImportLineDetail {
  line: ImportLine
  declaration: Declaration
  sources: SourceRow[]
  batch: {
    id: string
    status: string
    acquisition_method: string
    cds_report_type: string | null
    eori_context: 'GB' | 'XI' | null
    acquired_on: string | null
    window_start: string | null
    window_end: string | null
  }
  file: {
    document_version_id: string | null
    filename: string | null
    sha256: string | null
    size_bytes: number | null
  }
  versions: {
    id: string
    version: number
    supersedes_id: string | null
    is_current: boolean
    change_reason: string | null
    batch_id: string
    created_at: string | null
  }[]
  open_exceptions: RowException[]
}

/** Ledger filters as they appear in the URL (all text; empty means not set). */
export interface LedgerFilters {
  commodity_code: string
  origin: string
  from: string
  to: string
  batch_id: string
  entry_method: '' | EntryMethod
  has_open_exceptions: '' | 'true' | 'false'
  include_superseded: '' | 'true'
}
