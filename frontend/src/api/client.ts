import createClient, { type Middleware } from 'openapi-fetch'

import type { paths } from './schema'

const baseUrl = import.meta.env.VITE_API_URL ?? ''

// Look fetch up per call (not once at startup) so tests can replace it.
export const api = createClient<paths>({ baseUrl, credentials: 'same-origin', fetch: (r) => globalThis.fetch(r) })

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown) {
    super(messageFrom(body) ?? `Request failed (${status})`)
    this.status = status
    this.body = body
  }
}

/** DRF errors: {"detail": "..."} or {"field": ["...", ...]} or {"field": "..."} */
function messageFrom(body: unknown): string | undefined {
  if (!body || typeof body !== 'object') return undefined
  const record = body as Record<string, unknown>
  if (typeof record.detail === 'string') return record.detail
  for (const value of Object.values(record)) {
    if (typeof value === 'string') return value
    if (Array.isArray(value) && typeof value[0] === 'string') return value[0]
  }
  return undefined
}

export async function unwrap<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await promise
  if (error !== undefined || !response.ok) throw new ApiError(response.status, error ?? null)
  return data as T
}

export function csrfToken(): string | undefined {
  return document.cookie
    .split('; ')
    .find((c) => c.startsWith('csrftoken='))
    ?.split('=')[1]
}

/** Django rejects unsafe requests from a signed-in session without the CSRF token header. */
const csrf: Middleware = {
  onRequest({ request }) {
    const token = csrfToken()
    if (token && !['GET', 'HEAD', 'OPTIONS'].includes(request.method)) request.headers.set('X-CSRFToken', token)
    return request
  },
}

api.use(csrf)
