"""OpenTelemetry tracing: requests, SQL, Redis, model calls and the pipeline's own steps.

On when OTEL_EXPORTER_OTLP_ENDPOINT is set (Jaeger locally, the ADOT collector on AWS); without
it the tracer is a no-op and costs nothing.
"""

import os


def install(service: str) -> None:
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.django import DjangoInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    DjangoInstrumentor().instrument()
    PsycopgInstrumentor().instrument(enable_commenter=True)
    HTTPXClientInstrumentor().instrument()
    RedisInstrumentor().instrument()
