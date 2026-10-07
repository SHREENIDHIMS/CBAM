import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useApi } from '@/shared/api/ApiContext'
import {
  ALL_STATUSES,
  FINAL_STATUSES,
  type ExceptionFilters,
  type ImportBatch,
  type ImportLine,
  type ImportLineDetail,
  type Page,
  type RowException,
} from './types'

const DETAIL_POLL_MS = 3000
const LIST_POLL_MS = 5000
const enc = encodeURIComponent

/** Only a known, non-final status keeps polling; an unknown status counts as final. */
const LIVE: readonly string[] = ALL_STATUSES.filter((s) => !FINAL_STATUSES.includes(s))
export const isLive = (status: string): boolean => LIVE.includes(status)

export function qs(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) if (value) search.set(key, value)
  const text = search.toString()
  return text ? `?${text}` : ''
}

/** Refreshes every 5 seconds while any listed batch is still processing. */
export function useImportBatches(tenantId: string, status: string) {
  const api = useApi()
  return useInfiniteQuery({
    queryKey: ['imports', tenantId, 'batches', status],
    queryFn: ({ pageParam }) =>
      api.get<Page<ImportBatch>>(
        `/tenants/${enc(tenantId)}/import-batches${qs({ status, cursor: pageParam })}`,
      ),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data?.pages.some((p) => p.items.some((b) => isLive(b.status)))
        ? LIST_POLL_MS
        : false,
  })
}

/** Refreshes every 3 seconds until the batch reaches a final status (or the first fetch failed). */
export function useImportBatch(tenantId: string, batchId: string) {
  const api = useApi()
  return useQuery({
    queryKey: ['imports', tenantId, 'batch', batchId],
    queryFn: () =>
      api.get<ImportBatch>(`/tenants/${enc(tenantId)}/import-batches/${enc(batchId)}`),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && isLive(status) ? DETAIL_POLL_MS : false
    },
  })
}

/** `live` is true while the batch is processing: the list refreshes with it, and the final
 * state is part of the key so one more fetch happens when the batch finishes. */
export function useBatchExceptions(
  tenantId: string,
  batchId: string,
  filters: ExceptionFilters,
  live: boolean,
) {
  const api = useApi()
  return useInfiniteQuery({
    queryKey: ['imports', tenantId, 'exceptions', batchId, filters, live],
    queryFn: ({ pageParam }) =>
      api.get<Page<RowException>>(
        `/tenants/${enc(tenantId)}/import-batches/${enc(batchId)}/exceptions${qs({ ...filters, cursor: pageParam })}`,
      ),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    placeholderData: keepPreviousData,
    refetchInterval: live ? DETAIL_POLL_MS : false,
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
    `/tenants/${enc(tenantId)}/import-batches/${enc(batchId)}/exceptions${qs({ ...filters, format: 'csv' })}`,
    'text/csv',
  )
}

export function useImportLines(
  tenantId: string,
  params: Record<string, string>,
  enabled: boolean,
) {
  const api = useApi()
  return useInfiniteQuery({
    queryKey: ['imports', tenantId, 'lines', params],
    enabled,
    queryFn: ({ pageParam }) =>
      api.get<Page<ImportLine>>(
        `/tenants/${enc(tenantId)}/import-lines${qs({ ...params, cursor: pageParam })}`,
      ),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    placeholderData: keepPreviousData,
  })
}

export function useImportLine(tenantId: string, lineId: string) {
  const api = useApi()
  return useQuery({
    queryKey: ['imports', tenantId, 'line', lineId],
    queryFn: () =>
      api.get<ImportLineDetail>(`/tenants/${enc(tenantId)}/import-lines/${enc(lineId)}`),
  })
}
