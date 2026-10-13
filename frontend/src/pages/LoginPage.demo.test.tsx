import { screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { json, renderAt } from '../test/render'
import { LoginPage } from './LoginPage'

vi.mock('../lib/demo', () => ({ IS_DEMO: true, DEMO_LOGIN: { username: 'demo', password: 'demo-password' } }))

afterEach(() => vi.restoreAllMocks())

it('fills in the demo sign-in', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ detail: 'Authentication credentials were not provided.' }, 401))
  renderAt('/login', '/login', <LoginPage />)

  expect(await screen.findByLabelText('Username')).toHaveValue('demo')
  expect(screen.getByLabelText('Password')).toHaveValue('demo-password')
  expect(screen.getByText(/Public demo/)).toBeInTheDocument()
})
