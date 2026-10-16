# Evaluation

The pipeline is measured on two labelled public datasets with different conventions:

- [CORD](https://huggingface.co/datasets/naver-clova-ix/cord-v2): 100 test receipts, real photos
  of Indonesian receipts, crumpled and shadowed, store details blurred. Rupiah, no decimals
  (`56.100` is fifty-six thousand). Labels for every amount and line item.
- [SROIE](https://huggingface.co/datasets/jsdnrs/ICDAR2019-SROIE): 100 test receipts, scanned
  Malaysian receipts. Ringgit with two decimals (`38.90`). Labels for merchant, date and total.

Every run goes through the production code (pages, OCR, extraction, confidence checks, default
rules) and is compared field by field with the labels:

```bash
cd backend && uv run python -m evaluation.run --dataset cord|sroie --limit 100 --out ../docs/evaluation/<name>
```

## Current results (prompt 3)

| Judged on the total | [CORD](prompt-3/README.md) | [SROIE](sroie-prompt-3/README.md) |
|---|---|---|
| Totals extracted correctly (recall) | 82% | **96%** |
| Approved automatically | 53% | 52% |
| Wrong totals among the auto-approved | **0** | **0** |
| Wrong totals sent to a person instead | 16 of 16 | 4 of 4 |

Across both datasets: 100 of 191 receipts approved automatically (52%), none with a wrong total.

Models: `qwen2.5vl:3b` (OCR) and `qwen2.5:7b` (fields) through Ollama, on an Apple M5 laptop.

## Prompt 1 → prompt 2

Prompt 1's mistakes ([details](prompt-1/README.md)) had clear patterns: totals printed as `DUE`
weren't recognised, the CASH handed over was sometimes taken as the total, and when OCR listed
labels and amounts in separate columns the pairing was lost. Prompt 2 names the labels a total
goes by, says what is never the total, explains the column layout, and adds two fields, cash
paid and change, which give the confidence checks a second equation: **total = cash − change**.

| Judged on the total | Prompt 1 | [Prompt 2](prompt-2/README.md) |
|---|---|---|
| Totals extracted correctly (recall) | 76% | **85%** |
| Approved automatically | 42% | **52%** |
| Wrong totals among the auto-approved | **0** | **0** |
| Wrong totals sent to a person instead | 22 of 22 | 14 of 14 |

Prompt 2 is better on totals, subtotals (precision 69% → 85%) and approvals, and worse on service
charges (9 → 6 of 12 correct); totals matter most, so it is the default. Re-running the evaluation
for prompt 2 re-ran only extraction: the OCR came from the cache, because the cache key includes
each step's version and the OCR step hadn't changed.

## Prompt 2 → prompt 3: a second dataset finds what the first can't

On SROIE, [prompt 2](sroie/README.md) got only 49% of totals right: it read the decimal point in
`38.90` as a thousands separator and returned 3890. CORD, printed without decimals, could never
have shown this. The safety net held (the value isn't on the page, so all 51 wrong totals went to
a person), but it cost automation. Prompt 3 says how to tell the two separators apart (three
digits after it group thousands; one or two are decimals): SROIE totals went from 49% to 96%
correct, and CORD stayed the same within noise (77 → 75 of 91).

The same run exposed a bug outside the prompt. Correct totals like 193 were marked "not on the
page" because the receipt prints `RM193.00`, and the grounding check didn't try whole amounts
with zero cents. After the fix, the saved results were scored again with `--rescore` (model output
from the cache, model times kept): SROIE auto-approval rose from 13% to 52%, still with no wrong
totals.

## Calibration: fitted weights didn't generalise

The confidence score comes from hand-set penalties on the three checks. A
[logistic regression](calibration/README.md) fitted to the same checks on CORD was better
calibrated on CORD (expected calibration error 0.060 → 0.013) but worse on SROIE, which it never
saw (0.043 → 0.107). The hand-set penalties generalise better, so the pipeline keeps them.

## What the numbers say

- **The checks are what makes automation safe.** The models alone get up to half the totals
  wrong (SROIE, prompt 2); none of those were ever approved automatically, because a wrong total is either
  missing from the OCR text or breaks the receipt's arithmetic.
- **The threshold is set from data.** At confidence 0.5, wrong totals get approved on both
  datasets (2 on CORD, 1 on SROIE with prompt 3); from 0.6 up there are none. The default, 0.9, keeps a margin.
- **Where it still fails:** receipts where OCR loses the layout (labels and amounts in separate
  columns), and totals that are blurred or cut off. Those go to a person, which is the design.

## Speed and cost (prompt 1, all cold)

On the laptop, one document at a time: OCR p50 10.0 s, extraction p50 13.1 s, whole document p50
23.6 s, p95 53.9 s. A document whose content was processed before by the same versions takes
under a millisecond, from the cache. Throughput on a GPU server is in [`../../bench/`](../../bench/).

During the run, the OCR model fell into a repetition loop ("0000…") on 3 receipts; each was read
again with anti-repetition sampling and processed normally.
