// Load test for the API and pipeline, with the model stand-in (e2e/ollama_stub.py) so it measures
// the system, not the models.
//
//   k6 run -e BASE=http://localhost:8000 -e KEYS=key1,key2,key3,key4 -e BURST_KEY=key5 bench/load/load.js
//
// uploads:  unique receipts at a steady rate, spread over tenants (each under its upload limit)
// browsing: reviewers' reads (document lists and details) at the same time
// burst:    one tenant uploading far faster than its token bucket allows; expect 429s
import http from 'k6/http'
import { check } from 'k6'
import { Counter } from 'k6/metrics'

const BASE = __ENV.BASE || 'http://localhost:8000'
const KEYS = (__ENV.KEYS || '').split(',').filter(Boolean)
const BURST_KEY = __ENV.BURST_KEY || ''
const RECEIPT = open('../../e2e/receipt.png', 'b')
const rateLimited = new Counter('rate_limited')

export const options = {
  scenarios: {
    uploads: { executor: 'constant-arrival-rate', exec: 'uploadReceipt', rate: 2, timeUnit: '1s', duration: '2m', preAllocatedVUs: 10 },
    browsing: { executor: 'constant-arrival-rate', exec: 'browse', rate: 20, timeUnit: '1s', duration: '2m', preAllocatedVUs: 20 },
    burst: { executor: 'constant-arrival-rate', exec: 'burst', rate: 5, timeUnit: '1s', duration: '30s', startTime: '30s', preAllocatedVUs: 5 },
  },
  thresholds: {
    'http_req_duration{scenario:uploads}': ['p(95)<300'],
    'http_req_duration{scenario:browsing}': ['p(95)<150'],
    'http_req_failed{scenario:browsing}': ['rate<0.01'],
  },
}

// A different file every time: the same pixels plus random bytes after the PNG's end, which
// image readers ignore but which change the SHA-256, so nothing is deduplicated.
function uniqueReceipt() {
  const tail = new Uint8Array(16).map(() => Math.floor(Math.random() * 256))
  const body = new Uint8Array(RECEIPT.byteLength + tail.length)
  body.set(new Uint8Array(RECEIPT), 0)
  body.set(tail, RECEIPT.byteLength)
  return http.file(body.buffer, `receipt-${Date.now()}-${Math.random().toString(36).slice(2)}.png`, 'image/png')
}

const auth = (key) => ({ headers: { Authorization: `Api-Key ${key}` } })

export function uploadReceipt() {
  const key = KEYS[Math.floor(Math.random() * KEYS.length)]
  const res = http.post(`${BASE}/api/v1/documents`, { file: uniqueReceipt() }, auth(key))
  check(res, { 'uploaded (201)': (r) => r.status === 201 })
}

export function browse() {
  const key = KEYS[Math.floor(Math.random() * KEYS.length)]
  const list = http.get(`${BASE}/api/v1/documents?status=approved`, auth(key))
  check(list, { 'listed': (r) => r.status === 200 })
  const first = list.status === 200 && list.json('results.0.id')
  if (first) check(http.get(`${BASE}/api/v1/documents/${first}`, auth(key)), { 'detail': (r) => r.status === 200 })
}

export function burst() {
  const res = http.post(`${BASE}/api/v1/documents`, { file: uniqueReceipt() }, auth(BURST_KEY))
  if (res.status === 429) rateLimited.add(1)
  check(res, { 'accepted or told to wait': (r) => r.status === 201 || (r.status === 429 && r.headers['Retry-After']) })
}
