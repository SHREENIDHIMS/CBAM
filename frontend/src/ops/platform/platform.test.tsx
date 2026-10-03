import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import type { Member, Tenant } from '@/shared/api/types'
import { json, me, problem, renderApp, type Handler } from '@/test/renderApp'

const admin = me({ platform_admin: true, memberships: [], mfa: { required: true, passed: true } })

const tenant = (over: Partial<Tenant> = {}): Tenant => ({
  id: 't1',
  name: 'Alpha Ltd',
  status: 'active',
  row_version: 1,
  created_at: '2027-03-31T23:30:00Z',
  ...over,
})
const member = (over: Partial<Member> = {}): Member => ({
  membership_id: 'm1',
  user_id: 'u9',
  email: 'jo@example.test',
  display_name: 'Jo Bloggs',
  roles: ['operations'],
  row_version: 1,
  ...over,
})

/** A tiny fake of the platform API that records requests. */
function fakeApi(state: { tenants: Tenant[]; members: Member[] }) {
  const calls: { method: string; url: string; body?: unknown; ifMatch?: string | null }[] = []
  const handler: Handler = (url, init) => {
    const method = init?.method ?? 'GET'
    const headers = new Headers(init?.headers)
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    if (url.includes('/platform/')) {
      calls.push({
        method,
        url: url.replace('/api/v1', ''),
        body,
        ifMatch: headers.get('if-match'),
      })
    }
    if (url.endsWith('/platform/tenants') && method === 'GET') return json(state.tenants)
    if (url.endsWith('/platform/tenants') && method === 'POST') {
      const created = tenant({ id: 't2', name: body.name })
      state.tenants = [...state.tenants, created]
      return json(created, 201)
    }
    if (url.endsWith('/members') && method === 'GET') return json(state.members)
    return undefined
  }
  return { handler, calls }
}

describe('platform administration', () => {
  test('is not found for someone who is not a platform admin', async () => {
    renderApp('/ops/platform')
    expect(await screen.findByRole('heading', { name: 'Not found' })).toBeInTheDocument()
  })

  test('the client picker links platform admins to it', async () => {
    renderApp('/ops', { me: admin })
    expect(await screen.findByRole('link', { name: 'Platform administration' })).toHaveAttribute(
      'href',
      '/ops/platform',
    )
  })

  test('lists clients with status and UK dates, and adds one', async () => {
    const { handler, calls } = fakeApi({ tenants: [tenant()], members: [] })
    renderApp('/ops/platform', { me: admin, handler })
    const table = await screen.findByRole('table', { name: 'Client accounts' })
    expect(within(table).getByRole('link', { name: 'Alpha Ltd' })).toHaveAttribute(
      'href',
      '/ops/platform/tenants/t1',
    )
    expect(within(table).getByText('active')).toBeInTheDocument()
    expect(within(table).getByText('1 April 2027, 00:30')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Client name'), '  Beta Imports ')
    await userEvent.click(screen.getByRole('button', { name: 'Add client' }))
    expect(await screen.findByRole('link', { name: 'Beta Imports' })).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ name: 'Beta Imports' })
  })

  test('the add button stays disabled until there is a name', async () => {
    const { handler } = fakeApi({ tenants: [], members: [] })
    renderApp('/ops/platform', { me: admin, handler })
    expect(await screen.findByRole('button', { name: 'Add client' })).toBeDisabled()
  })
})

