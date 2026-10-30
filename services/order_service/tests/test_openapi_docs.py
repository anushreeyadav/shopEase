"""The OpenAPI document (Swagger UI) of order_service: complete, and consistent with behaviour."""

import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

# Operations that never return a 2xx body by design (documented where they are defined).
NO_SUCCESS_BODY = set()
ERROR_REF = {"$ref": "#/components/schemas/ErrorResponse"}
# Readiness answers 503 with its own body (which checks failed), not the error envelope.
OWN_ERROR_BODIES = {("get", "/health/ready", "503")}


@pytest.fixture(scope="module")
def app():
    return create_app(Settings(_env_file=None, APP_ENV="test"))


@pytest.fixture(scope="module")
def schema(app):
    return app.openapi()


def operations(schema):
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            yield method, path, operation


def test_service_and_tags_are_described(schema):
    assert len(schema["info"]["description"]) > 100
    declared = {tag["name"]: tag.get("description") for tag in schema.get("tags", [])}
    assert declared and all(declared.values())
    for method, path, operation in operations(schema):
        assert operation.get("tags") and set(operation["tags"]) <= set(declared), (method, path)


def test_every_operation_has_a_summary_and_documented_errors(schema):
    assert "ErrorResponse" in schema["components"]["schemas"]
    assert "HTTPValidationError" not in schema["components"]["schemas"]
    for method, path, operation in operations(schema):
        assert operation.get("summary"), (method, path)
        responses = operation["responses"]
        assert "default" in responses, (method, path)
        for code, response in responses.items():
            if (code == "default" or code[0] in "45") and (method, path, code) not in OWN_ERROR_BODIES:
                assert response["content"]["application/json"]["schema"] == ERROR_REF, (method, path, code)


def test_success_responses_have_schemas(schema):
    for method, path, operation in operations(schema):
        if (method, path) in NO_SUCCESS_BODY:
            continue
        success = {c: r for c, r in operation["responses"].items() if c.startswith("2")}
        assert success, (method, path)
        for code, response in success.items():
            if code == "204":
                continue
            body = response.get("content", {}).get("application/json", {}).get("schema")
            assert body, (method, path, code)


def test_request_bodies_have_examples(schema):
    components = schema["components"]["schemas"]
    for method, path, operation in operations(schema):
        if "requestBody" not in operation:
            continue
        body = operation["requestBody"]["content"]["application/json"]["schema"]
        ref = body.get("$ref") or next((s.get("$ref") for s in body.get("anyOf", []) if "$ref" in s), None)
        assert ref, (method, path)
        assert components[ref.rsplit("/", 1)[1]].get("examples"), (method, path)


def test_documented_security_matches_behaviour(app, schema):
    """Every operation documented as requiring a token really answers 401 without one."""
    assert set(schema["components"]["securitySchemes"]) == {"bearerAuth", "serviceToken"}
    client = TestClient(app, raise_server_exceptions=False)
    protected = 0
    for method, path, operation in operations(schema):
        security = operation.get("security")
        if not security or {} in security:
            continue
        protected += 1
        concrete = re.sub(r"\{[^/]+\}", str(uuid.uuid4()), path)
        response = client.request(method.upper(), concrete, json={})
        assert response.status_code == 401, (method, path, response.status_code)
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert protected >= 7
