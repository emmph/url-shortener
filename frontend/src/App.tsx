import { Suspense, lazy } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { ErrorBoundary } from './components/ErrorBoundary'
import { ProtectedRoute } from './components/ProtectedRoute'
import ErrorPage from './pages/ErrorPage'
import Home from './pages/Home'
import ScanningWait from './pages/ScanningWait'

// Split heavy admin and chart pages into lazy bundles
const AdminLogin = lazy(() => import('./pages/AdminLogin'))
const AdminDashboard = lazy(() => import('./pages/AdminDashboard'))
const LinkStats = lazy(() => import('./pages/LinkStats'))

function LazyFallback() {
  return (
    <div className="ds-root flex items-center justify-center p-8">
      <div className="ds-card ds-text px-5 py-3 text-sm font-medium">Loading...</div>
    </div>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <Suspense fallback={<LazyFallback />}>
        <Routes>
          {/* Eager Apple Liquid Glass public routes */}
          <Route path="/" element={<Home />} />
          <Route path="/scanning/:shortCode" element={<ScanningWait />} />
          <Route path="/error/:code" element={<ErrorPage />} />
          <Route path="/error" element={<ErrorPage />} />

          {/* Lazy Norwegian Designsystemet Admin & Stats routes */}
          <Route path="/admin/login" element={<AdminLogin />} />
          <Route
            path="/admin"
            element={
              <ProtectedRoute>
                <AdminDashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/stats/:shortCode"
            element={
              <ProtectedRoute>
                <LinkStats />
              </ProtectedRoute>
            }
          />

          {/* Catch-all unified 404 */}
          <Route path="*" element={<Navigate to="/error/404?reason=page_not_found" replace />} />
        </Routes>
      </Suspense>
    </ErrorBoundary>
  )
}
