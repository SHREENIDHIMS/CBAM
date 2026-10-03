import { createClient, type Session, type SupabaseClient } from '@supabase/supabase-js'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { AuthContext, type AuthApi } from './AuthContext'

/** Supabase Auth only (CLAUDE.md rule 18): the frontend never reads business tables here. */
function makeClient(): SupabaseClient | null {
  const url = import.meta.env.VITE_SUPABASE_URL
  const key = import.meta.env.VITE_SUPABASE_ANON_KEY
  if (!url || !key) return null
  return createClient(url, key, { auth: { persistSession: true, autoRefreshToken: true } })
}

export const supabase = makeClient()

function requireClient(): SupabaseClient {
  if (!supabase)
    throw new Error('Sign-in is not configured: set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY')
  return supabase
}

function fail(error: { message: string } | null): void {
  if (error) throw new Error(error.message)
}

export function SupabaseAuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [aal, setAal] = useState<'aal1' | 'aal2' | null>(null)
  const [loading, setLoading] = useState(supabase !== null)

  useEffect(() => {
    if (!supabase) return
    let cancelled = false
    async function load(next: Session | null) {
      setSession(next)
      if (next && supabase) {
        const { data } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel()
        if (!cancelled) setAal(data?.currentLevel === 'aal2' ? 'aal2' : 'aal1')
      } else if (!cancelled) {
        setAal(null)
      }
      if (!cancelled) setLoading(false)
    }
    void supabase.auth.getSession().then(({ data }) => load(data.session))
    const { data } = supabase.auth.onAuthStateChange((_event, next) => void load(next))
    return () => {
      cancelled = true
      data.subscription.unsubscribe()
    }
  }, [])

  const value = useMemo<AuthApi>(
    () => ({
      status: loading ? 'loading' : session ? 'signed_in' : 'signed_out',
      user: session ? { id: session.user.id, email: session.user.email } : null,
      aal,
      getAccessToken: async () =>
        (await requireClient().auth.getSession()).data.session?.access_token ?? null,
      async signIn(email, password) {
        fail((await requireClient().auth.signInWithPassword({ email, password })).error)
      },
      async signOut() {
        fail((await requireClient().auth.signOut()).error)
      },
      async requestPasswordReset(email) {
        fail(
          (
            await requireClient().auth.resetPasswordForEmail(email, {
              redirectTo: `${window.location.origin}/reset-password/update`,
            })
          ).error,
        )
      },
      async updatePassword(password) {
        fail((await requireClient().auth.updateUser({ password })).error)
      },
      mfa: {
        async listVerifiedFactors() {
          const { data, error } = await requireClient().auth.mfa.listFactors()
          fail(error)
          return (data?.totp ?? []).map((f) => ({ id: f.id }))
        },
        async enrol() {
          const { data, error } = await requireClient().auth.mfa.enroll({ factorType: 'totp' })
          fail(error)
          if (!data) throw new Error('Could not start MFA enrolment')
          return { factorId: data.id, qrCodeDataUrl: data.totp.qr_code, secret: data.totp.secret }
        },
        async verify(factorId, code) {
          fail((await requireClient().auth.mfa.challengeAndVerify({ factorId, code })).error)
        },
      },
    }),
    [aal, loading, session],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
