import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router'
import { useApi } from '@/shared/api/ApiContext'
import { Button } from '@/shared/components/ui/button'
import { formatDateTime } from '@/shared/lib/format'
import { describeError } from '../platform/errors'
import { statusLabel, windowText } from './format'
import { fetchExceptionsCsv, useBatchExceptions, useImportBatch } from './queries'
import type { ExceptionFilters } from './types'

function Row({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="flex gap-2 py-0.5">
      <dt className="w-48 font-medium">{term}</dt>
      <dd>{children}</dd>
    </div>
  )
}

export function BatchDetailPage() {
  const { tenantId = '', batchId = '' } = useParams()
  const api = useApi()
  const batch = useImportBatch(tenantId, batchId)
  const [filters, setFilters] = useState<ExceptionFilters>({ severity: '', status: '' })
  const exceptions = useBatchExceptions(tenantId, batchId, filters)
  const [csvError, setCsvError] = useState<string | null>(null)
  const rows = exceptions.data?.pages.flatMap((p) => p.items) ?? []

  async function downloadCsv() {
    setCsvError(null)
    try {
      const text = await fetchExceptionsCsv(api, tenantId, batchId, filters)
      const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }))
      const link = document.createElement('a')
      link.href = url
      link.download = `import-exceptions-${batchId}.csv`
      link.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      setCsvError(describeError(error))
    }
  }

  if (batch.isPending)
    return (
      <p role="status" className="p-6">
        Loading…
      </p>
    )
  if (batch.isError)
    return (
      <p role="alert" className="p-6">
        {describeError(batch.error)}
      </p>
    )
  const b = batch.data

  return (
    <main className="p-6">
      <p className="mb-2 text-sm">
        <Link className="underline" to="..">
          Back to imports
        </Link>
      </p>
      <h1 className="mb-4 text-2xl font-semibold">{b.filename ?? 'Unnamed file'}</h1>
      <h2 className="mb-2 text-lg font-semibold">Details</h2>
      <dl className="mb-6">
        <Row term="Status">
          <span role="status">{statusLabel(b.status)}</span>
        </Row>
        {b.failure_reason && <Row term="Failure reason">{b.failure_reason}</Row>}
        <Row term="Acquisition method">{statusLabel(b.acquisition_method)}</Row>
        <Row term="Report type">{b.cds_report_type ? statusLabel(b.cds_report_type) : '—'}</Row>
        <Row term="EORI">{b.eori ?? '—'}</Row>
        <Row term="Window">{windowText(b.window_start, b.window_end)}</Row>
        <Row term="Source owner">{b.source_owner ?? '—'}</Row>
        <Row term="Acquired on">{windowText(b.acquired_on, null)}</Row>
        <Row term="Layout status">{b.layout_status ? statusLabel(b.layout_status) : '—'}</Row>
        <Row term="File checksum (SHA-256)">{b.file_sha256 ?? '—'}</Row>
        <Row term="Created">{b.created_at ? formatDateTime(b.created_at) : '—'}</Row>
      </dl>
      <h2 className="mb-2 text-lg font-semibold">Counts</h2>
      <dl className="mb-6">
        <Row term="Rows processed">
          <progress
            value={b.rows_processed}
            max={b.rows_total || 1}
            aria-label="Rows processed"
            className="mr-2 align-middle"
          />
          {b.rows_processed} of {b.rows_total}
        </Row>
        <Row term="Rows valid">{b.rows_valid}</Row>
        <Row term="Rows rejected">{b.rows_rejected}</Row>
        <Row term="Lines created">{b.lines_created}</Row>
        <Row term="Lines unchanged">{b.lines_unchanged}</Row>
      </dl>

      <h2 className="mb-2 text-lg font-semibold">Exceptions</h2>
      <div className="mb-3 flex items-center gap-4">
        <label className="text-sm font-medium">
          Severity{' '}
          <select
            value={filters.severity}
            onChange={(e) =>
              setFilters({ ...filters, severity: e.target.value as ExceptionFilters['severity'] })
            }
            className="rounded-md border border-input px-2 py-1"
          >
            <option value="">All</option>
            <option value="error">error</option>
            <option value="warning">warning</option>
          </select>
        </label>
        <label className="text-sm font-medium">
          Exception status{' '}
          <select
            value={filters.status}
            onChange={(e) =>
              setFilters({ ...filters, status: e.target.value as ExceptionFilters['status'] })
            }
            className="rounded-md border border-input px-2 py-1"
          >
            <option value="">All</option>
            <option value="open">open</option>
            <option value="resolved">resolved</option>
            <option value="waived">waived</option>
          </select>
        </label>
        <Button variant="outline" size="sm" onClick={() => void downloadCsv()}>
          Download CSV
        </Button>
      </div>
      {csvError && <p role="alert">{csvError}</p>}
      {exceptions.isPending && <p role="status">Loading exceptions…</p>}
      {exceptions.isError && <p role="alert">{describeError(exceptions.error)}</p>}
      {exceptions.data && rows.length === 0 && <p>No exceptions found.</p>}
      {rows.length > 0 && (
        <table className="w-full text-left">
          <caption className="sr-only">Exceptions</caption>
          <thead>
            <tr>
              <th scope="col">Row</th>
              <th scope="col">Field</th>
              <th scope="col">Code</th>
              <th scope="col">Severity</th>
              <th scope="col">Message</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((x) => (
              <tr key={x.id} className="border-t">
                <td className="py-1">{x.row_number === 0 ? 'Whole file' : x.row_number}</td>
                <td>{x.field}</td>
                <td>{x.code}</td>
                <td>{x.severity}</td>
                <td>{x.message}</td>
                <td>{x.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {exceptions.hasNextPage && (
        <Button
          className="mt-4"
          variant="outline"
          disabled={exceptions.isFetchingNextPage}
          onClick={() => void exceptions.fetchNextPage()}
        >
          Load more
        </Button>
      )}
    </main>
  )
}
