import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'

import { json, renderAt } from '../test/render'
import { LoginPage } from './LoginPage'

afterEach(() => vi.restoreAllMocks())

it('explains a failed sign-in', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = (input as Request).url
    if (url.endsWith('/auth/me')) return json({ detail: 'Authentication credentials were not provided.' }, 401)
    if (url.endsWith('/auth/csrf')) return new Response(null, { status: 204 })
    return json({ detail: 'Wrong username or password.' }, 400)
  })
  renderAt('/login', '/login', <LoginPage />)

  await userEvent.type(await screen.findByLabelText('Username'), 'asha')
  await userEvent.type(screen.getByLabelText('Password'), 'nope')
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Wrong username or password.')
})
