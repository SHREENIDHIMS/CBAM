import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import App from '@/App'
import { ApiContext } from '@/shared/api/ApiContext'
import { createApi } from '@/shared/api/client'
import type { Me } from '@/shared/api/types'
import { AuthContext, type AuthApi } from '@/shared/auth/AuthContext'

export function fakeAuth(overrides: Partial<AuthApi> = {}): AuthApi {
  return {
    status: 'signed_in',
    user: { id: 'u1', email: 'ops@example.test' },
    aal: 'aal2',
    getAccessToken: async () => 'token',
    signIn: vi.fn().mockResolvedValue(undefined),
    signOut: vi.fn().mockResolvedValue(undefined),
    requestPasswordReset: vi.fn().mockResolvedValue(undefined),
    updatePassword: vi.fn().mockResolvedValue(undefined),
    mfa: {
      listVerifiedFactors: vi.fn().mockResolvedValue([]),
      enrol: vi.fn().mockResolvedValue({
        factorId: 'f1',
        qrCodeDataUrl: 'data:image/svg+xml;utf-8,<svg/>',
        secret: 'ABC123',
      }),
      verify: vi.fn().mockResolvedValue(undefined),
    },
    ...overrides,
  }
}

export function me(overrides: Partial<Me> = {}): Me {
  return {
    user_id: 'u1',
    platform_admin: false,
    mfa: { required: false, passed: false },
    memberships: [
      {
        tenant_id: 't1',
        tenant_name: 'Alpha Ltd',
        roles: ['client_admin'],
        permissions: ['tasks:read'],
        mfa_required: false,
      },
    ],
    ...overrides,
  }
}

export function renderApp(route: string, options: { auth?: AuthApi; me?: Me } = {}) {
  const auth = options.auth ?? fakeAuth()
  const fetchImpl = vi.fn(async (url: string) => {
    if (url.endsWith('/me')) {
      return new Response(JSON.stringify(options.me ?? me()), {
        headers: { 'content-type': 'application/json' },
      })
    }
    return new Response('{}', { status: 404 })
  })
  const api = createApi(() => auth.getAccessToken(), fetchImpl)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={auth}>
        <ApiContext.Provider value={api}>
          <MemoryRouter initialEntries={[route]}>
            <App />
          </MemoryRouter>
        </ApiContext.Provider>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
  return { ...utils, auth, fetchImpl }
}
