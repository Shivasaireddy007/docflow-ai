import getpass
from typing import Any

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError, CommandParser

from tenants.models import Membership, Tenant


class Command(BaseCommand):
    help = "Create a reviewer (or admin) who signs in to the review app."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("tenant", help="Tenant slug")
        parser.add_argument("username")
        parser.add_argument("--admin", action="store_true", help="Can also change the rules")
        parser.add_argument("--password", help="Prompted for if omitted")

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = Tenant.objects.filter(slug=options["tenant"]).first()
        if tenant is None:
            raise CommandError(f"No tenant {options['tenant']!r}.")
        password = options["password"] or getpass.getpass("Password: ")
        user, created = User.objects.get_or_create(username=options["username"])
        user.set_password(password)
        user.save()
        role = Membership.Role.ADMIN if options["admin"] else Membership.Role.REVIEWER
        Membership.objects.update_or_create(user=user, defaults={"tenant": tenant, "role": role})
        self.stdout.write(f"{'Created' if created else 'Updated'} {role} {user.username} in {tenant.name}.")
