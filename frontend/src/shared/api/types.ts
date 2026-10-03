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
