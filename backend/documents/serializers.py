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
    decision = serializers.SerializerMethodField()

    class Meta(DocumentSerializer.Meta):
        fields = [*DocumentSerializer.Meta.fields, "extraction", "decision"]
        read_only_fields = fields

    def get_extraction(self, document: Document) -> dict[str, Any] | None:
        extraction = document.latest_extraction()
        return ExtractionSerializer(extraction).data if extraction else None

    def get_decision(self, document: Document) -> dict[str, Any] | None:
        """The latest decision: its outcome, the values it stands on, and who made it."""
        decision = document.decisions.select_related("rule_set", "decided_by").order_by("-created_at").first()
        if decision is None:
            return None
        return {
            "outcome": decision.outcome,
            "decided_by": decision.decided_by.get_username() if decision.decided_by else "rules",
            "rules_version": decision.rule_set.version,
            "failed_rules": [r for r in decision.rule_results if not r["passed"]],
            "final_fields": decision.final_fields,
            "final_line_items": decision.final_line_items,
            "corrections": decision.corrections,
            "reason": decision.reason,
            "decided_at": decision.created_at,
        }


class UploadResultSerializer(DocumentSerializer):
    duplicate = serializers.BooleanField(help_text="True if this tenant already uploaded the same file")

    class Meta(DocumentSerializer.Meta):
        fields = [*DocumentSerializer.Meta.fields, "duplicate"]
        read_only_fields = fields
