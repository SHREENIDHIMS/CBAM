import { Link } from 'react-router'
import { formatDate } from '@/shared/lib/format'
import { describeError } from '../platform/errors'
import { useDatasets, useSources } from './queries'

const STATUS_HELP: Record<string, string> = {
  draft: 'Draft: its data cannot drive any decision',
  laid: 'Laid: its data cannot drive any decision',
  in_force: 'In force',
  commenced: 'Commenced',
  superseded: 'Superseded: its data cannot drive any decision',
}

export function ReferenceDataPage() {
  const datasets = useDatasets()
  const sources = useSources()
  return (
    <main className="mx-auto max-w-4xl p-6">
      <h1 className="mb-4 text-2xl font-semibold">Reference data</h1>
      <p className="mb-6 text-sm text-neutral-700">
        Law is data. A dataset version only drives decisions when it is active and its regulatory
        source is in force on the date of the transaction.
      </p>

      <h2 className="mb-2 text-lg font-semibold">Datasets</h2>
      {datasets.isPending && <p role="status">Loading…</p>}
      {datasets.isError && <p role="alert">{describeError(datasets.error)}</p>}
      {datasets.data && (
        <table className="mb-8 w-full text-left">
          <caption className="sr-only">Reference datasets</caption>
          <thead>
            <tr>
              <th scope="col" className="py-1">
                Dataset
              </th>
              <th scope="col">Active version</th>
              <th scope="col">Waiting for approval</th>
            </tr>
          </thead>
          <tbody>
            {datasets.data.map((d) => (
              <tr key={d.id} className="border-t">
                <td className="py-1">
                  <Link className="underline" to={`/ops/reference-data/${d.name}`}>
                    {d.name}
                  </Link>
                </td>
                <td>{d.active_version ?? 'None'}</td>
                <td>{d.pending_versions}</td>
              </tr>
            ))}
            {datasets.data.length === 0 && (
              <tr>
                <td colSpan={3} className="py-2">
                  No dataset has been loaded yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      <h2 className="mb-2 text-lg font-semibold">Regulatory sources</h2>
      {sources.isPending && <p role="status">Loading…</p>}
      {sources.isError && <p role="alert">{describeError(sources.error)}</p>}
      {sources.data && (
        <table className="w-full text-left">
          <caption className="sr-only">Regulatory sources</caption>
          <thead>
            <tr>
              <th scope="col" className="py-1">
                Source
              </th>
              <th scope="col">Status</th>
              <th scope="col">Commences</th>
            </tr>
          </thead>
          <tbody>
            {sources.data.map((s) => (
              <tr key={s.id} className="border-t align-top">
                <td className="py-1">
                  <div className="font-medium">{s.source_id}</div>
                  <div className="text-sm text-neutral-700">{s.title}</div>
                </td>
                <td>{STATUS_HELP[s.status] ?? s.status}</td>
                <td>{s.commencement_date ? formatDate(s.commencement_date) : 'Not set'}</td>
              </tr>
            ))}
            {sources.data.length === 0 && (
              <tr>
                <td colSpan={3} className="py-2">
                  No source has been registered yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </main>
  )
}
