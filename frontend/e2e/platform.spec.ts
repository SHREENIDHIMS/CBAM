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
        memberships: [],
        mfa: { required: true, passed: true },
      })
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
