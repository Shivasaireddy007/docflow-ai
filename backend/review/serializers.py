from typing import Any

from rest_framework import serializers

from documents.models import Document
from review.models import AuditEvent, Decision, RuleSet


class LoginSerializer(serializers.Serializer[Any]):
    username = serializers.CharField()
    password = serializers.CharField(style={"input_type": "password"})


class MeSerializer(serializers.Serializer[Any]):
    username = serializers.CharField()
    role = serializers.CharField()
    tenant = serializers.DictField()


class QueueItemSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    filename = serializers.CharField()
    status = serializers.ChoiceField(choices=Document.Status.choices)
    page_count = serializers.IntegerField(allow_null=True)
    created_at = serializers.DateTimeField()
    confidence = serializers.FloatField(allow_null=True)
    total = serializers.FloatField(allow_null=True)
    failed_rules = serializers.ListField(child=serializers.CharField())
    claimed_by = serializers.CharField(allow_null=True)


class DecisionSerializer(serializers.ModelSerializer[Decision]):
    decided_by = serializers.SerializerMethodField()
    rules_version = serializers.IntegerField(source="rule_set.version")

    class Meta:
        model = Decision
        fields = [
            "id", "outcome", "decided_by", "rules_version", "rule_results", "final_fields",
            "final_line_items", "corrections", "reason", "created_at",
        ]  # fmt: skip

    def get_decided_by(self, decision: Decision) -> str:
        return decision.decided_by.get_username() if decision.decided_by else "rules"


class AuditEventSerializer(serializers.ModelSerializer[AuditEvent]):
    class Meta:
        model = AuditEvent
        fields = ["actor", "action", "data", "created_at"]


class ReviewDecisionSerializer(serializers.Serializer[Any]):
    approve = serializers.BooleanField()
    corrections = serializers.DictField(child=serializers.JSONField(), required=False, default=dict)
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)

    def validate_corrections(self, value: dict[str, Any]) -> dict[str, Any]:
        from pipeline.schema import SCALAR_FIELDS

        if unknown := set(value) - set(SCALAR_FIELDS):
            raise serializers.ValidationError(f"Unknown fields: {', '.join(sorted(unknown))}")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs["approve"] and not attrs["reason"].strip():
            raise serializers.ValidationError({"reason": "Say why the document is rejected."})
        return attrs


class RuleSetSerializer(serializers.ModelSerializer[RuleSet]):
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = RuleSet
        fields = ["version", "rules", "note", "is_active", "created_by", "created_at"]

    def get_created_by(self, rule_set: RuleSet) -> str | None:
        return rule_set.created_by.get_username() if rule_set.created_by else None


class PublishRulesSerializer(serializers.Serializer[Any]):
    rules = serializers.JSONField()
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)
