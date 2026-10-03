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
