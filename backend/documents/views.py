import hashlib
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from documents import jobs
from documents.models import Document, Job
from documents.serializers import (
    DocumentDetailSerializer,
    DocumentSerializer,
    UploadResultSerializer,
    UploadSerializer,
)
from documents.storage import document_key, get_storage
from pipeline import files
from review import audit
from tenants.access import tenant_of

extend_schema_field(OpenApiTypes.OBJECT)(DocumentDetailSerializer.get_extraction)
extend_schema_field(OpenApiTypes.OBJECT)(DocumentDetailSerializer.get_decision)


class UnsupportedMediaType(ValidationError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE


class PayloadTooLarge(ValidationError):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE


class DocumentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet[Document]):
    """Your tenant's documents. Other tenants' documents don't exist as far as you can see (404)."""

    # Only for the API docs (types the {id} path parameter); requests always use get_queryset().
    queryset = Document.objects.none()

    def get_queryset(self) -> QuerySet[Document]:
        queryset = Document.objects.filter(tenant=tenant_of(self.request)).order_by("-created_at")
        if wanted := self.request.query_params.get("status"):
            queryset = queryset.filter(status=wanted)
        return queryset

    def get_serializer_class(self) -> type[DocumentSerializer]:
        return DocumentDetailSerializer if self.action == "retrieve" else DocumentSerializer

    @extend_schema(parameters=[OpenApiParameter("status", enum=Document.Status.values)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """List documents, newest first, optionally by status."""
        return super().list(request, *args, **kwargs)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """A document with its latest extraction: each field's value, confidence and checks."""
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        request={"multipart/form-data": UploadSerializer},
        responses={201: UploadResultSerializer, 200: UploadResultSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Upload a document for processing. `201` when new; `200` with the existing document if
        the same file was uploaded before. `413` if too large, `415` if not a supported type."""
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "Attach the document as `file`."})
        if upload.size is not None and upload.size > settings.MAX_UPLOAD_BYTES:
            raise PayloadTooLarge(
                {"file": f"Files can be up to {settings.MAX_UPLOAD_BYTES // 1_048_576} MB."}
            )
        data = upload.read()

        content_type = files.sniff(data)
        if content_type is None:
            raise UnsupportedMediaType({"file": "Upload a PDF, PNG, JPEG or WebP file."})
        try:
            pages = files.page_count(data, content_type)
        except files.UnsupportedFile as exc:
            raise UnsupportedMediaType({"file": str(exc)}) from exc
        if pages > settings.MAX_PAGES:
            raise ValidationError({"file": f"Documents can have up to {settings.MAX_PAGES} pages."})

        tenant = tenant_of(request)
        sha256 = hashlib.sha256(data).hexdigest()
        if existing := Document.objects.filter(tenant=tenant, sha256=sha256).first():
            return self._uploaded(existing, duplicate=True)

        # Stored before the row exists; the key is content-addressed, so a retry overwrites harmlessly.
        key = document_key(tenant.id, sha256)
        get_storage().put(key, data, content_type)
        try:
            with transaction.atomic():
                document = Document.objects.create(
                    tenant=tenant,
                    sha256=sha256,
                    filename=(upload.name or "document")[:255],
                    content_type=content_type,
                    size_bytes=len(data),
                    page_count=pages,
                    storage_key=key,
                )
                jobs.enqueue(document)
                audit.record(
                    tenant, audit.actor_of(request.user), "uploaded", document, filename=document.filename
                )
        except IntegrityError:
            # The same file was uploaded at the same moment by another request.
            return self._uploaded(Document.objects.get(tenant=tenant, sha256=sha256), duplicate=True)
        return self._uploaded(document, duplicate=False)

    def _uploaded(self, document: Document, *, duplicate: bool) -> Response:
        body = {**DocumentSerializer(document).data, "duplicate": duplicate}
        return Response(body, status=status.HTTP_200_OK if duplicate else status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={202: DocumentSerializer, 409: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def reprocess(self, request: Request, pk: str | None = None) -> Response:
        """Run the document through the current pipeline again, e.g. after a model upgrade.
        `409` while queued or processing, and once a decision is final (approved or rejected)."""
        document = self.get_object()
        with transaction.atomic():
            locked = Document.objects.select_for_update().get(pk=document.pk)
            if locked.status in (Document.Status.APPROVED, Document.Status.REJECTED):
                return Response({"detail": f"Already {locked.status}."}, status=status.HTTP_409_CONFLICT)
            if document.jobs.filter(status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).exists():
                return Response({"detail": "Already queued or processing."}, status=status.HTTP_409_CONFLICT)
            jobs.enqueue(document)
            Document.objects.filter(pk=document.pk).update(
                status=Document.Status.QUEUED, error="", claimed_by=None, claim_expires_at=None
            )
            audit.record(document.tenant, audit.actor_of(request.user), "reprocess_requested", document)
        document.refresh_from_db()
        return Response(DocumentSerializer(document).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(responses={(200, "image/png"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"], url_path=r"pages/(?P<number>\d+)")
    def page(self, request: Request, pk: str | None = None, number: str = "1") -> HttpResponse:
        """Page `number` (from 1) as a PNG, for showing the document beside its fields."""
        document = self.get_object()
        data = get_storage().get(document.storage_key)
        try:
            png = files.render_page(data, document.content_type, int(number) - 1)
        except IndexError:
            return HttpResponse(status=404)
        response = HttpResponse(png, content_type="image/png")
        response["Cache-Control"] = "private, max-age=3600"  # content-addressed: a page never changes
        return response
