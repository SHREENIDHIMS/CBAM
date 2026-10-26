import AxeBuilder from '@axe-core/playwright'
import { expect, test, type BrowserContext } from '@playwright/test'

// Import screens: a session is injected and the API is mocked, so this runs without Supabase or
// the backend (same approach as platform.spec.ts).
const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString('base64url')
const TENANT = '11111111-1111-4111-8111-111111111111'
const BATCH = '22222222-2222-4222-8222-222222222222'
const LINE = '33333333-3333-4333-8333-333333333333'

const line = {
  id: LINE,
  declaration_id: 'd1',
  mrn: '27GB000000000000A1',
  current_declaration_id: 'd1',
  declaration_superseded: true,
  acceptance_date: '2027-01-14',
  item_no: 1,
  version: 2,
  supersedes_id: null,
  is_current: true,
  commodity_code: '7208100000',
  description: 'Hot rolled coil',
  net_mass_kg: '1234.500000',
  customs_value_source: '9876.50',
  customs_value_currency: 'USD',
  customs_value_gbp: null,
  customs_value_gbp_note: null,
  valuation_basis: null,
  value_source: 'file',
  value_override_reason: null,
  country_of_origin_declared: 'CN',
  cpc: '4000',
  batch_id: BATCH,
  source_row_id: 's1',
  entry_method: 'cds',
  change_reason: 'source_changed',
  created_at: '2027-02-02T09:00:00Z',
  open_exceptions: 1,
}
const lineDetail = {
  line,
  declaration: {
    id: 'd1',
    mrn: line.mrn,
    version: 1,
    supersedes_id: null,
    is_current: true,
    acceptance_date: '2027-01-14',
    acceptance_at: null,
    procedure_code: '4000',
    additional_procedure_codes: null,
    importer: { id: 'p1', eori: 'GB123456789012', name: 'Importer Ltd' },
    declarant: null,
    representative: null,
    representation_type: 'direct',
    eori_context: 'GB',
    entry_method: 'cds',
    batch_id: BATCH,
    created_at: null,
  },
  sources: [
    {
      source_row_id: 's1',
      role: 'primary',
      report_type: 'import_item',
      batch_id: BATCH,
      row_number: 3,
      raw: { 'Commodity Code': '7208100000', Note: '<b>not bold</b>' },
      row_sha256: 'b'.repeat(64),
    },
  ],
  batch: {
    id: BATCH,
    status: 'completed',
    acquisition_method: 'get_customs_data',
    cds_report_type: 'import_item',
    eori_context: 'GB',
    acquired_on: null,
    window_start: null,
    window_end: null,
  },
  file: { document_version_id: null, filename: 'january.csv', sha256: 'a'.repeat(64), size_bytes: 1024 },
  versions: [
    {
      id: LINE,
      version: 2,
      supersedes_id: null,
      is_current: true,
      change_reason: 'source_changed',
      batch_id: BATCH,
      created_at: '2027-02-02T09:00:00Z',
    },
  ],
  open_exceptions: [],
}

const batch = {
  id: BATCH,
  status: 'completed_with_errors',
  file_sha256: 'a'.repeat(64),
  document_version_id: null,
  filename: 'january.csv',
  acquisition_method: 'get_customs_data',
  cds_report_type: 'import_item',
  eori: 'GB123456789012',
  window_start: '2027-01-01',
  window_end: '2027-01-31',
  source_owner: null,
  acquired_on: '2027-02-02',
  rows_total: 500,
  rows_processed: 500,
  rows_valid: 463,
  rows_rejected: 37,
  lines_created: 463,
  lines_unchanged: 0,
  failure_reason: null,
  report_layout_version_id: null,
  layout_status: 'active',
  created_at: '2027-02-02T09:00:00Z',
  created_by: null,
  row_version: 3,
}

