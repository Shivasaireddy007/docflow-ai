"""The Step Functions steps, one container Lambda each: prepare -> ocr -> extract -> decide.

Steps hand each other S3 keys, not content: page images, OCR text and fields live under
work/<tenant>/<sha256>/, because a state machine's payload is capped at 256 KB. Every step is
safe to retry: they read inputs and write outputs at fixed, content-addressed keys.

Results live in DynamoDB, one item per document keyed "<tenant>#<sha256>", with indexes for
listing a tenant's documents by upload time and the review queue by status.

With CALLBACK_URL set (the usual deployment), the pipeline is the processing tier of the review
app: `decide` sends the scored extraction to the app, signed with the callback secret, and the app
applies the tenant's rules, queue and audit trail; `report_failure` tells it about failures.
Without it, `decide` applies rules from config/rules/<tenant>.json itself (standalone mode).
"""

import hashlib
import json
import logging
import os
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import httpx  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402
from django.conf import settings  # noqa: E402

from core import signing  # noqa: E402
from lambdas import aws  # noqa: E402
from pipeline import confidence, files, schema  # noqa: E402
from pipeline.cache import ResultCache, sha256  # noqa: E402
from pipeline.providers import (  # noqa: E402
    ExtractionProvider,
    OcrProvider,
    default_providers,
    extraction_version,
    ocr_version,
    pipeline_version,
)
from review import rules  # noqa: E402

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

Event = dict[str, Any]


class CallbackError(Exception):
    """The review app didn't accept a report; Step Functions retries the step."""


def providers() -> tuple[OcrProvider, ExtractionProvider]:
    return default_providers()  # replaced in tests


def _callback_secret() -> str:
    if secret := os.environ.get("CALLBACK_SECRET"):
        return secret
    value: str = aws.secrets().get_secret_value(SecretId=os.environ["CALLBACK_SECRET_ARN"])["SecretString"]
    os.environ["CALLBACK_SECRET"] = value  # fetched once per container
    return value


def report(payload: dict[str, Any]) -> None:
    """Sends a signed report to the review app. A 404 means the document was uploaded straight to
    S3 rather than through the app, so there is nothing to update there."""
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", **signing.sign(_callback_secret(), body)}
    try:
        response = httpx.post(os.environ["CALLBACK_URL"], content=body, headers=headers, timeout=20)
    except httpx.HTTPError as exc:
        raise CallbackError(f"Review app unreachable: {exc}") from exc
    if response.status_code == 404:
        log.warning("Review app doesn't know %s#%s", payload["tenant_id"], payload["sha256"])
        return
    if response.status_code >= 300:
        raise CallbackError(f"Review app answered {response.status_code}: {response.text[:200]}")


def _cache() -> ResultCache:
    return ResultCache(aws.DynamoStore(aws.cache_table()), settings.RESULT_CACHE_SECONDS)


def _work(event: Event, name: str) -> str:
    return f"work/{event['tenant']}/{event['doc_hash']}/{name}"


def _get(key: str) -> bytes:
    body: bytes = aws.s3().get_object(Bucket=aws.bucket(), Key=key)["Body"].read()
    return body


def _put(key: str, data: bytes, content_type: str) -> None:
    aws.s3().put_object(Bucket=aws.bucket(), Key=key, Body=data, ContentType=content_type)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _dynamo(value: Any) -> Any:
    """DynamoDB stores numbers as Decimal and refuses floats."""
    return json.loads(json.dumps(value), parse_float=Decimal)


