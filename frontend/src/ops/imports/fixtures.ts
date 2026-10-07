import { me } from '@/test/renderApp'
import type { ImportBatch, RowException } from './types'

export const ID = '11111111-1111-4111-8111-111111111111'
export const reader = me({
  memberships: [
    {
      tenant_id: 't1',
      tenant_name: 'Alpha Ltd',
      roles: ['operations'],
      permissions: ['tasks:read', 'imports:read'],
      mfa_required: false,
    },
  ],
})

export const batch = (over: Partial<ImportBatch> = {}): ImportBatch => ({
  id: '11111111-1111-4111-8111-111111111111',
  status: 'completed',
  file_sha256: 'ab12',
  document_version_id: null,
  filename: 'march-items.csv',
  acquisition_method: 'cds_export',
  cds_report_type: 'import_item',
  eori: 'GB123456789012',
  window_start: '2027-03-01',
  window_end: '2027-03-31',
  source_owner: null,
  acquired_on: null,
  rows_total: 10,
  rows_processed: 10,
  rows_valid: 8,
  rows_rejected: 2,
  lines_created: 7,
  lines_unchanged: 1,
  failure_reason: null,
  report_layout_version_id: null,
  layout_status: 'active',
  created_at: '2027-03-31T23:30:00Z',
  created_by: null,
  row_version: 1,
  ...over,
})

export const exception = (over: Partial<RowException> = {}): RowException => ({
  id: 'e1',
  row_number: 3,
  field: 'line.commodity_code',
  code: 'CODE_INVALID',
  severity: 'error',
  message: 'The commodity code is not valid.',
  status: 'open',
  row_version: 1,
  ...over,
})

export const path = (url: string) => url.replace('/api/v1', '')
