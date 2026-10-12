from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone
from rest_framework import authentication, exceptions
from rest_framework.request import Request

from tenants.models import ApiKey, Tenant

# Recording every use would turn each read into a write; once a minute is enough to see activity.
LAST_USED_RESOLUTION = timedelta(minutes=1)


@dataclass(frozen=True)
class TenantUser:
    """The authenticated caller: a tenant, through one of its API keys."""

    tenant: Tenant
    api_key: ApiKey
    is_authenticated: bool = True


class ApiKeyAuthentication(authentication.BaseAuthentication):
    """`Authorization: Api-Key dfk_...`"""

    keyword = "Api-Key"

    def authenticate(self, request: Request) -> tuple[TenantUser, ApiKey] | None:
        header = authentication.get_authorization_header(request).decode(errors="replace")
        scheme, _, token = header.partition(" ")
        if scheme != self.keyword:
            return None
        key = ApiKey.find(token.strip())
        if key is None:
            raise exceptions.AuthenticationFailed("Invalid or revoked API key.")

        now = timezone.now()
        if key.last_used_at is None or now - key.last_used_at > LAST_USED_RESOLUTION:
            ApiKey.objects.filter(pk=key.pk).update(last_used_at=now)
        return TenantUser(tenant=key.tenant, api_key=key), key

    def authenticate_header(self, request: Request) -> str:
        return self.keyword
