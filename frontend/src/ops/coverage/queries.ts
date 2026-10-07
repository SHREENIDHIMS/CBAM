import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useApi } from '@/shared/api/ApiContext'
import { qs } from '../imports/queries'
import type { Calendar, Eori, ReportType, ScanResult, ThirdPartyAccess } from './types'

const enc = encodeURIComponent
const base = (tenantId: string) => `/tenants/${enc(tenantId)}/customs-data`
const erisKey = (tenantId: string) => ['coverage', tenantId, 'eoris'] as const

export function useEoris(tenantId: string) {
  const api = useApi()
  return useQuery({
    queryKey: erisKey(tenantId),
    queryFn: () => api.get<Eori[]>(`${base(tenantId)}/eoris`),
  })
}

export function useRegisterEori(tenantId: string) {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: {
      eori: string
      tracking_from: string
      third_party_access: ThirdPartyAccess
      note: string | null
    }) => api.post<Eori>(`${base(tenantId)}/eoris`, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: erisKey(tenantId) }),
  })
}

/** PATCH with If-Match from the row version. Reloads the register either way. */
export function useUpdateEori(tenantId: string, row: Eori) {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { third_party_access?: ThirdPartyAccess; note?: string | null }) =>
      api.patch<Eori>(`${base(tenantId)}/eoris/${enc(row.id)}`, input, {
        rowVersion: row.row_version,
      }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: erisKey(tenantId) }),
  })
}

export function useScan(tenantId: string) {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<ScanResult>(`${base(tenantId)}/coverage/scan`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tasks'] }),
  })
}

/** No placeholder data: switching report type or range shows Loading, never the old calendar. */
export function useCalendar(
  tenantId: string,
  p: { eori: string; reportType: ReportType; from: string; to: string },
  enabled: boolean,
) {
  const api = useApi()
  return useQuery({
    queryKey: ['coverage', tenantId, 'calendar', p],
    enabled,
    retry: false,
    queryFn: () =>
      api.get<Calendar>(
        `${base(tenantId)}/coverage${qs({ eori: p.eori, report_type: p.reportType, from: p.from, to: p.to })}`,
      ),
  })
}
