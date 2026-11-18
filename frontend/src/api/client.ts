import axios from 'axios'
import type {
  AdminLinkDetailStatsResponse,
  AdminLinkItem,
  AdminLinksListResponse,
  AdminOverviewResponse,
  AdminSessionResponse,
  BlockedUrlsListResponse,
  LinkCreateResponse,
  LinkStatsResponse,
  MaintenanceResponse,
  ScanStatusResponse,
  ServiceSettings,
} from '../types'

export const api = axios.create({
  baseURL: '/api/v1',
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
})

export async function createShortLink(payload: {
  original_url: string
  max_clicks: number | null
}): Promise<LinkCreateResponse> {
  const { data } = await api.post<LinkCreateResponse>('/links', payload)
  return data
}

export async function getScanStatus(shortCode: string): Promise<ScanStatusResponse> {
  const { data } = await api.get<ScanStatusResponse>(`/links/${shortCode}/scan-status`)
  return data
}

export async function getPublicLinkStats(shortCode: string): Promise<LinkStatsResponse> {
  const { data } = await api.get<LinkStatsResponse>(`/links/${shortCode}/stats`)
  return data
}

export async function adminLogin(username: string, password: string): Promise<AdminSessionResponse> {
  const { data } = await api.post<AdminSessionResponse>('/admin/login', { username, password })
  return data
}

export async function adminLogout(): Promise<void> {
  await api.post('/admin/logout')
}

export async function getAdminSession(): Promise<AdminSessionResponse> {
  const { data } = await api.get<AdminSessionResponse>('/admin/session')
  return data
}

export async function getAdminOverview(refresh = false): Promise<AdminOverviewResponse> {
  const { data } = await api.get<AdminOverviewResponse>('/admin/overview', {
    params: { refresh },
  })
  return data
}

export async function getAdminLinks(params: {
  page?: number
  limit?: number
  search?: string
  filter?: string
  scan_filter?: string
}): Promise<AdminLinksListResponse> {
  const { data } = await api.get<AdminLinksListResponse>('/admin/links', { params })
  return data
}

export async function getAdminLinkDetail(shortCode: string): Promise<AdminLinkDetailStatsResponse> {
  const { data } = await api.get<AdminLinkDetailStatsResponse>(`/admin/links/${shortCode}/stats`)
  return data
}

export async function updateAdminLink(
  shortCode: string,
  payload: {
    is_active?: boolean
    max_clicks?: number
    clear_max_clicks?: boolean
    reset_clicks?: boolean
    scan_status?: 'PENDING' | 'SCANNING' | 'SAFE'
  }
): Promise<AdminLinkItem> {
  const { data } = await api.patch<AdminLinkItem>(`/admin/links/${shortCode}`, payload)
  return data
}

export async function rescanAdminLink(shortCode: string): Promise<MaintenanceResponse> {
  const { data } = await api.post<MaintenanceResponse>(`/admin/links/${shortCode}/rescan`)
  return data
}

export async function deleteAdminLink(shortCode: string): Promise<MaintenanceResponse> {
  const { data } = await api.delete<MaintenanceResponse>(`/admin/links/${shortCode}`)
  return data
}

export async function getBlockedUrls(): Promise<BlockedUrlsListResponse> {
  const { data } = await api.get<BlockedUrlsListResponse>('/admin/blocked-urls')
  return data
}

export async function unblockUrl(id: number): Promise<MaintenanceResponse> {
  const { data } = await api.delete<MaintenanceResponse>(`/admin/blocked-urls/${id}`)
  return data
}

export async function getAdminSettings(): Promise<ServiceSettings> {
  const { data } = await api.get<ServiceSettings>('/admin/settings')
  return data
}

export async function updateAdminSettings(payload: ServiceSettings): Promise<ServiceSettings> {
  const { data } = await api.put<ServiceSettings>('/admin/settings', payload)
  return data
}

export async function cleanupLinks(): Promise<MaintenanceResponse> {
  const { data } = await api.post<MaintenanceResponse>('/admin/maintenance/cleanup')
  return data
}

export async function flushRedisCache(): Promise<MaintenanceResponse> {
  const { data } = await api.post<MaintenanceResponse>('/admin/maintenance/flush-cache')
  return data
}
