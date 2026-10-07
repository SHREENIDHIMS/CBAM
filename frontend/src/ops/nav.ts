/** Navigation inside a tenant. A link shows only if the user has its permission.
 * This hides links for convenience; the API enforces every permission regardless. */
export interface NavItem {
  label: string
  to: string // relative to /ops/t/:tenantId
  permission?: string
}

export const NAV_ITEMS: NavItem[] = [
  { label: 'Home', to: '' },
  { label: 'Tasks', to: 'tasks', permission: 'tasks:read' },
  { label: 'Imports', to: 'imports', permission: 'imports:read' },
]

export function visibleNav(permissions: ReadonlySet<string>): NavItem[] {
  return NAV_ITEMS.filter((item) => !item.permission || permissions.has(item.permission))
}
