import AxeBuilder from '@axe-core/playwright'
import { expect, test, type BrowserContext } from '@playwright/test'

// Signed-in screens: a Supabase-style session is injected and the API is mocked, so these run
// without Supabase or the backend. The token is never verified in the browser.
const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString('base64url')

async function signInAsPlatformAdmin(context: BrowserContext) {
  const exp = Math.floor(Date.now() / 1000) + 3600
  const jwt = `${b64({ alg: 'ES256', typ: 'JWT' })}.${b64({ sub: 'u-admin', aal: 'aal2', exp, email: 'admin@example.test', aud: 'authenticated' })}.sig`
  const session = {
    access_token: jwt,
    refresh_token: 'r',
    token_type: 'bearer',
    expires_in: 3600,
    expires_at: exp,
    user: {
      id: 'u-admin',
      aud: 'authenticated',
      email: 'admin@example.test',
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
    const send = (body: unknown) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.endsWith('/me')) {
      return send({
        user_id: 'u-admin',
        platform_admin: true,
        domain_owner: true,
        memberships: [],
        mfa: { required: true, passed: true },
      })
    }
    if (url.endsWith('/platform/datasets')) {
      return send([
        { id: 'd1', name: 'cbam_commodity_codes', active_version: null, pending_versions: 1 },
      ])
    }
    if (url.endsWith('/platform/sources')) {
      return send([
        {
          id: 's1',
          source_id: 'HMRC-CBAM-GOODS-SCOPE',
          title: 'Check which goods are in scope',
          source_type: 'guidance',
          url: null,
          publication_date: '2026-07-16',
          status: 'draft',
          commencement_date: null,
          effective_from: null,
          effective_to: null,
          retrieved_at: null,
          notes: null,
          row_version: 1,
        },
      ])
    }
    if (url.endsWith('/platform/datasets/cbam_commodity_codes/versions')) {
      return send([
        {
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
        },
      ])
    }
    if (url.endsWith('/platform/tenants')) {
      return send([
        {
          id: 't1',
          name: 'Alpha Imports Ltd',
          status: 'active',
          row_version: 1,
          created_at: '2027-03-31T23:30:00Z',
        },
      ])
    }
    if (url.endsWith('/members')) {
      return send([
        {
          membership_id: 'm1',
          user_id: 'u1',
          email: 'jo@example.test',
          display_name: 'Jo Bloggs',
          roles: ['operations'],
          row_version: 1,
        },
      ])
    }
    return route.fulfill({ status: 404, body: '{}' })
  })
}

for (const [path, heading] of [
  ['/ops/platform', 'Clients'],
  ['/ops/platform/tenants/t1', 'Alpha Imports Ltd'],
  ['/ops/reference-data', 'Reference data'],
  ['/ops/reference-data/cbam_commodity_codes', 'cbam_commodity_codes'],
] as const) {
  test(`no serious axe violations on ${path}`, async ({ page, context }) => {
    await signInAsPlatformAdmin(context)
    await page.goto(path)
    await expect(page.getByRole('heading', { name: heading })).toBeVisible()
    const { violations } = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag22aa'])
      .analyze()
    expect(violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')).toEqual([])
  })
}
