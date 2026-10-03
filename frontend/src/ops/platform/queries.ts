import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useApi } from '@/shared/api/ApiContext'
import type { Member, Tenant } from '@/shared/api/types'

const tenantsKey = ['platform', 'tenants'] as const
const membersKey = (tenantId: string) => ['platform', 'members', tenantId] as const

export function useTenants() {
  const api = useApi()
  return useQuery({ queryKey: tenantsKey, queryFn: () => api.get<Tenant[]>('/platform/tenants') })
}

export function useCreateTenant() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => api.post<Tenant>('/platform/tenants', { name }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: tenantsKey }),
  })
}

export function useChangeTenantStatus(tenant: Tenant) {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { status: Tenant['status']; reason: string }) =>
      api.patch<Tenant>(`/platform/tenants/${tenant.id}`, input, {
        rowVersion: tenant.row_version,
      }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: tenantsKey }),
  })
}

export function useMembers(tenantId: string) {
  const api = useApi()
  return useQuery({
    queryKey: membersKey(tenantId),
    queryFn: () => api.get<Member[]>(`/platform/tenants/${tenantId}/members`),
  })
}

export function useInvite(tenantId: string) {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { email: string; roles: string[]; display_name: string | null }) =>
      api.post<Member>(`/platform/tenants/${tenantId}/invitations`, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: membersKey(tenantId) }),
  })
}

export function useSetRoles(tenantId: string, member: Member) {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (roles: string[]) =>
      api.patch<Member>(
        `/platform/tenants/${tenantId}/members/${member.user_id}`,
        { roles },
        { rowVersion: member.row_version },
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: membersKey(tenantId) }),
  })
}

export function useRemoveMember(tenantId: string) {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => api.delete(`/platform/tenants/${tenantId}/members/${userId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: membersKey(tenantId) }),
  })
}
