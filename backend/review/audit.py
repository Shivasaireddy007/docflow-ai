from typing import Any

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

from documents.models import Document
from review.models import AuditEvent
from tenants.auth import TenantUser
from tenants.models import Tenant

PIPELINE = "pipeline"


def actor_of(user: object) -> str:
    """How a caller appears in the audit log."""
    if isinstance(user, TenantUser):
        return f"api-key:{user.api_key.prefix}"
    if isinstance(user, AbstractBaseUser) and not isinstance(user, AnonymousUser):
        return f"user:{user.get_username()}"
    return PIPELINE


def record(
    tenant: Tenant, actor: str, action: str, document: Document | None = None, **data: Any
) -> AuditEvent:
    return AuditEvent.objects.create(tenant=tenant, document=document, actor=actor, action=action, data=data)
