import { Link, useNavigate } from 'react-router-dom'

import { ConfidencePill } from '../components/Badges'
import { useClaimNext, useQueue, useStats } from '../hooks/queries'
import { formatAmount, timeAgo } from '../lib/format'

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="grid content-start gap-0.5 rounded-xl border border-line bg-surface p-4">
      <span className="text-xs font-semibold tracking-wide text-muted uppercase">{label}</span>
      <span className="text-2xl font-bold tabular">{value}</span>
      {note ? <span className="text-xs text-muted">{note}</span> : null}
    </div>
  )
}

export function QueuePage() {
  const { data: queue, isPending, isError } = useQueue()
  const { data: stats } = useStats()
  const next = useClaimNext()
  const navigate = useNavigate()

  const rate = stats?.auto_approve_rate_7d
  return (
    <div className="grid gap-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile label="Waiting for review" value={String(queue?.length ?? '–')} />
        <Tile
          label="Approved by the rules"
          value={rate === null || rate === undefined ? '–' : `${Math.round(rate * 100)}%`}
          note={stats ? `${stats.auto_approved_7d} of ${stats.decided_by_rules_7d} in 7 days` : undefined}
        />
        <Tile label="Reviewed" value={String(stats?.reviewed_7d ?? '–')} note="last 7 days" />
        <Tile label="Corrected by reviewers" value={String(stats?.corrected_7d ?? '–')} note="last 7 days" />
      </div>

      <section className="grid gap-3 rounded-xl border border-line bg-surface p-5" aria-labelledby="queue-title">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 id="queue-title" className="text-xl font-bold">
              Review queue
            </h1>
            <p className="text-sm text-muted">Documents the rules couldn't approve on their own, oldest first.</p>
          </div>
          <button
            type="button"
            disabled={!queue?.length || next.isPending}
            onClick={() => next.mutate(undefined, { onSuccess: (id) => id && navigate(`/review/${id}`) })}
            className="rounded-lg bg-brand px-4 py-2 font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
          >
            Review next
          </button>
        </div>

        {isError ? (
          <p className="text-crit">Couldn't load the queue.</p>
        ) : isPending ? (
          <p className="text-muted">Loading…</p>
        ) : queue.length === 0 ? (
          <p className="rounded-lg bg-good-soft p-4 text-good">Nothing to review. Every document so far passed its rules or has been decided.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-line text-left text-xs text-muted">
                <tr>
                  <th className="py-2 font-semibold">Document</th>
                  <th className="py-2 font-semibold">Uploaded</th>
                  <th className="py-2 font-semibold">Confidence</th>
                  <th className="py-2 text-right font-semibold">Total</th>
                  <th className="py-2 pl-6 font-semibold">Why it needs review</th>
                  <th className="py-2 font-semibold">Reviewer</th>
                </tr>
              </thead>
              <tbody>
                {queue.map((item) => (
                  <tr key={item.id} className="border-b border-line last:border-0 hover:bg-surface-2">
                    <td className="py-2.5">
                      <Link to={`/review/${item.id}`} className="font-semibold text-brand hover:underline">
                        {item.filename}
                      </Link>
                    </td>
                    <td className="py-2.5 text-muted">{timeAgo(item.created_at)}</td>
                    <td className="py-2.5">
                      <ConfidencePill value={item.confidence} />
                    </td>
                    <td className="py-2.5 text-right font-mono tabular">{formatAmount(item.total)}</td>
                    <td className="py-2.5 pl-6">
                      <span className="flex flex-wrap gap-1">
                        {item.failed_rules.map((rule) => (
                          <span key={rule} className="rounded bg-crit-soft px-1.5 py-0.5 font-mono text-xs text-crit">
                            {rule}
                          </span>
                        ))}
                      </span>
                    </td>
                    <td className="py-2.5 text-muted">{item.claimed_by ?? '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
