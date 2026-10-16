# 1. Confidence comes from checks anyone can verify, not from the model

**Context.** A receipt can be approved without a person only if we trust its fields. Language
models don't report calibrated confidence: asked how sure they are, they say "very" about invented
numbers too, and token probabilities from constrained JSON decoding say little about whether the
value is on the page.

**Decision.** Score every extracted field with three checks: *grounded* (the value is in the OCR
text, matched the way receipts print numbers), *valid* (well-formed: a real date, a non-negative
amount), and *consistent* (the receipt's own arithmetic agrees: items sum to the subtotal; subtotal
+ tax + service − discount = total; cash − change = total). A document is as confident as its
weakest field, and a receipt without a total is never auto-approvable. The penalties are set by hand.
A logistic regression fitted to the same checks on CORD was better calibrated on CORD but worse on
SROIE receipts it never saw (expected calibration error 0.107 against the hand-set 0.043), so the
hand-set penalties stay ([calibration](../evaluation/calibration/README.md)).

**Consequences.** An invented or misread total fails twice: it isn't on the page and it breaks the
arithmetic. On both datasets (100 receipts each), no wrong total was auto-approved. The cost is that correct receipts
whose arithmetic can't be checked (no subtotal printed) go to a person, and the checks depend on
OCR quality: a value the OCR dropped can't be grounded.

**Alternatives.** Ask the model for a confidence (uncalibrated); use token log-probabilities (not
available from every server, and they measure the decoder's certainty, not the document); a second
model to verify the first (doubles the cost, and correlated errors).
