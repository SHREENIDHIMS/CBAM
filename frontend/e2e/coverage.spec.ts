import AxeBuilder from '@axe-core/playwright'
import { expect, test, type BrowserContext } from '@playwright/test'

// Customs-data coverage screens: a session is injected and the API is mocked (same approach as
// imports.spec.ts), so this runs without Supabase or the backend.
const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString('base64url')
const TENANT = '11111111-1111-4111-8111-111111111111'
const BATCH = '22222222-2222-4222-8222-222222222222'
const EORI = 'GB123456789012'

const eoris = [
  {
    id: 'r1',
    eori: EORI,
    tracking_from: '2027-01-01',
    third_party_access: 'requested',
    access_recorded_on: '2027-02-03',
    note: 'Ask the agent first',
    row_version: 2,
    created_at: '2027-01-01T10:00:00Z',
  },
]
const calendar = {
  eori: EORI,
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
  overlaps: [{ covered_from: '2027-01-10', covered_to: '2027-01-12', batch_ids: [BATCH] }],
  complete: false,
  unavailable_latest_days: null,
  dataset_version_ids: [],
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
    if (url.includes('/customs-data/coverage/scan')) {
      return json({ eoris_scanned: 1, gap_tasks_created: 1, month_tasks_created: 0 })
    }
    if (url.includes('/customs-data/coverage')) return json(calendar)
    if (url.includes('/customs-data/eoris')) return json(eoris)
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
  })
}

const serious = (violations: { impact?: string | null }[]) =>
  violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')

test('EORI register: renders, scan result and edit form pass axe', async ({ page, context }) => {
  await signIn(context)
  await page.goto(`/ops/t/${TENANT}/customs-data`)
  await expect(page.getByRole('link', { name: EORI })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Register an EORI' })).toBeVisible()
  await page.getByRole('button', { name: 'Check for gaps now' }).click()
  await expect(page.getByRole('status')).toContainText('New gap tasks: 1')
  await page.getByRole('button', { name: `Edit access / note for ${EORI}` }).click()
  await expect(page.getByText(/cannot be changed/)).toBeVisible()
  const { violations } = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag22aa'])
    .analyze()
  expect(serious(violations)).toEqual([])
})

test('EORI register: a bad EORI shows an error and passes axe', async ({ page, context }) => {
  await signIn(context)
  await page.goto(`/ops/t/${TENANT}/customs-data`)
  await page.getByLabel('EORI', { exact: true }).fill('FR1')
  await page.getByRole('button', { name: 'Register EORI' }).click()
  await expect(page.getByText('EORI must be GB or XI followed by 12 digits.')).toBeVisible()
  const { violations } = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag22aa'])
    .analyze()
  expect(serious(violations)).toEqual([])
})

test('coverage calendar: states have text labels and the page passes axe', async ({
  page,
  context,
}) => {
  await signIn(context)
  await page.goto(`/ops/t/${TENANT}/customs-data/${EORI}`)
  const periods = page.getByRole('table', { name: 'Coverage periods' })
  for (const label of ['Loaded', 'Loaded with errors', 'Gap', 'Not yet available']) {
    await expect(periods.getByText(label, { exact: true })).toBeVisible()
  }
  await expect(page.getByRole('link', { name: BATCH })).toBeVisible()
  const { violations } = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag22aa'])
    .analyze()
  expect(serious(violations)).toEqual([])
})
