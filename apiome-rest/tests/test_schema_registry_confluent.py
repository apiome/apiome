"""Tests for the Confluent-compatible schema registry API (CDG-4.3, #5975).

Three layers, all over the in-memory doubles of :mod:`tests.schema_registry_fakes` (the store's
SQL is covered by ``test_schema_registry.py``):

* **Wire contract** with ``TestClient`` — the ``application/vnd.schemaregistry.v1+json`` content
  type, Confluent's ``{"error_code", "message"}`` bodies and codes, the NONE-only compatibility gate
  (``42290``), soft and permanent deletes, config and mode, ``/schemas/types`` labels, audit rows.
* **Auth** — basic auth with the API key as password, bearer keys, the ``registry:read`` /
  ``registry:write`` allowlist (a read-only key cannot register), wrong tenant, malformed headers.
* **The real client** — ``confluent-kafka``'s ``SchemaRegistryClient``, ``AvroSerializer`` /
  ``AvroDeserializer`` and ``JSONSerializer`` / ``JSONDeserializer`` against the app served by
  uvicorn on a random localhost port, with zero client changes. Skipped when confluent-kafka is
  not installed.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from typing import Any, Dict, Iterator, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import (
    API_KEY_SCOPE_REGISTRY_READ,
    API_KEY_SCOPE_REGISTRY_WRITE,
    acceptable_scopes_for_request,
)
from app.main import app
from app.schema_registry import SchemaRegistryError
from app.schema_registry_confluent_routes import (
    CONFLUENT_MEDIA_TYPE,
    ConfluentRegistryError,
    api_key_from_basic,
)
from tests.schema_registry_fakes import FakeCatalog, FakeStore

T = "11111111-1111-1111-1111-111111111111"
KEY = "apiome_test_registry_key"
BASE = "/registry/schema/acme"

ORDER = json.dumps(
    {"type": "record", "name": "Order", "namespace": "acme", "fields": [{"name": "id", "type": "string"}]}
)
ORDER_V2 = json.dumps(
    {
        "type": "record",
        "name": "Order",
        "namespace": "acme",
        "fields": [{"name": "id", "type": "string"}, {"name": "total", "type": ["null", "double"], "default": None}],
    }
)
PERSON = json.dumps(
    {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Person",
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
)


def _basic(password: str = KEY, user: str = "my-producer") -> Dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


class Registry:
    """The app wired to in-memory doubles, with one API key whose scopes a test can change."""

    def __init__(self) -> None:
        self.catalog = FakeCatalog()
        self.store = FakeStore(self.catalog)
        self.scopes: List[str] = [API_KEY_SCOPE_REGISTRY_READ, API_KEY_SCOPE_REGISTRY_WRITE]
        self.tenant_slug = "acme"
        self.permissions: List[str] = []
        self.audit: List[Dict[str, Any]] = []

    def validate_api_key(self, key: str) -> Any:
        if key != KEY:
            return None
        return {"tenant_slug": self.tenant_slug, "tenant_id": T, "scopes": list(self.scopes),
                "created_by_user_id": "u1"}

    def enforce(self, db, auth_data, resource, action, target=None) -> str:
        self.permissions.append(f"{resource}:{action}")
        return "u1"

    def record(self, db, auth_data, action, outcome="success", **kw) -> None:
        self.audit.append({"action": action, "outcome": outcome, **kw})


@pytest.fixture
def reg() -> Iterator[Registry]:
    """Patch the registry's collaborators; nothing reaches a database."""
    r = Registry()
    with patch("app.schema_registry_service.store", r.store), patch(
        "app.schema_registry_confluent_routes.store", r.store
    ), patch("app.schema_registry_confluent_routes.db", r.catalog), patch(
        "app.import_source_pipeline.run_adapter_import_job", r.catalog.run_import
    ), patch("app.auth.db.validate_api_key", r.validate_api_key), patch(
        "app.schema_registry_confluent_routes.enforce_permission", r.enforce
    ), patch("app.schema_registry_confluent_routes.record_registry_audit", r.record):
        yield r


client = TestClient(app)


def _post(path: str, body: Any, **headers: str):
    return client.post(BASE + path, json=body, headers={**_basic(), "Content-Type": CONFLUENT_MEDIA_TYPE, **headers})