def prepare(event: Event, context: object = None) -> Event:
    """Checks the upload, renders its pages, and claims the document. `skip` when this exact file
    was already processed for the tenant (uploads are deduplicated by content)."""
    key: str = event["key"]
    parts = key.split("/")
    if len(parts) < 4 or parts[0] != "tenants" or parts[2] != "uploads":
        raise files.UnsupportedFile(f"Uploads go to tenants/<tenant>/uploads/, not {key}")
    tenant = parts[1]

    data = _get(key)
    content_type = files.sniff(data)
    if content_type is None:
        raise files.UnsupportedFile("Not a PDF, PNG, JPEG or WebP file.")
    if files.page_count(data, content_type) > settings.MAX_PAGES:
        raise files.UnsupportedFile(f"Documents can have up to {settings.MAX_PAGES} pages.")
    doc_hash = hashlib.sha256(data).hexdigest()
    out = {"tenant": tenant, "doc_hash": doc_hash, "pk": f"{tenant}#{doc_hash}"}

    claim: dict[str, Any] = {}
    if not event.get("force"):  # reprocessing a known file skips the dedup condition
        claim = {
            # A failed document may be retried; anything else has been (or is being) processed.
            "ConditionExpression": "attribute_not_exists(pk) OR #s = :failed",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {":failed": "failed"},
        }
    try:
        aws.results_table().put_item(
            Item={
                "pk": out["pk"],
                "tenant_id": tenant,
                "doc_hash": doc_hash,
                "status": "processing",
                "filename": parts[-1],
                "source_key": key,
                "content_type": content_type,
                "uploaded_at": _now(),
            },
            **claim,
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        log.info("Already processed: %s", out["pk"])
        return {**out, "skip": True}

    pages = files.to_pages(data, content_type, settings.MAX_PAGES)
    page_keys = []
    for number, page in enumerate(pages, start=1):
        page_key = _work(out, f"page-{number}.png")
        _put(page_key, page, files.PNG)
        page_keys.append(page_key)
    return {**out, "skip": False, "pages": page_keys}


def ocr(event: Event, context: object = None) -> Event:
    pages = [_get(key) for key in event["pages"]]
    reader, _ = providers()
    cache = _cache()
    started = time.perf_counter()
    result = cache.get_or_compute(
        cache.key("ocr", event["tenant"], ocr_version(), sha256(*pages)), lambda: reader(pages)
    )
    ms = round((time.perf_counter() - started) * 1000)
    _put(_work(event, "ocr.txt"), result.value.encode(), "text/plain; charset=utf-8")
    return {**event, "ocr_key": _work(event, "ocr.txt"), "ocr_cached": result.hit, "ocr_ms": ms}


def extract(event: Event, context: object = None) -> Event:
    text = _get(event["ocr_key"]).decode()
    _, extractor = providers()
    cache = _cache()
    key = cache.key("extraction", event["tenant"], extraction_version(), sha256(text.encode()))
    started = time.perf_counter()
    result = cache.get_or_compute(key, lambda: extractor(text))
    ms = round((time.perf_counter() - started) * 1000)
    _put(_work(event, "fields.json"), json.dumps(result.value).encode(), "application/json")
    fields_key = _work(event, "fields.json")
    return {**event, "fields_key": fields_key, "extraction_cached": result.hit, "extraction_ms": ms}


def _tenant_rules(tenant: str) -> tuple[list[dict[str, Any]], str]:
    """config/rules/<tenant>.json in the bucket (versioned: the S3 version id is the rules version),
    or the defaults."""
    try:
        obj = aws.s3().get_object(Bucket=aws.bucket(), Key=f"config/rules/{tenant}.json")
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"NoSuchKey", "404"}:
            raise
        return rules.DEFAULT_RULES, "default"
    return rules.validate(json.loads(obj["Body"].read())), str(obj.get("VersionId") or "unversioned")


