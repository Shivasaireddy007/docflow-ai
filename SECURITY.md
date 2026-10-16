# Security

## Reporting a vulnerability

Please report security problems privately through GitHub:
[Report a vulnerability](https://github.com/Shivasaireddy007/docflow-ai/security/advisories/new).
Don't open a public issue.

Include what an attacker could do, the steps to reproduce, and the version or commit. You'll get
an acknowledgement within a few days and a fix or a plan within two weeks for confirmed issues.

## Supported versions

Only the latest release on `main` gets security fixes.

## Scope

In scope: the API and review app (tenant isolation, authentication, CSRF, uploads), the pipeline's
signed callback from AWS, and the Terraform in `infra/`. The public demo is a read-only copy whose
data resets on every restart; reports about its content or availability are out of scope.

## How the design handles security

- Every query is scoped to the caller's tenant; another tenant's document is a 404.
- API keys are stored only as hashes and compared in constant time. Reviewers use HttpOnly,
  SameSite session cookies with CSRF protection.
- Upload types come from the file's bytes, not its name; damaged files are rejected.
- Results from AWS are accepted only with a valid HMAC-SHA256 signature less than five minutes old.
- The audit table rejects UPDATE and DELETE at the database level.
- On AWS, data is encrypted with a customer-managed KMS key and deploys use GitHub OIDC, with no
  long-lived keys.
