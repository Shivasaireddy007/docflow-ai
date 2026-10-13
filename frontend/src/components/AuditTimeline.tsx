import type { AuditEvent } from '../api/types'
import { formatDateTime } from '../lib/format'

const ACTIONS: Record<string, string> = {
  uploaded: 'Uploaded',
  extracted: 'Read by the models',
  auto_approved: 'Approved by the rules',
  sent_to_review: 'Sent to review',
  claimed: 'Opened for review',
  approved: 'Approved',
  rejected: 'Rejected',
  reprocess_requested: 'Reprocessing requested',
  failed: 'Processing failed',
}

function detail(event: AuditEvent): string | null {
  const data = event.data as Record<string, unknown>
  if (event.action === 'extracted') return `confidence ${Number(data.confidence).toFixed(2)} · ${Math.round(Number(data.ms) / 100) / 10}s`
  if (event.action === 'sent_to_review') return `failed: ${(data.failed as string[]).join(', ')}`
  if (event.action === 'approved' || event.action === 'rejected') {
    const corrected = Object.keys((data.corrections as Record<string, unknown>) ?? {})
    const reason = data.reason ? `“${String(data.reason)}”` : ''
    return [corrected.length ? `corrected ${corrected.join(', ')}` : '', reason].filter(Boolean).join(' · ') || null
  }
  return null
}

export function AuditTimeline({ events }: { events: AuditEvent[] }) {
  return (
    <section aria-labelledby="audit-title" className="grid gap-2">
      <h2 id="audit-title" className="text-sm font-bold">
        History
      </h2>
      <ol className="grid gap-2 border-l-2 border-line pl-4 text-sm">
        {events.map((event, i) => (
          <li key={i} className="relative">
            <span className="absolute top-1.5 -left-[1.4rem] size-2.5 rounded-full border-2 border-surface bg-brand" aria-hidden="true" />
            <span className="font-semibold">{ACTIONS[event.action] ?? event.action}</span>{' '}
            <span className="text-muted">
              by <span className="font-mono text-xs">{event.actor}</span> · {formatDateTime(event.created_at)}
            </span>
            {detail(event) ? <div className="text-muted">{detail(event)}</div> : null}
          </li>
        ))}
      </ol>
    </section>
  )
}
