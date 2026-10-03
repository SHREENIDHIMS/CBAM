import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { Button } from '@/shared/components/ui/button'
import { AuthCard, Field, FormError } from '@/shared/components/AuthCard'
import { useAuth } from '@/shared/auth/AuthContext'

/** Opened from the reset email: Supabase has already signed the user in with a recovery session. */
const MIN_LENGTH = 12 // matches supabase/config.toml minimum_password_length

export function UpdatePassword() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (password.length < MIN_LENGTH) {
      setError(`Use at least ${MIN_LENGTH} characters.`)
      return
    }
    try {
      await auth.updatePassword(password)
      navigate('/ops', { replace: true })
    } catch {
      setError('We could not change the password. The link may have expired; request a new one.')
    }
  }

  if (auth.status === 'loading')
    return (
      <p role="status" className="p-6">
        Loading…
      </p>
    )
  if (auth.status === 'signed_out') {
    return (
      <AuthCard title="Choose a new password">
        <p role="alert">This link is not valid or has expired. Request a new reset link.</p>
      </AuthCard>
    )
  }
  return (
    <AuthCard title="Choose a new password">
      <form onSubmit={submit}>
        <FormError message={error} />
        <Field
          id="password"
          label="New password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={setPassword}
        />
        <Button type="submit">Change password</Button>
      </form>
    </AuthCard>
  )
}
