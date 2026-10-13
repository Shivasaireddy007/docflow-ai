# docflow-ai

[![CI](https://github.com/Shivasaireddy007/docflow-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/Shivasaireddy007/docflow-ai/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

![Python](https://img.shields.io/badge/Python_3.12-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django_REST-092E20?logo=django&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-000000?logo=ollama&logoColor=white)
![React](https://img.shields.io/badge/React_+_TypeScript-20232A?logo=react&logoColor=61DAFB)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)

A document-intelligence pipeline for receipts and invoices: upload a document, and self-hosted
models read it (OCR), extract its fields, and score each field's confidence with checks you can
verify. Versioned rules approve what they can; everything else goes to a review queue where a
person corrects and decides, with every step in an append-only audit trail.

![Reviewing a receipt: the model swapped subtotal and total, and the arithmetic check flags both](docs/images/review.png)

| Review queue | Rules |
|---|---|
| ![Queue with confidence and the rules each document failed](docs/images/queue.png) | ![Versioned rules in plain language](docs/images/rules.png) |

## Status

Built in stages; each is complete and tested before the next starts.

| Stage | Scope | Status |
|---|---|---|
| 1 | Django REST API, tenants and API keys, uploads to S3 (RustFS locally), OCR and extraction with self-hosted models, confidence checks, job queue, Docker, CI | ✅ Done |
| 2 | Versioned validation rules, auto-approve vs. human review, React reviewer UI, audit trail | ✅ Done |
| 3 | Content-addressed result cache, rate limiting, tracing, evaluation on a labelled public dataset | Next |
| 4 | AWS with Terraform: Step Functions and container Lambdas, DynamoDB, RDS, KMS, canary deploys, SLO alarms | |
| 5 | vLLM serving benchmark on a GPU; demo and release | |

## How it works

```mermaid
flowchart LR
    U[Upload] -->|"type from bytes, SHA-256"| S[(S3)]
    U --> Q[(PostgreSQL<br/>jobs)]
    Q -->|"SKIP LOCKED"| W[Worker]
    W --> O[OCR<br/>vision model]
    O --> X[Field extraction<br/>JSON-schema output]
    X --> C[Confidence checks]
    C --> RU{Versioned rules}
    RU -->|all pass| A[Approved]
    RU -->|any fail| H[Review queue]
    H -->|"claim, correct, decide"| A
    H --> RJ[Rejected]
```

Every step is written to an append-only audit trail.

## First results

Fifteen receipts from the public [CORD](https://huggingface.co/datasets/naver-clova-ix/cord-v2)
test set, photographed in real conditions (crumpled, shadowed), on an Apple M5 laptop with
`qwen2.5vl:3b` for OCR and `qwen2.5:7b` for extraction, under the default rules:

| | Receipts | Total correct |
|---|---|---|
| Approved automatically | 7 | 7 of 7: no wrong value was approved |
| Sent to review | 8 | 5; the other 3 were a swapped subtotal/total, a missing total and a receipt without a labelled total |

Every extraction the models got wrong went to a person, with the failed checks pointing at the
wrong fields. The cost is that some correct receipts are reviewed too; stage 3 measures that
trade-off on the full labelled test set. About 15 seconds per receipt (7 s OCR + 8 s extraction).

## Design decisions

### Pipeline

- **Confidence you can check, not the model's opinion.** Language models don't report calibrated
  confidence, so every extracted value is tested: is it actually in the OCR text (catches invented
  values), is it well-formed, and does the receipt's arithmetic agree (items add up to the
  subtotal; subtotal + tax + service − discount = total). A document is only as confident as its
  weakest field, and a receipt without a total is never auto-approvable.
- **Matching numbers the way receipts print them.** 56100 is found as `56.100`, `56,100`,
  `56 100` or `Rp56100`, but never inside another number (`500` in `12,500`) or glued to the
  number in the next column.
- **Deterministic, constrained models.** Temperature 0 and a fixed seed, so the same document
  gives the same result; extraction output is constrained to a JSON schema; output length is capped
  so a model that starts repeating itself stops.
- **Every result says what produced it.** Extractions store a pipeline version (OCR model,
  extraction model, prompt version), so results from a model upgrade can be compared or rolled back.
- **A queue that survives crashes.** Workers claim jobs with `SELECT … FOR UPDATE SKIP LOCKED`, so
  several run side by side without blocking each other; no row lock is held during the seconds a
  model takes. Failures retry with exponential backoff, a broken file fails at once, and a job left
  by a crashed worker is reclaimed when its lock times out.
- **Files judged by their bytes.** The type comes from the file's signature, not its name or
  Content-Type; damaged images and PDFs are rejected at upload; large pages are scaled down for the
  model.
- **Tenants are isolated.** Every query is scoped to the caller's tenant (other tenants' documents
  are a 404), storage keys are per tenant, and API keys are stored only as hashes and compared in
  constant time.
- **Uploads are idempotent.** Files are content-addressed (SHA-256) per tenant: uploading the same
  file again returns the existing document, including when two uploads race.

### Review

- **Rules are data, versioned per tenant.** A rule set is a list like
  `{"type": "max_amount", "field": "total", "max": 1000000}`, validated before it is published.
  Versions are never edited, a partial unique index allows one active version per tenant, and
  every decision records the version that made it, so "why was this approved?" always has an answer.
- **Approve only when every rule passes.** By default: a total is present, confidence ≥ 0.9, the
  arithmetic agrees, the amount is under a limit, and it isn't a duplicate. Anything else goes to
  the queue with the failed rules as the reasons.
- **Duplicates are caught across documents.** A second photo of an approved receipt (same merchant,
  date and total) goes to review. Two copies processed at the same moment can't both slip through:
  the check runs under a PostgreSQL advisory lock on the receipt's fingerprint.
- **Two reviewers never review the same document.** "Review next" leases the oldest unclaimed
  document with `SKIP LOCKED`; a lease left in a closed tab expires after 15 minutes. A decision is
  refused (`409`) if the document was already decided or someone else holds it.
- **Corrections are parsed like model output.** A reviewer typing `174.600` gets 174600, and the
  decision stores each change as `{"from": 194000, "to": 174600}`.
- **An audit trail that can't be rewritten.** Uploads, extractions, rule decisions, claims and
  reviews are recorded with who did them; a database trigger rejects any UPDATE or DELETE on the
  audit table, so not even a bug or an admin can change history.
- **Two kinds of caller.** Machines use API keys; reviewers sign in with a session cookie
  (HttpOnly, SameSite, CSRF-protected). The web app is served from the same origin as the API, so
  no tokens live in JavaScript.

## API

Authenticate with `Authorization: Api-Key <key>`. Interactive docs at `/api/docs/`; the spec is in
[`docs/openapi.yaml`](docs/openapi.yaml).

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/documents` | Upload a PDF, PNG, JPEG or WebP (`201`, or `200` if already uploaded) |
| GET | `/api/v1/documents` | List documents, newest first; `?status=queued\|processing\|extracted\|failed` |
| GET | `/api/v1/documents/{id}` | A document with its latest extraction: each field's value, confidence and checks |
| POST | `/api/v1/documents/{id}/reprocess` | Run it through the current pipeline again (not once decided) |
| GET | `/api/v1/documents/{id}/pages/{n}` | A page as an image |
| POST | `/api/v1/auth/login`, `/auth/logout`; GET `/auth/me` | Reviewer sessions |
| GET | `/api/v1/review/queue`, `/review/stats` | Documents waiting for review; approval and correction rates |
| POST | `/api/v1/review/next` | Claim the next document to review |
| GET | `/api/v1/review/documents/{id}` | Extraction, decisions and audit trail |
| POST | `/api/v1/review/documents/{id}/decision` | Approve or reject, with corrections |
| GET / POST | `/api/v1/rules` | Rule versions; publish a new one (admins) |
| GET | `/health`, `/ready` | Liveness and readiness |

## Running locally

You need Python 3.12 with [uv](https://docs.astral.sh/uv/), PostgreSQL and
[Ollama](https://ollama.com).

```bash
ollama pull qwen2.5vl:3b && ollama pull qwen2.5:7b    # about 8 GB

cd backend
uv sync
createdb docflow
uv run python manage.py migrate
uv run python manage.py create_tenant "Acme"           # prints an API key once
uv run python manage.py create_reviewer acme asha --admin
uv run python manage.py runserver                      # API at http://127.0.0.1:8000/api/docs/
uv run python manage.py run_worker                     # in another terminal
```

```bash
curl -H "Authorization: Api-Key <key>" -F "file=@receipt.jpg" http://127.0.0.1:8000/api/v1/documents

# Review app: http://localhost:5173 (proxies /api to the backend)
cd frontend && npm ci && npm run dev
```

### With Docker

```bash
docker compose up --build -d     # PostgreSQL, S3-compatible storage (RustFS), API, worker, web; Ollama on the host
docker compose exec api python manage.py create_tenant "Acme"
docker compose exec api python manage.py create_reviewer acme asha --admin   # review app at http://localhost:8080
scripts/smoke-test.sh <key>
```

## Tests and checks

```bash
cd backend && uv run pytest && uv run ruff check . && uv run mypy .
cd frontend && npm test && npm run typecheck && npm run lint
```

CI runs strict type checks, the backend tests against PostgreSQL, checks for missing migrations and
an up-to-date API spec and frontend types, the frontend tests, and the whole Docker Compose stack
with a stand-in for the models: an API smoke test, then a Playwright test where an admin tightens a
rule, uploads a receipt, and reviews what the rule sends to the queue.

## License

[MIT](LICENSE)
