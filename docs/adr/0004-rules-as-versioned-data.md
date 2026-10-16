# 4. Approval rules are versioned data, not code

**Context.** Each customer wants different limits ("anything over ₹50,000 needs a person"), and an
auditor will ask why a document was approved months later.

**Decision.** Rules are JSON (`{"type": "max_amount", "field": "total", "max": 50000}`) from a
small set of types, validated before publishing. Publishing creates a new version; versions are
never edited; one is active per tenant (a partial unique index). Every decision stores the version
and the result of every rule.

**Consequences.** Admins change policy without a deploy, and history stays explainable. New kinds
of rule still need code (a new type), which is deliberate: rule types are reviewed, rule values
aren't.

**Alternatives.** Rules in code (a deploy per policy change); a general expression language
(powerful, but hard to validate and to explain to an auditor).
