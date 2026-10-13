import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import type { Extraction, FieldValue, LineItem, RuleResult } from '../api/types'
import { AuditTimeline } from '../components/AuditTimeline'
import { CheckMarks, ConfidencePill, StatusBadge } from '../components/Badges'
import { PageViewer } from '../components/PageViewer'
import { RuleResults } from '../components/RuleResults'
import { useClaimNext, useDecide, useReviewDocument } from '../hooks/queries'
import { AMOUNT_FIELDS, FIELD_LABELS, FIELD_ORDER, formatAmount, formatValue } from '../lib/format'

function asText(value: FieldValue | undefined): string {
  return value === null || value === undefined ? '' : String(value)
}

type Submit = (decision: { approve: boolean; corrections: Record<string, string>; reason: string }) => void

export function ReviewPage() {
  const { id = '' } = useParams()
  const { data: doc, isPending, isError } = useReviewDocument(id)
  const decide = useDecide(id)
  const next = useClaimNext()
  const navigate = useNavigate()

  // Lives here, not in the form: once the decision lands the document is no longer under review,
  // the form unmounts, and callbacks attached to it would never run.
  const submit: Submit = async (decision) => {
    try {
      await decide.mutateAsync(decision)
    } catch {
      return // shown by the form
    }
    const nextId = await next.mutateAsync().catch(() => null)
    navigate(nextId ? `/review/${nextId}` : '/', { replace: true })
  }

  if (isError) return <p className="rounded-lg bg-crit-soft p-4 text-crit">Couldn't load this document.</p>
  if (isPending) return <p className="text-muted">Loading…</p>

  const extraction = doc.extraction as Extraction | null
  const latest = doc.decisions.at(-1)
  return (
    <div className="grid gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <Link to="/" className="text-sm font-semibold text-brand hover:underline">
          ← Queue
        </Link>
        <h1 className="text-xl font-bold">{doc.filename}</h1>
        <StatusBadge status={doc.status} />
        {extraction ? <ConfidencePill value={extraction.confidence} /> : null}
        {doc.claimed_by ? <span className="text-sm text-muted">Being reviewed by {doc.claimed_by}</span> : null}
      </div>

      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <PageViewer documentId={doc.id} pages={doc.page_count ?? 1} />
        <div className="grid gap-5 rounded-xl border border-line bg-surface p-5">
          {!extraction || !latest ? (
            <p className="text-muted">This document hasn't been read yet.</p>
          ) : (
            <>
              <RuleResults results={latest.rule_results as RuleResult[]} />
              {doc.status === 'needs_review' ? (
                <ReviewForm
                  key={latest.id}
                  extraction={extraction}
                  values={latest.final_fields as Record<string, FieldValue>}
                  onSubmit={submit}
                  pending={decide.isPending || next.isPending}
                  error={decide.error?.message ?? null}
                />
              ) : (
                <FinalFields extraction={extraction} values={latest.final_fields as Record<string, FieldValue>} decidedBy={latest.decided_by} outcome={latest.outcome} reason={latest.reason} />
              )}
              <LineItems items={latest.final_line_items as LineItem[]} />
              <details className="text-sm">
                <summary className="cursor-pointer font-semibold">Text read from the document</summary>
                <pre className="mt-2 max-h-72 overflow-auto rounded bg-surface-2 p-3 font-mono text-xs whitespace-pre-wrap">{extraction.ocr_text}</pre>
                <p className="mt-1 text-xs text-muted">
                  {extraction.pipeline_version} · read in {(extraction.ocr_ms / 1000).toFixed(1)}s, fields in {(extraction.extraction_ms / 1000).toFixed(1)}s
                </p>
              </details>
            </>
          )}
          <AuditTimeline events={doc.audit} />
        </div>
      </div>
    </div>
  )
}

type FormProps = {
  extraction: Extraction
  values: Record<string, FieldValue>
  onSubmit: Submit
  pending: boolean
  error: string | null
}

