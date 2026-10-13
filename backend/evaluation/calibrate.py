"""Fit field confidence to data, and check it on a dataset it wasn't fitted on.

    uv run python -m evaluation.calibrate --train ../docs/evaluation/prompt-3 \\
        --test ../docs/evaluation/sroie-prompt-3 --out ../docs/evaluation/calibration

The pipeline scores each extracted field from three checks (grounded in the OCR text, well-formed,
consistent with the receipt's arithmetic). The hand-set penalties give a score, not a probability.
This fits a logistic regression on the same checks to P(field is correct), reports how well each
version is calibrated on the held-out dataset (expected calibration error, Brier score, and a
reliability table: of the fields scored 0.9-1.0, how many were right?), and writes the weights.
"""

import argparse
import json
import math
from pathlib import Path
from typing import Any

from evaluation import metrics

FEATURES = ["grounded", "valid", "consistent", "inconsistent"]  # "unchecked" is the baseline
BINS = 10


def features(checks: dict[str, Any]) -> list[float]:
    consistent = checks.get("consistent")
    return [float(bool(checks.get("grounded"))), float(bool(checks.get("valid"))),
            float(consistent is True), float(consistent is False)]  # fmt: skip


def samples(results: dict[str, Any]) -> list[tuple[list[float], float, bool]]:
    """(features, heuristic confidence, correct) for every extracted field that has a label."""
    out = []
    for row in results["documents"]:
        for name, want in row["truth"].items():
            scored = (row.get("scored") or {}).get(name) or {}
            if want is None or scored.get("value") is None or not scored.get("checks"):
                continue
            out.append(
                (
                    features(scored["checks"]),
                    float(scored["confidence"]),
                    metrics.matches(scored["value"], want),
                )
            )
    return out


def sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))


def fit(
    data: list[tuple[list[float], float, bool]], steps: int = 4000, rate: float = 0.5, l2: float = 1e-3
) -> list[float]:
    """Logistic regression by gradient descent: [bias, *weights]."""
    w = [0.0] * (len(FEATURES) + 1)
    n = len(data)
    for _ in range(steps):
        grad = [0.0] * len(w)
        for x, _, y in data:
            error = sigmoid(w[0] + sum(wi * xi for wi, xi in zip(w[1:], x, strict=True))) - float(y)
            grad[0] += error
            for i, xi in enumerate(x, start=1):
                grad[i] += error * xi
        w = [
            wi - rate * (g / n + (l2 * wi if i else 0)) for i, (wi, g) in enumerate(zip(w, grad, strict=True))
        ]
    return w


def predict(w: list[float], x: list[float]) -> float:
    return sigmoid(w[0] + sum(wi * xi for wi, xi in zip(w[1:], x, strict=True)))


def reliability(pairs: list[tuple[float, bool]]) -> tuple[list[dict[str, Any]], float, float]:
    """Bins of predicted confidence with the observed accuracy in each; ECE; Brier score."""
    table = []
    ece = 0.0
    for b in range(BINS):
        low, high = b / BINS, (b + 1) / BINS
        inside = [(p, y) for p, y in pairs if low <= p < high or (b == BINS - 1 and p == 1.0)]
        if not inside:
            continue
        mean_p = sum(p for p, _ in inside) / len(inside)
        accuracy = sum(y for _, y in inside) / len(inside)
        ece += len(inside) / len(pairs) * abs(mean_p - accuracy)
        table.append(
            {"bin": f"{low:.1f}-{high:.1f}", "fields": len(inside), "predicted": mean_p, "correct": accuracy}
        )
    brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
    return table, ece, brier


def evaluate(w: list[float], data: list[tuple[list[float], float, bool]]) -> dict[str, Any]:
    heuristic = [(conf, y) for _, conf, y in data]
    fitted = [(predict(w, x), y) for x, _, y in data]
    h_table, h_ece, h_brier = reliability(heuristic)
    f_table, f_ece, f_brier = reliability(fitted)
    return {
        "fields": len(data),
        "accuracy": sum(y for *_, y in data) / len(data),
        "heuristic": {"ece": h_ece, "brier": h_brier, "table": h_table},
        "fitted": {"ece": f_ece, "brier": f_brier, "table": f_table},
    }


def render(train: str, test: str, w: list[float], held_out: dict[str, Any], in_sample: dict[str, Any]) -> str:
    def rows(table: list[dict[str, Any]]) -> list[str]:
        return [f"| {r['bin']} | {r['fields']} | {r['predicted']:.2f} | {r['correct']:.0%} |" for r in table]

    lines = [
        "# Confidence calibration",
        "",
        f"Fitted on `{train}` ({in_sample['fields']} labelled fields); tested on `{test}` "
        f"({held_out['fields']} fields from a different dataset, never seen in fitting).",
        "",
        "| On the held-out dataset | Hand-set penalties | Fitted |",
        "|---|---|---|",
        f"| Expected calibration error (lower is better) | {held_out['heuristic']['ece']:.3f} | "
        f"**{held_out['fitted']['ece']:.3f}** |",
        f"| Brier score (lower is better) | {held_out['heuristic']['brier']:.3f} | "
        f"**{held_out['fitted']['brier']:.3f}** |",
        "",
        "## Reliability on the held-out dataset",
        "",
        "Of the fields given a confidence in each band, the share that were actually right. A calibrated",
        "score has the two columns close.",
        "",
        "Hand-set penalties:",
        "",
        "| Confidence | Fields | Mean confidence | Actually right |",
        "|---|---|---|---|",
        *rows(held_out["heuristic"]["table"]),
        "",
        "Fitted:",
        "",
        "| Confidence | Fields | Mean confidence | Actually right |",
        "|---|---|---|---|",
        *rows(held_out["fitted"]["table"]),
        "",
        "## Weights",
        "",
        f"P(correct) = sigmoid({w[0]:+.2f} "
        + " ".join(f"{wi:+.2f}·{name}" for wi, name in zip(w[1:], FEATURES, strict=True))
        + ")",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--train", type=Path, required=True, help="Evaluation folder to fit on")
    parser.add_argument("--test", type=Path, required=True, help="Evaluation folder to check on")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    train = samples(json.loads((args.train / "results.json").read_text()))
    test = samples(json.loads((args.test / "results.json").read_text()))
    w = fit(train)
    held_out, in_sample = evaluate(w, test), evaluate(w, train)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "weights.json").write_text(json.dumps({"features": FEATURES, "weights": w}, indent=1))
    (args.out / "results.json").write_text(
        json.dumps({"held_out": held_out, "in_sample": in_sample}, indent=1)
    )
    (args.out / "README.md").write_text(render(args.train.name, args.test.name, w, held_out, in_sample))
    print(
        f"held-out ECE {held_out['heuristic']['ece']:.3f} -> {held_out['fitted']['ece']:.3f}; "
        f"wrote {args.out}"
    )


if __name__ == "__main__":
    main()
