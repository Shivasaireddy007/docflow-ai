# Architecture decisions

Short records of the choices that shape docflow: what was decided, why, and what it costs.

| # | Decision |
|---|---|
| [1](0001-verifiable-confidence.md) | Confidence comes from checks anyone can verify, not from the model |
| [2](0002-content-addressed-model-cache.md) | Model results are cached by content and step version |
| [3](0003-postgres-job-queue.md) | A PostgreSQL job queue with SKIP LOCKED, not a message broker |
| [4](0004-rules-as-versioned-data.md) | Approval rules are versioned data, not code |
| [5](0005-django-system-of-record.md) | On AWS, Step Functions processes and the Django app decides |
| [6](0006-self-hosted-models.md) | Self-hosted open models behind an OpenAI-compatible API |
| [7](0007-evaluation-before-prompts.md) | Prompts change only with an evaluation run behind them |
