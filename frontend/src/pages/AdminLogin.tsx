import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { Lock } from 'lucide-react'
import { adminLogin } from '../api/client'
import { ThemeToggle } from '../components/ThemeToggle'
import type { ApiErrorPayload } from '../types'

export default function AdminLogin() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // Authenticate and let server set HttpOnly cookie
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErrorMsg(null)
    setLoading(true)
    try {
      await adminLogin(username, password)
      navigate('/admin', { replace: true })
    } catch (err) {
      if (axios.isAxiosError<ApiErrorPayload>(err)) {
        setErrorMsg(err.response?.data?.detail || 'Login failed')
      } else {
        setErrorMsg('Could not reach the server')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="ds-root flex items-center justify-center px-4 py-12">
      <div className="fixed right-4 top-4">
        <ThemeToggle variant="ds" />
      </div>

      <div className="ds-card w-full max-w-md p-8">
        <div className="ds-divider mb-6 flex items-center gap-3 border-b pb-4">
          <div
            className="flex h-10 w-10 items-center justify-center rounded"
            style={{ backgroundColor: 'var(--ds-accent-subtle)', color: 'var(--ds-accent)' }}
          >
            <Lock className="h-5 w-5" />
          </div>
          <div>
            <h1 className="ds-text text-lg font-bold">Admin Panel</h1>
            <p className="ds-muted text-xs">Private access to analytics and controls</p>
          </div>
        </div>

        {errorMsg && (
          <div role="alert" className="ds-alert-danger mb-5 px-4 py-3 text-sm font-medium">
            {errorMsg}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="admin-user" className="ds-text mb-1.5 block text-sm font-semibold">
              Username
            </label>
            <input
              id="admin-user"
              type="text"
              required
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="ds-input"
            />
          </div>

          <div>
            <label htmlFor="admin-pass" className="ds-text mb-1.5 block text-sm font-semibold">
              Password
            </label>
            <input
              id="admin-pass"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="ds-input"
            />
          </div>

          <button type="submit" disabled={loading} className="ds-btn-primary w-full py-2.5">
            {loading ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        <div className="ds-divider mt-6 border-t pt-4 text-center">
          <Link to="/" className="ds-link text-xs font-semibold hover:underline">
            Back to URL Shortener
          </Link>
        </div>
      </div>
    </main>
  )
}
