"""Service endpoints, routing and configuration."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.main import app


def test_root_and_health(client):
    assert client.get("/").json()["service"] == "ShopEase Product Catalog Service"
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"


def test_title_version_and_swagger_docs(client):
    assert app.title == "ShopEase Product Catalog Service"
    assert app.version == "1.0.0"
    assert client.get("/health").json()["version"] == "1.0.0"
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "swagger-ui" in docs.text.lower()
    assert client.get("/openapi.json").json()["info"]["version"] == "1.0.0"


def test_database_health(client):
    response = client.get("/health/db")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_all_routes_are_registered():
    paths = set(app.openapi()["paths"])
    for expected in (
        "/api/categories/", "/api/categories/{category_id}",
        "/api/products/", "/api/products/{product_id}",
        "/api/inventory/low-stock", "/api/inventory/{product_id}",
        "/api/inventory/{product_id}/stock-in", "/api/inventory/{product_id}/stock-out",
        "/api/inventory/{product_id}/history",
    ):
        assert expected in paths


def test_placeholder_password_is_rejected():
    with pytest.raises(ValidationError):
        Settings(mysql_user="u", mysql_password="change-me", _env_file=None)


def test_password_is_masked_in_url():
    settings = Settings(mysql_user="u", mysql_password="s3cret-value", _env_file=None)
    assert "s3cret-value" not in str(settings.database_url)
    assert "s3cret-value" not in repr(settings)
