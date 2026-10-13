"""Scoring extractions against labels, and summarising a run."""

import statistics
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from evaluation.truth import EVALUATED_FIELDS, Truth

TOLERANCE = 0.5  # amounts are whole rupiah; anything closer than half a unit is the same number


def same(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) < TOLERANCE


@dataclass
class FieldScore:
    """For one field across the run. Precision: of the values extracted, how many were right.
    Recall: of the values on the receipts, how many were extracted right."""

    labelled: int
    extracted: int
    correct: int

    @property
    def precision(self) -> float | None:
        return self.correct / self.extracted if self.extracted else None

    @property
    def recall(self) -> float | None:
        return self.correct / self.labelled if self.labelled else None


def score_fields(rows: list[dict[str, Any]]) -> dict[str, FieldScore]:
    scores = {}
    for name in EVALUATED_FIELDS:
        labelled = extracted = correct = 0
        for row in rows:
            want, got = row["truth"][name], row["extracted"][name]
            labelled += want is not None
            extracted += got is not None
            correct += want is not None and same(got, want)
        scores[name] = FieldScore(labelled, extracted, correct)
    return scores


def score_items(predicted: list[float], truth: list[float]) -> tuple[int, int, int]:
    """(matched, predicted, labelled) line-item amounts, matched as multisets."""
    remaining = Counter(round(a) for a in truth)
    matched = 0
    for amount in predicted:
        if remaining[round(amount)] > 0:
            remaining[round(amount)] -= 1
            matched += 1
    return matched, len(predicted), len(truth)


def percentile(values: list[float], p: int) -> float | None:
    if len(values) < 2:
        return values[0] if values else None
    return statistics.quantiles(values, n=100, method="inclusive")[p - 1]


def row_for(truth: Truth, extracted: dict[str, Any], item_amounts: list[float]) -> dict[str, Any]:
    return {
        "truth": truth.fields,
        "extracted": {name: extracted.get(name) for name in EVALUATED_FIELDS},
        "total_correct": truth.fields["total"] is not None
        and same(extracted.get("total"), truth.fields["total"]),
        "items": score_items(item_amounts, truth.item_amounts),
    }


def decision_summary(rows: list[dict[str, Any]], approved_key: str = "auto_approved") -> dict[str, Any]:
    """How the rules' decisions compare with the truth, judged on the total (what gets paid)."""
    labelled = [r for r in rows if r["truth"]["total"] is not None]
    approved = [r for r in labelled if r[approved_key]]
    wrong = [r for r in labelled if not r["total_correct"]]
    return {
        "documents": len(labelled),
        "auto_approved": len(approved),
        "auto_approve_rate": len(approved) / len(labelled) if labelled else None,
        "wrong_auto_approvals": sum(not r["total_correct"] for r in approved),
        "auto_approval_error_rate": (sum(not r["total_correct"] for r in approved) / len(approved))
        if approved
        else None,
        "wrong_totals": len(wrong),
        "wrong_totals_caught": sum(not r[approved_key] for r in wrong),
    }


def as_dict(scores: dict[str, FieldScore]) -> dict[str, Any]:
    return {name: {**asdict(s), "precision": s.precision, "recall": s.recall} for name, s in scores.items()}