def _get(path: str, **kw):
    return client.get(BASE + path, headers=_basic(), **kw)


def _error(resp) -> Dict[str, Any]:
    assert resp.headers["content-type"].startswith(CONFLUENT_MEDIA_TYPE)
    body = resp.json()
    assert set(body) == {"error_code", "message"}
    return body


# --------------------------------------------------------------------------- pure helpers


def test_api_key_from_basic():
    assert api_key_from_basic(_basic()["Authorization"]) == KEY
    assert api_key_from_basic(_basic("pa:ss")["Authorization"]) == "pa:ss"
    assert api_key_from_basic("Basic !!!not-base64") is None
    assert api_key_from_basic("Basic " + base64.b64encode(b"no-colon").decode()) is None
    assert api_key_from_basic("Basic " + base64.b64encode(b"user:").decode()) is None
    assert api_key_from_basic("Bearer abc") is None


def test_error_mapping_uses_confluent_codes():
    cases = {
        "subject-not-found": (404, 40401),
        "version-not-found": (404, 40402),
        "schema-not-found": (404, 40403),
        "schema-invalid": (422, 42201),
        "version-invalid": (422, 42202),
        "compatibilityLevel-invalid": (422, 42203),
        "mode-invalid": (422, 42204),
        "subject-read-only": (422, 42205),
        "compatibility-rules-unavailable": (422, 42290),
    }
    for code, expected in cases.items():
        err = ConfluentRegistryError.from_registry(SchemaRegistryError(code, "m"))
        assert (err.status_code, err.error_code) == expected
    assert ConfluentRegistryError.from_registry(
        SchemaRegistryError("compatibility-rules-unavailable", "why")
    ).message.startswith("compatibility-rules-unavailable:")


@pytest.mark.parametrize(
    "method, path, scope",
    [
        ("GET", f"{BASE}/subjects", API_KEY_SCOPE_REGISTRY_READ),
        ("GET", f"{BASE}/schemas/ids/1", API_KEY_SCOPE_REGISTRY_READ),
        ("POST", f"{BASE}/subjects/orders-value", API_KEY_SCOPE_REGISTRY_READ),
        ("POST", f"{BASE}/compatibility/subjects/orders-value/versions/latest", API_KEY_SCOPE_REGISTRY_READ),
        ("POST", f"{BASE}/subjects/orders-value/versions", API_KEY_SCOPE_REGISTRY_WRITE),
        ("PUT", f"{BASE}/config", API_KEY_SCOPE_REGISTRY_WRITE),
        ("PUT", f"{BASE}/config/orders-value", API_KEY_SCOPE_REGISTRY_WRITE),
        ("PUT", f"{BASE}/mode", API_KEY_SCOPE_REGISTRY_WRITE),
        ("DELETE", f"{BASE}/subjects/orders-value", API_KEY_SCOPE_REGISTRY_WRITE),
    ],
)
def test_scope_allowlist(method, path, scope):
    assert acceptable_scopes_for_request(method, path) == [scope]


def test_registry_scopes_admit_nothing_else():
    for method, path in [("GET", "/v1/tenants/acme/schema-registry/subjects"), ("GET", "/v1/projects/acme/x/gate")]:
        scopes = acceptable_scopes_for_request(method, path)
        assert API_KEY_SCOPE_REGISTRY_READ not in scopes and API_KEY_SCOPE_REGISTRY_WRITE not in scopes


# --------------------------------------------------------------------------- auth


def test_basic_bearer_and_x_api_key_all_authenticate(reg):
    assert _get("/subjects").status_code == 200
    assert client.get(BASE + "/subjects", headers={"Authorization": f"Bearer {KEY}"}).status_code == 200
    assert client.get(BASE + "/subjects", headers={"X-API-Key": KEY}).status_code == 200


def test_missing_or_bad_credentials_are_confluent_401s(reg):
    for headers in ({}, _basic("wrong"), {"Authorization": "Basic %%%"}):
        resp = client.get(BASE + "/subjects", headers=headers)
        assert resp.status_code == 401
        assert _error(resp)["error_code"] == 40101


def test_another_tenants_key_is_403(reg):
    reg.tenant_slug = "other"
    resp = _get("/subjects")
    assert resp.status_code == 403 and _error(resp)["error_code"] == 40301


