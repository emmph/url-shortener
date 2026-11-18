export interface ApiErrorPayload {
  error_code: number
  reason: string
  detail: string
  error_url: string
}

export interface LinkCreateResponse {
  short_code: string
  short_url: string
  original_url: string
  max_clicks: number | null
  scan_status: 'PENDING' | 'SCANNING' | 'SAFE'
  estimated_wait_seconds: number
  expires_at: string | null
  created_at: string
}

export interface ScanStatusResponse {
  short_code: string
  scan_status: 'PENDING' | 'SCANNING' | 'SAFE' | 'REMOVED_UNSAFE'
  risk_score: number
  estimated_remaining_seconds: number
  estimated_remaining_minutes_text: string
  stage: string
  target_url?: string | null
  error_url?: string | null
}

export interface CountBucket {
  label: string
  count: number
}

export interface TimeseriesPoint {
  bucket: string
  clicks: number
}

export interface LinkStatsResponse {
  short_code: string
  original_url: string
  clicks_count: number
  unique_clicks: number
  max_clicks: number | null
  remaining_clicks: number | null
  is_active: boolean
  scan_status: string
  risk_score: number
  scan_report?: Record<string, unknown> | null
  created_at: string
  expires_at: string | null
  timeseries: TimeseriesPoint[]
  devices: CountBucket[]
  browsers: CountBucket[]
  referers: CountBucket[]
}

export interface RecentClickItem {
  clicked_at: string
  device_type: string
  browser: string
  referer: string | null
  ip_hash: string
}

export interface AdminLinkDetailStatsResponse extends LinkStatsResponse {
  recent_clicks: RecentClickItem[]
}

export interface AdminSessionResponse {
  authenticated: boolean
  username: string
}

export interface TopLinkItem {
  short_code: string
  original_url: string
  clicks_count: number
  max_clicks: number | null
  is_active: boolean
  scan_status: string
}

export interface AdminOverviewResponse {
  total_links: number
  active_links: number
  limited_links: number
  one_time_links: number
  exhausted_links: number
  pending_scan_links: number
  blocked_urls_count: number
  total_clicks: number
  clicks_24h: number
  clicks_7d: number
  unique_visitors_total: number
  timeseries_7d: TimeseriesPoint[]
  top_links: TopLinkItem[]
  devices: CountBucket[]
  browsers: CountBucket[]
  referers: CountBucket[]
  infra: {
    uptime_seconds: number
    scan_queue_depth: number
    analytics_buffer_depth: number
    redis: {
      mode: string
      connected: boolean
      keys: number
      used_memory_human: string
    }
  }
}

export interface AdminLinkItem {
  id: number
  short_code: string
  original_url: string
  max_clicks: number | null
  clicks_count: number
  is_active: boolean
  scan_status: string
  risk_score: number
  scan_report?: Record<string, unknown> | null
  expires_at: string | null
  created_at: string
}

export interface AdminLinksListResponse {
  total: number
  page: number
  limit: number
  items: AdminLinkItem[]
}

export interface BlockedUrlItem {
  id: number
  url_hash: string
  original_url: string
  domain: string
  reason: string
  max_cvss: number | null
  max_severity: string
  scan_report?: Record<string, unknown> | null
  blocked_at: string
}

export interface BlockedUrlsListResponse {
  total: number
  items: BlockedUrlItem[]
}

export interface ServiceSettings {
  allow_public_creation: boolean
  rate_limit_create_per_min: number
  default_max_clicks: number | null
  blocked_domains: string[]
  enable_security_scan: boolean
  min_block_cvss: number
  estimated_scan_seconds: number
}

export interface MaintenanceResponse {
  status: string
  affected_count: number
  detail: string
}
