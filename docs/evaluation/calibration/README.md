# Confidence calibration

Fitted on `prompt-3` (281 labelled fields); tested on `sroie-prompt-3` (293 fields from a different dataset, never seen in fitting).

| | Hand-set penalties | Fitted |
|---|---|---|
| Calibration error on `prompt-3`, fitted to | 0.060 | 0.013 |
| Calibration error on `sroie-prompt-3`, held out | 0.043 | 0.107 |
| Brier score on `sroie-prompt-3`, held out | 0.054 | 0.058 |

Lower is better for both. On receipts it wasn't fitted to, the hand-set penalties are better calibrated, so the pipeline keeps them.

## Reliability on the held-out dataset

Of the fields given a confidence in each band, the share that were actually right. A calibrated
score has the two columns close.

Hand-set penalties:

| Confidence | Fields | Mean confidence | Actually right |
|---|---|---|---|
| 0.2-0.3 | 1 | 0.25 | 0% |
| 0.5-0.6 | 8 | 0.51 | 25% |
| 0.7-0.8 | 26 | 0.70 | 100% |
| 0.9-1.0 | 258 | 0.96 | 95% |

Fitted:

| Confidence | Fields | Mean confidence | Actually right |
|---|---|---|---|
| 0.0-0.1 | 8 | 0.05 | 25% |
| 0.2-0.3 | 1 | 0.23 | 0% |
| 0.7-0.8 | 26 | 0.77 | 100% |
| 0.8-0.9 | 188 | 0.82 | 94% |
| 0.9-1.0 | 70 | 0.96 | 100% |

## Weights

P(correct) = sigmoid(-2.31 +4.54·grounded -0.69·valid +1.77·consistent -0.33·inconsistent)
