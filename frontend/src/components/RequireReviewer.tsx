import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { useMe } from '../hooks/queries'

export function RequireReviewer({ children }: { children: ReactNode }) {
  const { data: me, isPending } = useMe()
  const location = useLocation()
  if (isPending) return <p className="p-8 text-muted">Loading…</p>
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}
