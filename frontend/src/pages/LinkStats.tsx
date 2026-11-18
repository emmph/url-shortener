import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ArrowLeft } from 'lucide-react'
import { getPublicLinkStats } from '../api/client'
import { ThemeToggle } from '../components/ThemeToggle'

export default function LinkStats() {
  const { shortCode = '' } = useParams<{ shortCode: string }>()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['link-stats', shortCode],
    queryFn: () => getPublicLinkStats(shortCode),
    enabled: Boolean(shortCode),
  })

  if (isLoading) {
    return (
      <main className="ds-root flex items-center justify-center p-8">
        <div className="ds-card ds-text px-6 py-4 text-sm font-medium">Loading analytics...</div>
      </main>
    )
  }

  if (isError || !data) {
    return (
      <main className="ds-root flex items-center justify-center p-8">
        <div className="ds-card max-w-md p-6 text-center">
          <p className="text-sm font-semibold" style={{ color: 'var(--ds-danger-text)' }}>
            Analytics for "{shortCode}" are unavailable.
          </p>
          <Link to="/admin" className="ds-btn-secondary mt-4">
            Back to Admin
          </Link>
        </div>
      </main>
    )
  }

  const fullShortUrl = `${window.location.origin}/${data.short_code}`
  const cves = (data.scan_report?.cves as Array<Record<string, unknown>>) || []

  return (
    <main className="ds-root px-4 py-6 sm:px-8">
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="ds-divider flex flex-wrap items-center justify-between gap-4 border-b pb-4">
          <div>
            <Link
              to="/admin"
              className="ds-link mb-2 inline-flex items-center gap-1.5 text-xs font-semibold hover:underline"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to Admin Panel
            </Link>
            <h1 className="ds-text text-xl font-bold">
              Link Analytics: <span className="ds-link font-mono">/{data.short_code}</span>
            </h1>
            <p className="ds-muted mt-0.5 max-w-2xl truncate text-sm">{data.original_url}</p>
          </div>

          <div className="flex items-center gap-3">
            <ThemeToggle variant="ds" />
            <div className="ds-card flex items-center gap-3 p-3">
              <div className="rounded bg-white p-1">
                <QRCodeSVG value={fullShortUrl} size={60} />
              </div>
              <div className="text-xs">
                <div className="ds-text font-semibold">Link QR Code</div>
                <div className="ds-muted mt-1 font-mono">{fullShortUrl}</div>
              </div>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div className="ds-card p-4">
            <div className="ds-muted text-xs font-semibold">Total Clicks</div>
            <div className="ds-tabular ds-text mt-1 text-2xl font-bold">{data.clicks_count}</div>
          </div>
          <div className="ds-card p-4">
            <div className="ds-muted text-xs font-semibold">Unique Visitors (daily)</div>
            <div className="ds-tabular ds-text mt-1 text-2xl font-bold">{data.unique_clicks}</div>
          </div>
          <div className="ds-card p-4">
            <div className="ds-muted text-xs font-semibold">Click Limit</div>
            <div className="ds-tabular ds-text mt-1 text-2xl font-bold">
              {data.max_clicks !== null ? `${data.remaining_clicks ?? 0} / ${data.max_clicks}` : '∞'}
            </div>
          </div>
          <div className="ds-card p-4">
            <div className="ds-muted text-xs font-semibold">Security Status</div>
            <div className="mt-2 flex items-center gap-2">
              <span
                className={`ds-tag ${
                  data.scan_status === 'SAFE' ? 'ds-tag-success' : 'ds-tag-warning'
                }`}
              >
                {data.scan_status}
              </span>
              <span className="ds-tabular ds-muted text-xs font-semibold">
                Risk: {data.risk_score}/100
              </span>
            </div>
          </div>
        </div>

        <div className="grid gap-6 lg:grid-cols-3">
          <div className="ds-card p-5 lg:col-span-2">
            <h2 className="ds-text mb-4 text-sm font-bold">Daily Click Activity</h2>
            {data.timeseries.length === 0 ? (
              <p className="ds-muted py-12 text-center text-sm">No clicks recorded yet</p>
            ) : (
              <div className="h-64 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data.timeseries}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--ds-border)" />
                    <XAxis dataKey="bucket" tick={{ fontSize: 12, fill: 'var(--ds-text-muted)' }} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: 'var(--ds-text-muted)' }} />
                    <Tooltip />
                    <Bar dataKey="clicks" fill="var(--ds-accent)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          <div className="ds-card space-y-5 p-5">
            <div>
              <h3 className="ds-text mb-2 text-sm font-bold">Devices</h3>
              <ul className="space-y-1.5 text-sm">
                {data.devices.length === 0 && <li className="ds-muted">No data</li>}
                {data.devices.map((d) => (
                  <li key={d.label} className="flex justify-between">
                    <span className="ds-muted">{d.label}</span>
                    <span className="ds-tabular ds-text font-semibold">{d.count}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="ds-divider border-t pt-4">
              <h3 className="ds-text mb-2 text-sm font-bold">Browsers</h3>
              <ul className="space-y-1.5 text-sm">
                {data.browsers.length === 0 && <li className="ds-muted">No data</li>}
                {data.browsers.map((b) => (
                  <li key={b.label} className="flex justify-between">
                    <span className="ds-muted">{b.label}</span>
                    <span className="ds-tabular ds-text font-semibold">{b.count}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        <div className="ds-card p-5">
          <h2 className="ds-text mb-3 text-sm font-bold">Security Scan Report (CVE)</h2>
          <p className="ds-muted text-sm">
            {(data.scan_report?.reason as string) || 'Scan completed'}
          </p>
          {cves.length > 0 && (
            <div className="mt-3 overflow-x-auto">
              <table className="ds-table">
                <thead>
                  <tr>
                    <th>CVE ID</th>
                    <th>Software</th>
                    <th>Severity</th>
                    <th>CVSS</th>
                    <th>Summary</th>
                  </tr>
                </thead>
                <tbody>
                  {cves.map((c, idx) => (
                    <tr key={idx}>
                      <td className="font-mono font-semibold">{String(c.cve_id || '')}</td>
                      <td>{`${String(c.product || '')} ${String(c.version || '')}`}</td>
                      <td>
                        <span className="ds-tag ds-tag-info">{String(c.severity || 'LOW')}</span>
                      </td>
                      <td className="ds-tabular">{String(c.cvss ?? '')}</td>
                      <td className="ds-muted">{String(c.summary || '')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </main>
  )
}
