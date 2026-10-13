import type { RuleResult } from '../api/types'

export function RuleResults({ results }: { results: RuleResult[] }) {
  const failed = results.filter((r) => !r.passed)
  return (
    <section className="grid gap-2" aria-labelledby="rules-title">
      <h2 id="rules-title" className="text-sm font-bold">
        Rules{' '}
        <span className="font-normal text-muted">
          · {failed.length ? `${failed.length} of ${results.length} failed` : `all ${results.length} passed`}
        </span>
      </h2>
      <ul className="grid gap-1 text-sm">
        {[...failed, ...results.filter((r) => r.passed)].map((r) => (
          <li key={r.rule_id} className={`flex gap-2 rounded px-2 py-1.5 ${r.passed ? 'text-muted' : 'bg-crit-soft text-crit'}`}>
            <span aria-hidden="true" className="font-mono font-bold">
              {r.passed ? '✓' : '✕'}
            </span>
            <span>
              <span className="font-mono text-xs">{r.rule_id}</span> · {r.message}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
