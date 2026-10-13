import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, ApiError, unwrap } from '../api/client'
import type { DocumentStatus, Rule } from '../api/types'

export function useMe() {
  return useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        return await unwrap(api.GET('/api/v1/auth/me'))
      } catch (e) {
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return null
        throw e
      }
    },
    staleTime: 60_000,
  })
}

export function useLogin() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (credentials: { username: string; password: string }) => {
      await api.GET('/api/v1/auth/csrf')
      return unwrap(api.POST('/api/v1/auth/login', { body: credentials }))
    },
    onSuccess: (me) => client.setQueryData(['me'], me),
  })
}

export function useLogout() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/auth/logout')),
    onSettled: () => {
      client.clear()
      client.setQueryData(['me'], null)
    },
  })
}

export function useQueue() {
  return useQuery({ queryKey: ['queue'], queryFn: () => unwrap(api.GET('/api/v1/review/queue')), refetchInterval: 10_000 })
}

export function useStats() {
  return useQuery({ queryKey: ['stats'], queryFn: () => unwrap(api.GET('/api/v1/review/stats')), refetchInterval: 30_000 })
}

export function useReviewDocument(id: string) {
  return useQuery({
    queryKey: ['review-document', id],
    queryFn: () => unwrap(api.GET('/api/v1/review/documents/{document_id}', { params: { path: { document_id: id } } })),
  })
}

/** Claims the next document; resolves to its id, or null when the queue is empty. */
export function useClaimNext() {
  return useMutation({
    mutationFn: async () => {
      const { data, response } = await api.POST('/api/v1/review/next')
      if (response.status === 204) return null
      if (!response.ok || !data) throw new ApiError(response.status, null)
      return data.id
    },
  })
}

export function useDecide(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { approve: boolean; corrections: Record<string, string | number | null>; reason: string }) =>
      unwrap(api.POST('/api/v1/review/documents/{document_id}/decision', { params: { path: { document_id: id } }, body })),
    onSettled: () => {
      client.invalidateQueries({ queryKey: ['review-document', id] })
      client.invalidateQueries({ queryKey: ['queue'] })
      client.invalidateQueries({ queryKey: ['stats'] })
      client.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}

export function useDocuments(status: DocumentStatus | undefined, page: number) {
  return useQuery({
    queryKey: ['documents', status, page],
    queryFn: () => unwrap(api.GET('/api/v1/documents', { params: { query: { status, page } } })),
    placeholderData: keepPreviousData,
    refetchInterval: 10_000,
  })
}

export function useUpload() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData()
      body.append('file', file)
      // The generated type describes the form's fields; the browser needs the FormData itself.
      const { data, error, response } = await api.POST('/api/v1/documents', {
        body: body as unknown as { file: string },
        bodySerializer: (b) => b as unknown as FormData,
      })
      if (error !== undefined || !response.ok) throw new ApiError(response.status, error ?? null)
      return data
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ['documents'] }),
  })
}

export function useRules() {
  return useQuery({ queryKey: ['rules'], queryFn: () => unwrap(api.GET('/api/v1/rules')) })
}

export function usePublishRules() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { rules: Rule[]; note: string }) => unwrap(api.POST('/api/v1/rules', { body })),
    onSuccess: () => client.invalidateQueries({ queryKey: ['rules'] }),
  })
}
