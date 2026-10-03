/** Shapes returned by GET /api/v1/me (backend: app/modules/identity/schemas.py). */
export interface Membership {
  tenant_id: string
  tenant_name: string
  roles: string[]
  permissions: string[]
  mfa_required: boolean
}

export interface Me {
  user_id: string
  platform_admin: boolean
  domain_owner: boolean
  memberships: Membership[]
  mfa: { required: boolean; passed: boolean }
}

/** Platform admin API (backend: app/modules/platform_admin/schemas.py). */
export interface Tenant {
  id: string
  name: string
  status: 'active' | 'suspended' | 'closed'
  row_version: number
  created_at: string
}

export interface Member {
  membership_id: string
  user_id: string
  email: string
  display_name: string | null
  roles: string[]
  row_version: number
}

/** Reference data API (backend: app/modules/refdata/schemas.py). */
export interface RegulatorySource {
  id: string
  source_id: string
  title: string
  source_type: string
  url: string | null
  publication_date: string | null
  status: 'draft' | 'laid' | 'in_force' | 'commenced' | 'superseded'
  commencement_date: string | null
  effective_from: string | null
  effective_to: string | null
  retrieved_at: string | null
  notes: string | null
  row_version: number
}

export interface RefDataset {
  id: string
  name: string
  active_version: string | null
  pending_versions: number
}

export interface DatasetVersion {
  id: string
  dataset: string
  version: string
  source_ref: string
  source_status: RegulatorySource['status']
  checksum_sha256: string
  effective_from: string
  effective_to: string | null
  is_fixture: boolean
  row_count: number
  status: 'pending' | 'active' | 'retired'
  loaded_at: string
  activated_by: string | null
  activated_at: string | null
  retired_at: string | null
  has_impact_report: boolean
  row_version: number
  notes: string | null
  impact_report?: ImpactReport | null
}

export interface ImpactChange {
  change: 'added' | 'removed' | 'changed'
  key: Record<string, string | null>
  effective_from: string
}

export interface ImpactReport {
  dataset: string
  version: string
  compared_to: { id: string; version: string } | null
  generated_at: string
  rows: { added: number; removed: number; changed: number; unchanged: number }
  changes: ImpactChange[]
  changes_truncated: boolean
  coverage_gaps: { key: Record<string, string | null>; from: string; to: string | null }[]
  source: { source_id: string; status: string; outcome: string; reason: string }
  affected: {
    provider_registered: boolean
    count: number
    items: { kind: string; ref: string; detail: string }[]
    truncated: boolean
  }
  warnings: string[]
}
