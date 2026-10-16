# 7. Prompts change only with an evaluation run behind them

**Context.** A prompt edit that fixes one receipt can break ten others, and it's invisible without
measurement.

**Decision.** Every prompt version is evaluated on labelled receipts with the production code,
and the result is committed with it: per-field precision and
recall, the auto-approval rate and its error rate, and how many wrong totals reached a person. Two
datasets with different conventions (CORD: rupiah without decimals; SROIE: ringgit with two).

**Consequences.** Prompt 2 was driven by prompt 1's measured mistakes. SROIE then showed prompt 2
reading 38.90 as 3890 (49% of totals right), which CORD, printed without decimals, could never have
revealed; prompt 3 fixed it (96%) and left CORD unchanged within noise. The same run exposed a
grounding bug outside the prompt: RM193.00 wasn't matched to 193, so correct totals went to a
person; fixing it raised SROIE auto-approval from 13% to 52%, still with no wrong totals.
A run takes about an hour of model time on a laptop, half that when the OCR is cached, and a
minute to rescore when only the checks change.

**Alternatives.** Spot-checking a few receipts by eye (how prompt 1's problems would have shipped).
