import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { useState } from 'react'
import { Link, MemoryRouter, Route, Routes } from 'react-router'
import { TenantShell } from '@/ops/TenantShell'
import { ApiContext } from '@/shared/api/ApiContext'
import { createApi } from '@/shared/api/client'
import type { Me } from '@/shared/api/types'
import { AuthContext } from '@/shared/auth/AuthContext'
import { fakeAuth } from './renderApp'

function Page() {
  const [draft, setDraft] = useState('')
  return (
    <main>
      <label>
        Draft
        <input value={draft} onChange={(e) => setDraft(e.target.value)} />
      </label>
      <Link to="/ops/t/t2">Go to t2</Link>
    </main>
  )
}

/** The real TenantShell around a small stateful page, to prove state resets between clients. */
export function renderShellWithChild(me: Me) {
  const auth = fakeAuth()
  const api = createApi(
    () => auth.getAccessToken(),
    async () => new Response(JSON.stringify(me), { headers: { 'content-type': 'application/json' } }),
  )
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AuthContext.Provider value={auth}>
        <ApiContext.Provider value={api}>
          <MemoryRouter initialEntries={['/ops/t/t1']}>
            <Routes>
              <Route path="/ops/t/:tenantId" element={<TenantShell />}>
                <Route index element={<Page />} />
              </Route>
            </Routes>
          </MemoryRouter>
        </ApiContext.Provider>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}
