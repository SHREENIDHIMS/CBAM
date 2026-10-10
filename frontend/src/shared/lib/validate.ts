/** Format checks shared by several screens. These are input formats, not legal rules. */

/** A GB or XI EORI: two letters and twelve digits (the server uses the same pattern). */
export const EORI_PATTERN = /^(GB|XI)[0-9]{12}$/

/** A real calendar date in YYYY-MM-DD form (2027-13-45 is not). */
export function isRealDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}
