from django.apps import AppConfig


class TenantsConfig(AppConfig):
    name = "tenants"

    def ready(self) -> None:
        from tenants import schema  # noqa: F401  (registers the API-key scheme with the docs)
