"""Runs one document through the pipeline: pages -> OCR -> extraction -> confidence -> saved result."""

import time
from collections.abc import Callable

from django.conf import settings

from documents.models import Document, Extraction
from documents.storage import get_storage
from pipeline import confidence, files, schema
from pipeline.providers import ExtractionProvider, OcrProvider, default_providers, pipeline_version

ProvidersFactory = Callable[[], tuple[OcrProvider, ExtractionProvider]]

# Swapped in tests for fakes; points at Ollama otherwise.
providers: ProvidersFactory = default_providers


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def process(document: Document) -> Extraction:
    ocr, extract = providers()
    data = get_storage().get(document.storage_key)
    pages = files.to_pages(data, document.content_type, settings.MAX_PAGES)

    started = time.perf_counter()
    text = ocr(pages)
    ocr_ms = _ms(started)

    started = time.perf_counter()
    receipt = schema.coerce(extract(text))
    extraction_ms = _ms(started)

    fields, items, document_confidence = confidence.score(receipt, text)
    return Extraction.objects.create(
        document=document,
        pipeline_version=pipeline_version(),
        ocr_text=text,
        fields=fields,
        line_items=items,
        confidence=document_confidence,
        ocr_ms=ocr_ms,
        extraction_ms=extraction_ms,
    )
