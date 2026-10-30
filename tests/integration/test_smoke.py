"""Smoke: every component is up, documented and reachable the intended way."""

import pytest

from tests.integration.conftest import GATEWAY, SERVICES

COMPONENTS = {"api_gateway": GATEWAY, **SERVICES}


@pytest.mark.parametrize("name,base_url", COMPONENTS.items())
def test_liveness(gw, name, base_url):
    response = gw.get(f"{base_url}/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok" and response.json()["service"] == name


@pytest.mark.parametrize("name,base_url", COMPONENTS.items())
def test_readiness_and_database(gw, name, base_url):
    response = gw.get(f"{base_url}/health/ready")
    assert response.status_code == 200, response.text
    expected = {"database"} if name != "api_gateway" else set(SERVICES)
    assert set(response.json()["checks"]) == expected and set(response.json()["checks"].values()) == {"ok"}


@pytest.mark.parametrize("name,base_url", COMPONENTS.items())
def test_openapi_is_served_and_documents_errors(gw, name, base_url):
    schema = gw.get(f"{base_url}/openapi.json").json()
    assert schema["info"]["title"].startswith("ShopEase") and schema["info"]["description"]
    assert "ErrorResponse" in schema["components"]["schemas"]


@pytest.mark.parametrize(
    "path", ["/api/auth/.well-known/jwks.json", "/api/products", "/api/categories"]
)
def test_public_routes_reach_their_service(gw, path):
    response = gw.get(path)
    assert response.status_code == 200
    assert response.headers["X-Request-ID"].startswith("req-")


def test_internal_routes_are_not_routed(gw):
    response = gw.post("/internal/reservations/5e7a9c1b-3d5f-4e7a-9b1c-3d5e7f9a1b21/release")
    assert response.status_code == 404 and response.json()["error"]["code"] == "ROUTE_NOT_FOUND"
