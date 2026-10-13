import type { components } from './schema'

export type Me = components['schemas']['Me']
export type QueueItem = components['schemas']['QueueItem']
export type ReviewDocument = components['schemas']['ReviewDocument']
export type Decision = components['schemas']['Decision']
export type AuditEvent = components['schemas']['AuditEvent']
export type Stats = components['schemas']['Stats']
export type RuleSet = components['schemas']['RuleSet']
export type DocumentRow = components['schemas']['Document']
export type DocumentStatus = DocumentRow['status']

// JSON documents stored by the pipeline. The API returns them as free-form objects, so their
// shapes are declared here, matching backend/pipeline/confidence.py and review/rules.py.
export type FieldValue = string | number | null

export type FieldChecks = { grounded: boolean; valid: boolean; consistent: boolean | null }

export type FieldResult = { value: FieldValue; confidence: number | null; checks: FieldChecks | null }

export type LineItem = {
  description: string | null
  quantity: number | null
  unit_price: number | null
  amount: number | null
  confidence?: number
}

export type Extraction = {
  pipeline_version: string
  confidence: number
  fields: Record<string, FieldResult>
  line_items: LineItem[]
  ocr_text: string
  ocr_ms: number
  extraction_ms: number
  created_at: string
}

export type RuleResult = { rule_id: string; type: string; passed: boolean; message: string }

export type Rule = { id: string; type: string; field?: string; min?: number; max?: number; days?: number; values?: string[] }
