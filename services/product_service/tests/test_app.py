"""In-process tests for the product_service skeleton (no MySQL needed)."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

SERVICE = "product_service"
PREFIXES = ['/api/products', '/api/categories', '/internal/products', '/internal/reservations']
UUID_ROUTE = ('get', '/api/products/not-a-uuid')


def make_settings(**overrides) -> Settings:
    # Port 1 on localhost refuses connections at once, so the readiness check fails fast.
    values = {"MYSQL_HOST": "127.0.0.1", "MYSQL_PORT": 1, "APP_ENV": "test", **overrides}
    return Settings(_env_file=None, **values)


@pytest.fixture
def client():
    with TestClient(create_app(make_settings()), raise_server_exceptions=False) as test_client:
        yield test_client


def test_liveness(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "service": SERVICE,
        "status": "ok",
        "version": "0.1.0",
        "environment": "test",
    }


def test_readiness_reports_unavailable_database_without_leaking_details(client):
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "service": SERVICE,
        "status": "not_ready",
        "checks": {"database": "unavailable"},
    }
    assert "127.0.0.1" not in response.text


def test_openapi_and_docs_load(client):
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    assert "/health" in paths and "/health/ready" in paths
    business = [p for p in paths if not p.startswith("/health")]
    assert business, "expected planned routes in the OpenAPI schema"
    assert all(p.startswith(tuple(PREFIXES)) for p in business), business
    assert client.get("/docs").status_code == 200


def test_docs_can_be_disabled():
    with TestClient(create_app(make_settings(DOCS_ENABLED=False))) as test_client:
        assert test_client.get("/openapi.json").status_code == 404
        assert test_client.get("/docs").status_code == 404
        assert test_client.get("/health").status_code == 200


def test_unknown_route_uses_error_envelope(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ROUTE_NOT_FOUND"


def test_validation_error_envelope_does_not_echo_input(client):
    method, path = UUID_ROUTE
    response = client.request(method, path)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"] and all(set(d) == {"field", "issue"} for d in error["details"])
    assert "not-a-uuid" not in response.text


def test_request_id_is_echoed_or_generated(client):
    echoed = client.get("/health", headers={"X-Request-ID": "req-test-123"})
    assert echoed.headers["X-Request-ID"] == "req-test-123"
    generated = client.get("/health", headers={"X-Request-ID": "bad id\nwith newline"})
    assert generated.headers["X-Request-ID"].startswith("req-")
    assert generated.headers["X-Request-ID"] != "bad id\nwith newline"


def test_unreachable_database_gives_503_envelope(client):
    # make_settings points MySQL at a closed port.
    response = client.get("/api/products")
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "DATABASE_UNAVAILABLE"
    assert "127.0.0.1" not in response.text and "pymysql" not in response.text.lower()
