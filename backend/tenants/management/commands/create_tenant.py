from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.utils.text import slugify

from tenants.models import ApiKey, Tenant


class Command(BaseCommand):
    help = "Create a tenant (or reuse one by name) and issue it an API key, printed once."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("name")
        parser.add_argument("--key-name", default="default")

    def handle(self, *args: Any, **options: Any) -> None:
        tenant, _ = Tenant.objects.get_or_create(
            slug=slugify(options["name"]), defaults={"name": options["name"]}
        )
        _, plaintext = ApiKey.issue(tenant, options["key_name"])
        self.stdout.write(f"Tenant: {tenant.name} ({tenant.id})")
        self.stdout.write(f"API key (shown once): {plaintext}")
