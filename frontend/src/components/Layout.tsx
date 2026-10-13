import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { useLogout, useMe, useQueue } from '../hooks/queries'
import { IS_DEMO, REPO_URL } from '../lib/demo'
import { Logo } from './Logo'

export function Layout() {
  const { data: me } = useMe()
  const { data: queue } = useQueue()
  const logout = useLogout()
  const navigate = useNavigate()

  const link = ({ isActive }: { isActive: boolean }) =>
    `rounded-md px-3 py-1.5 text-sm font-semibold ${isActive ? 'bg-brand-soft text-brand-dark' : 'text-muted hover:text-ink'}`

  return (
    <div className="min-h-screen">
      {IS_DEMO ? (
        <p className="bg-ink px-4 py-2 text-center text-sm text-white">
          Public demo: these receipts were read by self-hosted models ahead of time, and uploads are off.
          Approve, correct or reject them as a reviewer would.{' '}
          <a href={REPO_URL} className="font-semibold underline">
            How it's built
          </a>
        </p>
      ) : null}
      <header className="sticky top-0 z-10 border-b border-line bg-surface">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5">
          <Logo />
          <nav className="flex items-center gap-1" aria-label="Main">
            <NavLink to="/" end className={link}>
              Queue
              {queue?.length ? (
                <span className="ml-1.5 rounded-full bg-warn-soft px-1.5 py-0.5 text-xs text-warn tabular">{queue.length}</span>
              ) : null}
            </NavLink>
            <NavLink to="/documents" className={link}>
              Documents
            </NavLink>
            <NavLink to="/rules" className={link}>
              Rules
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            {me ? (
              <span className="text-muted">
                <span className="font-semibold text-ink">{me.username}</span> · {me.tenant.name as string}
                {me.role === 'admin' ? ' · admin' : ''}
              </span>
            ) : null}
            <button
              type="button"
              className="font-semibold text-muted hover:text-ink"
              onClick={() => logout.mutate(undefined, { onSettled: () => navigate('/login') })}
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
