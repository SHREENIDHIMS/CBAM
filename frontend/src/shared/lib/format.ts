/** British English display helpers. Money and mass are decimal *strings*: never floats. */

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
] // prettier-ignore

const DECIMAL = /^(-?)(\d+)(?:\.(\d+))?$/

function groupThousands(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

/** '2027-03-14' -> '14 March 2027'. Legal dates are plain dates; no time zone is applied. */
export function formatDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (!match) throw new Error(`not a YYYY-MM-DD date: ${iso}`)
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])]
  const check = new Date(Date.UTC(year, month - 1, day))
  if (
    check.getUTCFullYear() !== year ||
    check.getUTCMonth() !== month - 1 ||
    check.getUTCDate() !== day
  ) {
    throw new Error(`not a real date: ${iso}`)
  }
  return `${day} ${MONTHS[month - 1]} ${year}`
}

/** An ISO instant with a zone, shown in UK time: '1 April 2027, 00:30'. */
export function formatDateTime(instant: string): string {
  if (!/(Z|[+-]\d{2}:?\d{2})$/.test(instant))
    throw new Error(`instant needs a time zone: ${instant}`)
  const date = new Date(instant)
  if (Number.isNaN(date.getTime())) throw new Error(`not a valid instant: ${instant}`)
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/London',
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    })
      .formatToParts(date)
      .map((p) => [p.type, p.value]),
  )
  return `${Number(parts.day)} ${MONTHS[Number(parts.month) - 1]} ${parts.year}, ${parts.hour}:${parts.minute}`
}

/** '1234.5' -> '£1,234.50'. Truncates beyond 2 decimal places (display only; never rounds up). */
export function formatGbp(amount: string): string {
  if (typeof amount !== 'string') throw new TypeError('amounts are decimal strings, not numbers')
  const match = DECIMAL.exec(amount)
  if (!match) throw new Error(`not a decimal string: ${amount}`)
  const [, sign, whole, fraction = ''] = match
  const pence = (fraction + '00').slice(0, 2)
  return `${sign}£${groupThousands(whole)}.${pence}`
}

/** '48200.000000' -> '48,200.000000 kg' (keeps the decimals it was given). */
export function formatMass(kg: string): string {
  if (typeof kg !== 'string') throw new TypeError('masses are decimal strings, not numbers')
  const match = DECIMAL.exec(kg)
  if (!match) throw new Error(`not a decimal string: ${kg}`)
  const [, sign, whole, fraction] = match
  return `${sign}${groupThousands(whole)}${fraction === undefined ? '' : `.${fraction}`} kg`
}
