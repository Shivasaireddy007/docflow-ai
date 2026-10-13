"""Where the AWS pipeline reports results: POST /api/v1/internal/pipeline-results.

Not for clients: the request is authenticated by an HMAC signature over its raw body with
CALLBACK_SECRET (core/signing.py), not by an API key or session. The result then goes through
the same path as the local worker's: an Extraction, the audit trail, and the tenant's rules.
Step Functions retries a delivery that fails, so a repeat is acknowledged without effect.
"""

import json
import logging
from typing import Any

from django.conf import settings
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core import signing
from documents.models import Document, Extraction
from review import audit
from review.decisions import decide_automatically

log = logging.getLogger(__name__)
ACTOR = "pipeline:aws"
WAITING = (Document.Status.QUEUED, Document.Status.PROCESSING)


@extend_schema(exclude=True)
class PipelineResultView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        body: bytes = request._request.body
        if not signing.verify(
            settings.CALLBACK_SECRET,
            body,
            request.headers.get("X-Docflow-Timestamp", ""),
            request.headers.get("X-Docflow-Signature", ""),
        ):
            return Response({"detail": "Bad or expired signature."}, status=status.HTTP_401_UNAUTHORIZED)
        report: dict[str, Any] = json.loads(body)

        with transaction.atomic():
            document = (
                Document.objects.select_for_update()
                .filter(tenant_id=report["tenant_id"], sha256=report["sha256"])
                .first()
            )
            if document is None:
                # Uploaded straight to S3, not through the API: nothing here to update.
                return Response({"detail": "Unknown document."}, status=status.HTTP_404_NOT_FOUND)
            if document.status not in WAITING:
                return Response({"duplicate": True})
            if "error" in report:
                Document.objects.filter(pk=document.pk).update(
                    status=Document.Status.FAILED, error=report["error"]
                )
                audit.record(document.tenant, ACTOR, "failed", document, error=report["error"])
                return Response({"status": "failed"})

            result = report["result"]
            extraction = Extraction.objects.create(
                document=document,
                pipeline_version=result["pipeline_version"],
                ocr_text=result["ocr_text"],
                fields=result["fields"],
                line_items=result["line_items"],
                confidence=result["confidence"],
                ocr_ms=result["ocr_ms"],
                extraction_ms=result["extraction_ms"],
                ocr_cached=result["ocr_cached"],
                extraction_cached=result["extraction_cached"],
            )
            audit.record(
                document.tenant,
                ACTOR,
                "extracted",
                document,
                pipeline_version=extraction.pipeline_version,
                confidence=extraction.confidence,
                ms=extraction.ocr_ms + extraction.extraction_ms,
                cached={"ocr": extraction.ocr_cached, "extraction": extraction.extraction_cached},
                execution=report.get("execution", ""),
            )
            decision = decide_automatically(document, extraction)
        return Response({"status": decision.outcome})
