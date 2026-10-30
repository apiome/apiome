"""MFI-32.7 (#4409): Postman collections normalize through the shared inferred-spec engine.

The Postman adapter already sat behind the import SPI; what this pins is that its normalizer now
hands requests to :mod:`app.inferred_spec` (MFI-32.1) and post-processes them with the shared
collection helpers (MFI-32.5), exactly like Insomnia and Bruno — while still writing the Postman
projection the emitter reads for a round trip.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.canonical_model import CanonicalApi, MessageRole, Operation, ParameterLocation
from app.import_preview_manifest import build_import_preview_manifest
from app.import_source import get_import_source, load_builtin_import_sources
from app.inference_provenance import INFERRED, SYNTHESIZED
from app.postman_normalizer import POSTMAN_EXTRAS_KEY

load_builtin_import_sources()

_SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"

#: Credentials planted in the collection; none may reach the model or the coverage manifest.
_PLANTED = ["demo-bearer-not-real", "demo-header-key-not-real", "demo-query-token-not-real", "demo-var-secret-not-real"]


def _request(
    name: str,
    method: str,
    path: List[str],
    *,
    query: Optional[List[Dict[str, Any]]] = None,
    headers: Optional[List[Dict[str, Any]]] = None,
    body: Optional[str] = None,
    responses: Optional[List[Dict[str, Any]]] = None,
    auth: Optional[Dict[str, Any]] = None,
    events: bool = False,
) -> Dict[str, Any]:
    """One Postman request item."""
    request: Dict[str, Any] = {
        "method": method,
        "header": headers or [],
        "url": {"raw": "{{baseUrl}}/" + "/".join(path), "host": ["{{baseUrl}}"], "path": path, "query": query or []},
    }
    if body is not None:
        request["body"] = {"mode": "raw", "raw": body, "options": {"raw": {"language": "json"}}}
    if auth is not None:
        request["auth"] = auth
    item: Dict[str, Any] = {"name": name, "request": request, "response": responses or []}
    if events:
        item["event"] = [{"listen": "prerequest", "script": {"exec": ["pm.environment.set('x', 1)"]}}]
    return item


def _collection(items: List[Dict[str, Any]], *, variables: Optional[List[Dict[str, Any]]] = None) -> str:
    """A v2.1 collection document."""
    return json.dumps(
        {
            "info": {"name": "Shop API", "schema": _SCHEMA},
            "item": items,
            "variable": variables if variables is not None else [{"key": "baseUrl", "value": "https://api.example.com"}],
        }
    )


def _import(text: str) -> CanonicalApi:
    adapter = get_import_source("postman")
    return adapter.normalize(adapter.parse(text))


def _operation(api: CanonicalApi, key: str) -> Operation:
    return next(op for op in api.operations() if op.key == key)


_SHOP = _collection(
    [
        {
            "name": "Orders",
            "item": [
                _request(
                    "List orders",
                    "GET",
                    ["orders"],
                    query=[{"key": "limit", "value": "{{pageSize}}"}],
                    responses=[{"name": "OK", "code": 200, "body": '[{"id": 1, "total": 9.5}]'}],
                ),
                _request(
                    "Create order",
                    "POST",
                    ["orders"],
                    headers=[{"key": "Content-Type", "value": "application/json"}],
                    body='{"sku": "A-1", "qty": 2}',
                    responses=[{"name": "Created", "code": 201, "body": '{"id": 7, "sku": "A-1", "qty": 2}'}],
                    auth={"type": "bearer", "bearer": [{"key": "token", "value": "demo-bearer-not-real"}]},
                ),
                _request("Get order 1", "GET", ["orders", "1"]),
                _request("Get order 2", "GET", ["orders", "2"]),
            ],
        },
        _request("Ping", "POST", ["ping"], body="hello", events=True),
    ],
    variables=[
        {"key": "baseUrl", "value": "https://api.example.com"},
        {"key": "pageSize", "value": "25"},
    ],
)


def test_operations_come_from_the_engine() -> None:
    api = _import(_SHOP)
    # The engine templates the numeric segment, so the two "Get order" requests are one operation.
    assert sorted(op.key for op in api.operations()) == [
        "GET /orders",
        "GET /orders/{id}",
        "POST /orders",
        "POST /ping",
    ]
    for operation in api.operations():
        assert operation.extras["provenance"] == INFERRED
        assert operation.extras["inference_evidence"]["sample_urls"]


def test_schemas_are_inferred_from_example_bodies() -> None:
    api = _import(_SHOP)
    create = _operation(api, "POST /orders")
    request = next(m for m in create.messages if m.role is MessageRole.REQUEST)
    response = next(m for m in create.messages if m.role is MessageRole.RESPONSE)
    assert request.payload is not None and response.payload is not None
    names = {typ.name for typ in api.types}
    assert {request.payload.name, response.payload.name} <= names
    fields = {field.name for typ in api.types if typ.name == request.payload.name for field in typ.fields}
    assert fields == {"sku", "qty"}


def test_folders_tag_operations_and_survive_as_the_postman_folder_path() -> None:
    api = _import(_SHOP)
    listing = _operation(api, "GET /orders")
    assert listing.tags == ["Orders"]
    assert listing.extras["postman_folder_path"] == ["Orders"]
    assert api.extras[POSTMAN_EXTRAS_KEY]["folders"] == ["Orders"]


def test_the_first_request_names_the_operation() -> None:
    api = _import(_SHOP)
    assert _operation(api, "GET /orders").name == "List orders"
    assert _operation(api, "GET /orders/{id}").name == "Get order 1"


def test_merged_requests_are_a_declared_limit() -> None:
    api = _import(_SHOP)
    limits = {limit["construct"]: limit for limit in api.extras[POSTMAN_EXTRAS_KEY]["capability_limits"]}
    assert limits["postman.merged_request"]["locations"] == ["Get order 1", "Get order 2"]


def test_request_auth_keeps_its_scheme_never_the_token() -> None:
    api = _import(_SHOP)
    create = _operation(api, "POST /orders")
    assert create.extras["postman_auth"] == {"type": "bearer", "parameters": ["token"]}
    assert create.extras["security"] == ["bearer"]
    assert "bearer" in api.extras["inferred_auth_schemes"]


def test_a_whole_variable_query_value_becomes_the_parameter_default() -> None:
    api = _import(_SHOP)
    limit = next(p for p in _operation(api, "GET /orders").parameters if p.name == "limit")
    assert limit.location is ParameterLocation.QUERY
    assert limit.default == "25"
    assert limit.extras["postman_sample"] == "{{pageSize}}"


def test_a_non_json_body_is_a_synthesized_string_with_its_raw_record() -> None:
    api = _import(_SHOP)
    ping = _operation(api, "POST /ping")
    [request] = [m for m in ping.messages if m.role is MessageRole.REQUEST]
    assert request.payload is not None and request.payload.name == "string"
    assert request.extras["provenance"] == SYNTHESIZED
    assert request.extras["postman_body_raw"] == "hello"


def test_the_emitter_contract_is_written() -> None:
    api = _import(_SHOP)
    create = _operation(api, "POST /orders")
    assert create.extras["postman_headers"] == [{"key": "Content-Type", "value": "application/json", "disabled": False}]
    request = next(m for m in create.messages if m.role is MessageRole.REQUEST)
    assert request.extras["postman_body_raw"] == '{"sku": "A-1", "qty": 2}'
    assert request.extras["postman_body_language"] == "json"
    response = next(m for m in create.messages if m.role is MessageRole.RESPONSE)
    assert response.name == "Created"
    assert api.extras["postman_schema_url"] == _SCHEMA
    assert api.extras["postman_variables"][0] == {"key": "baseUrl", "secret": False, "value": "https://api.example.com"}


def test_base_url_is_the_server() -> None:
    api = _import(_SHOP)
    assert [server.url for server in api.servers] == ["https://api.example.com"]


def test_scripts_reach_the_coverage_ledger_as_not_modelled() -> None:
    api = _import(_SHOP)
    manifest = build_import_preview_manifest(api, adapter_key="postman")
    rows = {row.source_construct: row for row in manifest.document_coverage}
    assert rows["postman.script"].coverage.value == "not-parsed-by-adapter"
    assert rows["postman.auth_credential"].coverage.value == "partially-mapped"
    assert rows["postman.merged_request"].coverage.value == "partially-mapped"


def test_no_planted_secret_reaches_the_model_or_the_manifest() -> None:
    text = _collection(
        [
            _request(
                "Secretive",
                "GET",
                ["accounts"],
                headers=[{"key": "X-Api-Key", "value": "demo-header-key-not-real"}],
                query=[{"key": "access_token", "value": "demo-query-token-not-real"}],
                auth={"type": "bearer", "bearer": [{"key": "token", "value": "demo-bearer-not-real"}]},
            )
        ],
        variables=[
            {"key": "baseUrl", "value": "https://api.example.com"},
            {"key": "clientSecret", "value": "demo-var-secret-not-real"},
        ],
    )
    api = _import(text)
    manifest = build_import_preview_manifest(api, adapter_key="postman")
    rendered = api.model_dump_json() + repr(manifest.document_coverage) + repr(manifest.entity_rows)
    for secret in _PLANTED:
        assert secret not in rendered, f"{secret} leaked"
    limits = {limit["construct"]: limit for limit in api.extras[POSTMAN_EXTRAS_KEY]["capability_limits"]}
    assert limits["postman.secret_variable"]["locations"] == ["clientSecret"]


def test_normalizing_is_deterministic() -> None:
    assert _import(_SHOP).model_dump_json() == _import(_SHOP).model_dump_json()
