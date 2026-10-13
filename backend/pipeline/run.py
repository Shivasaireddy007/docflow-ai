"""Runs one document through the pipeline: pages -> OCR -> extraction -> confidence -> saved result.

Each model step goes through the content-addressed cache, so content already seen by the same
version of a step is not sent to the model again.
"""

import time
from collections.abc import Callable

from django.conf import settings
from opentelemetry import trace

from documents.models import Document, Extraction
from documents.storage import get_storage
from pipeline import confidence, files, schema
from pipeline.cache import ResultCache, get_result_cache, sha256
from pipeline.providers import (
    ExtractionProvider,
    OcrProvider,
    default_providers,
    extraction_version,
    ocr_version,
    pipeline_version,
)

ProvidersFactory = Callable[[], tuple[OcrProvider, ExtractionProvider]]

# Swapped in tests for fakes; points at Ollama otherwise.
providers: ProvidersFactory = default_providers
result_cache: Callable[[], ResultCache] = get_result_cache

tracer = trace.get_tracer("docflow.pipeline")


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def process(document: Document) -> Extraction:
    ocr, extract = providers()
    cache = result_cache()
    with tracer.start_as_current_span("pipeline.render") as span:
        data = get_storage().get(document.storage_key)
        pages = files.to_pages(data, document.content_type, settings.MAX_PAGES)
        span.set_attribute("docflow.pages", len(pages))

    started = time.perf_counter()
    with tracer.start_as_current_span("pipeline.ocr") as span:
        key = cache.key("ocr", document.tenant_id, ocr_version(), sha256(*pages))
        read = cache.get_or_compute(key, lambda: ocr(pages))
        span.set_attributes({"docflow.model": settings.OCR_MODEL, "docflow.cache_hit": read.hit})
    text: str = read.value
    ocr_ms = _ms(started)

    started = time.perf_counter()
    with tracer.start_as_current_span("pipeline.extract") as span:
        key = cache.key("extraction", document.tenant_id, extraction_version(), sha256(text.encode()))
        extracted = cache.get_or_compute(key, lambda: extract(text))
        span.set_attributes({"docflow.model": settings.EXTRACTION_MODEL, "docflow.cache_hit": extracted.hit})
    receipt = schema.coerce(extracted.value)
    extraction_ms = _ms(started)

    with tracer.start_as_current_span("pipeline.score") as span:
        fields, items, document_confidence = confidence.score(receipt, text)
        span.set_attribute("docflow.confidence", document_confidence)
    return Extraction.objects.create(
        document=document,
        pipeline_version=pipeline_version(),
        ocr_text=text,
        fields=fields,
        line_items=items,
        confidence=document_confidence,
        ocr_ms=ocr_ms,
        extraction_ms=extraction_ms,
        ocr_cached=read.hit,
        extraction_cached=extracted.hit,
    )
