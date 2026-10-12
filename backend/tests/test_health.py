from django.test import Client


def test_health_and_ready(db: None) -> None:
    client = Client()

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ok", "database": "ok"}


def test_api_docs_are_served(db: None) -> None:
    response = Client().get("/api/schema/")

    assert response.status_code == 200
    assert b"/api/v1/documents" in response.content
