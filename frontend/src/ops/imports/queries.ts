import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useApi } from '@/shared/api/ApiContext'
import {
  FINAL_STATUSES,
  type ExceptionFilters,
  type ImportBatch,
  type Page,
  type RowException,
} from './types'

const POLL_MS = 3000

function qs(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) if (value) search.set(key, value)
  const text = search.toString()
  return text ? `?${text}` : ''
}

export function useImportBatches(tenantId: string, status: string) {
  const api = useApi()
  return useInfiniteQuery({
    queryKey: ['imports', tenantId, 'batches', status],
    queryFn: ({ pageParam }) =>
      api.get<Page<ImportBatch>>(
        `/tenants/${tenantId}/import-batches${qs({ status, cursor: pageParam })}`,
      ),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
}

/** Refreshes every 3 seconds until the batch reaches a final status. */
export function useImportBatch(tenantId: string, batchId: string) {
  const api = useApi()
  return useQuery({
    queryKey: ['imports', tenantId, 'batch', batchId],
    queryFn: () => api.get<ImportBatch>(`/tenants/${tenantId}/import-batches/${batchId}`),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && FINAL_STATUSES.includes(status) ? false : POLL_MS
    },
  })
}

export function useBatchExceptions(tenantId: string, batchId: string, filters: ExceptionFilters) {
  const api = useApi()
  return useInfiniteQuery({
    queryKey: ['imports', tenantId, 'exceptions', batchId, filters],
    queryFn: ({ pageParam }) =>
      api.get<Page<RowException>>(
        `/tenants/${tenantId}/import-batches/${batchId}/exceptions${qs({ ...filters, cursor: pageParam })}`,
      ),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
}

/** The server-built CSV, fetched with the bearer token. The content is not altered. */
export function fetchExceptionsCsv(
  api: ReturnType<typeof useApi>,
  tenantId: string,
  batchId: string,
  filters: ExceptionFilters,
): Promise<string> {
  return api.getText(
    `/tenants/${tenantId}/import-batches/${batchId}/exceptions${qs({ ...filters, format: 'csv' })}`,
    'text/csv',
  )
}
