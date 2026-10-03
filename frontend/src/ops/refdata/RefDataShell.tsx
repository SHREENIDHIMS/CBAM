import { Link, Outlet } from 'react-router'
import { useMe } from '@/shared/api/queries'

/** Reference data: for platform admins (read) and domain owners (read and activate).
 * The API enforces this too; hiding the page is only a convenience. */
export function RefDataShell() {
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
  if (!me.data.platform_admin && !me.data.domain_owner) {
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
        <strong>Reference data</strong>
        <Link to="/ops" className="text-sm underline">
          Back to client accounts
        </Link>
      </header>
      <Outlet />
    </div>
  )
}
