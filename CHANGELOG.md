# Changelog

Versions follow [semantic versioning](https://semver.org). Evaluation numbers are on the 100-receipt
test sets of CORD and SROIE; see [the evaluation](docs/evaluation/README.md).

## v1.1.0 (2026-10-16)

### Added

- **Public demo** at [docflow-demo.onrender.com](https://docflow-demo.onrender.com): a read-only
  copy with 15 receipts read by the real models, the demo sign-in filled in, and uploads off. One
  container with its own PostgreSQL and Redis; CI builds it and checks it within 512 MB.
- **A second dataset, SROIE** (Malaysian receipts, amounts with cents), alongside CORD.
- **Prompt 3**, which tells a decimal point from a thousands separator: SROIE totals right went
  from 49% to 96%, with CORD unchanged within noise.
- **Calibration experiment:** a logistic regression on the confidence checks, fitted on CORD and
  tested on SROIE. It was worse on the unseen dataset, so the hand-set penalties stay.
- **AWS results reported to the review app** over an HMAC-signed callback, so Django stays the
  system of record and the tenant's rules decide (`PROCESSING_BACKEND=stepfunctions`).
- **Prometheus metrics and a Grafana dashboard** (outcomes, step and model times, cache hit rate,
  API latency by route, rate-limited requests, reviews, queue depth), plus a CloudWatch dashboard
  for the AWS pipeline.
- **k6 load test** with results: reads p95 7.5 ms, uploads p95 11.4 ms, upload to decision p95
  965 ms, and only the tenant over its limit refused.
- **Architecture decision records** for the seven main design choices.
- `evaluation.run --rescore`: score saved receipts again after a change to the checks, reusing
  the cached model output and keeping the measured model times.
- Contributing guide, security policy, code of conduct, and issue and pull request templates.

### Fixed

- Whole amounts printed with cents (`RM193.00`) weren't found on the receipt, so correct totals
  went to review. SROIE auto-approval went from 13% to 52%, still with no wrong total approved.
- The queue-depth metric was counted once per Gunicorn worker (1,400 shown for 280 documents).
- Amounts used Indian digit grouping (`1,00,909`) on receipts in other currencies.
- Evaluation reports showed 0% line-item precision for datasets without line-item labels.

## v1.0.0 (2026-10-13)

First release.

- Django REST API with tenants and API keys; uploads checked by their bytes and stored by SHA-256.
- Self-hosted OCR and field extraction (Qwen2.5-VL and Qwen2.5 through Ollama, or vLLM through an
  OpenAI-compatible API), with repetition-loop detection and recovery.
- Confidence from checks that can be verified: grounded in the OCR text, well-formed, and
  consistent with the receipt's arithmetic.
- Versioned rules per tenant, automatic approval only when every rule passes, duplicate detection
  under a PostgreSQL advisory lock.
- React review app: a queue with leases, corrections, decisions and an append-only audit trail.
- Content-addressed model-result cache, Redis token-bucket rate limits, OpenTelemetry tracing.
- Evaluation on CORD: 52% approved automatically with no wrong totals (prompt 2).
- AWS in Terraform: S3, Step Functions, container Lambdas, DynamoDB, KMS, canary deploys, alarms;
  tested in CI without an AWS account.
- Serving benchmark for the OCR model.
