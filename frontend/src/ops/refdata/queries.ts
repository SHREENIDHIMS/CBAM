import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useApi } from '@/shared/api/ApiContext'
import type { DatasetVersion, ImpactReport, RefDataset, RegulatorySource } from '@/shared/api/types'

const root = ['refdata'] as const
const versionsKey = (dataset: string) => [...root, 'versions', dataset] as const

export function useSources() {
  const api = useApi()
  return useQuery({
    queryKey: [...root, 'sources'],
    queryFn: () => api.get<RegulatorySource[]>('/platform/sources'),
  })
}

export function useDatasets() {
  const api = useApi()
  return useQuery({
    queryKey: [...root, 'datasets'],
    queryFn: () => api.get<RefDataset[]>('/platform/datasets'),
  })
}

export function useVersions(dataset: string) {
  const api = useApi()
  return useQuery({
    queryKey: versionsKey(dataset),
    queryFn: () => api.get<DatasetVersion[]>(`/platform/datasets/${dataset}/versions`),
  })
}

export function useVersion(dataset: string, version: string | null) {
  const api = useApi()
  return useQuery({
    queryKey: [...root, 'version', dataset, version],
    enabled: version !== null,
    queryFn: () =>
      api.get<DatasetVersion>(
        `/platform/datasets/${dataset}/versions/${encodeURIComponent(version ?? '')}`,
      ),
  })
}

function useRefresh() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: root })
}

export function useImpactReport(dataset: string) {
  const api = useApi()
  const refresh = useRefresh()
  return useMutation({
    mutationFn: (version: string) =>
      api.post<ImpactReport>(
        `/platform/datasets/${dataset}/versions/${encodeURIComponent(version)}/impact`,
        {},
      ),
    onSettled: refresh,
  })
}

export function useActivate(dataset: string) {
  const api = useApi()
  const refresh = useRefresh()
  return useMutation({
    mutationFn: (input: { version: DatasetVersion; reason: string; acknowledge: boolean }) =>
      api.post<DatasetVersion>(
        `/platform/datasets/${dataset}/versions/${encodeURIComponent(input.version.version)}/activate`,
        { reason: input.reason, acknowledge_warnings: input.acknowledge },
        { rowVersion: input.version.row_version },
      ),
    onSettled: refresh,
  })
}