def test_a_read_only_key_cannot_register(reg):
    reg.scopes = [API_KEY_SCOPE_REGISTRY_READ]
    resp = _post("/subjects/orders-value/versions", {"schema": ORDER})
    assert resp.status_code == 403 and _error(resp)["error_code"] == 40301
    assert _get("/subjects").status_code == 200


def test_a_ci_key_cannot_reach_the_registry(reg):
    reg.scopes = ["lint:read"]
    assert _get("/subjects").status_code == 403


# --------------------------------------------------------------------------- subjects and versions


def test_register_lookup_and_read(reg):
    resp = _post("/subjects/orders-value/versions", {"schema": ORDER})
    assert resp.status_code == 200 and resp.json() == {"id": 1}
    assert resp.headers["content-type"].startswith(CONFLUENT_MEDIA_TYPE)
    assert _post("/subjects/orders-value/versions", {"schema": ORDER, "schemaType": "AVRO"}).json() == {"id": 1}
    assert _get("/subjects").json() == ["orders-value"]
    assert _get("/subjects/orders-value/versions").json() == [1]

    one = _get("/subjects/orders-value/versions/1").json()
    assert one == {"subject": "orders-value", "id": 1, "version": 1, "schema": ORDER}
    assert _get("/subjects/orders-value/versions/latest").json() == one
    assert _get("/subjects/orders-value/versions/-1").json() == one
    raw = _get("/subjects/orders-value/versions/1/schema")
    assert raw.text == ORDER

    found = _post("/subjects/orders-value", {"schema": ORDER}).json()
    assert (found["id"], found["version"], found["subject"]) == (1, 1, "orders-value")
    assert reg.permissions[0] == "imports:create"
    assert [a["action"] for a in reg.audit] == ["registry.subject.register"]  # the repeat created nothing
    assert reg.audit[0]["schema_id"] == "1" and reg.audit[0]["namespace"] == "orders-value"


def test_json_schema_registration_carries_its_type(reg):
    assert _post("/subjects/people-value/versions", {"schema": PERSON, "schemaType": "JSON"}).json() == {"id": 1}
    body = _get("/schemas/ids/1").json()
    assert body == {"schema": PERSON, "schemaType": "JSON"}


def test_not_found_codes(reg):
    _post("/subjects/orders-value/versions", {"schema": ORDER})
    assert _error(_get("/subjects/nope/versions"))["error_code"] == 40401
    assert _error(_get("/subjects/orders-value/versions/9"))["error_code"] == 40402
    assert _error(_get("/schemas/ids/99"))["error_code"] == 40403
    assert _error(_post("/subjects/orders-value", {"schema": ORDER_V2}))["error_code"] == 40403
    assert _error(_post("/subjects/nope", {"schema": ORDER}))["error_code"] == 40401
    bad = _get("/subjects/orders-value/versions/zero")
    assert bad.status_code == 422 and _error(bad)["error_code"] == 42202


def test_invalid_schemas_are_42201(reg):
    for body in ({"schema": "{not json"}, {"schema": ORDER, "schemaType": "XML"}, {"nothing": 1}):
        resp = _post("/subjects/orders-value/versions", body)
        assert resp.status_code == 422 and _error(resp)["error_code"] == 42201
    assert reg.audit and all(a["outcome"] == "failure" for a in reg.audit if "outcome" in a)


def test_ids_are_shared_across_subjects_and_listed(reg):
    _post("/subjects/orders-value/versions", {"schema": ORDER})
    assert _post("/subjects/audit-value/versions", {"schema": ORDER}).json() == {"id": 1}
    assert _get("/schemas/ids/1/subjects").json() == ["audit-value", "orders-value"]
    assert _get("/schemas/ids/1/versions").json() == [
        {"subject": "audit-value", "version": 1},
        {"subject": "orders-value", "version": 1},
    ]


# --------------------------------------------------------------------------- compatibility (NONE-only)


def test_a_second_version_under_backward_is_refused_with_42290(reg):
    _post("/subjects/orders-value/versions", {"schema": ORDER})  # the first version needs no verdict
    resp = _post("/subjects/orders-value/versions", {"schema": ORDER_V2})
    assert resp.status_code == 422
    body = _error(resp)
    assert body["error_code"] == 42290 and body["message"].startswith("compatibility-rules-unavailable")
    assert _get("/subjects/orders-value/versions").json() == [1]


