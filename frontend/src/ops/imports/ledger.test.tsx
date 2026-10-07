import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { json, me, problem, renderApp, type Handler } from '@/test/renderApp'
import { ID, batch, path, reader } from './fixtures'
import type { ImportLine, ImportLineDetail } from './types'

afterEach(() => vi.restoreAllMocks())

const LINE = '33333333-3333-4333-8333-333333333333'

const line = (over: Partial<ImportLine> = {}): ImportLine => ({
  id: LINE,
  declaration_id: 'd1',
  mrn: '27GB000000000000A1',
  current_declaration_id: 'd1',
  declaration_superseded: false,
  acceptance_date: '2027-03-14',
  item_no: 2,
  version: 1,
  supersedes_id: null,
  is_current: true,
  commodity_code: '7208100000',
  description: 'Hot rolled coil',
  net_mass_kg: '1234.500000',
  customs_value_source: '9876.50',
  customs_value_currency: 'USD',
  customs_value_gbp: null,
  customs_value_gbp_note: 'No FX rate applied here',
  valuation_basis: null,
  value_source: 'file',
  value_override_reason: null,
  country_of_origin_declared: 'CN',
  cpc: '4000',
  batch_id: ID,
  source_row_id: 's1',
  entry_method: 'cds',
  change_reason: null,
  created_at: '2027-03-31T23:30:00Z',
  open_exceptions: 3,
  ...over,
})

const detail = (over: Partial<ImportLineDetail> = {}): ImportLineDetail => ({
  line: line({ version: 2, change_reason: 'source_changed' }),
  declaration: {
    id: 'd1',
    mrn: '27GB000000000000A1',
    version: 1,
    supersedes_id: null,
    is_current: true,
    acceptance_date: '2027-03-14',
    acceptance_at: null,
    procedure_code: '4000',
    additional_procedure_codes: ['C07', 'F48'],
    importer: { id: 'p1', eori: 'GB123456789012', name: 'Importer Ltd' },
    declarant: { id: 'p2', eori: null, name: 'Declarant Ltd' },
    representative: null,
    representation_type: 'indirect',
    eori_context: 'GB',
    entry_method: 'cds',
    batch_id: ID,
    created_at: null,
  },
  sources: [
    {
      source_row_id: 's1',
      role: 'primary',
      report_type: 'import_item',
      batch_id: ID,
      row_number: 7,
      raw: { 'Commodity Code': '7208100000', Note: '<img src=x onerror=alert(1)>', Empty: '' },
      row_sha256: 'f'.repeat(64),
    },
    {
      source_row_id: 's2',
      role: 'duplicate_seen',
      report_type: 'import_item',
      batch_id: ID,
      row_number: 4,
      raw: { 'Commodity Code': '7208100000' },
      row_sha256: 'e'.repeat(64),
    },
  ],
  batch: {
    id: ID,
    status: 'completed',
    acquisition_method: 'cds_export',
    cds_report_type: 'import_item',
    eori_context: 'GB',
    acquired_on: null,
    window_start: null,
    window_end: null,
  },
  file: { document_version_id: null, filename: 'march-items.csv', sha256: 'c'.repeat(64), size_bytes: 2048 },
  versions: [
    {
      id: 'v1',
      version: 1,
      supersedes_id: null,
      is_current: false,
      change_reason: null,
      batch_id: ID,
      created_at: '2027-03-30T10:00:00Z',
    },
    {
      id: LINE,
      version: 2,
      supersedes_id: 'v1',
      is_current: true,
      change_reason: 'source_changed',
      batch_id: ID,
      created_at: '2027-03-31T23:30:00Z',
    },
  ],
  open_exceptions: [
    {
      id: 'e1',
      row_number: 7,
      field: 'line.cpc',
      code: 'CPC_ODD',
      severity: 'warning',
      message: 'The procedure code is unusual.',
      status: 'open',
      row_version: 1,
    },
  ],
  ...over,
})

function ledger(pages: Record<string, ImportLine[]> = { '': [line()] }) {
  const urls: string[] = []
  const handler: Handler = (url) => {
    const p = path(url)
    if (!p.startsWith('/tenants/t1/import-lines')) return undefined
    urls.push(p)
    const cursor = new URL(p, 'http://x').searchParams.get('cursor') ?? ''
    const next = cursor === '' && pages.c2 ? 'c2' : null
    return json({ items: pages[cursor] ?? [], next_cursor: next })
  }
  return { handler, urls }
}

