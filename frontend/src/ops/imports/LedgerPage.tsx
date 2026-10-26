import { useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { Button } from '@/shared/components/ui/button'
import { describeError } from '../platform/errors'
import { NO_FILTERS, readFilters, toParams, validateFilters, type FilterErrors } from './filters'
import { safeDate } from './format'
import { useImportLines } from './queries'
import { Shell } from './Shell'
import type { LedgerFilters } from './types'

function FilterForm({
  initial,
  urlErrors,
  onApply,
}: {
  initial: LedgerFilters
  urlErrors: FilterErrors
  onApply: (f: LedgerFilters) => void
}) {
  const [draft, setDraft] = useState(initial)
  const [submitErrors, setSubmitErrors] = useState<FilterErrors | null>(null)
  const errors = submitErrors ?? urlErrors
  const set = (key: keyof LedgerFilters, value: string) =>
    setDraft({ ...draft, [key]: value } as LedgerFilters)

  function submit(event: FormEvent) {
    event.preventDefault()
    const found = validateFilters(draft)
    setSubmitErrors(found)
    if (Object.keys(found).length === 0) onApply(draft)
  }

  const inputCls = 'rounded-md border border-input px-2 py-1'
  const err = (key: keyof LedgerFilters) =>
    errors[key] ? (
      <span id={`err-${key}`} role="alert" className="block text-sm">
        {errors[key]}
      </span>
    ) : null
  const aria = (key: keyof LedgerFilters) =>
    errors[key] ? { 'aria-invalid': true, 'aria-describedby': `err-${key}` } : {}

  return (
    <form onSubmit={submit} className="mb-4 flex flex-wrap items-start gap-4" noValidate>
      <div>
        <label htmlFor="f-code" className="block text-sm font-medium">
          Commodity code starts with
        </label>
        <input
          id="f-code"
          className={inputCls}
          inputMode="numeric"
          value={draft.commodity_code}
          onChange={(e) => set('commodity_code', e.target.value.trim())}
          {...aria('commodity_code')}
        />
        {err('commodity_code')}
      </div>
      <div>
        <label htmlFor="f-origin" className="block text-sm font-medium">
          Country of origin
        </label>
        <input
          id="f-origin"
          className={`${inputCls} w-24`}
          value={draft.origin}
          onChange={(e) => set('origin', e.target.value.trim().toUpperCase())}
          {...aria('origin')}
        />
        {err('origin')}
      </div>
      <div>
        <label htmlFor="f-from" className="block text-sm font-medium">
          Acceptance date (as reported) from
        </label>
        <input
          id="f-from"
          type="date"
          className={inputCls}
          value={draft.from}
          onChange={(e) => set('from', e.target.value)}
          {...aria('from')}
        />
        {err('from')}
      </div>
      <div>
        <label htmlFor="f-to" className="block text-sm font-medium">
          Acceptance date (as reported) to
        </label>
        <input
          id="f-to"
          type="date"
          className={inputCls}
          value={draft.to}
          onChange={(e) => set('to', e.target.value)}
          {...aria('to')}
        />
        {err('to')}
      </div>
      <div>
        <label htmlFor="f-batch" className="block text-sm font-medium">
          Import file id
        </label>
        <input
          id="f-batch"
          className={`${inputCls} w-80`}
          value={draft.batch_id}
          onChange={(e) => set('batch_id', e.target.value.trim())}
          {...aria('batch_id')}
        />
        {err('batch_id')}
      </div>
      <div>
        <label htmlFor="f-entry" className="block text-sm font-medium">
          Entry method
        </label>
        <select
          id="f-entry"
          className={inputCls}
          value={draft.entry_method}
          onChange={(e) => set('entry_method', e.target.value)}
          {...aria('entry_method')}
        >
          <option value="">All</option>
          {errors.entry_method && <option value={draft.entry_method}>{draft.entry_method}</option>}
          <option value="cds">cds</option>
          <option value="gcd">gcd</option>
          <option value="manual">manual</option>
          <option value="correction">correction</option>
        </select>
        {err('entry_method')}
      </div>
      <div>
        <label htmlFor="f-exc" className="block text-sm font-medium">
          Open exceptions
        </label>
        <select
          id="f-exc"
          className={inputCls}
          value={draft.has_open_exceptions}
          onChange={(e) => set('has_open_exceptions', e.target.value)}
          {...aria('has_open_exceptions')}
        >
          <option value="">Any</option>
          {errors.has_open_exceptions && (
            <option value={draft.has_open_exceptions}>{draft.has_open_exceptions}</option>
          )}
          <option value="true">Has open exceptions</option>
          <option value="false">None</option>
        </select>
        {err('has_open_exceptions')}
      </div>
      <div className="pt-5">
        <input
          id="f-sup"
          type="checkbox"
          className="mr-2"
          checked={draft.include_superseded === 'true'}
          onChange={(e) => set('include_superseded', e.target.checked ? 'true' : '')}
          {...aria('include_superseded')}
        />
        <label htmlFor="f-sup" className="text-sm font-medium">
          Include superseded versions
        </label>
        {err('include_superseded')}
      </div>
      <div className="flex gap-2 pt-5">
        <Button type="submit">Apply filters</Button>
        <Button type="button" variant="outline" onClick={() => onApply(NO_FILTERS)}>
          Clear
        </Button>
      </div>
    </form>
  )
}

export function LedgerPage() {
  const { tenantId = '' } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const applied = readFilters(searchParams)
  const urlErrors = validateFilters(applied)
  const invalid = Object.keys(urlErrors).length > 0
  // Nothing is requested while the filters in the URL are invalid.
  const lines = useImportLines(tenantId, toParams(applied), !invalid)
  const rows = lines.data?.pages.flatMap((p) => p.items) ?? []
  const updating = lines.isPlaceholderData

  return (
    <Shell tenantId={tenantId} title="Import ledger">
      <p className="mb-4 text-sm">
        Customs lines as reported. Scope, tax point, quarter and threshold columns arrive in Phase
        4; the acceptance date here is the date the report gave, not a tax point.
      </p>
      <FilterForm
        key={searchParams.toString()}
        initial={applied}
        urlErrors={urlErrors}
        onApply={(f) => setSearchParams(toParams(f))}
      />
      {!invalid && lines.isPending && <p role="status">Loading…</p>}
      {!invalid && updating && <p role="status">Updating results…</p>}
      {!invalid && lines.isError && <p role="alert">{describeError(lines.error)}</p>}
      {!invalid && lines.data && rows.length === 0 && !updating && <p>No import lines found.</p>}
      {!invalid && rows.length > 0 && (
        <div className="overflow-x-auto" aria-busy={updating} style={{ opacity: updating ? 0.5 : 1 }}>
          <table className="w-full text-left">
            <caption className="sr-only">Import lines</caption>
            <thead>
              <tr>
                <th scope="col">MRN</th>
                <th scope="col">Item</th>
                <th scope="col">Commodity code</th>
                <th scope="col">Origin</th>
                <th scope="col">Net mass (kg)</th>
                <th scope="col">Customs value</th>
                <th scope="col">Acceptance date (as reported)</th>
                <th scope="col">Version</th>
                <th scope="col">Entry method</th>
                <th scope="col">Open exceptions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((l) => (
                <tr key={l.id} className="border-t">
                  <td className="py-1">
                    <Link
                      className="underline"
                      to={`/ops/t/${encodeURIComponent(tenantId)}/imports/lines/${encodeURIComponent(l.id)}`}
                    >
                      {l.mrn}
                    </Link>
                    {l.declaration_superseded && (
                      <span className="ml-2 rounded border px-1 text-xs">
                        Superseded declaration
                      </span>
                    )}
                  </td>
                  <td>{l.item_no}</td>
                  <td>{l.commodity_code}</td>
                  <td>{l.country_of_origin_declared}</td>
                  <td>{l.net_mass_kg}</td>
                  <td>
                    {l.customs_value_source} {l.customs_value_currency}
                  </td>
                  <td>{safeDate(l.acceptance_date)}</td>
                  <td>
                    {l.version}
                    {!l.is_current && ' (superseded)'}
                  </td>
                  <td>{l.entry_method}</td>
                  <td>{l.open_exceptions}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!invalid && !updating && lines.hasNextPage && (
        <Button
          className="mt-4"
          variant="outline"
          disabled={lines.isFetchingNextPage}
          onClick={() => void lines.fetchNextPage()}
        >
          Load more
        </Button>
      )}
    </Shell>
  )
}
