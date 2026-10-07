import AxeBuilder from '@axe-core/playwright'
import { expect, test, type BrowserContext } from '@playwright/test'

// Import screens: a session is injected and the API is mocked, so this runs without Supabase or
// the backend (same approach as platform.spec.ts).
const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString('base64url')
const TENANT = '11111111-1111-4111-8111-111111111111'
const BATCH = '22222222-2222-4222-8222-222222222222'

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
