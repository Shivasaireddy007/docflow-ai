import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { json, renderAt } from '../test/render'
import { ReviewPage } from './ReviewPage'

const field = (value: unknown, confidence: number, grounded = true, consistent: boolean | null = true) => ({
  value,
  confidence,
  checks: { grounded, valid: true, consistent },
})

const DOCUMENT = {
  id: 'doc-1',
  filename: 'receipt-104.jpg',
  status: 'needs_review',
  page_count: 1,
  created_at: '2026-10-13T06:00:00Z',
  claimed_by: 'asha',
  extraction: {
    pipeline_version: 'ocr=qwen2.5vl:3b;llm=qwen2.5:7b;prompt=1',
    confidence: 0.25,
    fields: {
      merchant_name: field('Kopi Kenangan', 0.95, true, null),
      total: field(194000, 0.25, false, false),
      subtotal: field(194000, 1),
    },
    line_items: [],
    ocr_text: 'SUBTOTAL 194,000\nDISC 19,400\nTOTAL 174,600',
    ocr_ms: 7000,
    extraction_ms: 8000,
    ocr_cached: true,
    extraction_cached: false,
    created_at: '2026-10-13T06:00:20Z',
  },
  decisions: [
    {
      id: 1,
      outcome: 'needs_review',
      decided_by: 'rules',
      rules_version: 1,
      rule_results: [
        { rule_id: 'confident', type: 'min_confidence', passed: false, message: 'document confidence 0.25 (needs 0.90)' },
        { rule_id: 'total-present', type: 'required', passed: true, message: 'total is present' },
      ],
      final_fields: { merchant_name: 'Kopi Kenangan', total: 194000, subtotal: 194000 },
      final_line_items: [],
      corrections: {},
      reason: '',
      created_at: '2026-10-13T06:00:21Z',
    },
  ],
  audit: [{ actor: 'pipeline', action: 'sent_to_review', data: { failed: ['confident'] }, created_at: '2026-10-13T06:00:21Z' }],
}

afterEach(() => vi.restoreAllMocks())

/** A fake API that behaves like the real one: once decided, the document is no longer under review. */
function serve(onDecision: (body: Record<string, unknown>) => Response = () => json({ outcome: 'approved' }, 201)) {
  let decided = false
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const request = input as Request
    if (request.url.endsWith('/decision')) {
      const response = onDecision(await request.json())
      decided = response.ok
      return response
    }
    if (request.url.endsWith('/review/next')) return new Response(null, { status: 204 })
    return json(decided ? { ...DOCUMENT, status: 'approved' } : DOCUMENT)
  })
}

describe('ReviewPage', () => {
  it('shows each field with its confidence and the failed rules first', async () => {
    serve()
    renderAt('/review/doc-1', '/review/:id', <ReviewPage />)

    expect(await screen.findByLabelText('Total')).toHaveValue('194000')
    expect(screen.getByText('1 of 2 failed', { exact: false })).toBeInTheDocument()
    expect(screen.getByText(/document confidence 0.25/)).toBeInTheDocument()
    expect(screen.getAllByLabelText('Not found in the document text')).toHaveLength(1)
    expect(screen.getByText(/read from the cache, fields in 8.0s/)).toBeInTheDocument()
  })

  it('sends only the fields the reviewer changed', async () => {
    const decided: Record<string, unknown>[] = []
    serve((body) => {
      decided.push(body)
      return json({ outcome: 'approved' }, 201)
    })
    renderAt('/review/doc-1', '/review/:id', <ReviewPage />)
    const total = await screen.findByLabelText('Total')

    await userEvent.clear(total)
    await userEvent.type(total, '174600')
    await userEvent.click(screen.getByRole('button', { name: 'Approve with 1 correction & next' }))

    await waitFor(() => expect(decided).toEqual([{ approve: true, corrections: { total: '174600' }, reason: '' }]))
    expect(await screen.findByText('elsewhere')).toBeInTheDocument()
  })

  it('needs a reason to reject', async () => {
    serve()
    renderAt('/review/doc-1', '/review/:id', <ReviewPage />)

    await userEvent.click(await screen.findByRole('button', { name: 'Reject…' }))
    const reject = screen.getByRole('button', { name: 'Reject & next' })
    expect(reject).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Why is it rejected?'), 'Personal expense')
    expect(reject).toBeEnabled()
  })

  it('shows why a decision failed', async () => {
    serve(() => json({ detail: 'ravi is reviewing this document.' }, 409))
    renderAt('/review/doc-1', '/review/:id', <ReviewPage />)

    await userEvent.click(await screen.findByRole('button', { name: 'Approve & next' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('ravi is reviewing this document.')
  })
})
