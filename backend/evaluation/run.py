"""Evaluate the pipeline on CORD's labelled receipts.

    uv run python -m evaluation.run --limit 100          # writes docs/evaluation/

Runs the production code path (pages -> OCR -> extraction -> confidence -> default rules) with
the result cache, compares every field with the labels, and writes results.json and README.md.
A second pass over the same receipts measures the cache.

Model errors are retried with backoff, as the worker does. Each receipt's result is appended to
data/cord-eval/progress-<pipeline>.jsonl as it finishes, so an interrupted run resumes where it
stopped with its original timings; --fresh starts over.
"""

import argparse
import json
import os
import platform
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import httpx  # noqa: E402
from django.conf import settings  # noqa: E402
from django.utils import timezone  # noqa: E402

from evaluation import metrics, report, truth  # noqa: E402
from pipeline import confidence, files, schema  # noqa: E402
from pipeline.cache import get_result_cache, sha256  # noqa: E402
from pipeline.providers import (  # noqa: E402
    ModelError,
    ModelRepetition,
    default_providers,
    extraction_version,
    ocr_version,
    pipeline_version,
)
from review import rules  # noqa: E402

ROWS_URL = "https://datasets-server.huggingface.co/rows"
TENANT = "evaluation"
THRESHOLDS = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0]


def download(
    dataset: truth.Dataset, directory: Path, split: str, limit: int
) -> list[tuple[str, Path, dict[str, Any]]]:
    """A dataset's receipts and labels, fetched once and kept in `directory`."""
    directory.mkdir(parents=True, exist_ok=True)
    samples = []
    with httpx.Client(timeout=60, follow_redirects=True) as http:
        for offset in range(0, limit, 100):
            page = http.get(
                ROWS_URL,
                params={
                    "dataset": dataset.hf_id,
                    "config": "default",
                    "split": split,
                    "offset": offset,
                    "length": min(100, limit - offset),
                },
            )
            page.raise_for_status()
            for row in page.json()["rows"]:
                name = f"{split}-{row['row_idx']:03d}"
                image, label = directory / f"{name}.jpg", directory / f"{name}.json"
                if not image.exists():
                    image.write_bytes(http.get(row["row"]["image"]["src"]).content)
                if not label.exists():
                    label.write_text(json.dumps(dataset.label(row["row"]), ensure_ascii=False))
                samples.append((name, image, json.loads(label.read_text())))
    return samples


def evaluate_one(dataset: truth.Dataset, name: str, image: Path, gt: dict[str, Any]) -> dict[str, Any]:
    ocr, extract = default_providers()
    cache = get_result_cache()
    data = image.read_bytes()
    pages = files.to_pages(data, files.sniff(data) or files.JPEG, settings.MAX_PAGES)

    started = time.perf_counter()
    read = cache.get_or_compute(cache.key("ocr", TENANT, ocr_version(), sha256(*pages)), lambda: ocr(pages))
    ocr_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    text: str = read.value
    extracted = cache.get_or_compute(
        cache.key("extraction", TENANT, extraction_version(), sha256(text.encode())), lambda: extract(text)
    )
    extraction_ms = (time.perf_counter() - started) * 1000

    receipt = schema.coerce(extracted.value)
    fields, _, document_confidence = confidence.score(receipt, text)
    context = rules.Context(document_confidence, find_duplicate=lambda _f: None, today=timezone.localdate())
    results = rules.evaluate(rules.DEFAULT_RULES, fields, context)
    # The threshold sweep varies only the confidence rule; record whether everything else passed.
    others_pass = all(r.passed for r in results if r.type != "min_confidence")
    item_amounts = [amount for i in receipt.line_items if isinstance(amount := i.get("amount"), float)]

    return {
        "name": name,
        **metrics.row_for(dataset.parse(gt), receipt.fields, item_amounts),
        "scored": fields,  # value, confidence and checks per field: what calibration learns from
        "confidence": document_confidence,
        "auto_approved": all(r.passed for r in results),
        "other_rules_pass": others_pass,
        "failed_rules": [r.rule_id for r in results if not r.passed],
        "ocr_ms": round(ocr_ms),
        "extraction_ms": round(extraction_ms),
        "cached": {"ocr": read.hit, "extraction": extracted.hit},
    }


def unreadable(dataset: truth.Dataset, name: str, gt: dict[str, Any], error: str) -> dict[str, Any]:
    """A receipt the models couldn't read even with anti-repetition sampling: nothing extracted,
    so it would go to a person."""
    return {
        "name": name,
        **metrics.row_for(dataset.parse(gt), {}, []),
        "scored": {},
        "confidence": 0.0,
        "auto_approved": False,
        "other_rules_pass": False,
        "failed_rules": ["unreadable"],
        "ocr_ms": 0,
        "extraction_ms": 0,
        "cached": {"ocr": False, "extraction": False},
        "error": error,
    }


