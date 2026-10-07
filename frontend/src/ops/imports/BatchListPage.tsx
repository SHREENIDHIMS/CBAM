import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { Button } from '@/shared/components/ui/button'
import { describeError } from '../platform/errors'
import { safeDateTime, statusLabel, windowText } from './format'
import { useImportBatches } from './queries'
import { ALL_STATUSES } from './types'

export function BatchListPage() {
  const { tenantId = '' } = useParams()
  const [status, setStatus] = useState('')
  const batches = useImportBatches(tenantId, status)
  const rows = batches.data?.pages.flatMap((p) => p.items) ?? []

  return (
    <main className="p-6">
      <h1 className="mb-4 text-2xl font-semibold">Imports</h1>
      <p className="mb-4">
        <Link className="underline" to="lines">
          Open the import ledger
        </Link>{' '}
        to see the normalised customs lines.
      </p>
      <div className="mb-4">
        <label htmlFor="status-filter" className="mr-2 text-sm font-medium">
          Status
        </label>
        <select
          id="status-filter"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded-md border border-input px-2 py-1"
        >
          <option value="">All</option>
          {ALL_STATUSES.map((s) => (
            <option key={s} value={s}>
              {statusLabel(s)}
            </option>
          ))}
        </select>
      </div>
      {batches.isPending && <p role="status">Loading…</p>}
      {batches.isError && <p role="alert">{describeError(batches.error)}</p>}
      {batches.data && rows.length === 0 && <p>No import files found.</p>}
      {rows.length > 0 && (
        <table className="w-full text-left">
          <caption className="sr-only">Import batches</caption>
          <thead>
            <tr>
              <th scope="col">File</th>
              <th scope="col">Report type</th>
              <th scope="col">EORI</th>
              <th scope="col">Window</th>
              <th scope="col">Status</th>
              <th scope="col">Progress</th>
              <th scope="col">Rejected rows</th>
              <th scope="col">Created</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((b) => (
              <tr key={b.id} className="border-t">
                <td className="py-1">
                  <Link className="underline" to={b.id}>
                    {b.filename ?? 'Unnamed file'}
                  </Link>
                </td>
                <td>{b.cds_report_type ? statusLabel(b.cds_report_type) : '—'}</td>
                <td>{b.eori ?? '—'}</td>
                <td>{windowText(b.window_start, b.window_end)}</td>
                <td>{statusLabel(b.status)}</td>
                <td>
                  <progress
                    value={b.rows_processed}
                    max={b.rows_total || 1}
                    aria-label={`Progress for ${b.filename ?? 'file'}`}
                    className="mr-2 align-middle"
                  />
                  {b.rows_processed} of {b.rows_total} rows
                </td>
                <td>{b.rows_rejected}</td>
                <td>{safeDateTime(b.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {batches.hasNextPage && (
        <Button
          className="mt-4"
          variant="outline"
          disabled={batches.isFetchingNextPage}
          onClick={() => void batches.fetchNextPage()}
        >
          Load more
        </Button>
      )}
    </main>
  )
}
