import { Link, NavLink, Outlet, useLocation, useNavigate, useParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { Button } from '@/shared/components/ui/button'
import { useMe } from '@/shared/api/queries'
import { useAuth } from '@/shared/auth/AuthContext'
import { isNavActive, visibleNav } from './nav'

/** App shell for one client account: header, role-aware navigation, sign-out. */
export function TenantShell() {
  const { tenantId } = useParams()
  const auth = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const me = useMe()
  const { pathname } = useLocation()

  if (me.isPending)
    return (
      <p role="status" className="p-6">
        Loading…
      </p>
    )
  if (me.isError)
    return (
      <p role="alert" className="p-6">
        We could not load your account.
      </p>
    )
  const membership = me.data.memberships.find((m) => m.tenant_id === tenantId)
  if (!membership) {
    return (
      <main className="p-6">
        <h1 className="text-2xl font-semibold">Not found</h1>
        <p>That client account does not exist, or you do not have access to it.</p>
      </main>
    )
  }
  const nav = visibleNav(new Set(membership.permissions))

  async function signOut() {
    await auth.signOut()
    queryClient.clear()
    navigate('/signin', { replace: true })
  }

  return (
    <div>
      <header className="flex items-center justify-between border-b px-6 py-3">
        <div>
          <strong>{membership.tenant_name}</strong>
          {me.data.memberships.length > 1 && (
            <NavLink to="/ops" className="ml-3 text-sm underline">
              Switch client
            </NavLink>
          )}
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span>{auth.user?.email}</span>
          <Button variant="outline" size="sm" onClick={signOut}>
            Sign out
          </Button>
        </div>
      </header>
      <div className="flex">
        <nav aria-label="Main" className="w-48 border-r p-4">
          <ul className="space-y-1">
            {nav.map((item) => (
              <li key={item.label}>
                <Link
                  to={item.to === '' ? '.' : item.to}
                  aria-current={
                    isNavActive(item, pathname, `/ops/t/${tenantId}`) ? 'page' : undefined
                  }
                  className={
                    isNavActive(item, pathname, `/ops/t/${tenantId}`)
                      ? 'font-semibold underline'
                      : ''
                  }
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="flex-1">
          <Outlet key={tenantId} context={{ membership }} />
        </div>
      </div>
    </div>
  )
}
