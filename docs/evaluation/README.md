# Evaluation

The pipeline is measured on the 100 labelled receipts of the
[CORD](https://huggingface.co/datasets/naver-clova-ix/cord-v2) test set: real photos of Indonesian
receipts, crumpled and shadowed, with the store details blurred by the dataset. Every run goes
through the production code (pages, OCR, extraction, confidence checks, default rules) and is
compared field by field with the labels:

```bash
cd backend && uv run python -m evaluation.run --limit 100 --out ../docs/evaluation/<name>
```

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

## What the numbers say

- **The checks are what makes automation safe.** The models alone get about one total in six
  wrong; none of those were approved automatically in either run, because a wrong total is either
  missing from the OCR text or breaks the receipt's arithmetic.
- **The threshold is set from data.** With prompt 2, approving at confidence 0.5 would let 2 wrong
  totals through; from 0.6 up there are none. The default, 0.9, keeps a margin.
- **Where it still fails:** receipts where OCR loses the layout (labels and amounts in separate
  columns), and totals that are blurred or cut off. Those go to a person, which is the design.

## Speed and cost (prompt 1, all cold)

On the laptop, one document at a time: OCR p50 10.0 s, extraction p50 13.1 s, whole document p50
23.6 s, p95 53.9 s. A document whose content was processed before by the same versions takes
under a millisecond, from the cache. Throughput on a GPU server is in [`../../bench/`](../../bench/).

During the run, the OCR model fell into a repetition loop ("0000…") on 3 receipts; each was read
again with anti-repetition sampling and processed normally.
