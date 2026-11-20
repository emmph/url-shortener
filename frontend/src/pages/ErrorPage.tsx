import { Link, useParams, useSearchParams } from 'react-router-dom'
import { AlertTriangle, Ban, Clock, FileWarning, Lock, ServerCrash, ShieldAlert } from 'lucide-react'
import { ThemeToggle } from '../components/ThemeToggle'

interface ErrorCatalogEntry {
  code: number
  badge: string
  title: string
  description: string
  icon: typeof AlertTriangle
}

// Single lookup table for all HTTP error pages
const ERROR_CATALOG: Record<string, ErrorCatalogEntry> = {
  '410:unavailable': {
    code: 410,
    badge: '410 Gone',
    title: 'Link unavailable',
    description: 'This link is no longer valid or has reached its visit limit',
    icon: Clock,
  },
  '403:unsafe_url': {
    code: 403,
    badge: '403 Forbidden',
    title: 'Access blocked',
    description: 'Blocked by automated security screening due to CVE or phishing risk',
    icon: ShieldAlert,
  },
  '404:page_not_found': {
    code: 404,
    badge: '404 Not Found',
    title: 'Page not found',
    description: 'The requested page does not exist or has been removed',
    icon: FileWarning,
  },
  '413:payload_too_large': {
    code: 413,
    badge: '413 Payload Too Large',
    title: 'Request too large',
    description: 'The request body or URL exceeds the 2,048 character limit',
    icon: AlertTriangle,
  },
  '422:invalid_url': {
    code: 422,
    badge: '422 Unprocessable Entity',
    title: 'Invalid input',
    description: 'Enter an http or https URL and a click limit between 1 and 250',
    icon: Ban,
  },
  '429:rate_limit': {
    code: 429,
    badge: '429 Too Many Requests',
    title: 'Too many requests',
    description: 'Rate limit reached for your address. Wait a few minutes and try again.',
    icon: Lock,
  },
  '503:maintenance': {
    code: 503,
    badge: '503 Service Unavailable',
    title: 'Service unavailable',
    description: 'The service is temporarily unavailable for maintenance',
    icon: ServerCrash,
  },
  '500:server_error': {
    code: 500,
    badge: '500 Internal Server Error',
    title: 'Internal server error',
    description: 'Unexpected server error. Try refreshing in a moment.',
    icon: ServerCrash,
  },
}

const DEFAULT_REASON_BY_CODE: Record<string, string> = {
  '410': 'unavailable',
  '403': 'unsafe_url',
  '404': 'page_not_found',
  '413': 'payload_too_large',
  '422': 'invalid_url',
  '429': 'rate_limit',
  '503': 'maintenance',
  '500': 'server_error',
}

export default function ErrorPage() {
  const { code = '404' } = useParams<{ code: string }>()
  const [searchParams] = useSearchParams()
  const reason = searchParams.get('reason') || DEFAULT_REASON_BY_CODE[code] || 'page_not_found'

  // Pick matching catalog entry or fall back safely
  const entry =
    ERROR_CATALOG[`${code}:${reason}`] ||
    ERROR_CATALOG[`${code}:${DEFAULT_REASON_BY_CODE[code] ?? 'page_not_found'}`] ||
    ERROR_CATALOG['404:page_not_found']

  const Icon = entry.icon

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
          <Icon className="h-5 w-5" style={{ color: 'var(--lg-secondary)' }} strokeWidth={1.5} />
        </div>

        <span
          className="liquid-mono inline-block rounded-[6px] border px-3 py-1 text-xs font-medium"
          style={{
            backgroundColor: 'var(--lg-pill-bg)',
            borderColor: 'var(--lg-pill-border)',
            color: 'var(--lg-muted)',
          }}
        >
          {entry.badge}
        </span>

        <h1 className="mt-4 text-xl font-medium tracking-tight" style={{ color: 'var(--lg-text)' }}>
          {entry.title}
        </h1>
        <p className="mt-2 text-sm leading-6" style={{ color: 'var(--lg-secondary)' }}>
          {entry.description}
        </p>

        <div className="mt-6">
          <Link to="/" className="liquid-button inline-flex h-10 items-center justify-center px-5 text-sm">
            Back to home
          </Link>
        </div>
      </section>
    </main>
  )
}
