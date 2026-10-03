import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'
import { fakeAuth, me, renderApp } from './test/renderApp'

describe('signed out', () => {
  test('the ops area sends you to sign in', async () => {
    renderApp('/ops', { auth: fakeAuth({ status: 'signed_out', user: null, aal: null }) })
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  test('the supplier portal needs no account', () => {
    renderApp('/portal', { auth: fakeAuth({ status: 'signed_out', user: null, aal: null }) })
    expect(screen.getByRole('heading', { name: 'Supplier portal' })).toBeInTheDocument()
  })
})

describe('sign in form', () => {
  const signedOut = () => fakeAuth({ status: 'signed_out', user: null, aal: null })

  test('sends the trimmed email and the password', async () => {
    const auth = signedOut()
    renderApp('/signin', { auth })
    await userEvent.type(screen.getByLabelText('Email'), '  ops@example.test ')
    await userEvent.type(screen.getByLabelText('Password'), 'correct horse battery')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(auth.signIn).toHaveBeenCalledWith('ops@example.test', 'correct horse battery')
  })

  test('a failure shows one generic message', async () => {
    const auth = {
      ...signedOut(),
      signIn: vi.fn().mockRejectedValue(new Error('Invalid login credentials')),
    }
    renderApp('/signin', { auth })
    await userEvent.type(screen.getByLabelText('Email'), 'x@example.test')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The email or password is not correct.',
    )
    expect(screen.queryByText(/Invalid login credentials/)).not.toBeInTheDocument()
  })
})

describe('password reset', () => {
  test('always shows the same confirmation', async () => {
    const auth = fakeAuth({ status: 'signed_out', user: null, aal: null })
    renderApp('/reset-password', { auth })
    await userEvent.type(screen.getByLabelText('Email'), 'nobody@example.test')
    await userEvent.click(screen.getByRole('button', { name: 'Send reset link' }))
    expect(await screen.findByRole('status')).toHaveTextContent('If that email has an account')
    expect(auth.requestPasswordReset).toHaveBeenCalledWith('nobody@example.test')
  })

  test('the new password must be at least 12 characters', async () => {
    const auth = fakeAuth()
    renderApp('/reset-password/update', { auth })
    await userEvent.type(screen.getByLabelText('New password'), 'short')
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('at least 12 characters')
    expect(auth.updatePassword).not.toHaveBeenCalled()
  })

  test('without a recovery session the link is reported as invalid', () => {
    renderApp('/reset-password/update', {
      auth: fakeAuth({ status: 'signed_out', user: null, aal: null }),
    })
    expect(screen.getByRole('alert')).toHaveTextContent('not valid or has expired')
  })
})

describe('two-step verification', () => {
  const privileged = me({
    mfa: { required: true, passed: false },
    memberships: [
      {
        tenant_id: 't1',
        tenant_name: 'Alpha Ltd',
        roles: ['operations'],
        permissions: ['tasks:read'],
        mfa_required: true,
      },
    ],
  })

  test('a privileged role with a factor but no MFA is sent to the challenge', async () => {
    const auth = fakeAuth({ aal: 'aal1' })
    vi.mocked(auth.mfa.listVerifiedFactors).mockResolvedValue([{ id: 'f1' }])
    renderApp('/ops', { auth, me: privileged })
    expect(
      await screen.findByRole('heading', { name: 'Two-step verification' }),
    ).toBeInTheDocument()
  })

  test('a privileged role with no factor is sent to enrolment', async () => {
    renderApp('/ops/t/t1', { auth: fakeAuth({ aal: 'aal1' }), me: privileged })
    expect(
      await screen.findByRole('heading', { name: 'Set up two-step verification' }),
    ).toBeInTheDocument()
    expect(await screen.findByAltText('QR code for your authenticator app')).toBeInTheDocument()
    expect(screen.getByText('ABC123')).toBeInTheDocument()
  })

  test('a privileged role that passed MFA goes straight in', async () => {
    renderApp('/ops/t/t1', { auth: fakeAuth({ aal: 'aal2' }), me: privileged })
    expect(await screen.findByRole('heading', { name: 'Home' })).toBeInTheDocument()
  })

  test('an unprivileged role never sees the MFA screens', async () => {
    renderApp('/ops/t/t1', { auth: fakeAuth({ aal: 'aal1' }) })
    expect(await screen.findByRole('heading', { name: 'Home' })).toBeInTheDocument()
  })

  test('the challenge sends the six-digit code for the verified factor', async () => {
    const auth = fakeAuth({ aal: 'aal1' })
    vi.mocked(auth.mfa.listVerifiedFactors).mockResolvedValue([{ id: 'f1' }])
    renderApp('/mfa/challenge', { auth, me: privileged })
    await userEvent.type(await screen.findByLabelText('Six-digit code'), ' 123456 ')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))
    await waitFor(() => expect(auth.mfa.verify).toHaveBeenCalledWith('f1', '123456'))
  })

  test('a wrong code shows an error', async () => {
    const auth = fakeAuth({ aal: 'aal1' })
    vi.mocked(auth.mfa.listVerifiedFactors).mockResolvedValue([{ id: 'f1' }])
    vi.mocked(auth.mfa.verify).mockRejectedValue(new Error('bad code'))
    renderApp('/mfa/challenge', { auth, me: privileged })
    await userEvent.type(await screen.findByLabelText('Six-digit code'), '000000')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That code is not correct')
  })
})

describe('app shell', () => {
  test('one client account opens straight into it, with role-aware navigation', async () => {
    renderApp('/ops')
    expect(await screen.findByRole('heading', { name: 'Home' })).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(nav).toHaveTextContent('Home')
    expect(nav).toHaveTextContent('Tasks')
    expect(screen.getByText('Alpha Ltd')).toBeInTheDocument()
  })

  test('a link is hidden without its permission', async () => {
    const noTasks = me({
      memberships: [
        {
          tenant_id: 't1',
          tenant_name: 'Alpha Ltd',
          roles: ['supplier'],
          permissions: [],
          mfa_required: false,
        },
      ],
    })
    renderApp('/ops/t/t1', { me: noTasks })
    await screen.findByRole('heading', { name: 'Home' })
    expect(screen.getByRole('navigation', { name: 'Main' })).not.toHaveTextContent('Tasks')
  })

  test('several client accounts show a picker', async () => {
    const two = me({
      memberships: [
        {
          tenant_id: 't1',
          tenant_name: 'Alpha Ltd',
          roles: ['client_admin'],
          permissions: [],
          mfa_required: false,
        },
        {
          tenant_id: 't2',
          tenant_name: 'Beta Ltd',
          roles: ['reviewer'],
          permissions: [],
          mfa_required: false,
        },
      ],
    })
    renderApp('/ops', { me: two })
    expect(
      await screen.findByRole('heading', { name: 'Choose a client account' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Alpha Ltd' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Beta Ltd' })).toBeInTheDocument()
  })

  test("another tenant's id looks like it does not exist", async () => {
    renderApp('/ops/t/someone-elses-tenant')
    expect(await screen.findByRole('heading', { name: 'Not found' })).toBeInTheDocument()
  })

  test('signing out calls the auth layer and returns to sign in', async () => {
    const auth = fakeAuth()
    renderApp('/ops/t/t1', { auth })
    await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
    expect(auth.signOut).toHaveBeenCalled()
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  test('shows a message when you belong to no client account', async () => {
    renderApp('/ops', { me: me({ memberships: [] }) })
    expect(await screen.findByText(/do not have access to any client account/)).toBeInTheDocument()
  })
})
