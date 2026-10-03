import { Link, Navigate } from 'react-router'
import { useMe } from '@/shared/api/queries'

/** After sign-in: pick a client account (skipped when there is only one). */
export function OpsHome() {
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
  const { memberships, platform_admin: platformAdmin } = me.data
  if (memberships.length === 1 && !platformAdmin) {
    return <Navigate to={`/ops/t/${memberships[0].tenant_id}`} replace />
  }
  return (
    <main className="mx-auto max-w-2xl p-6">
      <h1 className="mb-4 text-2xl font-semibold">Choose a client account</h1>
      {memberships.length === 0 ? (
        <p>
          {platformAdmin
            ? 'You are a platform administrator and are not a member of any client account.'
            : 'You do not have access to any client account yet. Ask an administrator to add you.'}
        </p>
      ) : (
        <ul className="space-y-2">
          {memberships.map((m) => (
            <li key={m.tenant_id}>
              <Link className="underline" to={`/ops/t/${m.tenant_id}`}>
                {m.tenant_name}
              </Link>{' '}
              <span className="text-sm text-neutral-600">({m.roles.join(', ')})</span>
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}
