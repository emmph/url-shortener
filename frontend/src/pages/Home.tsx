import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { Check, ChevronDown, ChevronUp, Copy, Download, Link2, QrCode } from 'lucide-react'
import { QRCodeCanvas } from 'qrcode.react'
import { createShortLink } from '../api/client'
import { ThemeToggle } from '../components/ThemeToggle'
import type { ApiErrorPayload, LinkCreateResponse } from '../types'

type LinkMode = 'unlimited' | 'limited'

export default function Home() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<LinkMode>('unlimited')
  const [limitCount, setLimitCount] = useState<number>(1)
  const [urlInput, setUrlInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<LinkCreateResponse | null>(null)
  const [copied, setCopied] = useState(false)
  const [showQr, setShowQr] = useState(false)
  const qrCanvasRef = useRef<HTMLCanvasElement | null>(null)

  // Keep slider and number box synced within 1..250
  const handleLimitChange = (raw: number) => {
    if (Number.isNaN(raw)) {
      setLimitCount(1)
      return
    }
    setLimitCount(Math.min(250, Math.max(1, Math.round(raw))))
  }

  // Send link to API and route errors cleanly
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = urlInput.trim()
    if (!trimmed || loading) return

    setLoading(true)
    setCopied(false)
    setShowQr(false)
    try {
      const created = await createShortLink({
        original_url: trimmed,
        max_clicks: mode === 'unlimited' ? null : limitCount,
      })
      setResult(created)
    } catch (err) {
      if (axios.isAxiosError<ApiErrorPayload>(err)) {
        const status = err.response?.status ?? 500
        const errUrl = err.response?.data?.error_url
        if (errUrl) {
          navigate(errUrl)
          return
        }
        const reasonMap: Record<number, string> = {
          403: 'unsafe_url',
          410: 'unavailable',
          413: 'payload_too_large',
          422: 'invalid_url',
          429: 'rate_limit',
          503: 'maintenance',
        }
        navigate(`/error/${status}?reason=${reasonMap[status] ?? 'server_error'}`)
        return
      }
      navigate('/error/500?reason=server_error')
    } finally {
      setLoading(false)
    }
  }

  // One-click clipboard copy
  const handleCopy = async () => {
    if (!result) return
    try {
      await navigator.clipboard.writeText(result.short_url)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {
      // Clipboard blocked, ignore
    }
  }

  // Export QR code canvas as a crisp white-background JPG file
  const handleDownloadQr = () => {
    const sourceCanvas = qrCanvasRef.current
    if (!sourceCanvas || !result) return

    const exportCanvas = document.createElement('canvas')
    exportCanvas.width = 512
    exportCanvas.height = 512
    const ctx = exportCanvas.getContext('2d')
    if (!ctx) return

    // Paint pure white backdrop so JPEG stays crisp
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, exportCanvas.width, exportCanvas.height)
    ctx.imageSmoothingEnabled = false
    ctx.drawImage(sourceCanvas, 0, 0, exportCanvas.width, exportCanvas.height)

    const link = document.createElement('a')
    link.href = exportCanvas.toDataURL('image/jpeg', 0.95)
    link.download = `qr-${result.short_code}.jpg`
    link.click()
  }

  const isSafe = result?.scan_status === 'SAFE'
  const clickBudgetLabel = result
    ? result.max_clicks === null
      ? 'Unlimited'
      : `${result.max_clicks} ${result.max_clicks === 1 ? 'click' : 'clicks'}`
    : ''

  return (
    <main className="liquid-stage flex flex-col items-center justify-center px-6 py-12">
      {/* Corner theme toggle synced with OS preference by default */}
      <div className="fixed right-4 top-4 z-20">
        <ThemeToggle variant="glass" />
      </div>

      {/* Centered service intro spaced 32px above the main card */}
      <header className="mb-8 w-full max-w-[700px] space-y-2 text-center">
        <h1
          className="text-2xl font-medium tracking-tight sm:text-3xl"
          style={{ color: 'var(--lg-text)' }}
        >
          Fast, safe short links
        </h1>
        <p
          className="mx-auto max-w-[540px] text-sm leading-6 sm:text-base"
          style={{ color: 'var(--lg-secondary)' }}
        >
          Create permanent or click-limited links with instant QR codes. Every destination is
          screened for known vulnerabilities and malicious hosts in the background.
        </p>
      </header>

      {/* Main surface card (max-w-700px keeps URL input ~50% wider) */}
      <section className="liquid-glass-card w-full max-w-[700px] p-6">
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Centered mode switcher whose right edge aligns with the URL input edge (108px = 96px button + 12px gap) */}
          <div className="w-full space-y-3 sm:px-[108px]">
            <div className="liquid-segmented" role="tablist" aria-label="Link mode">
              <button
                type="button"
                role="tab"
                aria-selected={mode === 'unlimited'}
                data-active={mode === 'unlimited'}
                className="liquid-segmented-btn"
                onClick={() => setMode('unlimited')}
              >
                Unlimited
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mode === 'limited'}
                data-active={mode === 'limited'}
                className="liquid-segmented-btn"
                onClick={() => setMode('limited')}
              >
                Limited clicks
              </button>
            </div>

            {/* Slider + synced numeric input shown only in limited mode */}
            {mode === 'limited' && (
              <div className="liquid-glass-pill flex items-center gap-3 px-4 py-2">
                <span className="liquid-mono text-xs" style={{ color: 'var(--lg-muted)' }}>
                  Clicks
                </span>
                <input
                  type="range"
                  min={1}
                  max={250}
                  value={limitCount}
                  onChange={(e) => handleLimitChange(Number(e.target.value))}
                  aria-label="Click limit slider"
                  className="liquid-slider flex-1"
                />
                <input
                  type="number"
                  min={1}
                  max={250}
                  value={limitCount}
                  onChange={(e) => handleLimitChange(Number(e.target.value))}
                  aria-label="Custom click limit (1 to 250)"
                  className="liquid-input liquid-mono h-8 w-20 px-3 text-center text-sm font-medium tabular-nums"
                />
              </div>
            )}
          </div>

          {/* Wide URL field + fixed-width primary submit action */}
          <div className="flex flex-col gap-3 sm:flex-row">
            <div className="relative flex-1">
              <Link2
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2"
                style={{ color: 'var(--lg-muted)' }}
                strokeWidth={1.5}
                aria-hidden="true"
              />
              <input
                type="url"
                required
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                placeholder="https://example.com/path"
                aria-label="URL to shorten"
                className="liquid-input h-11 pl-9 pr-4 text-sm sm:text-base"
              />
            </div>
            <button
              type="submit"
              disabled={loading || !urlInput.trim()}
              className="liquid-button h-11 shrink-0 px-5 text-sm whitespace-nowrap sm:w-24 sm:px-0"
            >
              {loading ? 'Shortening' : 'Shorten'}
            </button>
          </div>
        </form>

        {/* Generated result row + expandable QR code block */}
        {result && (
          <div className="mt-6 space-y-3">
            <div className="liquid-glass-pill flex flex-col justify-between gap-3 p-3 sm:flex-row sm:items-center">
              <div className="min-w-0 space-y-1">
                <a
                  href={result.short_url}
                  className="liquid-mono block truncate text-sm font-medium underline underline-offset-4"
                  style={{ color: 'var(--lg-text)' }}
                >
                  {result.short_url}
                </a>
                {/* Signature monospace telemetry readout */}
                <div
                  className="liquid-mono flex items-center gap-2 text-xs"
                  style={{ color: 'var(--lg-muted)' }}
                >
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full"
                    style={{
                      backgroundColor: isSafe ? 'var(--lg-status-safe)' : 'var(--lg-status-warn)',
                    }}
                    aria-hidden="true"
                  />
                  <span>{isSafe ? 'Safe · CVE verified' : 'Pending · CVE scan'}</span>
                  <span aria-hidden="true">·</span>
                  <span>{clickBudgetLabel}</span>
                </div>
              </div>

              <div className="flex shrink-0 items-center gap-2">
                <button
                  type="button"
                  onClick={() => setShowQr((prev) => !prev)}
                  aria-expanded={showQr}
                  className="liquid-copy-btn inline-flex h-8 items-center gap-2 px-3 text-xs font-medium"
                >
                  <QrCode className="h-4 w-4 shrink-0" strokeWidth={1.5} />
                  <span>{showQr ? 'Hide QR code' : 'Show QR code'}</span>
                  {showQr ? (
                    <ChevronUp className="h-4 w-4 shrink-0" strokeWidth={1.5} />
                  ) : (
                    <ChevronDown className="h-4 w-4 shrink-0" strokeWidth={1.5} />
                  )}
                </button>
                <button
                  type="button"
                  onClick={handleCopy}
                  className="liquid-copy-btn inline-flex h-8 items-center gap-2 px-3 text-xs font-medium"
                >
                  {copied ? (
                    <>
                      <Check className="h-4 w-4 shrink-0" strokeWidth={1.5} />
                      <span>Copied</span>
                    </>
                  ) : (
                    <>
                      <Copy className="h-4 w-4 shrink-0" strokeWidth={1.5} />
                      <span>Copy</span>
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* Expandable optical QR moment inside the main card */}
            {showQr && (
              <div className="liquid-glass-pill flex flex-col items-center justify-between gap-4 p-4 sm:flex-row">
                <div className="flex items-center gap-4">
                  <div
                    className="rounded-[6px] border bg-white p-2"
                    style={{ borderColor: 'var(--lg-pill-border)' }}
                  >
                    <QRCodeCanvas
                      ref={qrCanvasRef}
                      value={result.short_url}
                      size={132}
                      level="M"
                      bgColor="#ffffff"
                      fgColor="#111827"
                      marginSize={2}
                    />
                  </div>
                  <div className="space-y-1 text-left">
                    <div
                      className="text-sm font-medium"
                      style={{ color: 'var(--lg-text)' }}
                    >
                      QR code ready
                    </div>
                    <div
                      className="text-xs leading-5"
                      style={{ color: 'var(--lg-secondary)' }}
                    >
                      Scan with any camera or export a crisp 512×512 JPG
                    </div>
                    <div
                      className="liquid-mono pt-1 text-xs"
                      style={{ color: 'var(--lg-muted)' }}
                    >
                      /{result.short_code} · JPG 512×512
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={handleDownloadQr}
                  className="liquid-button inline-flex h-10 shrink-0 items-center gap-2 px-4 text-xs sm:text-sm"
                >
                  <Download className="h-4 w-4 shrink-0" strokeWidth={1.5} />
                  <span>Download JPG</span>
                </button>
              </div>
            )}
          </div>
        )}
      </section>
    </main>
  )
}
