import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ShieldCheck } from 'lucide-react'
import { getScanStatus } from '../api/client'
import { ThemeToggle } from '../components/ThemeToggle'
import type { ScanStatusResponse } from '../types'

export default function ScanningWait() {
  const { shortCode } = useParams<{ shortCode: string }>()
  const navigate = useNavigate()
  const [statusData, setStatusData] = useState<ScanStatusResponse | null>(null)

  // Poll scan status until safe or removed
  useEffect(() => {
    if (!shortCode) {
      navigate('/error/410?reason=unavailable', { replace: true })
      return
    }

    let cancelled = false

    const poll = async () => {
      try {
        const res = await getScanStatus(shortCode)
        if (cancelled) return
        setStatusData(res)

        if (res.scan_status === 'SAFE') {
          window.location.replace(res.target_url || `/${shortCode}`)
          return
        }
        if (res.scan_status === 'REMOVED_UNSAFE') {
          navigate(res.error_url || '/error/410?reason=unavailable', { replace: true })
        }
      } catch {
        if (!cancelled) {
          navigate('/error/410?reason=unavailable', { replace: true })
        }
      }
    }

    poll()
    const timer = window.setInterval(poll, 1500)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [shortCode, navigate])

  const remSeconds = statusData?.estimated_remaining_seconds ?? 15
  const etaText = statusData?.estimated_remaining_minutes_text ?? 'about 15 sec'

  return (
    <main className="liquid-stage flex items-center justify-center px-4 py-12">
      <div className="liquid-orb liquid-orb-1" aria-hidden="true" />
      <div className="liquid-orb liquid-orb-2" aria-hidden="true" />

      <div className="fixed right-4 top-4 z-20">
        <ThemeToggle variant="glass" />
      </div>

      <section className="liquid-glass-card w-full max-w-md p-8 text-center">
        <div
          className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-xl border"
          style={{ background: 'var(--lg-pill-bg)', borderColor: 'var(--lg-pill-border)' }}
        >
          <ShieldCheck className="h-7 w-7 animate-pulse text-[#0062ba]" />
        </div>

        <h1 className="text-xl font-semibold tracking-tight" style={{ color: 'var(--lg-text)' }}>
          Security Scan in Progress
        </h1>

        <p className="mt-3 text-sm leading-relaxed" style={{ color: 'var(--lg-muted)' }}>
          This link is temporarily unavailable until our automated CVE and safety check finishes. It
          should be ready in <strong style={{ color: 'var(--lg-text)' }}>{etaText}</strong>.
        </p>

        <div className="mt-6">
          <div
            className="h-2 w-full overflow-hidden rounded-md"
            style={{ background: 'var(--lg-slider-track)' }}
          >
            <div
              className="h-full rounded-md bg-[#0062ba] transition-all duration-700"
              style={{ width: `${Math.min(92, Math.max(18, 100 - remSeconds * 4))}%` }}
            />
          </div>
          <p className="mt-2.5 text-xs" style={{ color: 'var(--lg-muted)' }}>
            {statusData?.stage ?? 'Checking TLS, headers, and known CVEs...'}
          </p>
        </div>
      </section>
    </main>
  )
}