def with_retries(
    dataset: truth.Dataset, name: str, image: Path, gt: dict[str, Any], attempts: int = 4
) -> dict[str, Any]:
    for attempt in range(1, attempts + 1):
        try:
            return evaluate_one(dataset, name, image, gt)
        except ModelRepetition as exc:
            return unreadable(dataset, name, gt, str(exc))
        except ModelError as exc:
            if attempt == attempts:
                raise
            wait = 5 * 2 ** (attempt - 1)
            print(f"    {name}: {exc}; retrying in {wait}s", flush=True)
            time.sleep(wait)
    raise AssertionError("unreachable")


def threshold_sweep(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sweep = []
    for threshold in THRESHOLDS:
        for row in rows:
            row["_approved"] = row["other_rules_pass"] and row["confidence"] >= threshold
        sweep.append({"threshold": threshold, **metrics.decision_summary(rows, "_approved")})
    for row in rows:
        row.pop("_approved", None)
    return sweep


def summarise(rows: list[dict[str, Any]], warm: list[dict[str, Any]]) -> dict[str, Any]:
    matched = sum(r["items"][0] for r in rows)
    predicted = sum(r["items"][1] for r in rows)
    labelled = sum(r["items"][2] for r in rows)
    read = [r for r in rows if "error" not in r]  # unreadable receipts have no model time to measure
    cold = [r["ocr_ms"] + r["extraction_ms"] for r in read if not any(r["cached"].values())]
    warm_ms = [r["ocr_ms"] + r["extraction_ms"] for r in warm]
    return {
        "fields": metrics.as_dict(metrics.score_fields(rows)),
        "line_items": {
            "matched": matched,
            "precision": matched / predicted if predicted else None,
            "recall": matched / labelled if labelled else None,
        },
        "decisions": metrics.decision_summary(rows),
        "threshold_sweep": threshold_sweep(rows),
        "latency_ms": {
            "ocr_p50": metrics.percentile([r["ocr_ms"] for r in read], 50),
            "ocr_p95": metrics.percentile([r["ocr_ms"] for r in read], 95),
            "extraction_p50": metrics.percentile([r["extraction_ms"] for r in read], 50),
            "extraction_p95": metrics.percentile([r["extraction_ms"] for r in read], 95),
            "document_p50": metrics.percentile(cold, 50),
            "document_p95": metrics.percentile(cold, 95),
            "cached_document_p50": metrics.percentile(warm_ms, 50),
            "cached_document_p95": metrics.percentile(warm_ms, 95),
        },
        "model_ms_per_document": round(sum(cold) / len(cold)) if cold else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    root = Path(__file__).resolve().parents[2]
    parser.add_argument("--dataset", choices=sorted(truth.DATASETS), default="cord")
    parser.add_argument("--split", default="test")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--data", type=Path, help="Where receipts are kept (default data/<dataset>-eval)")
    parser.add_argument("--out", type=Path, default=root / "docs" / "evaluation")
    parser.add_argument("--fresh", action="store_true", help="Ignore saved progress and start over")
    args = parser.parse_args()
    dataset = truth.DATASETS[args.dataset]
    args.data = args.data or root / "data" / f"{dataset.name}-eval"

    samples = download(dataset, args.data, args.split, args.limit)
    print(f"Evaluating {len(samples)} {dataset.name} receipts with {pipeline_version()}")
    progress = args.data / f"progress-{sha256(pipeline_version().encode())[:12]}.jsonl"
    if args.fresh:
        progress.unlink(missing_ok=True)
    done = (
        {row["name"]: row for row in map(json.loads, progress.read_text().splitlines())}
        if progress.exists()
        else {}
    )
    if done:
        print(f"Resuming: {len(done)} receipts already evaluated")
    rows = []
    for i, (name, image, gt) in enumerate(samples, start=1):
        if name in done:
            rows.append(done[name])
            continue
        row = with_retries(dataset, name, image, gt)
        with progress.open("a") as saved:
            saved.write(json.dumps(row) + "\n")
        rows.append(row)
        print(f"{i:3}/{len(samples)} {name} total={'ok' if row['total_correct'] else 'MISS':4} "
              f"conf={row['confidence']:.2f} {'auto' if row['auto_approved'] else 'review':6} "
              f"{row['ocr_ms'] / 1000:.1f}s+{row['extraction_ms'] / 1000:.1f}s", flush=True)  # fmt: skip

    print("Second pass (warm cache)")
    warm = [with_retries(dataset, name, image, gt) for name, image, gt in samples]

    result = {
        "run": {
            "date": datetime.now(UTC).isoformat(timespec="seconds"),
            "dataset": f"{dataset.hf_id} ({args.split}, {len(samples)} receipts)",
            "pipeline_version": pipeline_version(),
            "rules": rules.DEFAULT_RULES,
            "machine": f"{platform.machine()} {platform.system()} {platform.release()}",
        },
        "summary": summarise(rows, warm),
        "documents": rows,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(result, indent=1))
    (args.out / "README.md").write_text(report.render(result))
    print(f"Wrote {args.out / 'README.md'}")


if __name__ == "__main__":
    main()
