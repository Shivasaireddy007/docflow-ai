from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from rest_framework.test import APIClient

from documents import jobs
from pipeline import run
from tests.conftest import Models, image_bytes, upload


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(run, "tracer", provider.get_tracer("test"))
    yield exporter
    trace.get_tracer_provider()


def test_each_pipeline_step_is_traced(api: APIClient, models: Models, spans: InMemorySpanExporter) -> None:
    upload(api, image_bytes())
    jobs.run_once()

    recorded = {span.name: dict(span.attributes or {}) for span in spans.get_finished_spans()}
    assert list(recorded) == ["pipeline.render", "pipeline.ocr", "pipeline.extract", "pipeline.score"]
    assert recorded["pipeline.ocr"]["docflow.cache_hit"] is False
    assert recorded["pipeline.render"]["docflow.pages"] == 1
    assert recorded["pipeline.score"]["docflow.confidence"] == pytest.approx(0.95)
