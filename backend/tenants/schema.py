from typing import Any

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class ApiKeyScheme(OpenApiAuthenticationExtension):  # type: ignore[no-untyped-call]
    """Documents API-key authentication, so the docs' Authorize button works."""

    target_class = "tenants.auth.ApiKeyAuthentication"
    name = "ApiKey"

    def get_security_definition(self, auto_schema: Any) -> dict[str, str]:
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "`Api-Key dfk_...`, issued per tenant with `manage.py create_tenant`.",
        }
