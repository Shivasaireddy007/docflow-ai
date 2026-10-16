# 5. On AWS, Step Functions processes and the Django app decides

**Context.** The serverless pipeline (S3, Step Functions, Lambda, DynamoDB) scales to zero and
retries well, but the review queue, rules, users and audit trail live in the Django app. Two places
deciding would mean two rule engines and two audit trails.

**Decision.** Django is the system of record. On AWS, an upload goes to S3, which starts the state
machine; the final step reports the scored extraction to the app over HTTPS, signed with HMAC over
a timestamp and the body, and the app applies the tenant's rules exactly as it does for its local
worker. Failures are reported the same way. `PROCESSING_BACKEND` switches between the local worker
and Step Functions.

**Consequences.** One rules engine, one review queue, one audit trail, wherever processing runs.
The pipeline depends on the app being reachable; reports retry with backoff, and the app treats a
repeated report as a no-op. A standalone mode (rules from S3, results in DynamoDB) remains for
running the pipeline without the app.

**Alternatives.** Django reads results from DynamoDB (two sources of truth); Lambdas write to
PostgreSQL directly (VPC, connection limits, RDS Proxy, and business logic duplicated in Lambda).