def test_none_registers_without_a_check(reg):
    _post("/subjects/orders-value/versions", {"schema": ORDER})
    assert client.put(BASE + "/config/orders-value", json={"compatibility": "NONE"}, headers=_basic()).json() == {
        "compatibility": "NONE"
    }
    assert _post("/subjects/orders-value/versions", {"schema": ORDER_V2}).json() == {"id": 2}
    assert _get("/subjects/orders-value/versions").json() == [1, 2]


def test_compatibility_routes(reg):
    _post("/subjects/orders-value/versions", {"schema": ORDER})
    for path in ("/compatibility/subjects/orders-value/versions/latest", "/compatibility/subjects/orders-value/versions"):
        resp = _post(path, {"schema": ORDER_V2})
        assert resp.status_code == 422 and _error(resp)["error_code"] == 42290
    client.put(BASE + "/config", json={"compatibility": "NONE"}, headers=_basic())
    assert _post("/compatibility/subjects/orders-value/versions/1", {"schema": ORDER_V2}).json() == {
        "is_compatible": True,
        "messages": [],
    }
    assert _error(_post("/compatibility/subjects/orders-value/versions/7", {"schema": ORDER_V2}))["error_code"] == 40402
    assert _error(_post("/compatibility/subjects/nope/versions", {"schema": ORDER_V2}))["error_code"] == 40401


def test_schema_types_are_labelled(reg):
    with patch("app.schema_registry_confluent_routes.registrable_schema_types", return_value=("AVRO", "JSON")):
        assert _get("/schemas/types").json() == ["AVRO", "JSON"]
        detailed = _get("/schemas/types", params={"details": "true"}).json()
    assert detailed == [
        {"schemaType": "AVRO", "compatibilityRules": "unavailable", "registrableUnder": ["NONE"]},
        {"schemaType": "JSON", "compatibilityRules": "unavailable", "registrableUnder": ["NONE"]},
    ]


# --------------------------------------------------------------------------- config, mode, delete


def test_config_routes(reg):
    assert _get("/config").json() == {"compatibilityLevel": "BACKWARD"}
    resp = client.put(BASE + "/config", json={"compatibility": "FULL_TRANSITIVE"}, headers=_basic())
    assert resp.json() == {"compatibility": "FULL_TRANSITIVE"}
    assert _get("/config").json() == {"compatibilityLevel": "FULL_TRANSITIVE"}
    bad = client.put(BASE + "/config", json={"compatibility": "SIDEWAYS"}, headers=_basic())
    assert bad.status_code == 422 and _error(bad)["error_code"] == 42203

    _post("/subjects/orders-value/versions", {"schema": ORDER})
    assert _error(_get("/config/orders-value"))["error_code"] == 40408
    assert _get("/config/orders-value", params={"defaultToGlobal": "true"}).json() == {
        "compatibilityLevel": "FULL_TRANSITIVE"
    }
    client.put(BASE + "/config/orders-value", json={"compatibility": "NONE"}, headers=_basic())
    assert _get("/config/orders-value").json() == {"compatibilityLevel": "NONE"}
    assert [a["action"] for a in reg.audit].count("registry.subject.config") == 2


def test_mode_routes_and_readonly(reg):
    assert _get("/mode").json() == {"mode": "READWRITE"}
    bad = client.put(BASE + "/mode", json={"mode": "IMPORT"}, headers=_basic())
    assert bad.status_code == 422 and _error(bad)["error_code"] == 42204
    assert client.put(BASE + "/mode/orders-value", json={"mode": "READONLY"}, headers=_basic()).json() == {
        "mode": "READONLY"
    }
    assert _get("/mode/orders-value").json() == {"mode": "READONLY"}
    resp = _post("/subjects/orders-value/versions", {"schema": ORDER})
    assert resp.status_code == 422 and _error(resp)["error_code"] == 42205


