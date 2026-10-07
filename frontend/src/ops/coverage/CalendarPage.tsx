import { Link, useParams, useSearchParams } from 'react-router'
import { ApiError } from '@/shared/api/client'
import { EORI_PATTERN, isRealDate } from '@/shared/lib/validate'
import { safeDate, statusLabel } from '../imports/format'
import { Row, Shell } from '../imports/Shell'
import { describeError } from '../platform/errors'
import { useCalendar } from './queries'
import { REPORT_TYPES, type PeriodState, type ReportType } from './types'

const BACK = { to: 'customs-data', label: 'Back to customs data coverage' }

/** Text labels carry the meaning; the border style is only an extra cue. */
const STATE: Record<PeriodState, { label: string; cls: string }> = {
  loaded: { label: 'Loaded', cls: 'border-solid' },
  loaded_with_errors: { label: 'Loaded with errors', cls: 'border-dashed' },
  gap: { label: 'Gap', cls: 'border-double border-4' },
  not_yet_available: { label: 'Not yet available', cls: 'border-dotted' },
}
const stateLabel = (s: string) => STATE[s as PeriodState]?.label ?? statusLabel(s)

export function CalendarPage() {
  const { tenantId = '', eori = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const rawType = params.get('report_type') ?? 'import_item'
  const reportType = (REPORT_TYPES as readonly string[]).includes(rawType)
    ? (rawType as ReportType)
    : null
  const from = params.get('from') ?? ''
  const to = params.get('to') ?? ''
  const problems: string[] = []
  if (!EORI_PATTERN.test(eori)) problems.push('That EORI is not valid: use GB or XI and 12 digits.')
  if (!reportType) problems.push('Unknown report type.')
  if (from && !isRealDate(from)) problems.push('The from date is not a real date.')
  if (to && !isRealDate(to)) problems.push('The to date is not a real date.')
  if (from && to && isRealDate(from) && isRealDate(to) && from > to)
    problems.push('The from date cannot be after the to date.')
  const valid = problems.length === 0
  const calendar = useCalendar(
    tenantId,
    { eori, reportType: reportType ?? 'import_item', from, to },
    valid,
  )

  function set(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next)
  }

  const title = EORI_PATTERN.test(eori) ? `Coverage for ${eori}` : 'Customs data coverage'
  const c = calendar.data
  const notFound = calendar.error instanceof ApiError && calendar.error.status === 404

  return (
    <Shell tenantId={tenantId} title={title} back={BACK}>
      <p className="mb-4 text-sm">
        This is coverage of loaded customs data only. It is not a threshold, scope or tax point
        decision.
      </p>
      <div className="mb-4 flex flex-wrap items-end gap-4">
        <div>
          <label htmlFor="c-type" className="block text-sm font-medium">
            Report type
          </label>
          <select
            id="c-type"
            className="rounded-md border border-input px-2 py-1"
            value={rawType}
            onChange={(e) => set('report_type', e.target.value)}
          >
            {!reportType && <option value={rawType}>{rawType}</option>}
            {REPORT_TYPES.map((t) => (
              <option key={t} value={t}>
                {statusLabel(t)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="c-from" className="block text-sm font-medium">
            From (optional)
          </label>
          <input
            id="c-from"
            type="date"
            className="rounded-md border border-input px-2 py-1"
            value={from}
            onChange={(e) => set('from', e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="c-to" className="block text-sm font-medium">
            To (optional)
          </label>
          <input
            id="c-to"
            type="date"
            className="rounded-md border border-input px-2 py-1"
            value={to}
            onChange={(e) => set('to', e.target.value)}
          />
        </div>
      </div>

      {problems.map((m) => (
        <p key={m} role="alert">
          {m}
        </p>
      ))}
      {valid && calendar.isPending && <p role="status">Loading…</p>}
      {valid && notFound && (
        <p role="alert">Not registered and no reports loaded for this EORI and report type.</p>
      )}
      {valid && calendar.isError && !notFound && (
        <p role="alert">{describeError(calendar.error)}</p>
      )}

      {valid && c && (
        <>
          <h2 className="mb-2 text-lg font-semibold">Summary</h2>
          <dl className="mb-6">
            <Row term="Complete">{c.complete ? 'Yes' : 'No'}</Row>
            <Row term="Registered">{c.registered ? 'Yes' : 'No'}</Row>
            <Row term="Third-party access">{statusLabel(c.third_party_access)}</Row>
            <Row term="First day to cover">{safeDate(c.tracking_from)}</Row>
            <Row term="Showing">
              {safeDate(c.range_from)} to {safeDate(c.range_to)}
            </Row>
            <Row term="Latest days not yet available">
              {c.unavailable_latest_days === null
                ? 'No HMRC lag rule is active, so recent days show as gaps.'
                : `${c.unavailable_latest_days} days`}
            </Row>
          </dl>

          <h2 className="mb-2 text-lg font-semibold">Periods</h2>
          {c.periods.length === 0 ? (
            <p className="mb-6">No periods in this range.</p>
          ) : (
            <table className="mb-6 text-left">
              <caption className="sr-only">Coverage periods</caption>
              <thead>
                <tr>
                  <th scope="col">From</th>
                  <th scope="col">To</th>
                  <th scope="col">Days</th>
                  <th scope="col">State</th>
                </tr>
              </thead>
              <tbody>
                {c.periods.map((p) => (
                  <tr key={`${p.covered_from}-${p.state}`} className="border-t">
                    <td className="py-1 pr-4">{safeDate(p.covered_from)}</td>
                    <td className="pr-4">{safeDate(p.covered_to)}</td>
                    <td className="pr-4">{p.days}</td>
                    <td>
                      <span
                        className={`inline-block rounded border px-2 ${STATE[p.state]?.cls ?? ''}`}
                      >
                        {stateLabel(p.state)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h2 className="mb-2 text-lg font-semibold">Gaps</h2>
          {c.gaps.length === 0 ? (
            <p className="mb-6">No gaps.</p>
          ) : (
            <table className="mb-6 text-left">
              <caption className="sr-only">Gaps</caption>
              <thead>
                <tr>
                  <th scope="col">From</th>
                  <th scope="col">To</th>
                  <th scope="col">Days</th>
                </tr>
              </thead>
              <tbody>
                {c.gaps.map((g) => (
                  <tr key={g.covered_from} className="border-t">
                    <td className="py-1 pr-4">{safeDate(g.covered_from)}</td>
                    <td className="pr-4">{safeDate(g.covered_to)}</td>
                    <td>{g.days}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h2 className="mb-2 text-lg font-semibold">Overlaps</h2>
          {c.overlaps.length === 0 ? (
            <p>No overlaps.</p>
          ) : (
            <table className="text-left">
              <caption className="sr-only">Overlaps</caption>
              <thead>
                <tr>
                  <th scope="col">From</th>
                  <th scope="col">To</th>
                  <th scope="col">Import files</th>
                </tr>
              </thead>
              <tbody>
                {c.overlaps.map((o) => (
                  <tr key={`${o.covered_from}-${o.covered_to}-${o.batch_ids.join()}`} className="border-t">
                    <td className="py-1 pr-4">{safeDate(o.covered_from)}</td>
                    <td className="pr-4">{safeDate(o.covered_to)}</td>
                    <td>
                      {o.batch_ids.map((id, i) => (
                        <span key={id}>
                          {i > 0 && ', '}
                          <Link
                            className="underline"
                            to={`/ops/t/${encodeURIComponent(tenantId)}/imports/${encodeURIComponent(id)}`}
                          >
                            {id}
                          </Link>
                        </span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </Shell>
  )
}
