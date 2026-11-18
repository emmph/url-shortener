import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  Activity,
  BarChart3,
  Link2,
  LogOut,
  RefreshCw,
  Settings as SettingsIcon,
  ShieldAlert,
  Trash2,
} from 'lucide-react'
import {
  adminLogout,
  cleanupLinks,
  deleteAdminLink,
  flushRedisCache,
  getAdminLinks,
  getAdminOverview,
  getAdminSettings,
  getBlockedUrls,
  rescanAdminLink,
  unblockUrl,
  updateAdminLink,
  updateAdminSettings,
} from '../api/client'
import { ThemeToggle } from '../components/ThemeToggle'
import type { AdminLinkItem, ServiceSettings } from '../types'

type AdminTab = 'overview' | 'links' | 'blocked' | 'settings'

export default function AdminDashboard() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<AdminTab>('overview')
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all')
  const [page, setPage] = useState(1)
  const [notice, setNotice] = useState<string | null>(null)
  const [editingLimitCode, setEditingLimitCode] = useState<string | null>(null)
  const [editingLimitVal, setEditingLimitVal] = useState<number>(1)

  const overviewQuery = useQuery({
    queryKey: ['admin-overview'],
    queryFn: () => getAdminOverview(true),
    enabled: tab === 'overview',
  })

  const linksQuery = useQuery({
    queryKey: ['admin-links', page, search, filter],
    queryFn: () => getAdminLinks({ page, limit: 15, search: search || undefined, filter }),
    enabled: tab === 'links',
  })

  const blockedQuery = useQuery({
    queryKey: ['admin-blocked-urls'],
    queryFn: getBlockedUrls,
    enabled: tab === 'blocked',
  })

  const settingsQuery = useQuery({
    queryKey: ['admin-settings'],
    queryFn: getAdminSettings,
    enabled: tab === 'settings',
  })

  const [draftSettings, setDraftSettings] = useState<ServiceSettings | null>(null)
  const activeSettings = draftSettings ?? settingsQuery.data

  // Show temporary status banner
  const flashNotice = (msg: string) => {
    setNotice(msg)
    setTimeout(() => setNotice(null), 4000)
  }

  // Refresh all admin views after any change
  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['admin-overview'] })
    queryClient.invalidateQueries({ queryKey: ['admin-links'] })
    queryClient.invalidateQueries({ queryKey: ['admin-blocked-urls'] })
    queryClient.invalidateQueries({ queryKey: ['admin-settings'] })
  }

  const toggleLinkMutation = useMutation({
    mutationFn: (item: AdminLinkItem) =>
      updateAdminLink(item.short_code, { is_active: !item.is_active }),
    onSuccess: () => {
      invalidateAll()
      flashNotice('Link status updated')
    },
  })

  const saveLimitMutation = useMutation({
    mutationFn: ({ code, limit }: { code: string; limit: number }) =>
      updateAdminLink(code, { max_clicks: Math.min(250, Math.max(1, limit)) }),
    onSuccess: () => {
      setEditingLimitCode(null)
      invalidateAll()
      flashNotice('Click limit updated')
    },
  })

  const rescanMutation = useMutation({
    mutationFn: (code: string) => rescanAdminLink(code),
    onSuccess: (res) => {
      invalidateAll()
      flashNotice(res.detail)
    },
  })

  const deleteLinkMutation = useMutation({
    mutationFn: (code: string) => deleteAdminLink(code),
    onSuccess: (res) => {
      invalidateAll()
      flashNotice(res.detail)
    },
  })

  const unblockMutation = useMutation({
    mutationFn: (id: number) => unblockUrl(id),
    onSuccess: (res) => {
      invalidateAll()
      flashNotice(res.detail)
    },
  })

  const saveSettingsMutation = useMutation({
    mutationFn: (payload: ServiceSettings) => updateAdminSettings(payload),
    onSuccess: (updated) => {
      setDraftSettings(updated)
      invalidateAll()
      flashNotice('Service settings saved')
    },
  })

  const handleLogout = async () => {
    await adminLogout()
    navigate('/admin/login', { replace: true })
  }

  return (
    <div className="ds-root">
      {/* Top navigation header */}
      <header className="ds-header">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded bg-[#0062ba] text-white font-bold">
              URL
            </div>
            <div>
              <h1 className="ds-text text-base font-bold">URL Shortener Admin</h1>
              <p className="ds-muted text-xs">
                Global analytics, CVE security, and service configuration
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <ThemeToggle variant="ds" />
            <Link to="/" className="ds-btn-secondary">
              Public Page
            </Link>
            <button type="button" onClick={invalidateAll} className="ds-btn-secondary">
              <RefreshCw className="h-4 w-4" />
              Refresh
            </button>
            <button type="button" onClick={handleLogout} className="ds-btn-danger">
              <LogOut className="h-4 w-4" />
              Sign out
            </button>
          </div>
        </div>

        {/* Section tabs */}
        <nav className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 sm:px-6" aria-label="Admin sections">
          {[
            { id: 'overview' as const, label: 'Overview', icon: BarChart3 },
            { id: 'links' as const, label: 'Links', icon: Link2 },
            { id: 'blocked' as const, label: 'Blocked URLs (CVE)', icon: ShieldAlert },
            { id: 'settings' as const, label: 'Settings & Maintenance', icon: SettingsIcon },
          ].map((item) => {
            const Icon = item.icon
            const active = tab === item.id
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setTab(item.id)}
                className="inline-flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-semibold whitespace-nowrap cursor-pointer"
                style={{
                  borderColor: active ? 'var(--ds-accent)' : 'transparent',
                  color: active ? 'var(--ds-accent)' : 'var(--ds-text-muted)',
                }}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </button>
            )
          })}
        </nav>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        {notice && (
          <div role="status" className="ds-alert-success mb-5 px-4 py-3 text-sm font-semibold">
            {notice}
          </div>
        )}

        {/* TAB 1: OVERVIEW */}
        {tab === 'overview' && (
          <div className="space-y-6">
            {overviewQuery.isLoading || !overviewQuery.data ? (
              <div className="ds-card ds-text p-6 text-sm">Loading global overview...</div>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <div className="ds-card p-4">
                    <div className="ds-muted text-xs font-semibold">Total Links</div>
                    <div className="ds-tabular ds-text mt-1 text-2xl font-bold">
                      {overviewQuery.data.total_links}
                    </div>
                    <div className="ds-muted mt-1 text-xs">
                      Active: {overviewQuery.data.active_links}
                    </div>
                  </div>
                  <div className="ds-card p-4">
                    <div className="ds-muted text-xs font-semibold">Limited / One-Time</div>
                    <div className="ds-tabular ds-text mt-1 text-2xl font-bold">
                      {overviewQuery.data.limited_links}
                    </div>
                    <div className="ds-muted mt-1 text-xs">
                      One-time: {overviewQuery.data.one_time_links} | Exhausted:{' '}
                      {overviewQuery.data.exhausted_links}
                    </div>
                  </div>
                  <div className="ds-card p-4">
                    <div className="ds-muted text-xs font-semibold">Total Clicks</div>
                    <div className="ds-tabular ds-link mt-1 text-2xl font-bold">
                      {overviewQuery.data.total_clicks}
                    </div>
                    <div className="ds-muted mt-1 text-xs">
                      24h: {overviewQuery.data.clicks_24h} | Unique:{' '}
                      {overviewQuery.data.unique_visitors_total}
                    </div>
                  </div>
                  <div className="ds-card p-4">
                    <div className="ds-muted text-xs font-semibold">Blocked by CVE</div>
                    <div
                      className="ds-tabular mt-1 text-2xl font-bold"
                      style={{ color: 'var(--ds-danger-text)' }}
                    >
                      {overviewQuery.data.blocked_urls_count}
                    </div>
                    <div className="ds-muted mt-1 text-xs">
                      Pending scan: {overviewQuery.data.pending_scan_links}
                    </div>
                  </div>
                </div>

                <div className="grid gap-6 lg:grid-cols-3">
                  <div className="ds-card p-5 lg:col-span-2">
                    <h2 className="ds-text mb-4 text-sm font-bold">Clicks (Last 7 Days)</h2>
                    {overviewQuery.data.timeseries_7d.length === 0 ? (
                      <p className="ds-muted py-12 text-center text-sm">Not enough click data yet</p>
                    ) : (
                      <div className="h-64 w-full">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart data={overviewQuery.data.timeseries_7d}>
                            <CartesianGrid strokeDasharray="3 3" stroke="var(--ds-border)" />
                            <XAxis
                              dataKey="bucket"
                              tick={{ fontSize: 12, fill: 'var(--ds-text-muted)' }}
                            />
                            <YAxis
                              allowDecimals={false}
                              tick={{ fontSize: 12, fill: 'var(--ds-text-muted)' }}
                            />
                            <Tooltip />
                            <Bar dataKey="clicks" fill="var(--ds-accent)" radius={[4, 4, 0, 0]} />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                  </div>

                  <div className="ds-card space-y-4 p-5">
                    <div className="ds-divider flex items-center gap-2 border-b pb-2">
                      <Activity className="ds-link h-4 w-4" />
                      <h2 className="ds-text text-sm font-bold">Infrastructure Status</h2>
                    </div>
                    <dl className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <dt className="ds-muted">Redis mode</dt>
                        <dd className="ds-text font-mono text-xs font-semibold">
                          {overviewQuery.data.infra.redis.mode}
                        </dd>
                      </div>
                      <div className="flex justify-between">
                        <dt className="ds-muted">Redis keys</dt>
                        <dd className="ds-tabular ds-text font-semibold">
                          {overviewQuery.data.infra.redis.keys}
                        </dd>
                      </div>
                      <div className="flex justify-between">
                        <dt className="ds-muted">Redis memory</dt>
                        <dd className="ds-text font-mono text-xs font-semibold">
                          {overviewQuery.data.infra.redis.used_memory_human}
                        </dd>
                      </div>
                      <div className="flex justify-between">
                        <dt className="ds-muted">CVE scan queue</dt>
                        <dd className="ds-tabular ds-text font-semibold">
                          {overviewQuery.data.infra.scan_queue_depth}
                        </dd>
                      </div>
                      <div className="flex justify-between">
                        <dt className="ds-muted">Analytics buffer</dt>
                        <dd className="ds-tabular ds-text font-semibold">
                          {overviewQuery.data.infra.analytics_buffer_depth}
                        </dd>
                      </div>
                      <div className="flex justify-between">
                        <dt className="ds-muted">Uptime</dt>
                        <dd className="ds-tabular ds-text font-semibold">
                          {overviewQuery.data.infra.uptime_seconds}s
                        </dd>
                      </div>
                    </dl>
                  </div>
                </div>

                <div className="grid gap-6 lg:grid-cols-2">
                  <div className="ds-card p-5">
                    <h2 className="ds-text mb-3 text-sm font-bold">Top 10 Links</h2>
                    <div className="overflow-x-auto">
                      <table className="ds-table">
                        <thead>
                          <tr>
                            <th>Code</th>
                            <th>URL</th>
                            <th>Clicks</th>
                            <th>Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {overviewQuery.data.top_links.length === 0 && (
                            <tr>
                              <td colSpan={4} className="ds-muted text-center">
                                No links yet
                              </td>
                            </tr>
                          )}
                          {overviewQuery.data.top_links.map((item) => (
                            <tr key={item.short_code}>
                              <td>
                                <Link
                                  to={`/stats/${item.short_code}`}
                                  className="ds-link font-mono font-semibold hover:underline"
                                >
                                  /{item.short_code}
                                </Link>
                              </td>
                              <td className="ds-muted max-w-[240px] truncate">{item.original_url}</td>
                              <td className="ds-tabular ds-text font-semibold">
                                {item.clicks_count}
                                {item.max_clicks ? ` / ${item.max_clicks}` : ''}
                              </td>
                              <td>
                                <span
                                  className={`ds-tag ${
                                    item.is_active ? 'ds-tag-success' : 'ds-tag-neutral'
                                  }`}
                                >
                                  {item.is_active ? 'Active' : 'Disabled'}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  <div className="ds-card grid gap-4 p-5 sm:grid-cols-2">
                    <div>
                      <h3 className="ds-text mb-2 text-sm font-bold">Devices</h3>
                      <ul className="space-y-1.5 text-sm">
                        {overviewQuery.data.devices.length === 0 && (
                          <li className="ds-muted">No data</li>
                        )}
                        {overviewQuery.data.devices.map((d) => (
                          <li key={d.label} className="flex justify-between">
                            <span className="ds-muted">{d.label}</span>
                            <span className="ds-tabular ds-text font-semibold">{d.count}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <h3 className="ds-text mb-2 text-sm font-bold">Browsers</h3>
                      <ul className="space-y-1.5 text-sm">
                        {overviewQuery.data.browsers.length === 0 && (
                          <li className="ds-muted">No data</li>
                        )}
                        {overviewQuery.data.browsers.map((b) => (
                          <li key={b.label} className="flex justify-between">
                            <span className="ds-muted">{b.label}</span>
                            <span className="ds-tabular ds-text font-semibold">{b.count}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* TAB 2: LINKS MANAGEMENT */}
        {tab === 'links' && (
          <div className="ds-card space-y-4 p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-3">
                <input
                  type="search"
                  placeholder="Search by code or URL..."
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value)
                    setPage(1)
                  }}
                  className="ds-input w-64"
                />
                <select
                  value={filter}
                  onChange={(e) => {
                    setFilter(e.target.value)
                    setPage(1)
                  }}
                  className="ds-input w-48"
                >
                  <option value="all">All links</option>
                  <option value="active">Active</option>
                  <option value="limited">Limited</option>
                  <option value="one_time">One-time</option>
                  <option value="exhausted">Exhausted</option>
                  <option value="disabled">Disabled</option>
                </select>
              </div>
              <div className="ds-tabular ds-muted text-sm font-semibold">
                Found: {linksQuery.data?.total ?? 0}
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="ds-table">
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Target URL</th>
                    <th>Clicks / Limit</th>
                    <th>CVE Scan</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {linksQuery.data?.items.length === 0 && (
                    <tr>
                      <td colSpan={6} className="ds-muted py-8 text-center">
                        No links found
                      </td>
                    </tr>
                  )}
                  {linksQuery.data?.items.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <Link
                          to={`/stats/${item.short_code}`}
                          className="ds-link font-mono font-semibold hover:underline"
                        >
                          /{item.short_code}
                        </Link>
                      </td>
                      <td className="ds-muted max-w-[260px] truncate" title={item.original_url}>
                        {item.original_url}
                      </td>
                      <td className="ds-tabular">
                        {editingLimitCode === item.short_code ? (
                          <div className="flex items-center gap-1.5">
                            <input
                              type="number"
                              min={1}
                              max={250}
                              value={editingLimitVal}
                              onChange={(e) => setEditingLimitVal(Number(e.target.value))}
                              className="ds-input w-20 py-1 text-xs"
                            />
                            <button
                              type="button"
                              onClick={() =>
                                saveLimitMutation.mutate({
                                  code: item.short_code,
                                  limit: editingLimitVal,
                                })
                              }
                              className="ds-btn-primary px-2 py-1 text-xs"
                            >
                              Save
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            onClick={() => {
                              setEditingLimitCode(item.short_code)
                              setEditingLimitVal(item.max_clicks ?? 1)
                            }}
                            className="ds-text font-semibold hover:underline cursor-pointer"
                            title="Edit click limit (1..250)"
                          >
                            {item.clicks_count} / {item.max_clicks ?? '∞'}
                          </button>
                        )}
                      </td>
                      <td>
                        <span
                          className={`ds-tag ${
                            item.scan_status === 'SAFE' ? 'ds-tag-success' : 'ds-tag-warning'
                          }`}
                        >
                          {item.scan_status} ({item.risk_score})
                        </span>
                      </td>
                      <td>
                        <span
                          className={`ds-tag ${
                            item.is_active ? 'ds-tag-success' : 'ds-tag-neutral'
                          }`}
                        >
                          {item.is_active ? 'Active' : 'Disabled'}
                        </span>
                      </td>
                      <td>
                        {/* Fixed 3-column grid keeps Disable/Enable, Rescan, and Delete strictly aligned across rows */}
                        <div className="ds-actions-grid">
                          <button
                            type="button"
                            onClick={() => toggleLinkMutation.mutate(item)}
                            className="ds-btn-secondary ds-action-btn"
                          >
                            {item.is_active ? 'Disable' : 'Enable'}
                          </button>
                          <button
                            type="button"
                            onClick={() => rescanMutation.mutate(item.short_code)}
                            className="ds-btn-secondary ds-action-btn"
                          >
                            Rescan
                          </button>
                          <button
                            type="button"
                            onClick={() => deleteLinkMutation.mutate(item.short_code)}
                            className="ds-btn-danger ds-action-icon-btn"
                            aria-label={`Delete ${item.short_code}`}
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* TAB 3: BLOCKED URLS */}
        {tab === 'blocked' && (
          <div className="ds-card space-y-4 p-5">
            <div className="ds-divider flex items-center justify-between border-b pb-3">
              <div>
                <h2 className="ds-text text-base font-bold">Blocked URLs from CVE Scanner</h2>
                <p className="ds-muted text-xs">
                  Links rated MEDIUM, HIGH, or CRITICAL are deleted automatically and their URLs are
                  blocked from re-submission.
                </p>
              </div>
              <span className="ds-tag ds-tag-danger ds-tabular">
                Total: {blockedQuery.data?.total ?? 0}
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="ds-table">
                <thead>
                  <tr>
                    <th>Domain</th>
                    <th>Blocked URL</th>
                    <th>Severity / CVSS</th>
                    <th>Reason</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {blockedQuery.data?.items.length === 0 && (
                    <tr>
                      <td colSpan={5} className="ds-muted py-8 text-center">
                        No blocked URLs yet
                      </td>
                    </tr>
                  )}
                  {blockedQuery.data?.items.map((item) => (
                    <tr key={item.id}>
                      <td className="ds-text font-mono text-xs font-semibold">{item.domain}</td>
                      <td className="ds-muted max-w-[260px] truncate" title={item.original_url}>
                        {item.original_url}
                      </td>
                      <td>
                        <span className="ds-tag ds-tag-danger ds-tabular">
                          {item.max_severity} ({item.max_cvss ?? '-'})
                        </span>
                      </td>
                      <td className="ds-muted text-xs">{item.reason}</td>
                      <td>
                        <button
                          type="button"
                          onClick={() => unblockMutation.mutate(item.id)}
                          className="ds-btn-secondary px-2.5 py-1 text-xs"
                        >
                          Unblock
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* TAB 4: SETTINGS & MAINTENANCE */}
        {tab === 'settings' && activeSettings && (
          <div className="grid gap-6 lg:grid-cols-3">
            <form
              className="ds-card space-y-4 p-6 lg:col-span-2"
              onSubmit={(e) => {
                e.preventDefault()
                saveSettingsMutation.mutate(activeSettings)
              }}
            >
              <h2 className="ds-divider ds-text border-b pb-3 text-base font-bold">
                Dynamic Service Settings
              </h2>

              <label className="ds-divider flex items-center justify-between rounded border p-3 cursor-pointer">
                <div>
                  <div className="ds-text text-sm font-semibold">Allow public link creation</div>
                  <div className="ds-muted text-xs">
                    When disabled, public submissions return 503 Service Unavailable
                  </div>
                </div>
                <input
                  type="checkbox"
                  checked={activeSettings.allow_public_creation}
                  onChange={(e) =>
                    setDraftSettings({ ...activeSettings, allow_public_creation: e.target.checked })
                  }
                  className="h-5 w-5 accent-[#0062ba]"
                />
              </label>

              <label className="ds-divider flex items-center justify-between rounded border p-3 cursor-pointer">
                <div>
                  <div className="ds-text text-sm font-semibold">
                    Enable background CVE security scan
                  </div>
                  <div className="ds-muted text-xs">
                    New links are scanned before their first redirect is allowed
                  </div>
                </div>
                <input
                  type="checkbox"
                  checked={activeSettings.enable_security_scan}
                  onChange={(e) =>
                    setDraftSettings({ ...activeSettings, enable_security_scan: e.target.checked })
                  }
                  className="h-5 w-5 accent-[#0062ba]"
                />
              </label>

              {/* All 3 blocks use identical layout & height so nothing shifts */}
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <div className="flex flex-col justify-between gap-1.5">
                  <label htmlFor="set-rate" className="ds-text text-xs font-semibold leading-4">
                    Create limit / min (IP)
                  </label>
                  <input
                    id="set-rate"
                    type="number"
                    min={1}
                    max={10000}
                    value={activeSettings.rate_limit_create_per_min}
                    onChange={(e) =>
                      setDraftSettings({
                        ...activeSettings,
                        rate_limit_create_per_min: Number(e.target.value),
                      })
                    }
                    className="ds-input ds-tabular h-10"
                  />
                </div>

                <div className="flex flex-col justify-between gap-1.5">
                  <label htmlFor="set-cvss" className="ds-text text-xs font-semibold leading-4">
                    CVSS threshold (4.0+)
                  </label>
                  <input
                    id="set-cvss"
                    type="number"
                    step="0.1"
                    min={0}
                    max={10}
                    value={activeSettings.min_block_cvss}
                    onChange={(e) =>
                      setDraftSettings({
                        ...activeSettings,
                        min_block_cvss: Number(e.target.value),
                      })
                    }
                    className="ds-input ds-tabular h-10"
                  />
                </div>

                <div className="flex flex-col justify-between gap-1.5">
                  <label htmlFor="set-eta" className="ds-text text-xs font-semibold leading-4">
                    Est. scan time (sec)
                  </label>
                  <input
                    id="set-eta"
                    type="number"
                    min={5}
                    max={600}
                    value={activeSettings.estimated_scan_seconds}
                    onChange={(e) =>
                      setDraftSettings({
                        ...activeSettings,
                        estimated_scan_seconds: Number(e.target.value),
                      })
                    }
                    className="ds-input ds-tabular h-10"
                  />
                </div>
              </div>

              <div>
                <label htmlFor="set-domains" className="ds-text mb-1 block text-xs font-semibold">
                  Blocked domains (comma separated)
                </label>
                <input
                  id="set-domains"
                  type="text"
                  value={activeSettings.blocked_domains.join(', ')}
                  onChange={(e) =>
                    setDraftSettings({
                      ...activeSettings,
                      blocked_domains: e.target.value
                        .split(',')
                        .map((s) => s.trim())
                        .filter(Boolean),
                    })
                  }
                  placeholder="evil.com, phishing.example"
                  className="ds-input h-10"
                />
              </div>

              <button
                type="submit"
                disabled={saveSettingsMutation.isPending}
                className="ds-btn-primary"
              >
                {saveSettingsMutation.isPending ? 'Saving...' : 'Save Settings'}
              </button>
            </form>

            <div className="ds-card space-y-4 p-6">
              <h2 className="ds-divider ds-text border-b pb-3 text-base font-bold">
                System Maintenance
              </h2>
              <p className="ds-muted text-xs">
                Quick actions to clean stale database records or flush cached Redis entries.
              </p>

              <button
                type="button"
                onClick={async () => {
                  const res = await cleanupLinks()
                  invalidateAll()
                  flashNotice(res.detail)
                }}
                className="ds-btn-secondary w-full"
              >
                Clean up expired & exhausted links
              </button>

              <button
                type="button"
                onClick={async () => {
                  const res = await flushRedisCache()
                  invalidateAll()
                  flashNotice(res.detail)
                }}
                className="ds-btn-danger w-full py-2"
              >
                Flush Redis cache
              </button>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
