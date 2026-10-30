"""``POST /v1/import/{tenant_slug}/postman/openapi`` — Postman → OpenAPI through the SPI (MFI-32.7)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.postman_convert_routes import MAX_COLLECTION_CHARS, convert_postman_to_openapi

client = TestClient(app)

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "postman"
_URL = "/v1/import/acme/postman/openapi"
_SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch):
    app.dependency_overrides[validate_authentication] = lambda tenant_slug: {
        "tenant_id": "t1",
        "tenant_slug": tenant_slug,
        "user_id": "u1",
        "auth_method": "jwt",
    }
    granted: List[tuple] = []
    monkeypatch.setattr(
        "app.postman_convert_routes.enforce_permission",
        lambda _db, _auth, resource, action, **_: granted.append((resource, action)) or "u1",
    )
    yield granted
    app.dependency_overrides.pop(validate_authentication, None)


def _collection(**extra: Any) -> str:
    """A small v2.1 collection with a JSON request body and a saved example response."""
    document: Dict[str, Any] = {
        "info": {"name": "Shop API", "schema": _SCHEMA},
        "item": [
            {
                "name": "Create order",
                "request": {
                    "method": "POST",
                    "header": [
                        {"key": "Content-Type", "value": "application/json"},
                        {"key": "Authorization", "value": "Bearer demo-convert-token-not-real"},
                    ],
                    "url": {"raw": "{{baseUrl}}/orders", "host": ["{{baseUrl}}"], "path": ["orders"]},
                    "body": {"mode": "raw", "raw": '{"sku": "A-1", "qty": 2}'},
                },
                "response": [{"name": "Created", "code": 201, "body": '{"id": 7}'}],
                "event": [{"listen": "test", "script": {"exec": ["pm.test('ok', () => {})"]}}],
            }
        ],
        "variable": [{"key": "baseUrl", "value": "https://api.example.com"}],
    }
    document.update(extra)
    return json.dumps(document)


def test_converts_a_collection_to_openapi_with_inferred_schemas(_auth) -> None:
    response = client.post(_URL, json={"document": _collection(), "filename": "shop.postman_collection.json"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_kind"] == "postman"
    document = body["openapi"]
    assert document["openapi"].startswith("3.1")
    assert document["info"]["title"] == "Shop API"
    assert document["info"]["version"] == "1.0.0"
    assert document["servers"] == [
        {"url": "https://api.example.com", "description": "From Postman collection variable"}
    ]
    post = document["paths"]["/orders"]["post"]
    ref = post["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    schema = document["components"]["schemas"][ref.rsplit("/", 1)[-1]]
    assert set(schema["properties"]) == {"sku", "qty"}
    assert "201" in post["responses"]
    assert _auth == [("imports", "create")]


def test_warnings_name_what_the_conversion_leaves_out() -> None:
    body = client.post(_URL, json={"document": _collection()}).json()
    assert any(warning.startswith("Pre-request and test scripts are run by Postman") and "(Create order)" in warning
               for warning in body["warnings"])


def test_no_credential_reaches_the_openapi_document() -> None:
    body = client.post(_URL, json={"document": _collection()}).json()
    assert "demo-convert-token-not-real" not in json.dumps(body)


def test_base_url_replaces_the_servers() -> None:
    body = client.post(_URL, json={"document": _collection(), "base_url": "https://staging.example.com"}).json()
    assert body["openapi"]["servers"] == [{"url": "https://staging.example.com"}]


def test_a_document_that_is_not_a_postman_collection_is_refused() -> None:
    response = client.post(_URL, json={"document": json.dumps({"openapi": "3.1.0", "info": {}, "paths": {}})})
    assert response.status_code == 422
    assert response.json()["detail"]["code"]


def test_an_oversized_document_is_refused_before_parsing() -> None:
    response = client.post(_URL, json={"document": " " * (MAX_COLLECTION_CHARS + 1)})
    assert response.status_code == 422


def test_the_permission_check_can_refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    def _deny(*_args: Any, **_kwargs: Any) -> str:
        raise HTTPException(status_code=403, detail="imports:create required")

    monkeypatch.setattr("app.postman_convert_routes.enforce_permission", _deny)
    assert client.post(_URL, json={"document": _collection()}).status_code == 403


@pytest.mark.parametrize("path", sorted(_EXAMPLES.glob("*.json")), ids=lambda p: p.name)
def test_every_committed_example_converts(path: Path) -> None:
    result = convert_postman_to_openapi(path.read_text(encoding="utf-8"))
    assert result.openapi["paths"]
