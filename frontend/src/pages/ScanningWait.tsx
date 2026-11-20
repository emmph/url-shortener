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

  // Poll Redis-backed scan status until safe or removed
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
  const progressRatio = Math.min(0.92, Math.max(0.18, (100 - remSeconds * 4) / 100))

  return (
    <main className="liquid-stage flex items-center justify-center px-6 py-12">
      <div className="fixed right-4 top-4 z-20">
        <ThemeToggle variant="glass" />
      </div>

      <section className="liquid-glass-card w-full max-w-md p-6 text-center">
        <div
          className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-[10px] border"
          style={{ backgroundColor: 'var(--lg-pill-bg)', borderColor: 'var(--lg-pill-border)' }}
        >
          <ShieldCheck
            className="h-5 w-5"
            style={{ color: 'var(--lg-accent)' }}
            strokeWidth={1.5}
          />
        </div>

        {/* Signature monospace security readout */}
        <div
          className="liquid-mono mb-3 inline-flex items-center gap-2 rounded-[6px] border px-3 py-1 text-xs"
          style={{
            backgroundColor: 'var(--lg-pill-bg)',
            borderColor: 'var(--lg-pill-border)',
            color: 'var(--lg-muted)',
          }}
        >
          <span
            className="inline-block h-1.5 w-1.5 rounded-full"
            style={{ backgroundColor: 'var(--lg-status-warn)' }}
            aria-hidden="true"
          />
          <span>Scanning · TLS, CVE, SSRF</span>
        </div>

        <h1 className="text-xl font-medium tracking-tight" style={{ color: 'var(--lg-text)' }}>
          Security scan in progress
        </h1>

        <p className="mt-2 text-sm leading-6" style={{ color: 'var(--lg-secondary)' }}>
          This link opens once automated CVE and host safety checks finish. Estimated wait:{' '}
          <span className="liquid-mono font-medium" style={{ color: 'var(--lg-text)' }}>
            {etaText}
          </span>
          .
        </p>

        {/* GPU-composited scaleX bar avoids animating width */}
        <div className="mt-6 space-y-2">
          <div
            className="h-1.5 w-full overflow-hidden rounded-[4px]"
            style={{ backgroundColor: 'var(--lg-slider-track)' }}
          >
            <div
              className="h-full w-full origin-left rounded-[4px] transition-transform duration-300"
              style={{
                backgroundColor: 'var(--lg-accent)',
                transform: `scaleX(${progressRatio})`,
                transitionTimingFunction: 'cubic-bezier(0.22, 1, 0.36, 1)',
              }}
            />
          </div>
          <p className="liquid-mono text-xs" style={{ color: 'var(--lg-muted)' }}>
            {statusData?.stage ?? 'Checking TLS, headers, and known CVEs'}
          </p>
        </div>
      </section>
    </main>
  )
}
