import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { Logo } from '../components/Logo'
import { useLogin, useMe } from '../hooks/queries'
import { DEMO_LOGIN, IS_DEMO } from '../lib/demo'

export function LoginPage() {
  const { data: me } = useMe()
  const login = useLogin()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState(IS_DEMO ? DEMO_LOGIN.username : '')
  const [password, setPassword] = useState(IS_DEMO ? DEMO_LOGIN.password : '')
  const from = (location.state as { from?: string } | null)?.from ?? '/'

  if (me) return <Navigate to={from} replace />

  return (
    <main className="grid min-h-screen place-items-center px-4">
      <form
        className="grid w-full max-w-sm gap-4 rounded-xl border border-line bg-surface p-6"
        onSubmit={(e) => {
          e.preventDefault()
          login.mutate({ username, password }, { onSuccess: () => navigate(from, { replace: true }) })
        }}
      >
        <Logo />
        <h1 className="text-lg font-bold">Sign in to review documents</h1>
        {IS_DEMO ? (
          <p className="rounded-md bg-brand-soft p-3 text-sm text-brand-dark">
            Public demo. The sign-in is filled in for you: press <strong>Sign in</strong>.
          </p>
        ) : null}
        <label className="grid gap-1 text-sm">
          <span className="font-semibold">Username</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required className="rounded-md border border-line px-3 py-2" />
        </label>
        <label className="grid gap-1 text-sm">
          <span className="font-semibold">Password</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required className="rounded-md border border-line px-3 py-2" />
        </label>
        {login.isError ? (
          <p role="alert" className="rounded-md bg-crit-soft p-3 text-sm text-crit">
            {login.error.message}
          </p>
        ) : null}
        <button type="submit" disabled={login.isPending} className="rounded-lg bg-brand px-4 py-2 font-semibold text-white hover:bg-brand-dark disabled:opacity-50">
          {login.isPending ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}
