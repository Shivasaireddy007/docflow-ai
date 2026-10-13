import type { FieldValue, Rule } from '../api/types'

export const FIELD_LABELS: Record<string, string> = {
  merchant_name: 'Merchant',
  receipt_date: 'Date',
  currency: 'Currency',
  subtotal: 'Subtotal',
  tax: 'Tax',
  service_charge: 'Service charge',
  discount: 'Discount',
  total: 'Total',
}

export const FIELD_ORDER = Object.keys(FIELD_LABELS)

export const AMOUNT_FIELDS = new Set(['subtotal', 'tax', 'service_charge', 'discount', 'total'])

const number = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 })

/** 174600 -> "1,74,600" (amounts are shown without a currency the receipt may not state). */
export function formatAmount(value: number | null | undefined): string {
  return value === null || value === undefined ? '–' : number.format(value)
}

export function formatValue(name: string, value: FieldValue): string {
  if (value === null) return ''
  return AMOUNT_FIELDS.has(name) && typeof value === 'number' ? formatAmount(value) : String(value)
}

export type Tone = 'good' | 'warn' | 'crit' | 'none'

/** Confidence bands match the default auto-approve threshold (0.9). */
export function confidenceTone(confidence: number | null | undefined): Tone {
  if (confidence === null || confidence === undefined) return 'none'
  if (confidence >= 0.9) return 'good'
  if (confidence >= 0.6) return 'warn'
  return 'crit'
}

const relative = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

export function timeAgo(iso: string, now: number = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000)
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ['day', 86400],
    ['hour', 3600],
    ['minute', 60],
  ]
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) return relative.format(Math.round(seconds / size), unit)
  }
  return 'just now'
}

const dateTime = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })

export function formatDateTime(iso: string): string {
  return dateTime.format(new Date(iso))
}

/** A rule as a sentence: {"type": "max_amount", "field": "total", "max": 50000} -> "Total is at most 50,000". */
export function describeRule(rule: Rule): string {
  const label = rule.field ? (FIELD_LABELS[rule.field] ?? rule.field) : ''
  switch (rule.type) {
    case 'required':
      return `${label} is present`
    case 'min_confidence':
      return `${rule.field ? `${label} confidence` : 'Confidence'} is at least ${rule.min?.toFixed(2)}`
    case 'max_amount':
      return `${label} is at most ${formatAmount(rule.max)}`
    case 'consistent':
      return `${label} matches the receipt's arithmetic`
    case 'max_age_days':
      return `${label} is within the last ${rule.days} days`
    case 'allowed_values':
      return `${label} is one of ${rule.values?.join(', ')}`
    case 'unique_receipt':
      return 'Not a duplicate of an approved receipt'
    default:
      return rule.type
  }
}

export const STATUS_LABELS: Record<string, string> = {
  queued: 'Queued',
  processing: 'Processing',
  needs_review: 'Needs review',
  approved: 'Approved',
  rejected: 'Rejected',
  failed: 'Failed',
}
