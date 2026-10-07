import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { json, problem, renderApp, type Handler } from '@/test/renderApp'
import { ID, batch, exception, path, reader } from './fixtures'
import type { ImportBatch, RowException } from './types'

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

// Fake only the interval timers: react-query's refetchInterval uses setInterval.
const fakeIntervals = () => vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
const batchUrl = `/tenants/t1/import-batches/${ID}`
const detailRoute = `/ops/t/t1/imports/${ID}`
const batchCalls = (calls: string[]) => calls.filter((c) => !c.includes('/exceptions')).length

function live(state: { batch: ImportBatch; exceptions: RowException[] }) {
  const calls: string[] = []
  const handler: Handler = (url) => {
    const p = path(url)
    if (!p.startsWith(batchUrl)) return undefined
    calls.push(p)
    if (p.includes('/exceptions')) return json({ items: state.exceptions, next_cursor: null })
    return json(state.batch)
  }
  return { handler, calls }
}

describe('R1-003 detail: live refresh and failures', () => {
  test('polls every 3 seconds while not final, then stops', async () => {
    fakeIntervals()
    const state = {
      batch: batch({ id: ID, status: 'parsing', rows_processed: 2 }),
      exceptions: [] as RowException[],
    }
    const { handler, calls } = live(state)
    renderApp(detailRoute, { me: reader, handler })
    await screen.findByText('2 of 10')
    expect(batchCalls(calls)).toBe(1)
    state.batch = batch({ id: ID, status: 'completed' })
    await vi.advanceTimersByTimeAsync(3000)
    expect(await screen.findByText('10 of 10')).toBeInTheDocument()
    expect(batchCalls(calls)).toBe(2)
    await vi.advanceTimersByTimeAsync(9000)
    expect(batchCalls(calls)).toBe(2)
  })

  test('exceptions refresh when the batch finishes, with no empty message while processing', async () => {
    fakeIntervals()
    const state = {
      batch: batch({ id: ID, status: 'validating' }),
      exceptions: [] as RowException[],
    }
    const { handler } = live(state)
    renderApp(detailRoute, { me: reader, handler })
    expect(await screen.findByText(/Still processing/)).toBeInTheDocument()
    expect(screen.queryByText('No exceptions found.')).not.toBeInTheDocument()
    state.batch = batch({ id: ID, status: 'completed_with_errors' })
    state.exceptions = [exception({ code: 'LATE_ONE' })]
    await vi.advanceTimersByTimeAsync(3000)
    expect(await screen.findByText('LATE_ONE')).toBeInTheDocument()
    expect(screen.queryByText(/Still processing/)).not.toBeInTheDocument()
  })

  test('an unknown status counts as final: no polling', async () => {
    fakeIntervals()
    const state = {
      batch: batch({ id: ID, status: 'brand_new' as ImportBatch['status'] }),
      exceptions: [] as RowException[],
    }
    const { handler, calls } = live(state)
    renderApp(detailRoute, { me: reader, handler })
    await screen.findByText('brand new')
    await vi.advanceTimersByTimeAsync(12000)
    expect(batchCalls(calls)).toBe(1)
  })

  test('a 404 shows the error, keeps the page landmark and does not poll', async () => {
    fakeIntervals()
    const calls: string[] = []
    const handler: Handler = (url) => {
      const p = path(url)
      if (!p.startsWith(batchUrl)) return undefined
      calls.push(p)
      return problem(404, 'not-found', 'No such import file.')
    }
    renderApp(detailRoute, { me: reader, handler })
    expect(await screen.findByText('No such import file.')).toBeInTheDocument()
    expect(screen.getAllByRole('main').length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: 'Back to imports' })).toBeInTheDocument()
    await vi.advanceTimersByTimeAsync(12000)
    expect(batchCalls(calls)).toBe(1)
  })

  test('Back to imports goes to the tenant imports list', async () => {
    const { handler } = live({ batch: batch({ id: ID }), exceptions: [] })
    renderApp(detailRoute, { me: reader, handler })
    expect(await screen.findByRole('link', { name: 'Back to imports' })).toHaveAttribute(
      'href',
      '/ops/t/t1/imports',
    )
  })

  test('a batch id that is not a UUID is Not found and sends no request', async () => {
    const { fetchImpl } = renderApp('/ops/t/t1/imports/..%2Fx', { me: reader })
    expect(await screen.findByRole('heading', { name: 'Not found' })).toBeInTheDocument()
    expect(fetchImpl.mock.calls.some(([u]) => u.includes('import-batches'))).toBe(false)
  })

  test('malformed dates show as raw text, and an empty field is a dash', async () => {
    const { handler } = live({
      batch: batch({ id: ID, window_start: '2027-13-45', created_at: 'yesterday' }),
      exceptions: [exception({ field: '' })],
    })
    renderApp(detailRoute, { me: reader, handler })
    expect(await screen.findByText(/2027-13-45/)).toBeInTheDocument()
    expect(screen.getByText('yesterday')).toBeInTheDocument()
    const table = await screen.findByRole('table', { name: 'Exceptions' })
    expect(within(table).getByText('—')).toBeInTheDocument()
  })

  test('Download CSV is disabled and says Preparing while the request is pending', async () => {
    const { handler: base } = live({ batch: batch({ id: ID }), exceptions: [] })
    let release: (r: Response) => void = () => {}
    let csvRequests = 0
    const handler: Handler = (url, init) => {
      if (path(url).includes('format=csv')) {
        csvRequests += 1
        return new Promise<Response>((resolve) => (release = resolve))
      }
      return base(url, init)
    }
    Object.assign(URL, { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    renderApp(detailRoute, { me: reader, handler })
    await screen.findByText('No exceptions found.')
    await userEvent.click(screen.getByRole('button', { name: 'Download CSV' }))
    const busy = await screen.findByRole('button', { name: 'Preparing…' })
    expect(busy).toBeDisabled()
    await userEvent.click(busy)
    expect(csvRequests).toBe(1)
    release(new Response('a\r\n'))
    expect(await screen.findByRole('button', { name: 'Download CSV' })).toBeEnabled()
  })
})

describe('R1-003 list: live refresh', () => {
  function listHandler(status: ImportBatch['status']) {
    let n = 0
    const handler: Handler = (url) => {
      if (!path(url).startsWith('/tenants/t1/import-batches')) return undefined
      n += 1
      return json({ items: [batch({ status })], next_cursor: null })
    }
    return { handler, count: () => n }
  }

  test('refreshes every 5 seconds while a row is processing', async () => {
    fakeIntervals()
    const { handler, count } = listHandler('parsing')
    renderApp('/ops/t/t1/imports', { me: reader, handler })
    await screen.findByRole('table', { name: 'Import batches' })
    expect(count()).toBe(1)
    await vi.advanceTimersByTimeAsync(5000)
    expect(count()).toBe(2)
  })

  test('does not refresh when every row is final', async () => {
    fakeIntervals()
    const { handler, count } = listHandler('completed')
    renderApp('/ops/t/t1/imports', { me: reader, handler })
    await screen.findByRole('table', { name: 'Import batches' })
    await vi.advanceTimersByTimeAsync(15000)
    expect(count()).toBe(1)
  })
})
