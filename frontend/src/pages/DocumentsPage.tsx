import { useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import type { DocumentStatus } from '../api/types'
import { StatusBadge } from '../components/Badges'
import { useDocuments, useUpload } from '../hooks/queries'
import { IS_DEMO } from '../lib/demo'
import { STATUS_LABELS, timeAgo } from '../lib/format'

const FILTERS: (DocumentStatus | undefined)[] = [undefined, 'needs_review', 'approved', 'rejected', 'queued', 'failed']

export function DocumentsPage() {
  const [params, setParams] = useSearchParams()
  const status = (params.get('status') ?? undefined) as DocumentStatus | undefined
  const page = Number(params.get('page') ?? 1)
  const { data, isPending, isError } = useDocuments(status, page)
  const upload = useUpload()
  const input = useRef<HTMLInputElement>(null)
  const [uploaded, setUploaded] = useState<string | null>(null)

  const pages = data ? Math.max(1, Math.ceil(data.count / 25)) : 1
  const go = (next: Record<string, string | undefined>) => {
    const merged = { status, page: String(page), ...next }
    setParams(Object.fromEntries(Object.entries(merged).filter(([, v]) => v !== undefined && v !== '1')) as Record<string, string>)
  }

  return (
    <section className="grid gap-4 rounded-xl border border-line bg-surface p-5" aria-labelledby="documents-title">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 id="documents-title" className="text-xl font-bold">
          Documents
        </h1>
        {IS_DEMO ? (
          <p className="text-sm text-muted">Uploads are off in this demo.</p>
        ) : (
        <div className="flex items-center gap-3">
            {uploaded ? <span className="text-sm text-good">{uploaded}</span> : null}
            {upload.isError ? <span className="text-sm text-crit">{upload.error.message}</span> : null}
            <input
              ref={input}
              type="file"
              accept="application/pdf,image/png,image/jpeg,image/webp"
              className="hidden"
              aria-label="Choose a document to upload"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (!file) return
                setUploaded(null)
                upload.mutate(file, {
                  onSuccess: (doc) => setUploaded(doc?.duplicate ? `${file.name} was already uploaded` : `Uploaded ${file.name}`),
                })
                e.target.value = ''
              }}
            />
            <button
              type="button"
              onClick={() => input.current?.click()}
              disabled={upload.isPending}
              className="rounded-lg bg-brand px-4 py-2 font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
            >
              {upload.isPending ? 'Uploading…' : 'Upload document'}
            </button>
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-1" role="tablist" aria-label="Filter by status">
        {FILTERS.map((s) => (
          <button
            key={s ?? 'all'}
            type="button"
            role="tab"
            aria-selected={status === s}
            onClick={() => go({ status: s, page: undefined })}
            className={`rounded-md px-3 py-1 text-sm font-semibold ${status === s ? 'bg-ink text-white' : 'text-muted hover:text-ink'}`}
          >
            {s ? STATUS_LABELS[s] : 'All'}
          </button>
        ))}
      </div>

      {isError ? (
        <p className="text-crit">Couldn't load documents.</p>
      ) : isPending ? (
        <p className="text-muted">Loading…</p>
      ) : data.results.length === 0 ? (
        <p className="text-muted">No documents here yet. Upload a receipt or invoice to start.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-line text-left text-xs text-muted">
              <tr>
                <th className="py-2 font-semibold">Document</th>
                <th className="py-2 font-semibold">Status</th>
                <th className="py-2 font-semibold">Pages</th>
                <th className="py-2 font-semibold">Uploaded</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((doc) => (
                <tr key={doc.id} className="border-b border-line last:border-0 hover:bg-surface-2">
                  <td className="py-2.5">
                    <Link to={`/review/${doc.id}`} className="font-semibold text-brand hover:underline">
                      {doc.filename}
                    </Link>
                    {doc.error ? <div className="text-xs text-crit">{doc.error}</div> : null}
                  </td>
                  <td className="py-2.5">
                    <StatusBadge status={doc.status} />
                  </td>
                  <td className="py-2.5 tabular">{doc.page_count ?? '–'}</td>
                  <td className="py-2.5 text-muted">{timeAgo(doc.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {pages > 1 ? (
        <nav className="flex items-center justify-center gap-3 text-sm" aria-label="Pages">
          <button type="button" disabled={page === 1} onClick={() => go({ page: String(page - 1) })} className="rounded border border-line px-3 py-1 disabled:opacity-40">
            Previous
          </button>
          <span className="text-muted tabular">
            Page {page} of {pages}
          </span>
          <button type="button" disabled={page === pages} onClick={() => go({ page: String(page + 1) })} className="rounded border border-line px-3 py-1 disabled:opacity-40">
            Next
          </button>
        </nav>
      ) : null}
    </section>
  )
}
