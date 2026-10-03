/** Roles a client member can hold (platform_admin is never a client role). Product access
 * control, not law; the backend is the source of truth and rejects anything else. */
export interface RoleInfo {
  value: string
  label: string
  needsMfa: boolean
}

export const ASSIGNABLE_ROLES: RoleInfo[] = [
  { value: 'client_admin', label: 'Client admin', needsMfa: false },
  { value: 'operations', label: 'Operations', needsMfa: true },
  { value: 'reviewer', label: 'Reviewer', needsMfa: true },
  { value: 'approver', label: 'Approver', needsMfa: true },
  { value: 'domain_owner', label: 'Domain owner', needsMfa: true },
  { value: 'tax_agent', label: 'Tax agent', needsMfa: false },
  { value: 'supplier', label: 'Supplier', needsMfa: false },
]

export function roleLabel(value: string): string {
  return ASSIGNABLE_ROLES.find((r) => r.value === value)?.label ?? value
}
