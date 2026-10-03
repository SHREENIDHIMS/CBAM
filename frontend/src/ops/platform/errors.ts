import { ApiError } from '@/shared/api/client'

/** A message a person can act on, from an API failure. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.slug === 'stale-version') {
      return 'Someone else changed this record. Reload the page and try again.'
    }
    if (error.slug === 'recent-auth-required') return 'Please sign in again to confirm this action.'
    if (error.slug === 'not-configured')
      return 'Inviting people is not set up for this environment yet.'
    if (error.slug === 'auth-admin')
      return 'The sign-in service could not complete that. Try again shortly.'
    if (error.detail) return error.detail
    return error.message
  }
  return 'Something went wrong. Please try again.'
}
