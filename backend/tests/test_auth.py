from django.utils import timezone
from rest_framework.test import APIClient

from tenants.models import ApiKey, Tenant


def test_requests_without_a_key_are_rejected(db: None) -> None:
    response = APIClient().get("/api/v1/documents")

    assert response.status_code == 401
    assert response["WWW-Authenticate"] == "Api-Key"


def test_a_valid_key_authenticates_and_records_use(tenant: Tenant) -> None:
    key, plaintext = ApiKey.issue(tenant, "ci")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {plaintext}")

    assert client.get("/api/v1/documents").status_code == 200
    key.refresh_from_db()
    assert key.last_used_at is not None


def test_only_a_hash_of_the_key_is_stored(tenant: Tenant) -> None:
    key, plaintext = ApiKey.issue(tenant, "ci")

    secret = plaintext.split("_", 2)[2]
    assert secret not in key.secret_hash
    assert plaintext.startswith(f"dfk_{key.prefix}_")


def test_wrong_malformed_and_revoked_keys_are_rejected(tenant: Tenant) -> None:
    key, plaintext = ApiKey.issue(tenant, "ci")
    wrong_secret = plaintext[:-4] + "AAAA"
    key_from_other_prefix = "dfk_000000000000_" + plaintext.split("_", 2)[2]

    for token in [wrong_secret, key_from_other_prefix, "not-a-key", "dfk_only"]:
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Api-Key {token}")
        assert client.get("/api/v1/documents").status_code == 401, token

    key.revoked_at = timezone.now()
    key.save()
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {plaintext}")
    assert client.get("/api/v1/documents").status_code == 401
