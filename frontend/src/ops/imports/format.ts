import { formatDate } from '@/shared/lib/format'

export const statusLabel = (s: string) => s.replaceAll('_', ' ')

export function windowText(start: string | null, end: string | null): string {
  if (!start) return '—'
  return end ? `${formatDate(start)} to ${formatDate(end)}` : formatDate(start)
}