describe('R1-005 import ledger', () => {
  test('shows lines with decimal strings unchanged, a link to the line and a Phase 4 note', async () => {
    const { handler, urls } = ledger({
      '': [line(), line({ id: 'x', declaration_superseded: true, mrn: 'OLDMRN' })],
    })
    renderApp('/ops/t/t1/imports/lines', { me: reader, handler })
    const table = await screen.findByRole('table', { name: 'Import lines' })
    expect(urls[0]).toBe('/tenants/t1/import-lines')
    expect(within(table).getAllByText('1234.500000').length).toBeGreaterThan(0)
    expect(within(table).getAllByText('9876.50 USD').length).toBeGreaterThan(0)
    expect(within(table).getByRole('link', { name: '27GB000000000000A1' })).toHaveAttribute(
      'href',
      `/ops/t/t1/imports/lines/${LINE}`,
    )
    expect(within(table).getAllByText('14 March 2027').length).toBeGreaterThan(0)
    expect(within(table).getByText('Superseded declaration')).toBeInTheDocument()
    expect(within(table).getAllByText('Acceptance date (as reported)').length).toBe(1)
    expect(screen.getByText(/arrive in Phase 4/)).toBeInTheDocument()
    expect(within(table).queryByText(/tax point/i)).not.toBeInTheDocument()
  })

  test('filters build the query string and the URL', async () => {
    const { handler, urls } = ledger()
    renderApp('/ops/t/t1/imports/lines', { me: reader, handler })
    await screen.findByRole('table', { name: 'Import lines' })
    await userEvent.type(screen.getByLabelText('Commodity code starts with'), '7208')
    await userEvent.type(screen.getByLabelText('Country of origin'), 'CN')
    await userEvent.type(screen.getByLabelText('Acceptance date (as reported) from'), '2027-03-01')
    await userEvent.type(screen.getByLabelText('Acceptance date (as reported) to'), '2027-03-31')
    await userEvent.type(screen.getByLabelText('Import file id'), ID)
    await userEvent.selectOptions(screen.getByLabelText('Entry method'), 'gcd')
    await userEvent.selectOptions(screen.getByLabelText('Open exceptions'), 'true')
    await userEvent.click(screen.getByLabelText('Include superseded versions'))
    await userEvent.click(screen.getByRole('button', { name: 'Apply filters' }))
    await waitFor(() => expect(urls.length).toBeGreaterThan(1))
    const params = new URL(urls[urls.length - 1], 'http://x').searchParams
    expect(Object.fromEntries(params)).toEqual({
      commodity_code: '7208',
      origin: 'CN',
      from: '2027-03-01',
      to: '2027-03-31',
      batch_id: ID,
      entry_method: 'gcd',
      has_open_exceptions: 'true',
      include_superseded: 'true',
    })
  })

  test('a bad commodity prefix is blocked with a message and nothing is sent', async () => {
    const { handler, urls } = ledger()
    renderApp('/ops/t/t1/imports/lines', { me: reader, handler })
    await screen.findByRole('table', { name: 'Import lines' })
    await userEvent.type(screen.getByLabelText('Commodity code starts with'), '72ab')
    await userEvent.click(screen.getByRole('button', { name: 'Apply filters' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('1 to 10 digits')
    expect(urls).toHaveLength(1)
  })

  test('filters in the URL are applied; invalid ones are reported and not sent', async () => {
    const { handler, urls } = ledger()
    renderApp('/ops/t/t1/imports/lines?commodity_code=72&origin=cn&include_superseded=true', {
      me: reader,
      handler,
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('2-letter country code')
    await screen.findByRole('table', { name: 'Import lines' })
    const params = new URL(urls[0], 'http://x').searchParams
    expect(Object.fromEntries(params)).toEqual({ commodity_code: '72', include_superseded: 'true' })
    expect(screen.getByLabelText('Commodity code starts with')).toHaveValue('72')
  })

  test('superseded versions are marked when included', async () => {
    const { handler } = ledger({ '': [line({ is_current: false, version: 1 })] })
    renderApp('/ops/t/t1/imports/lines?include_superseded=true', { me: reader, handler })
    expect(await screen.findByText('1 (superseded)')).toBeInTheDocument()
  })

  test('Load more follows the cursor', async () => {
    const { handler, urls } = ledger({ '': [line()], c2: [line({ id: 'y', mrn: 'SECONDMRN' })] })
    renderApp('/ops/t/t1/imports/lines', { me: reader, handler })
    await userEvent.click(await screen.findByRole('button', { name: 'Load more' }))
    expect(await screen.findByRole('link', { name: 'SECONDMRN' })).toBeInTheDocument()
    expect(urls.some((u) => u.includes('cursor=c2'))).toBe(true)
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  })

  test('shows an empty message and a 403 error', async () => {
    const empty = renderApp('/ops/t/t1/imports/lines', { me: reader, handler: ledger({ '': [] }).handler })
    expect(await screen.findByText('No import lines found.')).toBeInTheDocument()
    empty.unmount()
    renderApp('/ops/t/t1/imports/lines', {
      me: reader,
      handler: (url) =>
        path(url).startsWith('/tenants/') ? problem(403, 'forbidden', 'Not allowed.') : undefined,
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('Not allowed.')
  })

  test('the import list links to the ledger and the nav shows Import ledger with imports:read', async () => {
    renderApp('/ops/t/t1/imports', {
      me: reader,
      handler: (url) =>
        path(url).startsWith('/tenants/t1/import-batches')
          ? json({ items: [batch()], next_cursor: null })
          : undefined,
    })
    expect(await screen.findByRole('link', { name: 'Open the import ledger' })).toHaveAttribute(
      'href',
      '/ops/t/t1/imports/lines',
    )
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: 'Import ledger' })).toHaveAttribute(
      'href',
      '/ops/t/t1/imports/lines',
    )
  })

  test('the ledger nav item is hidden without imports:read', async () => {
    renderApp('/ops/t/t1', { me: me() })
    const nav = await screen.findByRole('navigation', { name: 'Main' })
    expect(within(nav).queryByRole('link', { name: 'Import ledger' })).not.toBeInTheDocument()
  })
})

describe('R1-005 / R1-010 line detail', () => {
  const route = `/ops/t/t1/imports/lines/${LINE}`
  const withDetail = (d: ImportLineDetail = detail()): Handler => (url) =>
    path(url) === `/tenants/t1/import-lines/${LINE}` ? json(d) : undefined

  test('shows the line, declaration, sources, stored file, versions and exceptions', async () => {
    renderApp(route, { me: reader, handler: withDetail() })
    expect(await screen.findByRole('heading', { name: /27GB000000000000A1, item 2/ })).toBeInTheDocument()
    expect(screen.getByText('1234.500000')).toBeInTheDocument()
    expect(screen.getByText('Importer Ltd · GB123456789012')).toBeInTheDocument()
    expect(screen.getByText('Declarant Ltd')).toBeInTheDocument()
    expect(screen.getByText('indirect')).toBeInTheDocument()
    expect(screen.getByText('C07, F48')).toBeInTheDocument()

    const primary = screen.getByRole('region', { name: 'Source row 7 (primary)' })
    expect(within(primary).getByText('f'.repeat(64), { exact: false })).toBeInTheDocument()
    expect(within(primary).getByRole('link', { name: 'Open import file' })).toHaveAttribute(
      'href',
      `/ops/t/t1/imports/${ID}`,
    )
    expect(screen.getByRole('region', { name: 'Source row 4 (duplicate_seen)' })).toBeInTheDocument()

    expect(screen.getByText('march-items.csv')).toBeInTheDocument()
    expect(screen.getByText('2048')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to import ledger' })).toHaveAttribute(
      'href',
      '/ops/t/t1/imports/lines',
    )

    const versions = screen.getByRole('table', { name: 'Versions of this line' })
    expect(within(versions).getAllByRole('row')).toHaveLength(3)
    expect(within(versions).getByText('Current (this version)')).toBeInTheDocument()
    expect(within(versions).getByText('source changed')).toBeInTheDocument()

    const exceptions = screen.getByRole('table', { name: 'Open exceptions of the source rows' })
    expect(within(exceptions).getByText('The procedure code is unusual.')).toBeInTheDocument()
  })

  test('raw cell text is rendered as text, never markup', async () => {
    const { container } = renderApp(route, { me: reader, handler: withDetail() })
    expect(await screen.findByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(container.querySelector('img')).toBeNull()
  })

  test('a missing line shows the error with the back link; a bad id sends no request', async () => {
    const notFound = renderApp(route, {
      me: reader,
      handler: (url) =>
        path(url).startsWith('/tenants/t1/import-lines/')
          ? problem(404, 'not-found', 'No such line.')
          : undefined,
    })
    expect(await screen.findByText('No such line.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to import ledger' })).toBeInTheDocument()
    notFound.unmount()

    const { fetchImpl } = renderApp('/ops/t/t1/imports/lines/..%2Fx', { me: reader })
    expect(await screen.findByRole('heading', { name: 'Not found' })).toBeInTheDocument()
    expect(fetchImpl.mock.calls.some(([u]) => u.includes('import-lines'))).toBe(false)
  })

  test('a 403 is shown', async () => {
    renderApp(route, {
      me: reader,
      handler: (url) =>
        path(url).startsWith('/tenants/t1/import-lines/')
          ? problem(403, 'forbidden', 'Not allowed.')
          : undefined,
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('Not allowed.')
  })
})
