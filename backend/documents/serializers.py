from typing import Any

from rest_framework import serializers

from documents.models import Document, Extraction


class UploadSerializer(serializers.Serializer[Any]):
    file = serializers.FileField(help_text="A receipt or invoice: PDF, PNG, JPEG or WebP")


class ExtractionSerializer(serializers.ModelSerializer[Extraction]):
    class Meta:
        model = Extraction
        fields = [
            "pipeline_version",
            "confidence",
            "fields",
            "line_items",
            "ocr_text",
            "ocr_ms",
            "extraction_ms",
            "created_at",
        ]


class DocumentSerializer(serializers.ModelSerializer[Document]):
    class Meta:
        model = Document
        fields = [
            "id",
            "filename",
            "content_type",
            "size_bytes",
            "page_count",
            "sha256",
            "status",
            "error",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class DocumentDetailSerializer(DocumentSerializer):
    extraction = serializers.SerializerMethodField()

    class Meta(DocumentSerializer.Meta):
        fields = [*DocumentSerializer.Meta.fields, "extraction"]
        read_only_fields = fields

    def get_extraction(self, document: Document) -> dict[str, Any] | None:
        extraction = document.latest_extraction()
        return ExtractionSerializer(extraction).data if extraction else None


class UploadResultSerializer(DocumentSerializer):
    duplicate = serializers.BooleanField(help_text="True if this tenant already uploaded the same file")

    class Meta(DocumentSerializer.Meta):
        fields = [*DocumentSerializer.Meta.fields, "duplicate"]
        read_only_fields = fields
