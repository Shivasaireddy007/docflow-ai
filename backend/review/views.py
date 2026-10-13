from datetime import timedelta
from typing import Any, cast
from uuid import UUID

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db.models import Count, OuterRef, Q, Subquery
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import Throttled
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.ratelimit import Bucket, get_limiter
from documents.models import Document, Extraction
from documents.serializers import ExtractionSerializer
from review import audit, decisions
from review.models import AuditEvent, Decision, RuleSet
from review.rules import RULE_TYPES, InvalidRules
from review.serializers import (
    AuditEventSerializer,
    DecisionSerializer,
    LoginSerializer,
    MeSerializer,
    NextSerializer,
    PublishRulesSerializer,
    QueueItemSerializer,
    ReviewDecisionSerializer,
    ReviewDocumentSerializer,
    RuleSetSerializer,
    RulesListingSerializer,
    StatsSerializer,
)
from tenants.access import IsReviewer, IsTenantAdmin, membership_of, reviewer
from tenants.models import Membership


def _me(user: User) -> dict[str, Any]:
    membership = Membership.objects.select_related("tenant").get(user=user)
    return {
        "username": user.get_username(),
        "role": membership.role,
        "tenant": {"id": str(membership.tenant_id), "name": membership.tenant.name},
    }


@method_decorator(ensure_csrf_cookie, name="get")
class CsrfView(APIView):
    """Sets the CSRF cookie the web app sends back as X-CSRFToken."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(responses={204: None})
    def get(self, request: Request) -> Response:
        return Response(status=status.HTTP_204_NO_CONTENT)


class LoginView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=LoginSerializer, responses={200: MeSerializer, 400: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        """Sign in a reviewer; starts a session (cookie)."""
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        # Per username and address, so guessing one account's password is slow but a busy office
        # behind one address isn't locked out.
        who = f"login:{data.validated_data['username'].lower()}:{request.META.get('REMOTE_ADDR', '')}"
        if wait := get_limiter().take(who, Bucket.parse(settings.LOGIN_RATE)):
            raise Throttled(wait=wait, detail="Too many sign-in attempts; try again shortly.")
        user = authenticate(
            request, username=data.validated_data["username"], password=data.validated_data["password"]
        )
        if not isinstance(user, User) or membership_of(user) is None:
            return Response({"detail": "Wrong username or password."}, status=status.HTTP_400_BAD_REQUEST)
        login(request._request, user)
        return Response(_me(user))


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsReviewer]

    @extend_schema(responses=MeSerializer)
    def get(self, request: Request) -> Response:
        """The signed-in reviewer."""
        return Response(_me(cast(User, request.user)))


def _queue_rows(tenant_id: UUID, statuses: list[str]) -> list[dict[str, Any]]:
    latest = Decision.objects.filter(document=OuterRef("pk")).order_by("-created_at")
    latest_extraction = Extraction.objects.filter(document=OuterRef("pk")).order_by("-created_at")
    documents = (
        Document.objects.filter(tenant_id=tenant_id, status__in=statuses)
        .select_related("claimed_by")
        .annotate(
            rule_results=Subquery(latest.values("rule_results")[:1]),
            confidence=Subquery(latest_extraction.values("confidence")[:1]),
            final=Subquery(latest.values("final_fields")[:1]),
        )
        .order_by("created_at")[:200]
    )
    now = timezone.now()
    rows = []
    for d in documents:
        claimed = d.claimed_by if d.claim_expires_at and d.claim_expires_at > now else None
        rows.append(
            {
                "id": d.id,
                "filename": d.filename,
                "status": d.status,
                "page_count": d.page_count,
                "created_at": d.created_at,
                "confidence": d.confidence,
                "total": (d.final or {}).get("total"),
                "failed_rules": [r["rule_id"] for r in d.rule_results or [] if not r["passed"]],
                "claimed_by": claimed.get_username() if claimed else None,
            }
        )
    return rows


class QueueView(APIView):
    permission_classes = [IsReviewer]

    @extend_schema(responses=QueueItemSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Documents waiting for review, oldest first, with why each needs a person."""
        membership = reviewer(request)
        return Response(
            QueueItemSerializer(_queue_rows(membership.tenant_id, ["needs_review"]), many=True).data
        )


class NextView(APIView):
    permission_classes = [IsReviewer]

    @extend_schema(request=None, responses={200: NextSerializer, 204: None})
    def post(self, request: Request) -> Response:
        """Claim the next document to review (or keep your current one). `204` when the queue is empty."""
        document = decisions.claim_next(cast(User, request.user))
        if document is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response({"id": str(document.id)})


