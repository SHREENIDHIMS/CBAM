import { UUID } from './Shell'
import type { LedgerFilters } from './types'

export const NO_FILTERS: LedgerFilters = {
  commodity_code: '',
  origin: '',
  from: '',
  to: '',
  batch_id: '',
  entry_method: '',
  has_open_exceptions: '',
  include_superseded: '',
}

const KEYS = Object.keys(NO_FILTERS) as (keyof LedgerFilters)[]
const ENTRY = ['cds', 'gcd', 'manual', 'correction']

/** A real calendar date in YYYY-MM-DD form (2027-13-45 is not). */
function isRealDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

export function readFilters(params: URLSearchParams): LedgerFilters {
  const out: Record<string, string> = { ...NO_FILTERS }
  for (const key of KEYS) out[key] = params.get(key) ?? ''
  out.origin = out.origin.toUpperCase()
  return out as unknown as LedgerFilters
}

export type FilterErrors = Partial<Record<keyof LedgerFilters, string>>

/** Messages for values the API would refuse. A request is sent only when this is empty. */
export function validateFilters(f: LedgerFilters): FilterErrors {
  const errors: FilterErrors = {}
  if (f.commodity_code && !/^\d{1,10}$/.test(f.commodity_code))
    errors.commodity_code = 'Commodity code must be 1 to 10 digits.'
  if (f.origin && !/^[A-Z]{2}$/.test(f.origin))
    errors.origin = 'Origin must be a 2-letter country code, for example CN.'
  if (f.from && !isRealDate(f.from)) errors.from = 'Enter the from date as a real date.'
  if (f.to && !isRealDate(f.to)) errors.to = 'Enter the to date as a real date.'
  if (!errors.from && !errors.to && f.from && f.to && f.to < f.from)
    errors.to = 'The to date cannot be before the from date.'
  if (f.batch_id && !UUID.test(f.batch_id)) errors.batch_id = 'Import file id must be a UUID.'
  if (f.entry_method && !ENTRY.includes(f.entry_method))
    errors.entry_method = 'Entry method must be cds, gcd, manual or correction.'
  if (f.has_open_exceptions && !['true', 'false'].includes(f.has_open_exceptions))
    errors.has_open_exceptions = 'Open exceptions must be true or false.'
  if (f.include_superseded && f.include_superseded !== 'true')
    errors.include_superseded = 'Include superseded must be true.'
  return errors
}

/** The non-empty filters as API / URL parameters. Call it only for filters that validated. */
export function toParams(f: LedgerFilters): Record<string, string> {
  const out: Record<string, string> = {}
  for (const key of KEYS) if (f[key]) out[key] = f[key]
  return out
}
