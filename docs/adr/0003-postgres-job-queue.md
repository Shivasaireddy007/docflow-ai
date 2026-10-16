# 3. A PostgreSQL job queue with SKIP LOCKED, not a message broker

**Context.** Uploads must be processed exactly once, survive crashes, retry with backoff, and let
several workers run side by side. Locally the stack should stay small.

**Decision.** A `jobs` table claimed with `SELECT … FOR UPDATE SKIP LOCKED`. The claim commits
before the model call, so no lock is held for the seconds a model takes; a job whose worker died is
reclaimed when its lock times out; failures back off exponentially; a broken file or a model that
can't stop repeating fails at once instead of retrying.

**Consequences.** The job and the document change in the same database, with transactions, and no
extra service to run. It is fine for hundreds of documents a minute; beyond that, or on AWS, the
same pipeline runs in Step Functions (ADR 5).

**Alternatives.** Celery with Redis or RabbitMQ (another service, and at-least-once delivery to
handle anyway); SQS (cloud-only, so different locally).