class ReviewDocumentView(APIView):
    permission_classes = [IsReviewer]

    @extend_schema(responses={200: ReviewDocumentSerializer, 404: OpenApiTypes.OBJECT})
    def get(self, request: Request, document_id: str) -> Response:
        """Everything a reviewer needs: the extraction, every decision so far, and the audit trail."""
        membership = reviewer(request)
        document = (
            Document.objects.filter(tenant=membership.tenant, pk=document_id)
            .select_related("claimed_by")
            .first()
        )
        if document is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        extraction = document.latest_extraction()
        history = document.decisions.select_related("rule_set", "decided_by").order_by("created_at")
        events = AuditEvent.objects.filter(document=document).order_by("created_at")
        claimed = document.claim_expires_at is not None and document.claim_expires_at > timezone.now()
        return Response(
            {
                "id": str(document.id),
                "filename": document.filename,
                "status": document.status,
                "page_count": document.page_count,
                "created_at": document.created_at,
                "claimed_by": document.claimed_by.get_username() if claimed and document.claimed_by else None,
                "extraction": ExtractionSerializer(extraction).data if extraction else None,
                "decisions": DecisionSerializer(history, many=True).data,
                "audit": AuditEventSerializer(events, many=True).data,
            }
        )


class DecisionView(APIView):
    permission_classes = [IsReviewer]

    @extend_schema(
        request=ReviewDecisionSerializer, responses={201: DecisionSerializer, 409: OpenApiTypes.OBJECT}
    )
    def post(self, request: Request, document_id: str) -> Response:
        """Approve or reject a document, with corrected values. `409` if someone else decided it first
        or is reviewing it."""
        data = ReviewDecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            decision = decisions.decide_by_reviewer(
                document_id,
                cast(User, request.user),
                approve=data.validated_data["approve"],
                corrections=data.validated_data["corrections"],
                reason=data.validated_data["reason"],
            )
        except Document.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except decisions.Conflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(DecisionSerializer(decision).data, status=status.HTTP_201_CREATED)


class StatsView(APIView):
    permission_classes = [IsReviewer]

    @extend_schema(responses=StatsSerializer)
    def get(self, request: Request) -> Response:
        """Queue size, documents by status, and how many decisions the rules made on their own (7 days)."""
        membership = reviewer(request)
        tenant = membership.tenant
        by_status = dict(
            Document.objects.filter(tenant=tenant)
            .values_list("status")
            .annotate(n=Count("id"))
            .values_list("status", "n")
        )
        since = timezone.now() - timedelta(days=7)
        first_decisions = Decision.objects.filter(
            tenant=tenant, created_at__gte=since, decided_by__isnull=True
        )
        counts = first_decisions.aggregate(
            total=Count("id"), auto=Count("id", filter=Q(outcome=Decision.Outcome.AUTO_APPROVED))
        )
        reviewed = Decision.objects.filter(tenant=tenant, created_at__gte=since, decided_by__isnull=False)
        return Response(
            {
                "by_status": by_status,
                "auto_approved_7d": counts["auto"],
                "decided_by_rules_7d": counts["total"],
                "auto_approve_rate_7d": counts["auto"] / counts["total"] if counts["total"] else None,
                "reviewed_7d": reviewed.count(),
                "corrected_7d": reviewed.exclude(corrections={}).count(),
            }
        )


class RulesView(APIView):
    def get_permissions(self) -> list[Any]:
        return [IsTenantAdmin()] if self.request.method == "POST" else [IsReviewer()]

    @extend_schema(responses=RulesListingSerializer)
    def get(self, request: Request) -> Response:
        """The active rules, every earlier version, and the rule types available."""
        membership = reviewer(request)
        active = RuleSet.active_for(membership.tenant)
        versions = (
            RuleSet.objects.filter(tenant=membership.tenant).select_related("created_by").order_by("-version")
        )
        return Response(
            {
                "active": RuleSetSerializer(active).data,
                "versions": RuleSetSerializer(versions, many=True).data,
                "types": {name: sorted(params) for name, (params, _) in RULE_TYPES.items()},
            }
        )

    @extend_schema(
        request=PublishRulesSerializer, responses={201: RuleSetSerializer, 400: OpenApiTypes.OBJECT}
    )
    def post(self, request: Request) -> Response:
        """Publish a new version of the rules (admins). Takes effect for the next decision."""
        membership = reviewer(request)
        data = PublishRulesSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            rule_set = RuleSet.publish(
                membership.tenant,
                data.validated_data["rules"],
                user=request.user,
                note=data.validated_data["note"],
            )
        except InvalidRules as exc:
            return Response({"rules": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        audit.record(
            membership.tenant, audit.actor_of(request.user), "rules_published", version=rule_set.version
        )
        return Response(RuleSetSerializer(rule_set).data, status=status.HTTP_201_CREATED)