function ReviewForm({ extraction, values, onSubmit, pending, error }: FormProps) {
  const [edited, setEdited] = useState<Record<string, string>>({})
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')

  const corrections = Object.fromEntries(Object.entries(edited).filter(([name, text]) => text !== asText(values[name])))
  const count = Object.keys(corrections).length
  const submit = (approve: boolean) => onSubmit({ approve, corrections, reason })

  return (
    <form
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault()
        submit(true)
      }}
    >
      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm font-bold">Fields</legend>
        {FIELD_ORDER.map((name) => {
          const result = extraction.fields[name]
          const text = edited[name] ?? asText(values[name])
          const changed = name in corrections
          return (
            <div key={name} className="grid grid-cols-[7.5rem_minmax(0,1fr)_auto] items-center gap-3">
              <label htmlFor={`field-${name}`} className="text-sm text-muted">
                {FIELD_LABELS[name]}
              </label>
              <input
                id={`field-${name}`}
                value={text}
                inputMode={AMOUNT_FIELDS.has(name) ? 'decimal' : undefined}
                placeholder={name === 'receipt_date' ? 'YYYY-MM-DD' : 'Not on the document'}
                onChange={(e) => setEdited({ ...edited, [name]: e.target.value })}
                className={`rounded-md border px-2.5 py-1.5 font-mono text-sm tabular ${changed ? 'border-warn bg-warn-soft' : 'border-line bg-surface'}`}
              />
              <span className="flex items-center gap-2">
                <ConfidencePill value={result?.confidence} />
                <CheckMarks checks={result?.checks ?? null} />
              </span>
            </div>
          )
        })}
      </fieldset>

      {rejecting ? (
        <label className="grid gap-1 text-sm">
          <span className="font-semibold">Why is it rejected?</span>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            className="rounded-md border border-line px-2.5 py-1.5"
            placeholder="For example: personal expense, unreadable, not a receipt"
          />
        </label>
      ) : null}

      {error ? (
        <p role="alert" className="rounded-md bg-crit-soft p-3 text-sm text-crit">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {rejecting ? (
          <>
            <button type="button" disabled={!reason.trim() || pending} onClick={() => submit(false)} className="rounded-lg bg-crit px-4 py-2 font-semibold text-white disabled:opacity-50">
              Reject &amp; next
            </button>
            <button type="button" onClick={() => setRejecting(false)} className="rounded-lg px-4 py-2 font-semibold text-muted hover:text-ink">
              Cancel
            </button>
          </>
        ) : (
          <>
            <button type="submit" disabled={pending} className="rounded-lg bg-brand px-4 py-2 font-semibold text-white hover:bg-brand-dark disabled:opacity-50">
              {count ? `Approve with ${count} correction${count > 1 ? 's' : ''} & next` : 'Approve & next'}
            </button>
            <button type="button" onClick={() => setRejecting(true)} className="rounded-lg border border-line px-4 py-2 font-semibold hover:border-crit hover:text-crit">
              Reject…
            </button>
          </>
        )}
      </div>
    </form>
  )
}

function FinalFields(props: { extraction: Extraction; values: Record<string, FieldValue>; decidedBy: string; outcome: string; reason: string }) {
  const { extraction, values, decidedBy, outcome, reason } = props
  return (
    <section className="grid gap-2" aria-labelledby="final-title">
      <h2 id="final-title" className="text-sm font-bold">
        {outcome === 'rejected' ? 'Rejected' : 'Approved'} by {decidedBy}
        {reason ? <span className="font-normal text-muted"> · “{reason}”</span> : null}
      </h2>
      <dl className="grid gap-1.5 text-sm">
        {FIELD_ORDER.map((name) => (
          <div key={name} className="grid grid-cols-[7.5rem_minmax(0,1fr)_auto] items-center gap-3">
            <dt className="text-muted">{FIELD_LABELS[name]}</dt>
            <dd className="font-mono tabular">{formatValue(name, values[name] ?? null) || <span className="text-muted">–</span>}</dd>
            <dd>
              <ConfidencePill value={extraction.fields[name]?.confidence} />
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function LineItems({ items }: { items: LineItem[] }) {
  if (!items.length) return null
  return (
    <section aria-labelledby="items-title" className="grid gap-2">
      <h2 id="items-title" className="text-sm font-bold">
        Line items <span className="font-normal text-muted">· {items.length}</span>
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted">
            <tr>
              <th className="py-1 font-semibold">Item</th>
              <th className="py-1 text-right font-semibold">Qty</th>
              <th className="py-1 text-right font-semibold">Price</th>
              <th className="py-1 text-right font-semibold">Amount</th>
            </tr>
          </thead>
          <tbody className="font-mono tabular">
            {items.map((item, i) => (
              <tr key={i} className="border-t border-line">
                <td className="py-1 font-sans">{item.description ?? '–'}</td>
                <td className="py-1 text-right">{item.quantity ?? '–'}</td>
                <td className="py-1 text-right">{formatAmount(item.unit_price)}</td>
                <td className="py-1 text-right">{formatAmount(item.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
