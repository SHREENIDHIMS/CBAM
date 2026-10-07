import { useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { Button } from '@/shared/components/ui/button'
import { describeError } from '../platform/errors'
import { NO_FILTERS, readFilters, toParams, validateFilters } from './filters'
import { safeDate } from './format'
import { useImportLines } from './queries'
import type { LedgerFilters } from './types'

type Errors = Partial<Record<keyof LedgerFilters, string>>

function FilterForm({
  initial,
  urlErrors,
  onApply,
}: {
  initial: LedgerFilters
  urlErrors: Errors
  onApply: (f: LedgerFilters) => void
}) {
  const [draft, setDraft] = useState(initial)
  const [submitErrors, setSubmitErrors] = useState<Errors | null>(null)
  const errors = submitErrors ?? urlErrors
  const set = (key: keyof LedgerFilters, value: string) =>
    setDraft({ ...draft, [key]: value } as LedgerFilters)

  function submit(event: FormEvent) {
    event.preventDefault()
    const found = validateFilters(draft)
    setSubmitErrors(found)
    if (Object.keys(found).length === 0) onApply(draft)
  }

  const input = 'rounded-md border border-input px-2 py-1'
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
          className={input}
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
          className={`${input} w-24`}
          value={draft.origin}
          onChange={(e) => set('origin', e.target.value.trim())}
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
          className={input}
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
          className={input}
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
          className={`${input} w-80`}
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
          className={input}
          value={draft.entry_method}
          onChange={(e) => set('entry_method', e.target.value)}
        >
          <option value="">All</option>
          <option value="cds">cds</option>
          <option value="gcd">gcd</option>
          <option value="manual">manual</option>
          <option value="correction">correction</option>
        </select>
      </div>
      <div>
        <label htmlFor="f-exc" className="block text-sm font-medium">
          Open exceptions
        </label>
        <select
          id="f-exc"
          className={input}
          value={draft.has_open_exceptions}
          onChange={(e) => set('has_open_exceptions', e.target.value)}
        >
          <option value="">Any</option>
          <option value="true">Has open exceptions</option>
          <option value="false">None</option>
        </select>
      </div>
      <div className="pt-5">
        <label className="text-sm font-medium">
          <input
            type="checkbox"
            checked={draft.include_superseded === 'true'}
            onChange={(e) => set('include_superseded', e.target.checked ? 'true' : '')}
          />{' '}
          Include superseded versions
        </label>
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
  const lines = useImportLines(tenantId, toParams(applied))
  const rows = lines.data?.pages.flatMap((p) => p.items) ?? []

  function apply(f: LedgerFilters) {
    setSearchParams(toParams(f))
  }

  return (
    <main className="p-6">
      <p className="mb-2 text-sm">
        <Link className="underline" to={`/ops/t/${encodeURIComponent(tenantId)}/imports`}>
          Back to imports
        </Link>
      </p>
      <h1 className="mb-2 text-2xl font-semibold">Import ledger</h1>
      <p className="mb-4 text-sm">
        Customs lines as reported. Scope, tax point, quarter and threshold columns arrive in Phase
        4; the acceptance date here is the date the report gave, not a tax point.
      </p>
      <FilterForm key={searchParams.toString()} initial={applied} urlErrors={urlErrors} onApply={apply} />
      {lines.isPending && <p role="status">Loading…</p>}
      {lines.isError && <p role="alert">{describeError(lines.error)}</p>}
      {lines.data && rows.length === 0 && <p>No import lines found.</p>}
      {rows.length > 0 && (
        <div className="overflow-x-auto">
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
      {lines.hasNextPage && (
        <Button
          className="mt-4"
          variant="outline"
          disabled={lines.isFetchingNextPage}
          onClick={() => void lines.fetchNextPage()}
        >
          Load more
        </Button>
      )}
    </main>
  )
}
