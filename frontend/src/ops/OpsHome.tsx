import { Link, Navigate } from 'react-router'
import { useMe } from '@/shared/api/queries'

/** Landing workspace after sign-in. */
export function OpsHome() {
  const me = useMe()
  if (me.isPending) return <p role="status" className="p-6">Loading…</p>
  if (me.isError) return <p role="alert" className="p-6">We could not load your account.</p>
  const { memberships, platform_admin: platformAdmin, domain_owner: domainOwner } = me.data
  if (memberships.length === 1 && !platformAdmin && !domainOwner) return <Navigate to={`/ops/t/${memberships[0].tenant_id}`} replace />
  return (
    <main className="min-h-screen bg-[#f4f7f3] px-5 py-10 sm:px-8">
      <div className="mx-auto max-w-5xl">
        <div className="mb-10 flex items-end justify-between gap-4">
            <div><p className="eyebrow text-emerald-700">Operations overview</p><h1 className="mt-2 text-4xl font-semibold tracking-tight text-[#173b2b]">Choose a client account</h1><p className="mt-2 max-w-xl text-slate-600">Choose a client account to review customs data, coverage and open tasks.</p></div>
          <div className="brand-mark hidden sm:grid">C</div>
        </div>
        <div className="mb-8 grid gap-4 sm:grid-cols-2">
          {platformAdmin && <Link aria-label="Platform administration" className="rounded-2xl border border-[#d4e2d6] bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md" to="/ops/platform"><p className="text-sm font-semibold text-emerald-700">Platform</p><p className="mt-2 text-xl font-semibold text-[#173b2b]">Administration</p><p className="mt-1 text-sm text-slate-500">Manage client accounts and memberships.</p></Link>}
          {(platformAdmin || domainOwner) && <Link aria-label="Reference data" className="rounded-2xl border border-[#d4e2d6] bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md" to="/ops/reference-data"><p className="text-sm font-semibold text-emerald-700">Governance</p><p className="mt-2 text-xl font-semibold text-[#173b2b]">Reference data</p><p className="mt-1 text-sm text-slate-500">Review sources, versions and activation status.</p></Link>}
        </div>
        {memberships.length === 0 ? <section className="rounded-2xl border border-dashed border-[#b9cdbb] bg-white p-8"><h2 className="text-xl font-semibold text-[#173b2b]">No client workspace yet</h2><p className="mt-2 text-slate-600">{platformAdmin || domainOwner ? 'Create or invite a client account to begin.' : 'You do not have access to any client account yet. Ask an administrator to add you.'}</p></section> : <ul className="grid gap-4 sm:grid-cols-2">{memberships.map((m) => <li key={m.tenant_id} className="rounded-2xl border border-[#d4e2d6] bg-white p-5 shadow-sm"><Link className="text-xl font-semibold text-[#173b2b] hover:underline" to={`/ops/t/${m.tenant_id}`}>{m.tenant_name}</Link><p className="mt-2 text-sm text-slate-500">{m.roles.join(', ')}</p><span className="mt-5 inline-block text-sm font-semibold text-emerald-700">Open workspace →</span></li>)}</ul>}
      </div>
    </main>
  )
}
