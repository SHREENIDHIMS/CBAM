import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { Button } from '@/shared/components/ui/button'
import { AuthCard, Field, FormError } from '@/shared/components/AuthCard'
import { useAuth } from '@/shared/auth/AuthContext'

export function SignIn() {
  const auth = useAuth()
  const navigate = useNavigate()
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/ops'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await auth.signIn(email.trim(), password)
      navigate(from, { replace: true })
    } catch {
      // Same message whatever went wrong, so the form never reveals which emails exist.
      setError('The email or password is not correct.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard title="Sign in">
      <form onSubmit={submit}>
        <FormError message={error} />
        <Field
          id="email"
          label="Email"
          type="email"
          autoComplete="username"
          value={email}
          onChange={setEmail}
        />
        <Field
          id="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={setPassword}
        />
        <Button type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
      <p className="mt-4 text-sm">
        <Link to="/reset-password" className="underline">
          Forgotten your password?
        </Link>
      </p>
    </AuthCard>
  )
}