describe('a client', () => {
  test('shows its people with role labels', async () => {
    const { handler } = fakeApi({
      tenants: [tenant()],
      members: [member({ roles: ['operations', 'reviewer'] })],
    })
    renderApp('/ops/platform/tenants/t1', { me: admin, handler })
    expect(await screen.findByRole('heading', { name: 'Alpha Ltd' })).toBeInTheDocument()
    const table = await screen.findByRole('table', { name: 'People with access to Alpha Ltd' })
    expect(within(table).getByRole('cell', { name: /^jo@example\.test/ })).toBeInTheDocument()
    expect(within(table).getByText('Operations, Reviewer')).toBeInTheDocument()
  })

  test('an unknown client is not found', async () => {
    const { handler } = fakeApi({ tenants: [tenant()], members: [] })
    renderApp('/ops/platform/tenants/nope', { me: admin, handler })
    expect(await screen.findByRole('heading', { name: 'Not found' })).toBeInTheDocument()
  })

  test('invites someone with the chosen roles', async () => {
    const base = fakeApi({ tenants: [tenant()], members: [] })
    const handler: Handler = (url, init) => {
      if (url.endsWith('/invitations')) {
        base.calls.push({ method: 'POST', url, body: JSON.parse(String(init?.body)) })
        return json(member({ email: 'new@example.test', roles: ['reviewer'] }), 201)
      }
      return base.handler(url, init)
    }
    renderApp('/ops/platform/tenants/t1', { me: admin, handler })
    await userEvent.type(await screen.findByLabelText('Email'), ' new@example.test ')
    await userEvent.type(screen.getByLabelText('Name (optional)'), 'New Person')
    const send = screen.getByRole('button', { name: 'Send invitation' })
    expect(send).toBeDisabled()
    await userEvent.click(screen.getByLabelText('Reviewer'))
    expect(send).toBeEnabled()
    await userEvent.click(send)
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Invitation sent to new@example.test.',
    )
    expect(base.calls.find((c) => c.url.endsWith('/invitations'))?.body).toEqual({
      email: 'new@example.test',
      roles: ['reviewer'],
      display_name: 'New Person',
    })
  })

  test('says which roles need two-step verification', async () => {
    const { handler } = fakeApi({ tenants: [tenant()], members: [] })
    renderApp('/ops/platform/tenants/t1', { me: admin, handler })
    const operations = await screen.findByLabelText('Operations')
    expect(operations.parentElement).toHaveTextContent('needs two-step verification')
    expect(screen.getByLabelText('Client admin').parentElement).not.toHaveTextContent('two-step')
  })

  test('shows the reason when an invitation is refused', async () => {
    const base = fakeApi({ tenants: [tenant()], members: [] })
    const handler: Handler = (url, init) =>
      url.endsWith('/invitations')
        ? problem(422, 'invalid-request', 'That person is already a member of this client')
        : base.handler(url, init)
    renderApp('/ops/platform/tenants/t1', { me: admin, handler })
    await userEvent.type(await screen.findByLabelText('Email'), 'dup@example.test')
    await userEvent.click(screen.getByLabelText('Reviewer'))
    await userEvent.click(screen.getByRole('button', { name: 'Send invitation' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already a member')
  })

  test('changes roles using the row version, and explains a stale save', async () => {
    const base = fakeApi({ tenants: [tenant()], members: [member({ row_version: 4 })] })
    let fail = false
    const handler: Handler = (url, init) => {
      if (url.includes('/members/u9') && init?.method === 'PATCH') {
        base.calls.push({
          method: 'PATCH',
          url,
          body: JSON.parse(String(init.body)),
          ifMatch: new Headers(init.headers).get('if-match'),
        })
        return fail
          ? problem(409, 'stale-version')
          : json(member({ roles: ['reviewer'], row_version: 5 }))
      }
      return base.handler(url, init)
    }
    renderApp('/ops/platform/tenants/t1', { me: admin, handler })
    await userEvent.click(await screen.findByRole('button', { name: /Edit roles/ }))
    const editor = within(screen.getByRole('group', { name: 'Roles for jo@example.test' }))
    await userEvent.click(editor.getByLabelText('Operations'))
    await userEvent.click(editor.getByLabelText('Reviewer'))
    fail = true
    await userEvent.click(screen.getByRole('button', { name: /Save roles/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Someone else changed this record')
    const patch = base.calls.find((c) => c.method === 'PATCH')
    expect(patch?.ifMatch).toBe('"4"')
    expect(patch?.body).toEqual({ roles: ['reviewer'] })
  })

  test('the save button needs at least one role', async () => {
    const { handler } = fakeApi({ tenants: [tenant()], members: [member()] })
    renderApp('/ops/platform/tenants/t1', { me: admin, handler })
    await userEvent.click(await screen.findByRole('button', { name: /Edit roles/ }))
    const editor = within(screen.getByRole('group', { name: 'Roles for jo@example.test' }))
    await userEvent.click(editor.getByLabelText('Operations'))
    expect(screen.getByRole('button', { name: /Save roles/ })).toBeDisabled()
  })

  test('removing someone asks first', async () => {
    const base = fakeApi({ tenants: [tenant()], members: [member()] })
    const handler: Handler = (url, init) => {
      if (init?.method === 'DELETE') {
        base.calls.push({ method: 'DELETE', url })
        return json(null, 204)
      }
      return base.handler(url, init)
    }
    renderApp('/ops/platform/tenants/t1', { me: admin, handler })
    await userEvent.click(await screen.findByRole('button', { name: /^Remove/ }))
    expect(base.calls.some((c) => c.method === 'DELETE')).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: /Yes, remove/ }))
    await waitFor(() => expect(base.calls.some((c) => c.method === 'DELETE')).toBe(true))
    expect(base.calls.find((c) => c.method === 'DELETE')?.url).toBe(
      '/api/v1/platform/tenants/t1/members/u9',
    )
  })

  test('suspending needs a reason and sends the row version', async () => {
    const base = fakeApi({ tenants: [tenant({ row_version: 3 })], members: [] })
    const handler: Handler = (url, init) => {
      if (url.endsWith('/platform/tenants/t1') && init?.method === 'PATCH') {
        base.calls.push({
          method: 'PATCH',
          url,
          body: JSON.parse(String(init.body)),
          ifMatch: new Headers(init.headers).get('if-match'),
        })
        return json(tenant({ status: 'suspended', row_version: 4 }))
      }
      return base.handler(url, init)
    }
    renderApp('/ops/platform/tenants/t1', { me: admin, handler })
    const suspend = await screen.findByRole('button', { name: 'Suspend' })
    expect(suspend).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Reason for the change'), 'unpaid invoice')
    await userEvent.click(suspend)
    await waitFor(() => expect(base.calls.some((c) => c.method === 'PATCH')).toBe(true))
    const patch = base.calls.find((c) => c.method === 'PATCH')
    expect(patch?.ifMatch).toBe('"3"')
    expect(patch?.body).toEqual({ status: 'suspended', reason: 'unpaid invoice' })
  })

  test('a closed client cannot be reopened or invited to', async () => {
    const { handler } = fakeApi({ tenants: [tenant({ status: 'closed' })], members: [] })
    renderApp('/ops/platform/tenants/t1', { me: admin, handler })
    expect(await screen.findByText(/cannot be reopened here/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reactivate' })).not.toBeInTheDocument()
    expect(screen.getByText('People can only be invited to an active client.')).toBeInTheDocument()
  })
})