async function signIn(context: BrowserContext) {
  const exp = Math.floor(Date.now() / 1000) + 3600
  const jwt = `${b64({ alg: 'ES256', typ: 'JWT' })}.${b64({ sub: 'u-ops', aal: 'aal2', exp, email: 'ops@example.test', aud: 'authenticated' })}.sig`
  const session = {
    access_token: jwt,
    refresh_token: 'r',
    token_type: 'bearer',
    expires_in: 3600,
    expires_at: exp,
    user: {
      id: 'u-ops',
      aud: 'authenticated',
      email: 'ops@example.test',
      app_metadata: {},
      user_metadata: {},
      created_at: '2027-01-01T00:00:00Z',
      factors: [],
    },
  }
  await context.addInitScript(
    (s) => localStorage.setItem('sb-127-auth-token', JSON.stringify(s)),
    session,
  )
  await context.route('**/api/v1/**', (route) => {
    const url = route.request().url()
    const json = (body: unknown) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.endsWith('/me')) {
      return json({
        user_id: 'u-ops',
        platform_admin: false,
        domain_owner: false,
        memberships: [
          {
            tenant_id: TENANT,
            tenant_name: 'Example Imports Ltd',
            roles: ['operations'],
            permissions: ['imports:read', 'imports:write', 'tasks:read'],
            mfa_required: true,
          },
        ],
        mfa: { required: true, passed: true },
      })
    }
    if (url.includes('/exceptions') && url.includes('format=csv')) {
      return route.fulfill({
        status: 200,
        contentType: 'text/csv',
        body: "row_number,field,code,severity,message,status\n0,,FILE_NOTE,warning,'=whole file,open\n",
      })
    }
    if (url.includes('/exceptions')) {
      return json({
        items: [
          {
            id: 'e1',
            row_number: 0,
            field: '',
            code: 'FILE_NOTE',
            severity: 'warning',
            message: 'A problem with the whole file',
            status: 'open',
            row_version: 1,
          },
          {
            id: 'e2',
            row_number: 12,
            field: 'line.net_mass_kg',
            code: 'NET_MASS_PRECISION',
            severity: 'error',
            message: 'Net mass has more than 6 decimal places',
            status: 'open',
            row_version: 1,
          },
        ],
        next_cursor: null,
      })
    }
    if (url.includes(`/import-lines/${LINE}`)) return json(lineDetail)
    if (url.includes('/import-lines')) return json({ items: [line], next_cursor: null })
    if (url.includes(`/import-batches/${BATCH}`)) return json(batch)
    if (url.includes('/import-batches')) return json({ items: [batch], next_cursor: null })
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
  })
}

for (const [name, path] of [
  ['batch list', `/ops/t/${TENANT}/imports`],
  ['batch detail', `/ops/t/${TENANT}/imports/${BATCH}`],
] as const) {
  test(`${name}: renders and has no serious axe violations`, async ({ page, context }) => {
    await signIn(context)
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.getByText('january.csv').first()).toBeVisible()
    const { violations } = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag22aa'])
      .analyze()
    expect(violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')).toEqual([])
  })
}

for (const [name, path, text] of [
  ['import ledger', `/ops/t/${TENANT}/imports/lines`, '27GB000000000000A1'],
  ['line detail', `/ops/t/${TENANT}/imports/lines/${LINE}`, '<b>not bold</b>'],
] as const) {
  test(`${name}: renders decimal strings as given and has no serious axe violations`, async ({
    page,
    context,
  }) => {
    await signIn(context)
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.getByText(text).first()).toBeVisible()
    await expect(page.getByText('1234.500000').first()).toBeVisible()
    const { violations } = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag22aa'])
      .analyze()
    expect(violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')).toEqual([])
  })
}

test('import ledger: a bad commodity prefix shows a message and passes axe', async ({
  page,
  context,
}) => {
  await signIn(context)
  await page.goto(`/ops/t/${TENANT}/imports/lines`)
  await page.getByLabel('Commodity code starts with').fill('72ab')
  await page.getByRole('button', { name: 'Apply filters' }).click()
  await expect(page.getByRole('alert')).toContainText('1 to 10 digits')
  const { violations } = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag22aa'])
    .analyze()
  expect(violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')).toEqual([])
})

test('batch detail: exceptions show "Whole file" and the CSV downloads unchanged', async ({
  page,
  context,
}) => {
  await signIn(context)
  await page.goto(`/ops/t/${TENANT}/imports/${BATCH}`)
  await expect(page.getByText('Whole file', { exact: true })).toBeVisible()
  await expect(page.getByText('Net mass has more than 6 decimal places')).toBeVisible()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: /download csv/i }).click()
  const file = await download
  const path = await file.path()
  const text = (await import('node:fs')).readFileSync(path, 'utf8')
  expect(text).toContain("'=whole file")
})
