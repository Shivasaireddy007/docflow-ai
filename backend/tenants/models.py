import hashlib
import hmac
import secrets
import uuid

from django.db import models
from django.utils import timezone

KEY_PREFIX = "dfk"


def _hash(secret: str) -> str:
    # API keys are 256-bit random strings, so a fast hash is enough: there is nothing to brute-force.
    return hashlib.sha256(secret.encode()).hexdigest()


class Tenant(models.Model):
    """A customer. Every document, key and result belongs to exactly one tenant."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class ApiKey(models.Model):
    """A tenant's API key: `dfk_<prefix>_<secret>`. Only a hash of the secret is stored."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(max_length=80)
    prefix = models.CharField(max_length=16, unique=True, help_text="Public part, used to find the key")
    secret_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.tenant} / {self.name} ({self.prefix})"

    @classmethod
    def issue(cls, tenant: Tenant, name: str) -> tuple["ApiKey", str]:
        """Creates a key and returns it with its plaintext, which is never stored or shown again."""
        prefix = secrets.token_hex(6)
        secret = secrets.token_urlsafe(32)
        key = cls.objects.create(tenant=tenant, name=name, prefix=prefix, secret_hash=_hash(secret))
        return key, f"{KEY_PREFIX}_{prefix}_{secret}"

    @classmethod
    def find(cls, plaintext: str) -> "ApiKey | None":
        """The active key matching a plaintext key, compared in constant time."""
        try:
            label, prefix, secret = plaintext.split("_", 2)
        except ValueError:
            return None
        if label != KEY_PREFIX:
            return None
        key = cls.objects.select_related("tenant").filter(prefix=prefix, revoked_at__isnull=True).first()
        if key is None or not hmac.compare_digest(key.secret_hash, _hash(secret)):
            return None
        return key

    def revoke(self) -> None:
        self.revoked_at = timezone.now()
        self.save(update_fields=["revoked_at"])


class Membership(models.Model):
    """A person who works in a tenant's review queue. Admins can also change the rules."""

    class Role(models.TextChoices):
        REVIEWER = "reviewer"
        ADMIN = "admin"

    user = models.OneToOneField("auth.User", on_delete=models.CASCADE, related_name="membership")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="members")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.REVIEWER)

    def __str__(self) -> str:
        return f"{self.user} ({self.role}) in {self.tenant}"
