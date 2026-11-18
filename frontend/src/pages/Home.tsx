import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { Check, Copy, Link2 } from 'lucide-react'
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

  return (
    <main className="liquid-stage flex flex-col items-center justify-center px-4 py-12">
      <div className="liquid-orb liquid-orb-1" aria-hidden="true" />
      <div className="liquid-orb liquid-orb-2" aria-hidden="true" />

      {/* Subtle corner theme toggle matching OS preference by default */}
      <div className="fixed right-4 top-4 z-20">
        <ThemeToggle variant="glass" />
      </div>

      {/* Short, clean intro above the form */}
      <header className="relative z-10 mb-20 w-full max-w-[640px] space-y-2.5 text-center">
        <h1
          className="text-2xl font-semibold tracking-tight sm:text-3xl"
          style={{ color: 'var(--lg-text)' }}
        >
          Fast, safe short links
        </h1>
        <p
          className="mx-auto max-w-[540px] text-sm leading-relaxed sm:text-base"
          style={{ color: 'var(--lg-muted)' }}
        >
          Create permanent or click-limited links in seconds. Every destination is
          screened for known vulnerabilities and malicious hosts in the background.
        </p>
      </header>

      {/* Wider main card so URL input grows ~50% */}
      <section className="liquid-glass-card w-full max-w-[700px] p-6 sm:p-8">
        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Keep switcher at original compact width */}
          <div className="mx-auto w-full max-w-[448px] space-y-3">
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

            {/* Slider + number input shown only in limited mode */}
            {mode === 'limited' && (
              <div className="liquid-glass-pill flex items-center gap-3 px-4 py-2.5">
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
                  className="liquid-input w-20 px-3 py-1.5 text-center text-sm font-semibold tabular-nums"
                />
              </div>
            )}
          </div>

          {/* Wide URL input (~50% wider) + fixed-width button */}
          <div className="flex flex-col gap-3 sm:flex-row">
            <div className="relative flex-1">
              <Link2
                className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2"
                style={{ color: 'var(--lg-muted)' }}
                aria-hidden="true"
              />
              <input
                type="url"
                required
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                placeholder="https://example.com/..."
                aria-label="URL to shorten"
                className="liquid-input py-3.5 pl-10 pr-4 text-sm sm:text-base"
              />
            </div>
            <button
              type="submit"
              disabled={loading || !urlInput.trim()}
              className="liquid-button shrink-0 px-6 py-3.5 text-sm sm:text-base whitespace-nowrap"
            >
              {loading ? 'Shortening...' : 'Shorten'}
            </button>
          </div>
        </form>

        {/* Compact result box shown after creation */}
        {result && (
          <div className="liquid-glass-pill mt-5 flex items-center justify-between gap-3 px-4 py-2.5">
            <a
              href={result.short_url}
              className="truncate text-sm font-medium underline underline-offset-4"
              style={{ color: 'var(--lg-text)' }}
            >
              {result.short_url}
            </a>
            <button
              type="button"
              onClick={handleCopy}
              className="liquid-copy-btn inline-flex shrink-0 items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold"
            >
              {copied ? (
                <>
                  <Check className="h-3.5 w-3.5" />
                  Copied
                </>
              ) : (
                <>
                  <Copy className="h-3.5 w-3.5" />
                  Copy
                </>
              )}
            </button>
          </div>
        )}
      </section>
    </main>
  )
}
