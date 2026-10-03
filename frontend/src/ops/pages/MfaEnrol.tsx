import { useEffect, useState, type FormEvent } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router'
import { Button } from '@/shared/components/ui/button'
import { AuthCard, Field, FormError } from '@/shared/components/AuthCard'
import { useAuth, type MfaEnrolment } from '@/shared/auth/AuthContext'

export function MfaEnrol() {
  const auth = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/ops'
  const [enrolment, setEnrolment] = useState<MfaEnrolment | null>(null)
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    auth.mfa
      .enrol()
      .then((e) => !cancelled && setEnrolment(e))
      .catch(() => !cancelled && setError('We could not start setting up the authenticator app.'))
    return () => {
      cancelled = true
    }
  }, [auth.mfa])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!enrolment) return
    setError(null)
    try {
      await auth.mfa.verify(enrolment.factorId, code.trim())
      await queryClient.invalidateQueries({ queryKey: ['mfa-factors'] })
      navigate(from, { replace: true })
    } catch {
      setError('That code is not correct. Check the app and try again.')
    }
  }

  return (
    <AuthCard title="Set up two-step verification">
      <p className="mb-4">
        Your role needs two-step verification. Scan this code with an authenticator app, then enter
        the six-digit code it shows.
      </p>
      <FormError message={error} />
      {enrolment ? (
        <>
          <img
            src={enrolment.qrCodeDataUrl}
            alt="QR code for your authenticator app"
            className="mb-2 h-48 w-48"
          />
          <p className="mb-4 text-sm">
            Cannot scan it? Enter this key instead: <code>{enrolment.secret}</code>
          </p>
          <form onSubmit={submit}>
            <Field
              id="code"
              label="Six-digit code"
              autoComplete="one-time-code"
              inputMode="numeric"
              value={code}
              onChange={setCode}
            />
            <Button type="submit">Confirm</Button>
          </form>
        </>
      ) : (
        !error && <p role="status">Preparing your code…</p>
      )}
    </AuthCard>
  )
}
