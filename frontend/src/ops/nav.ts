/** Navigation inside a tenant. A link shows only if the user has its permission.
 * This hides links for convenience; the API enforces every permission regardless. */
export interface NavItem {
  label: string
  to: string // relative to /ops/t/:tenantId
  permission?: string
  except?: string // not active under this sub-path (it has its own item)
}

export const NAV_ITEMS: NavItem[] = [
  { label: 'Home', to: '' },
  { label: 'Tasks', to: 'tasks', permission: 'tasks:read' },
  { label: 'Imports', to: 'imports', permission: 'imports:read', except: 'imports/lines' },
  { label: 'Import ledger', to: 'imports/lines', permission: 'imports:read' },
  { label: 'Customs data coverage', to: 'customs-data', permission: 'imports:read' },
]

export function visibleNav(permissions: ReadonlySet<string>): NavItem[] {
  return NAV_ITEMS.filter((item) => !item.permission || permissions.has(item.permission))
}

/** Is this item the current page? `base` is /ops/t/:tenantId; Home matches only exactly. */
export function isNavActive(item: NavItem, pathname: string, base: string): boolean {
  const own = item.to === '' ? base : `${base}/${item.to}`
  if (item.to === '') return pathname === own
  if (item.except && (pathname === `${base}/${item.except}` || pathname.startsWith(`${base}/${item.except}/`)))
    return false
  return pathname === own || pathname.startsWith(`${own}/`)
}
