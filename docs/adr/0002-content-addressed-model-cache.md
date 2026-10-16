# 2. Model results are cached by content and step version

**Context.** Model calls are the slow, expensive part (seconds per page on a GPU). The same content
recurs: a re-uploaded PDF re-saved by a phone, a reprocess after a rules change, an evaluation
re-run after a prompt change.

**Decision.** Cache each step's output under `(tenant, sha256(version of that step), sha256(exactly
what the model sees))`: page images for OCR, OCR text for extraction. Redis locally, DynamoDB on
AWS, with a TTL. A miss or an unavailable store just computes.

**Consequences.** Changing the extraction prompt invalidates extraction only; OCR is reused, which
made re-evaluating each new prompt a few minutes instead of an hour. Keys are per tenant, so one
tenant can't learn from response times what another uploaded, at the cost of no sharing across
tenants. Results must be deterministic for a cache to be honest: temperature 0 and a fixed seed.

**Alternatives.** Cache by document id (misses identical content in different files, and survives
a model change it shouldn't); no cache (pays twice for every reprocess).
