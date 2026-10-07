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
