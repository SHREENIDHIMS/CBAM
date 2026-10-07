import { formatDate, formatDateTime } from '@/shared/lib/format'

export const statusLabel = (s: string) => s.replaceAll('_', ' ')

/** Display helpers that never throw: a malformed value shows as the raw text, not a blank page. */
export function safeDate(iso: string | null): string {
  if (!iso) return '—'
  try {
    return formatDate(iso)
  } catch {
    return iso
  }
}

export function safeDateTime(instant: string | null): string {
  if (!instant) return '—'
  try {
    return formatDateTime(instant)
  } catch {
    return instant
  }
}

export function windowText(start: string | null, end: string | null): string {
  if (!start) return '—'
  return end ? `${safeDate(start)} to ${safeDate(end)}` : safeDate(start)
}
