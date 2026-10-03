import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { useMe } from '@/shared/api/queries'
import type { DatasetVersion, ImpactReport } from '@/shared/api/types'
import { Button } from '@/shared/components/ui/button'
import { formatDate, formatDateTime } from '@/shared/lib/format'
import { describeError } from '../platform/errors'
import { useActivate, useImpactReport, useVersion, useVersions } from './queries'

export function DatasetPage() {
  const { dataset = '' } = useParams()
  const me = useMe()
  const versions = useVersions(dataset)
  const [selected, setSelected] = useState<string | null>(null)
  const canDecide = me.data?.domain_owner === true

  return (
    <main className="mx-auto max-w-4xl p-6">
      <p className="mb-2 text-sm">
        <Link className="underline" to="/ops/reference-data">
          All reference data
        </Link>
      </p>
      <h1 className="mb-4 text-2xl font-semibold">{dataset}</h1>
      {versions.isPending && <p role="status">Loading…</p>}
      {versions.isError && <p role="alert">{describeError(versions.error)}</p>}
      {versions.data && (
        <table className="mb-8 w-full text-left">
          <caption className="sr-only">Versions of {dataset}</caption>
          <thead>
            <tr>
              <th scope="col" className="py-1">
                Version
              </th>
              <th scope="col">Status</th>
              <th scope="col">Source</th>
              <th scope="col">Rows</th>
              <th scope="col">Loaded</th>
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {versions.data.map((v) => (
              <tr key={v.id} className="border-t align-top">
                <td className="py-1">
                  {v.version}
                  {v.is_fixture && <span className="ml-2 text-sm">(test data)</span>}
                </td>
                <td>{v.status}</td>
                <td>
                  {v.source_ref}
                  <div className="text-sm text-neutral-700">{v.source_status}</div>
                </td>
                <td>{v.row_count}</td>
                <td>{formatDateTime(v.loaded_at)}</td>
                <td>
                  <Button variant="outline" size="sm" onClick={() => setSelected(v.version)}>
                    Review {v.version}
                  </Button>
                </td>
              </tr>
            ))}
            {versions.data.length === 0 && (
              <tr>
                <td colSpan={6} className="py-2">
                  No version has been loaded yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
      {selected && <VersionPanel dataset={dataset} version={selected} canDecide={canDecide} />}
    </main>
  )
}

function VersionPanel({
  dataset,
  version,
  canDecide,
}: {
  dataset: string
  version: string
  canDecide: boolean
}) {
  const detail = useVersion(dataset, version)
  const impact = useImpactReport(dataset)
  const activate = useActivate(dataset)
  const [confirmed, setConfirmed] = useState(false)

  if (detail.isPending) return <p role="status">Loading…</p>
  if (detail.isError) return <p role="alert">{describeError(detail.error)}</p>
  const v: DatasetVersion = detail.data
  const report: ImpactReport | null = impact.data ?? v.impact_report ?? null
  const pending = v.status === 'pending'

  return (
    <section aria-labelledby="version-heading" className="border-t pt-4">
      <h2 id="version-heading" className="mb-2 text-lg font-semibold">
        Version {v.version}
      </h2>
      <dl className="mb-4 grid grid-cols-[max-content_1fr] gap-x-4 text-sm">
        <dt>Status</dt>
        <dd>{v.status}</dd>
        <dt>Source</dt>
        <dd>
          {v.source_ref} ({v.source_status})
        </dd>
        <dt>Applies from</dt>
        <dd>{formatDate(v.effective_from)}</dd>
        <dt>Checksum</dt>
        <dd className="break-all font-mono">{v.checksum_sha256}</dd>
      </dl>

      {v.is_fixture && (
        <p role="note" className="mb-4 text-sm">
          This is test data, not law.
        </p>
      )}

      {pending && canDecide && (
        <div className="mb-4 flex gap-2">
          <Button
            variant="outline"
            disabled={impact.isPending}
            onClick={() => impact.mutate(v.version)}
          >
            Generate impact report
          </Button>
        </div>
      )}
      {impact.isError && <p role="alert">{describeError(impact.error)}</p>}

      {report ? (
        <ReportView report={report} />
      ) : (
        <p>{pending ? 'No impact report yet.' : 'No impact report was recorded.'}</p>
      )}

      {pending && canDecide && report && (
        <div className="mt-6 border-t pt-4">
          <label className="mb-3 flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            <span>I have read the impact report and approve this version.</span>
          </label>
          {activate.isError && <p role="alert">{describeError(activate.error)}</p>}
          <Button disabled={!confirmed || activate.isPending} onClick={() => activate.mutate(v)}>
            Activate version {v.version}
          </Button>
        </div>
      )}
      {pending && !canDecide && (
        <p className="mt-4 text-sm">Only a domain owner can generate the report and activate.</p>
      )}
    </section>
  )
}

function ReportView({ report }: { report: ImpactReport }) {
  const { rows } = report
  return (
    <div>
      <h3 className="mb-1 font-semibold">Impact report</h3>
      <p className="mb-2 text-sm">
        Compared with{' '}
        {report.compared_to ? `version ${report.compared_to.version}` : 'no active version'}:{' '}
        {rows.added} added, {rows.removed} removed, {rows.changed} changed, {rows.unchanged}{' '}
        unchanged.
      </p>
      {report.warnings.length > 0 && (
        <ul className="mb-3 list-disc pl-5 text-sm" aria-label="Warnings">
          {report.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {report.changes.length > 0 && (
        <table className="mb-3 w-full text-left text-sm">
          <caption className="sr-only">Changed rows</caption>
          <thead>
            <tr>
              <th scope="col">Change</th>
              <th scope="col">Row</th>
              <th scope="col">From</th>
            </tr>
          </thead>
          <tbody>
            {report.changes.map((c, i) => (
              <tr key={i} className="border-t">
                <td>{c.change}</td>
                <td>{Object.values(c.key).join(' / ') || 'The only row'}</td>
                <td>{formatDate(c.effective_from)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {report.changes_truncated && <p className="text-sm">Only the first changes are listed.</p>}
      <h4 className="mb-1 font-medium">Records affected</h4>
      {report.affected.provider_registered ? (
        report.affected.items.length > 0 ? (
          <ul className="list-disc pl-5 text-sm">
            {report.affected.items.map((a) => (
              <li key={`${a.kind}-${a.ref}`}>
                {a.ref}: {a.detail}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm">No existing record would change outcome.</p>
        )
      ) : (
        <p className="text-sm">Existing records are not checked for this dataset yet.</p>
      )}
    </div>
  )
}