def test_soft_then_permanent_delete(reg):
    _post("/subjects/orders-value/versions", {"schema": ORDER})
    live = client.delete(BASE + "/subjects/orders-value", params={"permanent": "true"}, headers=_basic())
    assert _error(live)["error_code"] == 40405

    assert client.delete(BASE + "/subjects/orders-value", headers=_basic()).json() == [1]
    assert _get("/subjects").json() == []
    assert _get("/subjects", params={"deleted": "true"}).json() == ["orders-value"]
    assert _get("/schemas/ids/1").status_code == 200  # ids keep resolving
    again = client.delete(BASE + "/subjects/orders-value", headers=_basic())
    assert _error(again)["error_code"] == 40404

    gone = client.delete(BASE + "/subjects/orders-value", params={"permanent": "true"}, headers=_basic())
    assert gone.json() == [1]
    assert _get("/subjects", params={"deleted": "true"}).json() == []
    assert _error(client.delete(BASE + "/subjects/orders-value", headers=_basic()))["error_code"] == 40401
    assert "imports:edit" in reg.permissions and "imports:delete" in reg.permissions
    deletes = [a for a in reg.audit if a["action"] == "registry.subject.delete"]
    assert [d["detail"]["permanent"] for d in deletes] == [False, True]


# --------------------------------------------------------------------------- the real client


@pytest.fixture
def served(reg) -> Iterator[str]:
    """Serve the app with uvicorn on a random localhost port; yield the registry base URL."""
    uvicorn = pytest.importorskip("uvicorn")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, lifespan="off", log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "uvicorn did not start"
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}{BASE}"
    finally:
        server.should_exit = True
        thread.join(10)


def test_confluent_kafka_client_with_zero_changes(reg, served):
    """The confluent-kafka client registers, looks up, serializes and deserializes against Apiome."""
    pytest.importorskip("confluent_kafka.schema_registry")
    pytest.importorskip("fastavro")
    from confluent_kafka.schema_registry import Schema, SchemaRegistryClient
    from confluent_kafka.schema_registry.avro import AvroDeserializer, AvroSerializer
    from confluent_kafka.schema_registry.json_schema import JSONDeserializer, JSONSerializer
    from confluent_kafka.serialization import MessageField, SerializationContext

    conf = {"url": served, "basic.auth.user.info": f"producer:{KEY}"}
    producer = SchemaRegistryClient(conf)

    schema_id = producer.register_schema("orders-value", Schema(ORDER, "AVRO"))
    assert schema_id == 1
    assert producer.register_schema("orders-value", Schema(ORDER, "AVRO")) == 1
    assert producer.get_subjects() == ["orders-value"]
    latest = producer.get_latest_version("orders-value")
    assert (latest.schema_id, latest.version, latest.schema.schema_str) == (1, 1, ORDER)
    assert producer.lookup_schema("orders-value", Schema(ORDER, "AVRO")).version == 1
    assert producer.get_compatibility() == "BACKWARD"

    orders = SerializationContext("orders", MessageField.VALUE)
    payload = AvroSerializer(producer, ORDER)({"id": "o-1"}, orders)
    assert payload[0] == 0 and int.from_bytes(payload[1:5], "big") == 1  # Confluent wire format
    # A fresh client has nothing cached: it must fetch the writer schema by id.
    consumer = SchemaRegistryClient({"url": served, "basic.auth.user.info": f"consumer:{KEY}"})
    assert AvroDeserializer(consumer)(payload, orders) == {"id": "o-1"}

    people = SerializationContext("people", MessageField.VALUE)
    json_payload = JSONSerializer(PERSON, producer)({"name": "Ada"}, people)
    assert JSONDeserializer(PERSON, schema_registry_client=consumer)(json_payload, people) == {"name": "Ada"}
    assert sorted(producer.get_subjects()) == ["orders-value", "people-value"]

    # BACKWARD has no XPC-4.x rules yet: a second version is refused, not accepted unchecked.
    from confluent_kafka.schema_registry.error import SchemaRegistryError as ClientError

    with pytest.raises(ClientError) as exc:
        producer.register_schema("orders-value", Schema(ORDER_V2, "AVRO"))
    assert exc.value.http_status_code == 422 and exc.value.error_code == 42290
    producer.set_compatibility("orders-value", "NONE")
    assert producer.register_schema("orders-value", Schema(ORDER_V2, "AVRO")) == 3
    assert producer.test_compatibility("orders-value", Schema(ORDER_V2, "AVRO")) is True
    assert producer.delete_subject("people-value") == [1]
