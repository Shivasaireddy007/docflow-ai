"""Who is calling, and for which tenant: an API key (machines) or a signed-in reviewer (people)."""

from typing import Any

from django.contrib.auth.models import User
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from tenants.auth import TenantUser
from tenants.models import Membership, Tenant


def membership_of(user: object) -> Membership | None:
    if isinstance(user, User) and user.is_authenticated:
        return Membership.objects.select_related("tenant").filter(user=user).first()
    return None


def reviewer(request: Request) -> Membership:
    """The signed-in reviewer's membership; views using it are behind IsReviewer."""
    membership = membership_of(request.user)
    if membership is None:
        raise PermissionDenied("Sign in as a reviewer.")
    return membership


def tenant_of(request: Request) -> Tenant:
    if isinstance(request.user, TenantUser):
        return request.user.tenant
    if membership := membership_of(request.user):
        return membership.tenant
    raise PermissionDenied("This account doesn't belong to a tenant.")


class HasTenant(BasePermission):
    """An API key, or a person who belongs to a tenant."""

    def has_permission(self, request: Request, view: Any) -> bool:
        return isinstance(request.user, TenantUser) or membership_of(request.user) is not None


class IsReviewer(BasePermission):
    """A signed-in person in a tenant's review team. API keys can't review."""

    message = "Sign in as a reviewer."

    def has_permission(self, request: Request, view: Any) -> bool:
        return membership_of(request.user) is not None


class IsTenantAdmin(BasePermission):
    message = "Only admins can change the rules."

    def has_permission(self, request: Request, view: Any) -> bool:
        membership = membership_of(request.user)
        return membership is not None and membership.role == Membership.Role.ADMIN
