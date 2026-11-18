import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Navigate } from 'react-router-dom'
import { getAdminSession } from '../api/client'

// Guard private admin routes with server cookie check
export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['admin-session'],
    queryFn: getAdminSession,
    retry: false,
  })

  if (isLoading) {
    return (
      <div className="ds-root flex items-center justify-center p-8">
        <div className="ds-card ds-text px-6 py-4 text-sm font-medium">
          Checking admin session...
        </div>
      </div>
    )
  }

  if (isError || !data?.authenticated) {
    return <Navigate to="/admin/login" replace />
  }

  return <>{children}</>
}
