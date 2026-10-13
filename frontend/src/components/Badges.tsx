import type { FieldChecks } from '../api/types'
import { STATUS_LABELS, confidenceTone, type Tone } from '../lib/format'

const TONES: Record<Tone, string> = {
  good: 'bg-good-soft text-good',
  warn: 'bg-warn-soft text-warn',
  crit: 'bg-crit-soft text-crit',
  none: 'bg-surface-2 text-muted',
}

export function ConfidencePill({ value }: { value: number | null | undefined }) {
  const tone = confidenceTone(value)
  return (
    <span className={`inline-flex min-w-12 justify-center rounded-full px-2 py-0.5 font-mono text-xs font-medium tabular ${TONES[tone]}`}>
      {value === null || value === undefined ? 'n/a' : value.toFixed(2)}
    </span>
  )
}

const STATUS_TONES: Record<string, Tone> = {
  approved: 'good',
  needs_review: 'warn',
  rejected: 'crit',
  failed: 'crit',
  queued: 'none',
  processing: 'none',
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${TONES[STATUS_TONES[status] ?? 'none']}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  )
}

const CHECK_LABELS: Record<keyof FieldChecks, [string, string, string]> = {
  grounded: ['Found in the document', 'Not found in the document text', ''],
  valid: ['Well-formed', 'Not a valid value', ''],
  consistent: ['Arithmetic agrees', "Arithmetic doesn't add up", 'Nothing to check against'],
}

/** Three small marks: grounded, valid, consistent. Each says what it means, not just its colour. */
export function CheckMarks({ checks }: { checks: FieldChecks | null }) {
  if (!checks) return null
  return (
    <span className="flex gap-1" aria-label="Checks">
      {(Object.keys(CHECK_LABELS) as (keyof FieldChecks)[]).map((name) => {
        const result = checks[name]
        const [ok, bad, unchecked] = CHECK_LABELS[name]
        const label = result === null ? unchecked : result ? ok : bad
        const style = result === null ? 'border-line text-muted' : result ? 'border-good text-good' : 'border-crit bg-crit-soft text-crit'
        return (
          <span key={name} title={label} aria-label={label} className={`grid size-5 place-items-center rounded border font-mono text-[10px] font-bold ${style}`}>
            {name[0].toUpperCase()}
          </span>
        )
      })}
    </span>
  )
}
