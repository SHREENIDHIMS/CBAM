import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { json, problem, renderApp, type Handler } from '@/test/renderApp'
import { ID, batch, exception, path, reader } from './fixtures'
import type { ImportBatch, RowException } from './types'

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('R1-003 import batch list', () => {
  test('shows each batch with progress, UK dates and a link to its detail', async () => {
    const handler: Handler = (url) =>
      path(url).startsWith('/tenants/t1/import-batches')
        ? json({ items: [batch()], next_cursor: null })
        : undefined
    renderApp('/ops/t/t1/imports', { me: reader, handler })
    const table = await screen.findByRole('table', { name: 'Import batches' })
    expect(within(table).getByRole('link', { name: 'march-items.csv' })).toHaveAttribute(
      'href',
      `/ops/t/t1/imports/${ID}`,
    )
    expect(within(table).getByText('GB123456789012')).toBeInTheDocument()
    expect(within(table).getByText('1 March 2027 to 31 March 2027')).toBeInTheDocument()
    expect(within(table).getByText('completed')).toBeInTheDocument()
    expect(within(table).getByText('10 of 10 rows')).toBeInTheDocument()
    expect(within(table).getByText('1 April 2027, 00:30')).toBeInTheDocument()
    expect(within(table).getByRole('progressbar', { name: /march-items/ })).toBeInTheDocument()
  })

  test('the status filter and Load more use the API query string', async () => {
    const urls: string[] = []
    const handler: Handler = (url) => {
      const p = path(url)
      if (!p.startsWith('/tenants/t1/import-batches')) return undefined
      urls.push(p)
      if (p.includes('cursor=c2')) {
        return json({ items: [batch({ id: 'b2', filename: 'second.csv' })], next_cursor: null })
      }
      return json({ items: [batch()], next_cursor: 'c2' })
    }
    renderApp('/ops/t/t1/imports', { me: reader, handler })
    await screen.findByRole('link', { name: 'march-items.csv' })
    await userEvent.click(screen.getByRole('button', { name: 'Load more' }))
    expect(await screen.findByRole('link', { name: 'second.csv' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText('Status'), 'failed')
    await waitFor(() => expect(urls).toContain('/tenants/t1/import-batches?status=failed'))
  })

  test('says so when there are no files', async () => {
    renderApp('/ops/t/t1/imports', {
      me: reader,
      handler: (url) =>
        path(url).startsWith('/tenants/') ? json({ items: [], next_cursor: null }) : undefined,
    })
    expect(await screen.findByText('No import files found.')).toBeInTheDocument()
  })

  test('shows a permission error from the API', async () => {
    renderApp('/ops/t/t1/imports', {
      me: reader,
      handler: (url) =>
        path(url).startsWith('/tenants/') ? problem(403, 'forbidden', 'Not allowed.') : undefined,
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('Not allowed.')
  })
})

describe('navigation', () => {
  test('Imports shows with imports:read', async () => {
    renderApp('/ops/t/t1', { me: reader })
    const nav = await screen.findByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: 'Imports' })).toHaveAttribute(
      'href',
      '/ops/t/t1/imports',
    )
  })

  test('Imports is hidden without imports:read', async () => {
    renderApp('/ops/t/t1')
    const nav = await screen.findByRole('navigation', { name: 'Main' })
    expect(within(nav).queryByRole('link', { name: 'Imports' })).not.toBeInTheDocument()
  })
})

describe('R1-003 / R1-025 batch detail', () => {
  function detailHandler(state: { batch: ImportBatch; exceptions?: RowException[] }) {
    const calls: string[] = []
    const handler: Handler = (url) => {
      const p = path(url)
      if (!p.startsWith(`/tenants/t1/import-batches/${ID}`)) return undefined
      calls.push(p)
      if (p.includes('/exceptions')) {
        if (p.includes('format=csv')) {
          return new Response('row_number,field\r\n3,line.x\r\n', {
            headers: { 'content-type': 'text/csv' },
          })
        }
        if (p.includes('cursor=c2')) {
          return json({
            items: [exception({ id: 'e2', row_number: 9, code: 'SECOND' })],
            next_cursor: null,
          })
        }
        return json({ items: state.exceptions ?? [], next_cursor: state.exceptions ? 'c2' : null })
      }
      return json(state.batch)
    }
    return { handler, calls }
  }

  test('shows provenance, counters, layout status and a plain-text failure reason', async () => {
    const { handler } = detailHandler({
      batch: batch({ status: 'failed', failure_reason: 'worker_crash_loop' }),
    })
    renderApp(`/ops/t/t1/imports/${ID}`, { me: reader, handler })
    expect(await screen.findByRole('heading', { name: 'march-items.csv' })).toBeInTheDocument()
    expect(screen.getByText('worker_crash_loop')).toBeInTheDocument()
    expect(screen.getByText('GB123456789012')).toBeInTheDocument()
    expect(screen.getByText('1 March 2027 to 31 March 2027')).toBeInTheDocument()
    expect(screen.getByText('active')).toBeInTheDocument()
    expect(screen.getByText('Lines created').nextSibling).toHaveTextContent('7')
    expect(screen.getByText('Lines unchanged').nextSibling).toHaveTextContent('1')
    expect(screen.getByText('Rows rejected').nextSibling).toHaveTextContent('2')
    expect(screen.getByText('Rows valid').nextSibling).toHaveTextContent('8')
    expect(screen.getByText('Rows processed').nextSibling).toHaveTextContent('10 of 10')
  })

  test('lists exceptions, labels row 0 as Whole file, and loads more', async () => {
    const { handler, calls } = detailHandler({
      batch: batch(),
      exceptions: [
        exception({
          id: 'e0',
          row_number: 0,
          field: 'file',
          code: 'FILE_UNREADABLE',
          message: '<b>Unreadable</b>',
        }),
        exception(),
      ],
    })
    renderApp(`/ops/t/t1/imports/${ID}`, { me: reader, handler })
    const table = await screen.findByRole('table', { name: 'Exceptions' })
    expect(within(table).getByText('Whole file')).toBeInTheDocument()
    expect(within(table).getByText('3')).toBeInTheDocument()
    expect(within(table).getByText('line.commodity_code')).toBeInTheDocument()
    expect(within(table).getByText('CODE_INVALID')).toBeInTheDocument()
    // Messages are text, never markup.
    expect(within(table).getByText('<b>Unreadable</b>')).toBeInTheDocument()
    expect(table.querySelector('b')).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'Load more' }))
    expect(await within(table).findByText('SECOND')).toBeInTheDocument()
    expect(calls.some((c) => c.includes('cursor=c2'))).toBe(true)
  })

  test('exception filters are sent to the API', async () => {
    const { handler, calls } = detailHandler({ batch: batch(), exceptions: [exception()] })
    renderApp(`/ops/t/t1/imports/${ID}`, { me: reader, handler })
    await screen.findByRole('table', { name: 'Exceptions' })
    await userEvent.selectOptions(screen.getByLabelText('Severity'), 'warning')
    await userEvent.selectOptions(screen.getByLabelText('Exception status'), 'open')
    await waitFor(() =>
      expect(calls).toContain(
        `/tenants/t1/import-batches/${ID}/exceptions?severity=warning&status=open`,
      ),
    )
  })

  test('Download CSV fetches format=csv through the api client and saves a file', async () => {
    const { handler, calls } = detailHandler({ batch: batch(), exceptions: [exception()] })
    const create = vi.fn(() => 'blob:csv')
    const revoke = vi.fn()
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const { fetchImpl } = renderApp(`/ops/t/t1/imports/${ID}`, { me: reader, handler })
    await screen.findByRole('table', { name: 'Exceptions' })
    await userEvent.click(screen.getByRole('button', { name: 'Download CSV' }))
    await waitFor(() => expect(click).toHaveBeenCalled())
    expect(click.mock.contexts[0]).toHaveProperty('download', `import-exceptions-${ID}.csv`)
    expect(calls).toContain(`/tenants/t1/import-batches/${ID}/exceptions?format=csv`)
    const csvCall = fetchImpl.mock.calls.find(([u]) => u.includes('format=csv'))
    const headers = new Headers(csvCall?.[1]?.headers)
    expect(headers.get('authorization')).toBe('Bearer token')
    const blob = (create.mock.calls[0] as unknown as [Blob])[0]
    expect(await blob.text()).toBe('row_number,field\r\n3,line.x\r\n')
    await waitFor(() => expect(revoke).toHaveBeenCalledWith('blob:csv'))
  })

  test('a failed CSV download shows an error', async () => {
    const handler: Handler = (url) => {
      const p = path(url)
      if (p.includes('format=csv')) return problem(403, 'forbidden', 'Not allowed.')
      if (p.includes('/exceptions')) return json({ items: [], next_cursor: null })
      if (p.startsWith(`/tenants/t1/import-batches/${ID}`)) return json(batch())
      return undefined
    }
    renderApp(`/ops/t/t1/imports/${ID}`, { me: reader, handler })
    await screen.findByText('No exceptions found.')
    await userEvent.click(screen.getByRole('button', { name: 'Download CSV' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Not allowed.')
  })
})
