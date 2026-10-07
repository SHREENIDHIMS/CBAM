/** Customs-data coverage API (backend: app/modules/coverage/schemas.py). */
export type ThirdPartyAccess = 'unknown' | 'requested' | 'granted' | 'revoked'
export type ReportType = 'import_item' | 'import_header' | 'import_tax_lines' | 'export_item'
export type PeriodState = 'loaded' | 'loaded_with_errors' | 'gap' | 'not_yet_available'

/** The server's EORI format (a GB or XI EORI: two letters and twelve digits). */
export const EORI_PATTERN = /^(GB|XI)[0-9]{12}$/

export const ACCESS_VALUES: readonly ThirdPartyAccess[] = [
  'unknown',
  'requested',
  'granted',
  'revoked',
]
export const REPORT_TYPES: readonly ReportType[] = [
  'import_item',
  'import_header',
  'import_tax_lines',
  'export_item',
]
export const NOTE_MAX = 500

export interface Eori {
  id: string
  eori: string
  tracking_from: string
  third_party_access: ThirdPartyAccess
  access_recorded_on: string | null
  note: string | null
  row_version: number
  created_at: string
}

export interface Period {
  covered_from: string
  covered_to: string
  state: PeriodState
  days: number
}

export interface Overlap {
  covered_from: string
  covered_to: string
  batch_ids: string[]
}

export interface Calendar {
  eori: string
  report_type: ReportType
  tracking_from: string
  registered: boolean
  third_party_access: ThirdPartyAccess
  range_from: string
  range_to: string
  periods: Period[]
  gaps: Period[]
  overlaps: Overlap[]
  complete: boolean
  unavailable_latest_days: number | null
  dataset_version_ids: string[]
}

export interface ScanResult {
  eoris_scanned: number
  gap_tasks_created: number
  month_tasks_created: number
}
