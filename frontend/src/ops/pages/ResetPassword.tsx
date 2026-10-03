import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { Button } from '@/shared/components/ui/button'
import { AuthCard, Field, FormError } from '@/shared/components/AuthCard'
import { useAuth } from '@/shared/auth/AuthContext'

export function ResetPassword() {
  const auth = useAuth()
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      await auth.requestPasswordReset(email.trim())
    } catch {
      setError('We could not send the email. Please try again.')
      return
    }
    // Always the same confirmation, so this never reveals which emails have accounts.
    setSent(true)
  }

  return (
    <AuthCard title="Reset your password">
      {sent ? (
        <p role="status">
          If that email has an account, we have sent a link to reset the password.
        </p>
      ) : (
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
          <Button type="submit">Send reset link</Button>
        </form>
      )}
      <p className="mt-4 text-sm">
        <Link to="/signin" className="underline">
          Back to sign in
        </Link>
      </p>
    </AuthCard>
  )
}