def _claim_fingerprint(tenant: str, fingerprint: str, pk: str) -> str | None:
    """Atomically records an approved receipt's fingerprint; returns the document that already
    holds it, if any. The conditional write is what stops two copies both being approved."""
    table = aws.results_table()
    try:
        table.put_item(
            Item={"pk": f"fingerprint#{tenant}#{fingerprint}", "document": pk},
            ConditionExpression="attribute_not_exists(pk) OR document = :me",
            ExpressionAttributeValues={":me": pk},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        holder = table.get_item(Key={"pk": f"fingerprint#{tenant}#{fingerprint}"}).get("Item") or {}
        return str(holder.get("document", "another document"))
    return None


def decide(event: Event, context: object = None) -> Event:
    text = _get(event["ocr_key"]).decode()
    receipt = schema.coerce(json.loads(_get(event["fields_key"])))
    fields, items, document_confidence = confidence.score(receipt, text)
    if os.environ.get("CALLBACK_URL"):
        return _report_to_app(event, text, fields, items, document_confidence)
    rule_list, rules_version = _tenant_rules(event["tenant"])

    fingerprint = rules.fingerprint(fields)
    context_ = rules.Context(
        document_confidence, find_duplicate=lambda _f: None, today=datetime.now(UTC).date()
    )
    results = rules.evaluate(rule_list, fields, context_)
    checks_duplicates = any(rule["type"] == "unique_receipt" for rule in rule_list)
    if (
        all(r.passed for r in results)
        and fingerprint
        and checks_duplicates
        and (duplicate_of := _claim_fingerprint(event["tenant"], fingerprint, event["pk"]))
    ):
        results = [
            rules.RuleResult(r.rule_id, r.type, False, f"same merchant, date and total as {duplicate_of}")
            if r.type == "unique_receipt"
            else r
            for r in results
        ]
    approved = all(r.passed for r in results)
    outcome = "auto_approved" if approved else "needs_review"

    values = {
        "status": outcome,
        "fields": fields,
        "line_items": items,
        "confidence": document_confidence,
        "rule_results": [r.as_dict() for r in results],
        "rules_version": rules_version,
        "pipeline_version": pipeline_version(),
        "cached": {
            "ocr": event.get("ocr_cached", False),
            "extraction": event.get("extraction_cached", False),
        },
        "decided_at": _now(),
    }
    # Every name goes through a placeholder: several (status, fields, ...) are DynamoDB reserved words.
    aws.results_table().update_item(
        Key={"pk": event["pk"]},
        UpdateExpression="SET " + ", ".join(f"#{name} = :{name}" for name in values),
        ExpressionAttributeNames={f"#{name}": name for name in values},
        ExpressionAttributeValues=_dynamo({f":{name}": value for name, value in values.items()}),
    )
    # CloudWatch embedded metric format: a log line that becomes metrics, no API calls needed.
    metric_definition = {
        "Namespace": "docflow",
        "Dimensions": [["Outcome"]],
        "Metrics": [{"Name": "Documents", "Unit": "Count"}, {"Name": "Confidence", "Unit": "None"}],
    }
    emf = {"Timestamp": int(datetime.now(UTC).timestamp() * 1000), "CloudWatchMetrics": [metric_definition]}
    print(json.dumps({"_aws": emf, "Outcome": outcome, "Documents": 1, "Confidence": document_confidence}))
    return {"pk": event["pk"], "status": outcome, "confidence": document_confidence}


def _report_to_app(
    event: Event, text: str, fields: dict[str, Any], items: list[dict[str, Any]], document_confidence: float
) -> Event:
    """Integrated mode: the review app applies the rules; this reports the extraction and records it."""
    report(
        {
            "tenant_id": event["tenant"],
            "sha256": event["doc_hash"],
            "execution": event.get("execution", ""),
            "result": {
                "pipeline_version": pipeline_version(),
                "ocr_text": text,
                "fields": fields,
                "line_items": items,
                "confidence": document_confidence,
                "ocr_ms": event.get("ocr_ms", 0),
                "extraction_ms": event.get("extraction_ms", 0),
                "ocr_cached": event.get("ocr_cached", False),
                "extraction_cached": event.get("extraction_cached", False),
            },
        }
    )
    values = {"status": "reported", "confidence": document_confidence, "pipeline_version": pipeline_version()}
    aws.results_table().update_item(
        Key={"pk": event["pk"]},
        UpdateExpression="SET " + ", ".join(f"#{name} = :{name}" for name in values),
        ExpressionAttributeNames={f"#{name}": name for name in values},
        ExpressionAttributeValues=_dynamo({f":{name}": value for name, value in values.items()}),
    )
    return {"pk": event["pk"], "status": "reported", "confidence": document_confidence}


def report_failure(event: Event, context: object = None) -> Event:
    """Failure path: tells the review app the document failed, so it isn't left waiting."""
    if os.environ.get("CALLBACK_URL") and "tenant" in event and "doc_hash" in event:
        error = event.get("error") or {}
        report(
            {
                "tenant_id": event["tenant"],
                "sha256": event["doc_hash"],
                "error": f"{error.get('Error', 'Failed')}: {str(error.get('Cause', ''))[:500]}",
            }
        )
    return event
