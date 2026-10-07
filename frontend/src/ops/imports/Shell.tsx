import type { ReactNode } from 'react'
import { Link } from 'react-router'

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function Row({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="flex gap-2 py-0.5">
      <dt className="w-48 shrink-0 font-medium">{term}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  )
}

/** A page with a <main> landmark and a way back, used for loading, error and loaded states. */
export function Shell({
  tenantId,
  title,
  children,
  back = { to: 'imports', label: 'Back to imports' },
}: {
  tenantId: string
  title: string
  children: ReactNode
  back?: { to: string; label: string }
}) {
  return (
    <main className="p-6">
      <p className="mb-2 text-sm">
        <Link className="underline" to={`/ops/t/${encodeURIComponent(tenantId)}/${back.to}`}>
          {back.label}
        </Link>
      </p>
      <h1 className="mb-4 text-2xl font-semibold">{title}</h1>
      {children}
    </main>
  )
}
