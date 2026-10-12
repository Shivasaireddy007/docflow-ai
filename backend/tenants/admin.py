from django.contrib import admin

from tenants.models import ApiKey, Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin[Tenant]):
    list_display = ["name", "slug", "created_at"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin[ApiKey]):
    list_display = ["tenant", "name", "prefix", "created_at", "last_used_at", "revoked_at"]
    readonly_fields = ["prefix", "secret_hash", "last_used_at"]
