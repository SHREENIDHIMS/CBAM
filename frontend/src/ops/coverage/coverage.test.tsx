import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { json, me, problem, renderApp, type Handler } from '@/test/renderApp'
import { ID, batch, reader } from '../imports/fixtures'
import type { Calendar, Eori } from './types'

afterEach(() => vi.restoreAllMocks())

const writer = me({
  memberships: [
    {
      tenant_id: 't1',
      tenant_name: 'Alpha Ltd',
      roles: ['operations'],
      permissions: ['tasks:read', 'imports:read', 'imports:write'],
      mfa_required: false,
    },
  ],
})
const E = 'GB123456789012'
const path = (url: string) => url.replace('/api/v1', '')

const eoriRow = (over: Partial<Eori> = {}): Eori => ({
  id: 'r1',
  eori: E,
  tracking_from: '2027-01-01',
  third_party_access: 'requested',
  access_recorded_on: '2027-02-03',
  note: 'Ask the agent <b>first</b>',
  row_version: 4,
  created_at: '2027-01-01T10:00:00Z',
  ...over,
})

const calendar = (over: Partial<Calendar> = {}): Calendar => ({
  eori: E,
  report_type: 'import_item',
  tracking_from: '2027-01-01',
  registered: true,
  third_party_access: 'granted',
  range_from: '2027-01-01',
  range_to: '2027-03-31',
  periods: [
    { covered_from: '2027-01-01', covered_to: '2027-01-31', state: 'loaded', days: 31 },
    { covered_from: '2027-02-01', covered_to: '2027-02-14', state: 'loaded_with_errors', days: 14 },
    { covered_from: '2027-02-15', covered_to: '2027-03-20', state: 'gap', days: 34 },
    { covered_from: '2027-03-21', covered_to: '2027-03-31', state: 'not_yet_available', days: 11 },
  ],
  gaps: [{ covered_from: '2027-02-15', covered_to: '2027-03-20', state: 'gap', days: 34 }],
  overlaps: [{ covered_from: '2027-01-10', covered_to: '2027-01-12', batch_ids: [ID] }],
  complete: false,
  unavailable_latest_days: null,
  dataset_version_ids: [],
  ...over,
})

