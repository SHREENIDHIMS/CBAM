import { Link, useParams } from 'react-router'
import { describeError } from '../platform/errors'
import { safeDate, safeDateTime, statusLabel } from './format'
import { useImportLine } from './queries'
import { Row, Shell, UUID } from './Shell'
import type { Party } from './types'

const BACK = { to: 'imports/lines', label: 'Back to import ledger' }
const text = (v: unknown): string =>
  typeof v === 'string' ? v : v === null || v === undefined ? '' : JSON.stringify(v)

function PartyRow({ term, party }: { term: string; party: Party | null }) {
  return (
    <Row term={term}>
      {party ? [party.name, party.eori].filter(Boolean).join(' · ') || '—' : '—'}
    </Row>
  )
}

export function LineDetailPage() {
  const { tenantId = '', lineId = '' } = useParams()
  if (!UUID.test(lineId)) {
    return (
      <Shell tenantId={tenantId} title="Not found" back={BACK}>
        <p>That import line does not exist.</p>
      </Shell>
    )
  }
  return <LineDetail tenantId={tenantId} lineId={lineId} />
}

function LineDetail({ tenantId, lineId }: { tenantId: string; lineId: string }) {
  const query = useImportLine(tenantId, lineId)
  if (query.isPending)
    return (
      <Shell tenantId={tenantId} title="Import line" back={BACK}>
        <p role="status">Loading…</p>
      </Shell>
    )
  if (query.isError)
    return (
      <Shell tenantId={tenantId} title="Import line" back={BACK}>
        <p role="alert">{describeError(query.error)}</p>
      </Shell>
    )
  const { line, declaration: d, sources, file, versions, open_exceptions } = query.data
  const batchLink = (id: string) => `/ops/t/${encodeURIComponent(tenantId)}/imports/${encodeURIComponent(id)}`

  return (
    <Shell tenantId={tenantId} title={`${line.mrn}, item ${line.item_no}`} back={BACK}>
      <p className="mb-4 text-sm">
        Scope, tax point, quarter and threshold decisions arrive in Phase 4. The acceptance date is
        as reported, not a tax point.
      </p>

      <h2 className="mb-2 text-lg font-semibold">Line</h2>
      <dl className="mb-6">
        <Row term="Version">
          {line.version}
          {line.is_current ? ' (current)' : ' (superseded)'}
        </Row>
        <Row term="Entry method">{line.entry_method}</Row>
        <Row term="Change reason">{line.change_reason ? statusLabel(line.change_reason) : '—'}</Row>
        <Row term="Commodity code">{line.commodity_code}</Row>
        <Row term="Description">{line.description ?? '—'}</Row>
        <Row term="Net mass (kg)">{line.net_mass_kg}</Row>
        <Row term="Customs value">
          {line.customs_value_source} {line.customs_value_currency}
        </Row>
        <Row term="Customs value (GBP)">{line.customs_value_gbp ?? '—'}</Row>
        {line.customs_value_gbp_note && (
          <Row term="GBP note">{line.customs_value_gbp_note}</Row>
        )}
        <Row term="Valuation basis">{line.valuation_basis ?? '—'}</Row>
        <Row term="Value source">{line.value_source}</Row>
        {line.value_override_reason && (
          <Row term="Override reason">{line.value_override_reason}</Row>
        )}
        <Row term="Country of origin">{line.country_of_origin_declared}</Row>
        <Row term="Customs procedure code">{line.cpc ?? '—'}</Row>
        <Row term="Created">{safeDateTime(line.created_at)}</Row>
        {line.declaration_superseded && (
          <Row term="Declaration">
            <span className="rounded border px-1 text-xs">Superseded declaration</span> A later
            file corrected the declaration header.
          </Row>
        )}
      </dl>

      <h2 className="mb-2 text-lg font-semibold">Declaration</h2>
      <dl className="mb-6">
        <Row term="MRN">{d.mrn}</Row>
        <Row term="Version">
          {d.version}
          {d.is_current ? ' (current)' : ' (superseded)'}
        </Row>
        <Row term="Acceptance date (as reported)">{safeDate(d.acceptance_date)}</Row>
        <Row term="Acceptance time">{safeDateTime(d.acceptance_at)}</Row>
        <Row term="Procedure code">{d.procedure_code ?? '—'}</Row>
        <Row term="Additional procedure codes">
          {d.additional_procedure_codes?.length ? d.additional_procedure_codes.join(', ') : '—'}
        </Row>
        <PartyRow term="Importer" party={d.importer} />
        <PartyRow term="Declarant" party={d.declarant} />
        <PartyRow term="Representative" party={d.representative} />
        <Row term="Representation type (as reported)">{d.representation_type}</Row>
        <Row term="EORI context">{d.eori_context ?? '—'}</Row>
      </dl>

      <h2 className="mb-2 text-lg font-semibold">Source rows</h2>
      {sources.length === 0 && <p className="mb-6">No source rows.</p>}
      {sources.map((s) => (
        <section
          key={s.source_row_id}
          aria-label={`Source row ${s.row_number} (${s.role})`}
          className="mb-4 rounded border p-3"
        >
          <p className="mb-1">
            <strong>{statusLabel(s.role)}</strong>
            {' · '}
            {s.report_type ? statusLabel(s.report_type) : 'unknown report type'}
            {' · row '}
            {s.row_number}
            {' · '}
            <Link className="underline" to={batchLink(s.batch_id)}>
              Open import file
            </Link>
          </p>
          <p className="mb-2 break-all text-sm">SHA-256: {s.row_sha256}</p>
          <table className="text-left text-sm">
            <caption className="sr-only">
              Raw cells of {s.role} row {s.row_number}
            </caption>
            <thead>
              <tr>
                <th scope="col">Column</th>
                <th scope="col">Cell text</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(s.raw ?? {}).map(([key, value]) => (
                <tr key={key} className="border-t">
                  <th scope="row" className="pr-4 font-normal">
                    {key}
                  </th>
                  <td className="whitespace-pre-wrap break-all">{text(value) || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}

      <h2 className="mb-2 text-lg font-semibold">Stored file</h2>
      <dl className="mb-6">
        <Row term="File name">{file.filename ?? '—'}</Row>
        <Row term="SHA-256">{file.sha256 ?? '—'}</Row>
        <Row term="Size (bytes)">{file.size_bytes ?? '—'}</Row>
      </dl>

      <h2 className="mb-2 text-lg font-semibold">Version history</h2>
      <table className="mb-6 text-left">
        <caption className="sr-only">Versions of this line</caption>
        <thead>
          <tr>
            <th scope="col">Version</th>
            <th scope="col">Change reason</th>
            <th scope="col">Created</th>
            <th scope="col">Current</th>
          </tr>
        </thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.id} className="border-t">
              <td className="py-1 pr-4">{v.version}</td>
              <td className="pr-4">{v.change_reason ? statusLabel(v.change_reason) : '—'}</td>
              <td className="pr-4">{safeDateTime(v.created_at)}</td>
              <td>
                {v.is_current ? 'Current' : ''}
                {v.id === line.id ? ' (this version)' : ''}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2 className="mb-2 text-lg font-semibold">Open exceptions</h2>
      {open_exceptions.length === 0 ? (
        <p>No open exceptions.</p>
      ) : (
        <table className="text-left">
          <caption className="sr-only">Open exceptions of the source rows</caption>
          <thead>
            <tr>
              <th scope="col">Row</th>
              <th scope="col">Field</th>
              <th scope="col">Code</th>
              <th scope="col">Severity</th>
              <th scope="col">Message</th>
            </tr>
          </thead>
          <tbody>
            {open_exceptions.map((x) => (
              <tr key={x.id} className="border-t">
                <td className="py-1 pr-4">{x.row_number === 0 ? 'Whole file' : x.row_number}</td>
                <td className="pr-4">{x.field || '—'}</td>
                <td className="pr-4">{x.code}</td>
                <td className="pr-4">{x.severity}</td>
                <td>{x.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Shell>
  )
}
