import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { useApi } from '@/shared/api/ApiContext'
import { Button } from '@/shared/components/ui/button'
import { EORI_PATTERN } from '../coverage/types'
import { describeError } from '../platform/errors'
import { safeDateTime, statusLabel, windowText } from './format'
import { Row, Shell, UUID } from './Shell'
import { fetchExceptionsCsv, isLive, useBatchExceptions, useImportBatch } from './queries'
import type { ExceptionFilters } from './types'

/** Checks the id before any request is sent. */
export function BatchDetailPage() {
  const { tenantId = '', batchId = '' } = useParams()
  if (!UUID.test(batchId)) {
    return (
      <Shell tenantId={tenantId} title="Not found">
        <p>That import file does not exist.</p>
      </Shell>
    )
  }
  return <BatchDetail tenantId={tenantId} batchId={batchId} />
}

function BatchDetail({ tenantId, batchId }: { tenantId: string; batchId: string }) {
  const api = useApi()
  const batch = useImportBatch(tenantId, batchId)
  const live = batch.data ? isLive(batch.data.status) : false
  const [filters, setFilters] = useState<ExceptionFilters>({ severity: '', status: '' })
  const exceptions = useBatchExceptions(tenantId, batchId, filters, live)
  const [csvError, setCsvError] = useState<string | null>(null)
  const [preparing, setPreparing] = useState(false)
  const rows = exceptions.data?.pages.flatMap((p) => p.items) ?? []

  async function downloadCsv() {
    setCsvError(null)
    setPreparing(true)
    try {
      const text = await fetchExceptionsCsv(api, tenantId, batchId, filters)
      const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }))
      const link = document.createElement('a')
      link.href = url
      link.download = `import-exceptions-${batchId}.csv`
      document.body.appendChild(link)
      link.click()
      link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 0)
    } catch (error) {
      setCsvError(describeError(error))
    } finally {
      setPreparing(false)
    }
  }

  if (batch.isPending)
    return (
      <Shell tenantId={tenantId} title="Import file">
        <p role="status">Loading…</p>
      </Shell>
    )
  if (batch.isError)
    return (
      <Shell tenantId={tenantId} title="Import file">
        <p role="alert">{describeError(batch.error)}</p>
      </Shell>
    )
  const b = batch.data

  return (
    <Shell tenantId={tenantId} title={b.filename ?? 'Unnamed file'}>
      <h2 className="mb-2 text-lg font-semibold">Details</h2>
      <dl className="mb-6">
        <Row term="Status">{statusLabel(b.status)}</Row>
        {b.failure_reason && <Row term="Failure reason">{b.failure_reason}</Row>}
        <Row term="Acquisition method">{statusLabel(b.acquisition_method)}</Row>
        <Row term="Report type">{b.cds_report_type ? statusLabel(b.cds_report_type) : '—'}</Row>
        <Row term="EORI">
          {b.eori && EORI_PATTERN.test(b.eori) ? (
            <Link
              className="underline"
              to={`/ops/t/${encodeURIComponent(tenantId)}/customs-data/${b.eori}`}
            >
              {b.eori}
            </Link>
          ) : (
            (b.eori ?? '—')
          )}
        </Row>
        <Row term="Window">{windowText(b.window_start, b.window_end)}</Row>
        <Row term="Source owner">{b.source_owner ?? '—'}</Row>
        <Row term="Acquired on">{windowText(b.acquired_on, null)}</Row>
        <Row term="Layout status">{b.layout_status ? statusLabel(b.layout_status) : '—'}</Row>
        <Row term="File checksum (SHA-256)">{b.file_sha256 ?? '—'}</Row>
        <Row term="Created">{safeDateTime(b.created_at)}</Row>
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
        <Button variant="outline" size="sm" disabled={preparing} onClick={() => void downloadCsv()}>
          {preparing ? 'Preparing…' : 'Download CSV'}
        </Button>
      </div>
      {csvError && <p role="alert">{csvError}</p>}
      {exceptions.isPending && <p role="status">Loading exceptions…</p>}
      {exceptions.isError && <p role="alert">{describeError(exceptions.error)}</p>}
      {exceptions.data && rows.length === 0 && (
        <p>{live ? 'Still processing. Exceptions may appear here.' : 'No exceptions found.'}</p>
      )}
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
                <td>{x.field || '—'}</td>
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
    </Shell>
  )
}