describe('R1-054 EORI register', () => {
  function register(rows: Eori[] = [eoriRow()]) {
    const calls: { method: string; url: string; body?: unknown; ifMatch?: string | null }[] = []
    const handler: Handler = (url, init) => {
      const p = path(url)
      if (!p.startsWith('/tenants/t1/customs-data')) return undefined
      const method = init?.method ?? 'GET'
      calls.push({
        method,
        url: p,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
        ifMatch: new Headers(init?.headers).get('if-match'),
      })
      if (p.endsWith('/eoris') && method === 'GET') return json(rows)
      return undefined
    }
    return { handler, calls }
  }

  test('lists EORIs with UK dates, access status and a calendar link; note is text only', async () => {
    const { handler } = register()
    const { container } = renderApp('/ops/t/t1/customs-data', { me: reader, handler })
    const table = await screen.findByRole('table', { name: 'Registered EORIs' })
    expect(within(table).getByRole('link', { name: E })).toHaveAttribute(
      'href',
      `/ops/t/t1/customs-data/${E}`,
    )
    expect(within(table).getByText('1 January 2027')).toBeInTheDocument()
    expect(within(table).getByText('requested (recorded 3 February 2027)')).toBeInTheDocument()
    expect(within(table).getByText('Ask the agent <b>first</b>')).toBeInTheDocument()
    expect(container.querySelector('b')).toBeNull()
    expect(within(table).getByText('4')).toBeInTheDocument()
    expect(screen.getByText(/not a threshold or tax point/)).toBeInTheDocument()
  })

  test('a read-only user sees no write controls', async () => {
    const { handler } = register()
    renderApp('/ops/t/t1/customs-data', { me: reader, handler })
    await screen.findByRole('table', { name: 'Registered EORIs' })
    expect(screen.queryByRole('button', { name: /Edit access/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Check for gaps now' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Register an EORI' })).not.toBeInTheDocument()
  })

  test('the nav item shows with imports:read only', async () => {
    renderApp('/ops/t/t1/customs-data', { me: reader, handler: register().handler })
    const nav = await screen.findByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: 'Customs data coverage' })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })

  test('registering validates the EORI, date and note before sending', async () => {
    const { handler, calls } = register()
    renderApp('/ops/t/t1/customs-data', { me: writer, handler })
    await screen.findByRole('table', { name: 'Registered EORIs' })
    await userEvent.type(screen.getByLabelText('EORI'), 'fr123')
    await userEvent.click(screen.getByLabelText('Note (optional)'))
    await userEvent.paste('x'.repeat(501))
    await userEvent.click(screen.getByRole('button', { name: 'Register EORI' }))
    const alerts = await screen.findAllByRole('alert')
    expect(alerts.map((a) => a.textContent)).toEqual(
      expect.arrayContaining([
        'EORI must be GB or XI followed by 12 digits.',
        'Enter the first day to cover as a real date.',
        'Note can be at most 500 characters.',
      ]),
    )
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0)
  })

  test('registers an EORI (upper-cased) and shows a 409 duplicate message', async () => {
    const { handler, calls } = register()
    let posts = 0
    const wrapped: Handler = (url, init) => {
      if (init?.method === 'POST' && path(url).endsWith('/eoris')) {
        posts += 1
        calls.push({ method: 'POST', url: path(url), body: JSON.parse(String(init.body)) })
        return posts === 1
          ? json(eoriRow(), 201)
          : problem(409, 'conflict', 'That EORI is already registered.')
      }
      return handler(url, init)
    }
    renderApp('/ops/t/t1/customs-data', { me: writer, handler: wrapped })
    await screen.findByRole('table', { name: 'Registered EORIs' })
    const submit = async () => {
      await userEvent.clear(screen.getByLabelText('EORI'))
      await userEvent.type(screen.getByLabelText('EORI'), 'xi123456789012')
      await userEvent.type(screen.getByLabelText('First day to cover'), '2027-01-01')
      await userEvent.selectOptions(screen.getByLabelText('Third-party access'), 'granted')
      await userEvent.click(screen.getByRole('button', { name: 'Register EORI' }))
    }
    await submit()
    await waitFor(() => expect(screen.getByLabelText('EORI')).toHaveValue(''))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      eori: 'XI123456789012',
      tracking_from: '2027-01-01',
      third_party_access: 'granted',
      note: null,
    })
    await submit()
    expect(await screen.findByRole('alert')).toHaveTextContent('already registered')
  })

  test('shows a 422 message from the server', async () => {
    const { handler } = register()
    const wrapped: Handler = (url, init) =>
      init?.method === 'POST'
        ? problem(422, 'validation', 'EORI prefix not allowed.')
        : handler(url, init)
    renderApp('/ops/t/t1/customs-data', { me: writer, handler: wrapped })
    await screen.findByRole('table', { name: 'Registered EORIs' })
    await userEvent.type(screen.getByLabelText('EORI'), 'GB123456789012')
    await userEvent.type(screen.getByLabelText('First day to cover'), '2027-01-01')
    await userEvent.click(screen.getByRole('button', { name: 'Register EORI' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('EORI prefix not allowed.')
  })

  test('editing sends only changed fields with If-Match and says the first day cannot change', async () => {
    const { handler, calls } = register()
    const wrapped: Handler = (url, init) =>
      init?.method === 'PATCH' ? json(eoriRow({ row_version: 5 })) : handler(url, init)
    const spy = vi.fn(wrapped)
    renderApp('/ops/t/t1/customs-data', { me: writer, handler: spy })
    await userEvent.click(await screen.findByRole('button', { name: `Edit access / note for ${E}` }))
    const form = screen.getByRole('form', { name: `Edit ${E}` })
    expect(within(form).getByText(/cannot be changed/)).toBeInTheDocument()
    await userEvent.selectOptions(within(form).getByLabelText(`Third-party access for ${E}`), 'granted')
    await userEvent.click(within(form).getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(spy.mock.calls.some(([, i]) => i?.method === 'PATCH')).toBe(true))
    const patch = spy.mock.calls.find(([, i]) => i?.method === 'PATCH')!
    expect(patch[0]).toBe('/api/v1/tenants/t1/customs-data/eoris/r1')
    expect(JSON.parse(String(patch[1]?.body))).toEqual({ third_party_access: 'granted' })
    expect(new Headers(patch[1]?.headers).get('if-match')).toBe('"4"')
    expect(calls.length).toBeGreaterThan(0)
  })

  test('a stale edit (409) tells the user to reload and reloads the register', async () => {
    const { handler, calls } = register()
    const wrapped: Handler = (url, init) =>
      init?.method === 'PATCH' ? problem(409, 'stale-version') : handler(url, init)
    renderApp('/ops/t/t1/customs-data', { me: writer, handler: wrapped })
    await userEvent.click(await screen.findByRole('button', { name: `Edit access / note for ${E}` }))
    await userEvent.type(screen.getByLabelText(`Note for ${E}`), ' more')
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Reload the page')
    await waitFor(() => expect(calls.filter((c) => c.method === 'GET').length).toBeGreaterThan(1))
  })

  test('Check for gaps now shows the counts', async () => {
    const { handler, calls } = register()
    const wrapped: Handler = (url, init) =>
      init?.method === 'POST' && path(url).endsWith('/coverage/scan')
        ? json({ eoris_scanned: 2, gap_tasks_created: 3, month_tasks_created: 1 })
        : handler(url, init)
    renderApp('/ops/t/t1/customs-data', { me: writer, handler: wrapped })
    await userEvent.click(await screen.findByRole('button', { name: 'Check for gaps now' }))
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Checked 2 EORI(s). New gap tasks: 3. New monthly tasks: 1.',
    )
    expect(calls.length).toBeGreaterThan(0)
  })

  test('an empty register and a 403 are shown', async () => {
    const empty = renderApp('/ops/t/t1/customs-data', { me: reader, handler: register([]).handler })
    expect(await screen.findByText('No EORIs registered yet.')).toBeInTheDocument()
    empty.unmount()
    renderApp('/ops/t/t1/customs-data', {
      me: reader,
      handler: (url) =>
        path(url).startsWith('/tenants/') ? problem(403, 'forbidden', 'Not allowed.') : undefined,
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('Not allowed.')
  })
})

describe('R1-054 coverage calendar', () => {
  function cal(c: Calendar | Response = calendar()) {
    const urls: string[] = []
    const handler: Handler = (url) => {
      const p = path(url)
      if (!p.startsWith('/tenants/t1/customs-data/coverage')) return undefined
      urls.push(p)
      return c instanceof Response ? c.clone() : json(c)
    }
    return { handler, urls }
  }
  const route = `/ops/t/t1/customs-data/${E}`

  test('shows the summary, periods with text labels, gaps and overlaps linking to the batch', async () => {
    const { handler, urls } = cal()
    renderApp(route, { me: reader, handler })
    await screen.findByRole('table', { name: 'Coverage periods' })
    expect(screen.getByRole('heading', { name: `Coverage for ${E}` })).toBeInTheDocument()
    expect(urls[0]).toBe(`/tenants/t1/customs-data/coverage?eori=${E}&report_type=import_item`)
    expect(screen.getByText('Complete').nextSibling).toHaveTextContent('No')
    expect(screen.getByText('Third-party access').nextSibling).toHaveTextContent('granted')
    expect(screen.getByText('First day to cover').nextSibling).toHaveTextContent('1 January 2027')
    expect(screen.getByText('Latest days not yet available').nextSibling).toHaveTextContent(
      'No HMRC lag rule is active, so recent days show as gaps.',
    )
    const periods = screen.getByRole('table', { name: 'Coverage periods' })
    const labels = within(periods)
      .getAllByRole('row')
      .slice(1)
      .map((r) => within(r).getAllByRole('cell')[3].textContent)
    expect(labels).toEqual(['Loaded', 'Loaded with errors', 'Gap', 'Not yet available'])
    const gaps = screen.getByRole('table', { name: 'Gaps' })
    expect(within(gaps).getByText('15 February 2027')).toBeInTheDocument()
    expect(within(gaps).getByText('34')).toBeInTheDocument()
    const overlaps = screen.getByRole('table', { name: 'Overlaps' })
    expect(within(overlaps).getByRole('link', { name: ID })).toHaveAttribute(
      'href',
      `/ops/t/t1/imports/${ID}`,
    )
    expect(screen.getByText(/not a threshold, scope or tax point/)).toBeInTheDocument()
  })

  test('shows the lag in days when a rule is active', async () => {
    renderApp(route, { me: reader, handler: cal(calendar({ unavailable_latest_days: 5 })).handler })
    expect(await screen.findByText('5 days')).toBeInTheDocument()
  })

  test('switching report type and range requests again, with Loading in between', async () => {
    const { handler, urls } = cal()
    renderApp(route, { me: reader, handler })
    await screen.findByRole('table', { name: 'Coverage periods' })
    await userEvent.selectOptions(screen.getByLabelText('Report type'), 'import_header')
    await waitFor(() =>
      expect(urls).toContain(`/tenants/t1/customs-data/coverage?eori=${E}&report_type=import_header`),
    )
    await userEvent.type(screen.getByLabelText('From (optional)'), '2027-02-01')
    await waitFor(() =>
      expect(urls).toContain(
        `/tenants/t1/customs-data/coverage?eori=${E}&report_type=import_header&from=2027-02-01`,
      ),
    )
  })

  test('404 shows the not-registered state; 422 shows the server message', async () => {
    const notFound = renderApp(route, {
      me: reader,
      handler: cal(problem(404, 'not-found', 'EORI not known.')).handler,
    })
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Not registered and no reports loaded',
    )
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    notFound.unmount()
    renderApp(route, {
      me: reader,
      handler: cal(problem(422, 'validation', 'The range is over 2000 days.')).handler,
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('The range is over 2000 days.')
  })

  test('an invalid EORI or date sends no request', async () => {
    const { handler, urls } = cal()
    const bad = renderApp('/ops/t/t1/customs-data/..%2Fx', { me: reader, handler })
    expect(await screen.findByRole('alert')).toHaveTextContent('not valid')
    bad.unmount()
    renderApp(`${route}?from=2027-13-45&report_type=nope`, { me: reader, handler })
    const alerts = await screen.findAllByRole('alert')
    expect(alerts.map((a) => a.textContent)).toEqual(
      expect.arrayContaining(['The from date is not a real date.', 'Unknown report type.']),
    )
    expect(urls).toHaveLength(0)
  })

  test('the batch detail page links an EORI to its calendar', async () => {
    renderApp(`/ops/t/t1/imports/${ID}`, {
      me: reader,
      handler: (url) =>
        path(url).startsWith(`/tenants/t1/import-batches/${ID}`)
          ? json(path(url).includes('/exceptions') ? { items: [], next_cursor: null } : batch())
          : undefined,
    })
    expect(await screen.findByRole('link', { name: 'GB123456789012' })).toHaveAttribute(
      'href',
      '/ops/t/t1/customs-data/GB123456789012',
    )
  })
})
