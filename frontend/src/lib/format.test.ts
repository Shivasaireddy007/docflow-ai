import { describe, expect, it } from 'vitest'

import { confidenceTone, describeRule, formatAmount, formatValue, timeAgo } from './format'

describe('format', () => {
  it('groups amounts the Indian way and leaves text alone', () => {
    expect(formatAmount(174600)).toBe('1,74,600')
    expect(formatAmount(null)).toBe('–')
    expect(formatValue('total', 56100)).toBe('56,100')
    expect(formatValue('merchant_name', 'Kopi Kenangan')).toBe('Kopi Kenangan')
  })

  it('bands confidence around the auto-approve threshold', () => {
    expect([0.95, 0.9, 0.7, 0.25, null].map(confidenceTone)).toEqual(['good', 'good', 'warn', 'crit', 'none'])
  })

  it('describes rules as sentences', () => {
    expect(describeRule({ id: 'a', type: 'max_amount', field: 'total', max: 1000000 })).toBe('Total is at most 10,00,000')
    expect(describeRule({ id: 'b', type: 'min_confidence', min: 0.9 })).toBe('Confidence is at least 0.90')
    expect(describeRule({ id: 'c', type: 'unique_receipt' })).toBe('Not a duplicate of an approved receipt')
  })

  it('says how long ago', () => {
    const now = Date.parse('2026-10-13T12:00:00Z')
    expect(timeAgo('2026-10-13T11:58:00Z', now)).toBe('2 minutes ago')
    expect(timeAgo('2026-10-12T12:00:00Z', now)).toBe('yesterday')
    expect(timeAgo('2026-10-13T11:59:58Z', now)).toBe('just now')
  })
})
