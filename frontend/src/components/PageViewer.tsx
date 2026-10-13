import { useState } from 'react'

/** The document's pages, rendered by the API, so reviewers compare fields with the original. */
export function PageViewer({ documentId, pages }: { documentId: string; pages: number }) {
  const [page, setPage] = useState(1)
  const [zoomed, setZoomed] = useState(false)
  const count = Math.max(pages, 1)

  return (
    <section className="grid content-start gap-2" aria-label="Document">
      <div className="flex items-center justify-between text-sm">
        <span className="text-muted tabular">
          Page {page} of {count}
        </span>
        <div className="flex gap-1">
          <button type="button" className="rounded border border-line bg-surface px-2 py-1 disabled:opacity-40" disabled={page === 1} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          <button type="button" className="rounded border border-line bg-surface px-2 py-1 disabled:opacity-40" disabled={page === count} onClick={() => setPage(page + 1)}>
            Next
          </button>
          <button type="button" className="rounded border border-line bg-surface px-2 py-1" aria-pressed={zoomed} onClick={() => setZoomed(!zoomed)}>
            {zoomed ? 'Fit' : 'Zoom'}
          </button>
        </div>
      </div>
      <div className={`overflow-auto rounded-lg border border-line bg-[#2a3138] p-3 ${zoomed ? 'max-h-[80vh]' : ''}`}>
        <img
          key={page}
          src={`/api/v1/documents/${documentId}/pages/${page}`}
          alt={`Page ${page} of the document`}
          className={`mx-auto bg-white ${zoomed ? 'max-w-none' : 'max-h-[70vh] w-auto'}`}
        />
      </div>
    </section>
  )
}
