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
const DATE = /^\d{4}-\d{2}-\d{2}$/

export function readFilters(params: URLSearchParams): LedgerFilters {
  const out = { ...NO_FILTERS }
  for (const key of KEYS) (out as Record<string, string>)[key] = params.get(key) ?? ''
  return out
}

/** Messages for values the API would refuse. Nothing is sent until these are fixed. */
export function validateFilters(f: LedgerFilters): Partial<Record<keyof LedgerFilters, string>> {
  const errors: Partial<Record<keyof LedgerFilters, string>> = {}
  if (f.commodity_code && !/^\d{1,10}$/.test(f.commodity_code))
    errors.commodity_code = 'Commodity code must be 1 to 10 digits.'
  if (f.origin && !/^[A-Z]{2}$/.test(f.origin))
    errors.origin = 'Origin must be a 2-letter country code in capitals, for example CN.'
  if (f.from && !DATE.test(f.from)) errors.from = 'Enter the from date as a date.'
  if (f.to && !DATE.test(f.to)) errors.to = 'Enter the to date as a date.'
  if (f.from && f.to && DATE.test(f.from) && DATE.test(f.to) && f.to < f.from)
    errors.to = 'The to date cannot be before the from date.'
  if (f.batch_id && !UUID.test(f.batch_id)) errors.batch_id = 'Import file id must be a UUID.'
  if (f.entry_method && !ENTRY.includes(f.entry_method))
    errors.entry_method = 'Unknown entry method.'
  return errors
}

/** The valid, non-empty filters, as API / URL parameters. */
export function toParams(f: LedgerFilters): Record<string, string> {
  const errors = validateFilters(f)
  const out: Record<string, string> = {}
  for (const key of KEYS) {
    const value = f[key]
    if (!value || errors[key]) continue
    if (key === 'has_open_exceptions' && value !== 'true' && value !== 'false') continue
    if (key === 'include_superseded' && value !== 'true') continue
    out[key] = value
  }
  return out
}
