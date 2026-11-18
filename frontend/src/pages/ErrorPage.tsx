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
    title: 'Link Unavailable',
    description: 'This link is no longer valid or has reached its maximum visit limit.',
    icon: Clock,
  },
  '403:unsafe_url': {
    code: 403,
    badge: '403 Forbidden',
    title: 'Access Blocked',
    description:
      'This URL was blocked by our security scanner due to detected CVE vulnerabilities or phishing risk.',
    icon: ShieldAlert,
  },
  '404:page_not_found': {
    code: 404,
    badge: '404 Not Found',
    title: 'Page Not Found',
    description: 'The requested page does not exist or has been removed.',
    icon: FileWarning,
  },
  '413:payload_too_large': {
    code: 413,
    badge: '413 Payload Too Large',
    title: 'Request Too Large',
    description: 'The request body or URL length exceeds the allowed limit (2048 characters).',
    icon: AlertTriangle,
  },
  '422:invalid_url': {
    code: 422,
    badge: '422 Unprocessable Entity',
    title: 'Invalid Input',
    description: 'The URL format is unsafe or invalid, or the click limit is outside 1–250.',
    icon: Ban,
  },
  '429:rate_limit': {
    code: 429,
    badge: '429 Too Many Requests',
    title: 'Too Many Requests',
    description: 'Rate limit exceeded. Please wait a few minutes and try again.',
    icon: Lock,
  },
  '503:maintenance': {
    code: 503,
    badge: '503 Service Unavailable',
    title: 'Service Unavailable',
    description: 'The service is under maintenance or temporarily overloaded.',
    icon: ServerCrash,
  },
  '500:server_error': {
    code: 500,
    badge: '500 Internal Server Error',
    title: 'Internal Server Error',
    description: 'Something went wrong on our end. Please try refreshing later.',
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
    <main className="liquid-stage flex items-center justify-center px-4 py-12">
      <div className="liquid-orb liquid-orb-1" aria-hidden="true" />
      <div className="liquid-orb liquid-orb-2" aria-hidden="true" />

      <div className="fixed right-4 top-4 z-20">
        <ThemeToggle variant="glass" />
      </div>

      <section className="liquid-glass-card w-full max-w-md p-8 text-center">
        <div
          className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl border"
          style={{ background: 'var(--lg-pill-bg)', borderColor: 'var(--lg-pill-border)' }}
        >
          <Icon className="h-7 w-7" style={{ color: 'var(--lg-text)' }} />
        </div>

        <span
          className="liquid-glass-pill inline-block px-3.5 py-1 text-xs font-semibold tracking-wide"
          style={{ color: 'var(--lg-muted)' }}
        >
          {entry.badge}
        </span>

        <h1 className="mt-4 text-xl font-semibold" style={{ color: 'var(--lg-text)' }}>
          {entry.title}
        </h1>
        <p className="mt-2.5 text-sm leading-relaxed" style={{ color: 'var(--lg-muted)' }}>
          {entry.description}
        </p>

        <div className="mt-6">
          <Link to="/" className="liquid-button inline-flex items-center justify-center px-6 py-2.5 text-sm">
            Back to Home
          </Link>
        </div>
      </section>
    </main>
  )
}
