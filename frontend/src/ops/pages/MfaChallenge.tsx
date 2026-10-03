import { useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router'
import { Button } from '@/shared/components/ui/button'
import { AuthCard, Field, FormError } from '@/shared/components/AuthCard'
import { useAuth } from '@/shared/auth/AuthContext'

export function MfaChallenge() {
  const auth = useAuth()
  const navigate = useNavigate()
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/ops'
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const factors = useQuery({
    queryKey: ['mfa-factors'],
    queryFn: () => auth.mfa.listVerifiedFactors(),
  })

  async function submit(event: FormEvent) {
    event.preventDefault()
    const factor = factors.data?.[0]
    if (!factor) return
    setError(null)
    try {
      await auth.mfa.verify(factor.id, code.trim())
      navigate(from, { replace: true })
    } catch {
      setError('That code is not correct. Check the app and try again.')
    }
  }

  return (
    <AuthCard title="Two-step verification">
      <p className="mb-4">Enter the six-digit code from your authenticator app.</p>
      <form onSubmit={submit}>
        <FormError message={error} />
        <Field
          id="code"
          label="Six-digit code"
          autoComplete="one-time-code"
          inputMode="numeric"
          value={code}
          onChange={setCode}
        />
        <Button type="submit" disabled={!factors.data?.length}>
          Verify
        </Button>
      </form>
    </AuthCard>
  )
}
