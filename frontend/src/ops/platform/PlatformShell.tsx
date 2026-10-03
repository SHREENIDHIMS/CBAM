import { Link, Outlet } from 'react-router'
import { useMe } from '@/shared/api/queries'

/** Platform administration: only for platform admins. The API enforces this too. */
export function PlatformShell() {
  const me = useMe()
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
  if (!me.data.platform_admin) {
    return (
      <main className="p-6">
        <h1 className="text-2xl font-semibold">Not found</h1>
        <p>That page does not exist, or you do not have access to it.</p>
      </main>
    )
  }
  return (
    <div>
      <header className="flex items-center justify-between border-b px-6 py-3">
        <strong>Platform administration</strong>
        <Link to="/ops" className="text-sm underline">
          Back to client accounts
        </Link>
      </header>
      <Outlet />
    </div>
  )
}
