import { useQuery } from '@tanstack/react-query'
import { useApi } from './ApiContext'
import type { Me } from './types'

export function useMe(enabled = true) {
  const api = useApi()
  return useQuery({
    queryKey: ['me'],
    queryFn: () => api.get<Me>('/me'),
    enabled,
    staleTime: 30_000,
  })
}
