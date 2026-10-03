import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { Button } from '@/shared/components/ui/button'
import { Field, FormError } from '@/shared/components/AuthCard'
import { formatDateTime } from '@/shared/lib/format'
import { describeError } from './errors'
import { useCreateTenant, useTenants } from './queries'

export function ClientsPage() {
  const tenants = useTenants()
  const create = useCreateTenant()
  const [name, setName] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    try {
      await create.mutateAsync(name.trim())
      setName('')
    } catch {
      // The error is shown from the mutation state below.
    }
  }

  return (
    <main className="mx-auto max-w-3xl p-6">
      <h1 className="mb-4 text-2xl font-semibold">Clients</h1>
      {tenants.isPending && <p role="status">Loading…</p>}
      {tenants.isError && <p role="alert">{describeError(tenants.error)}</p>}
      {tenants.data && (
        <table className="mb-8 w-full text-left">
          <caption className="sr-only">Client accounts</caption>
          <thead>
            <tr>
              <th scope="col" className="py-1">
                Name
              </th>
              <th scope="col">Status</th>
              <th scope="col">Created</th>
            </tr>
          </thead>
          <tbody>
            {tenants.data.map((t) => (
              <tr key={t.id} className="border-t">
                <td className="py-1">
                  <Link className="underline" to={`/ops/platform/tenants/${t.id}`}>
                    {t.name}
                  </Link>
                </td>
                <td>{t.status}</td>
                <td>{formatDateTime(t.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h2 className="mb-2 text-lg font-semibold">Add a client</h2>
      <form onSubmit={submit} className="max-w-md">
        <FormError message={create.isError ? describeError(create.error) : null} />
        <Field id="client-name" label="Client name" value={name} onChange={setName} />
        <Button type="submit" disabled={create.isPending || name.trim() === ''}>
          Add client
        </Button>
      </form>
    </main>
  )
}
