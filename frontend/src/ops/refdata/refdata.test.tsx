import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import type { DatasetVersion, ImpactReport, RefDataset, RegulatorySource } from '@/shared/api/types'
import { json, me, problem, renderApp, type Handler } from '@/test/renderApp'

const owner = me({ domain_owner: true, memberships: [], mfa: { required: true, passed: true } })
const admin = me({ platform_admin: true, memberships: [], mfa: { required: true, passed: true } })

const dataset: RefDataset = {
  id: 'd1',
  name: 'cbam_commodity_codes',
  active_version: null,
  pending_versions: 1,
}
const source: RegulatorySource = {
  id: 's1',
  source_id: 'HMRC-CBAM-GOODS-SCOPE',
  title: 'Check which goods are in scope',
  source_type: 'guidance',
  url: null,
  publication_date: '2026-07-16',
  status: 'draft',
  commencement_date: '2027-01-01',
  effective_from: null,
  effective_to: null,
  retrieved_at: null,
  notes: null,
  row_version: 1,
}
const version = (over: Partial<DatasetVersion> = {}): DatasetVersion => ({
  id: 'v1',
  dataset: 'cbam_commodity_codes',
  version: '2027.1',
  source_ref: 'HMRC-CBAM-GOODS-SCOPE',
  source_status: 'draft',
  checksum_sha256: 'a'.repeat(64),
  effective_from: '2027-01-01',
  effective_to: null,
  is_fixture: false,
  row_count: 54,
  status: 'pending',
  loaded_at: '2026-10-03T07:00:00Z',
  activated_by: null,
  activated_at: null,
  retired_at: null,
  has_impact_report: false,
  row_version: 1,
  notes: null,
  impact_report: null,
  ...over,
})
const report: ImpactReport = {
  dataset: 'cbam_commodity_codes',
  version: '2027.1',
  compared_to: null,
  generated_at: '2026-10-03T07:05:00Z',
  rows: { added: 54, removed: 0, changed: 0, unchanged: 0 },
  changes: [{ change: 'added', key: { code_prefix: '7601' }, effective_from: '2027-01-01' }],
  changes_truncated: false,
  coverage_gaps: [],
  source: {
    source_id: 'HMRC-CBAM-GOODS-SCOPE',
    status: 'draft',
    outcome: 'NOT_ACTIVE',
    reason: 'x',
  },
  affected: { provider_registered: false, count: 0, items: [], truncated: false },
  warnings: [
    'Source HMRC-CBAM-GOODS-SCOPE would not allow this data to drive decisions yet: draft',
  ],
}

function fakeApi(state: { version: DatasetVersion }) {
  const calls: { method: string; url: string; ifMatch: string | null }[] = []
  const handler: Handler = (url, init) => {
    const method = init?.method ?? 'GET'
    const path = url.replace('/api/v1', '')
    if (path.startsWith('/platform/')) {
      calls.push({ method, url: path, ifMatch: new Headers(init?.headers).get('if-match') })
    }
    if (path === '/platform/datasets') return json([dataset])
    if (path === '/platform/sources') return json([source])
    if (path === '/platform/datasets/cbam_commodity_codes/versions') return json([state.version])
    if (path.endsWith('/versions/2027.1') && method === 'GET') return json(state.version)
    if (path.endsWith('/impact') && method === 'POST') {
      state.version = version({ has_impact_report: true, impact_report: report })
      return json(report)
    }
    if (path.endsWith('/activate') && method === 'POST') {
      state.version = version({ status: 'active', has_impact_report: true, impact_report: report })
      return json(state.version)
    }
    return undefined
  }
  return { handler, calls }
}

describe('reference data screens', () => {
  test('are not found for an ordinary client user', async () => {
    renderApp('/ops/reference-data')
    expect(await screen.findByRole('heading', { name: 'Not found' })).toBeInTheDocument()
  })

  test('the client picker links domain owners to them', async () => {
    renderApp('/ops', { me: owner })
    expect(await screen.findByRole('link', { name: 'Reference data' })).toHaveAttribute(
      'href',
      '/ops/reference-data',
    )
  })

  test('list datasets and sources and say what a draft source means', async () => {
    const { handler } = fakeApi({ version: version() })
    renderApp('/ops/reference-data', { me: admin, handler })
    const datasets = await screen.findByRole('table', { name: 'Reference datasets' })
    expect(within(datasets).getByRole('link', { name: 'cbam_commodity_codes' })).toHaveAttribute(
      'href',
      '/ops/reference-data/cbam_commodity_codes',
    )
    expect(within(datasets).getByText('None')).toBeInTheDocument()
    const sources = await screen.findByRole('table', { name: 'Regulatory sources' })
    expect(
      within(sources).getByText('Draft: its data cannot drive any decision'),
    ).toBeInTheDocument()
    expect(within(sources).getByText('1 January 2027')).toBeInTheDocument()
  })

  test('a platform admin can review a version but not generate a report or activate', async () => {
    const { handler } = fakeApi({ version: version() })
    renderApp('/ops/reference-data/cbam_commodity_codes', { me: admin, handler })
    await userEvent.click(await screen.findByRole('button', { name: 'Review 2027.1' }))
    expect(
      await screen.findByText('Only a domain owner can generate the report and activate.'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Generate impact report' })).toBeNull()
    expect(screen.queryByRole('button', { name: /Activate version/ })).toBeNull()
  })

  test('a domain owner generates the report, confirms and activates with the row version', async () => {
    const { handler, calls } = fakeApi({ version: version() })
    renderApp('/ops/reference-data/cbam_commodity_codes', { me: owner, handler })
    await userEvent.click(await screen.findByRole('button', { name: 'Review 2027.1' }))
    expect(await screen.findByText('No impact report yet.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Activate version/ })).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'Generate impact report' }))
    expect(
      await screen.findByText(/54 added, 0 removed, 0 changed, 0 unchanged/),
    ).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Warnings' })).toHaveTextContent('draft')
    expect(
      screen.getByText('Existing records are not checked for this dataset yet.'),
    ).toBeInTheDocument()

    const activate = await screen.findByRole('button', { name: 'Activate version 2027.1' })
    expect(activate).toBeDisabled()
    await userEvent.click(screen.getByLabelText(/I have read the impact report/))
    expect(activate).toBeEnabled()
    await userEvent.click(activate)

    await waitFor(() =>
      expect(calls.find((c) => c.url.endsWith('/activate'))).toMatchObject({
        method: 'POST',
        ifMatch: '"1"',
      }),
    )
  })

  test('shows a problem returned when activation is refused', async () => {
    const state = { version: version({ has_impact_report: true, impact_report: report }) }
    const { handler } = fakeApi(state)
    const refusing: Handler = (url, init) =>
      url.endsWith('/activate')
        ? problem(409, 'rule-blocked', 'The active version changed after the impact report')
        : handler(url, init)
    renderApp('/ops/reference-data/cbam_commodity_codes', { me: owner, handler: refusing })
    await userEvent.click(await screen.findByRole('button', { name: 'Review 2027.1' }))
    await userEvent.click(await screen.findByLabelText(/I have read the impact report/))
    await userEvent.click(screen.getByRole('button', { name: 'Activate version 2027.1' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The active version changed')
  })
})
