import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode, useMemo, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import App from './App'
import './index.css'
import { ApiContext } from './shared/api/ApiContext'
import { createApi } from './shared/api/client'
import { useAuth } from './shared/auth/AuthContext'
import { SupabaseAuthProvider } from './shared/auth/SupabaseAuthProvider'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

function ApiProvider({ children }: { children: ReactNode }) {
  const auth = useAuth()
  const api = useMemo(() => createApi(() => auth.getAccessToken()), [auth])
  return <ApiContext.Provider value={api}>{children}</ApiContext.Provider>
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <SupabaseAuthProvider>
        <ApiProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </ApiProvider>
      </SupabaseAuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
