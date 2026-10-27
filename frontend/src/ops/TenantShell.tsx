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
    <div className="min-h-screen bg-[#f4f7f3]">
      <header className="flex items-center justify-between border-b border-[#dbe5dc] bg-white px-6 py-4 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="brand-mark">C</div>
          <div>
            <p className="eyebrow text-emerald-700">CBAM CONTROL ROOM</p>
            <strong className="text-lg text-[#173b2b]">{membership.tenant_name}</strong>
          </div>
          {me.data.memberships.length > 1 && (
            <NavLink to="/ops" className="ml-3 text-sm underline">
              Switch client
            </NavLink>
          )}
        </div>
        <div className="flex items-center gap-3 text-sm text-slate-600">
          <span className="hidden sm:inline">{auth.user?.email}</span>
          <Button variant="outline" size="sm" onClick={signOut}>
            Sign out
          </Button>
        </div>
      </header>
      <div className="mx-auto flex max-w-[1600px]">
        <nav aria-label="Main" className="hidden w-60 shrink-0 border-r border-[#dbe5dc] bg-white p-5 md:block">
          <p className="mb-3 px-3 text-xs font-bold uppercase tracking-[.14em] text-slate-400">Workspace</p>
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
                      ? 'rounded-lg bg-[#e9f3d7] px-3 py-2 font-semibold text-[#173b2b]'
                      : 'rounded-lg px-3 py-2 text-slate-600 hover:bg-slate-50'
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
