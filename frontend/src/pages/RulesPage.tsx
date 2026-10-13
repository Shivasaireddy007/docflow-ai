import { useState } from 'react'

import type { Rule } from '../api/types'
import { useMe, usePublishRules, useRules } from '../hooks/queries'
import { describeRule, formatDateTime } from '../lib/format'

export function RulesPage() {
  const { data, isPending, isError } = useRules()
  const { data: me } = useMe()
  const [draft, setDraft] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [parseError, setParseError] = useState<string | null>(null)
  const publish = usePublishRules()

  if (isError) return <p className="rounded-lg bg-crit-soft p-4 text-crit">Couldn't load the rules.</p>
  if (isPending) return <p className="text-muted">Loading…</p>

  const active = data.active
  const rules = active.rules as Rule[]
  const isAdmin = me?.role === 'admin'

  const submit = () => {
    let parsed: Rule[]
    try {
      parsed = JSON.parse(draft ?? '')
    } catch {
      setParseError("That isn't valid JSON.")
      return
    }
    setParseError(null)
    publish.mutate({ rules: parsed, note }, { onSuccess: () => { setDraft(null); setNote('') } })
  }

  return (
    <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <section className="grid gap-4 rounded-xl border border-line bg-surface p-5" aria-labelledby="rules-title">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h1 id="rules-title" className="text-xl font-bold">
            Rules <span className="font-normal text-muted">· version {active.version}</span>
          </h1>
          {isAdmin && draft === null ? (
            <button type="button" onClick={() => setDraft(JSON.stringify(rules, null, 2))} className="rounded-lg border border-line px-3 py-1.5 text-sm font-semibold hover:border-brand hover:text-brand">
              Edit rules
            </button>
          ) : null}
        </div>
        <p className="text-sm text-muted">
          A document is approved automatically only when every rule passes. Otherwise it goes to the review queue with the failed rules as the reasons.
        </p>

        {draft === null ? (
          <ol className="grid gap-2">
            {rules.map((rule) => (
              <li key={rule.id} className="flex items-baseline gap-3 rounded-lg bg-surface-2 px-3 py-2">
                <span className="font-mono text-xs text-muted">{rule.id}</span>
                <span>{describeRule(rule)}</span>
              </li>
            ))}
          </ol>
        ) : (
          <div className="grid gap-3">
            <label htmlFor="rules-json" className="text-sm font-semibold">
              Rules (JSON)
            </label>
            <textarea id="rules-json" value={draft} onChange={(e) => setDraft(e.target.value)} rows={16} spellCheck={false} className="rounded-md border border-line p-3 font-mono text-xs" />
            <p className="text-xs text-muted">
              Types:{' '}
              {Object.entries(data.types).map(([type, params]) => (
                <span key={type} className="mr-2 font-mono">
                  {type}({params.join(', ')})
                </span>
              ))}
            </p>
            <label className="grid gap-1 text-sm">
              <span className="font-semibold">What changed?</span>
              <input value={note} onChange={(e) => setNote(e.target.value)} className="rounded-md border border-line px-2.5 py-1.5" placeholder="For example: raise the amount limit to 2,00,000" />
            </label>
            {parseError || publish.isError ? (
              <p role="alert" className="rounded-md bg-crit-soft p-3 text-sm text-crit">
                {parseError ?? publish.error?.message}
              </p>
            ) : null}
            <div className="flex gap-2">
              <button type="button" onClick={submit} disabled={publish.isPending} className="rounded-lg bg-brand px-4 py-2 font-semibold text-white hover:bg-brand-dark disabled:opacity-50">
                Publish version {data.versions[0].version + 1}
              </button>
              <button type="button" onClick={() => setDraft(null)} className="rounded-lg px-4 py-2 font-semibold text-muted hover:text-ink">
                Cancel
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="grid gap-3 rounded-xl border border-line bg-surface p-5" aria-labelledby="versions-title">
        <h2 id="versions-title" className="font-bold">
          History
        </h2>
        <ol className="grid gap-2 text-sm">
          {data.versions.map((v) => (
            <li key={v.version} className="flex justify-between gap-3 border-b border-line pb-2 last:border-0">
              <span>
                <span className="font-semibold">v{v.version}</span> {v.is_active ? <span className="text-good">· active</span> : null}
                <span className="block text-muted">{v.note || '–'}</span>
              </span>
              <span className="text-right text-muted">
                {v.created_by ?? 'system'}
                <span className="block">{formatDateTime(v.created_at)}</span>
              </span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}
