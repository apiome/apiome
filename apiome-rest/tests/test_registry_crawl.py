"""Registry-as-source ingestion — MFI-18.5 (#3978).

The crawl SPI (:mod:`app.registry_crawl`) runs on the CDG-1.1 connector engine. These tests drive
:func:`app.catalog_connector_sync.run_connector_sync` over the in-memory connector store with a
fake registry behind an httpx transport, for each built-in crawl (A2A registry, xRegistry, FHIR
``/metadata``), and assert the acceptance criteria:

* a registry endpoint bulk-imports its artifacts as **individually versioned catalog entries**
  (one inventory row and one catalog item per artifact, each parsed by the adapter it names);
* a **re-crawl imports only changed artifacts**;
* every revision carries **per-artifact provenance**;
* fetches are **rate-limited, budgeted, size-capped and SSRF-guarded**.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx
import pytest
from catalog_connector_fakes import FakeConnectorStore, FakeDb, restore_builtin_sources

from app import registry_crawl as rc
from app.catalog_connector_sync import register_connector_source, run_connector_sync, syncable_kinds
from app.catalog_connectors import KINDS, ConnectorError, connector_provenance_metadata
from app.config import settings
from app.import_source import (
    describe_import_sources,
    get_import_source,
    load_builtin_import_sources,
    resolve_import_source_key,
)
from app.refresh_source import RefreshSourceError
from app.registry_crawl import (
    HostRateLimiter,
    Page,
    RegistryConnectorSource,
    RegistryHttp,
    get_registry_crawl,
    paginate,
    registry_crawl_protocols,
    validate_registry_scope,
)

load_builtin_import_sources()

TENANT = "11111111-1111-4111-8111-111111111111"
ACTOR = "33333333-3333-4333-8333-333333333333"
_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui/examples"
_CARD = json.loads((_EXAMPLES / "a2a/02-typical-travel-concierge.json").read_text())
_ECHO = json.loads((_EXAMPLES / "a2a/01-minimal-echo-agent.json").read_text())


# ---------------------------------------------------------------------------
# A fake registry and the engine harness
# ---------------------------------------------------------------------------


class FakeRegistry:
    """Routes ``GET url`` (with query) to a body, a ``(status, body)`` or ``(status, body, headers)``."""

    def __init__(self) -> None:
        self.routes: Dict[str, Any] = {}
        self.requests: List[str] = []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            self.requests.append(url)
            route = self.routes.get(url)
            if route is None:
                return httpx.Response(404, text="not found")
            if not isinstance(route, tuple):
                route = (200, route)
            status, body = route[0], route[1]
            headers = route[2] if len(route) > 2 else {}
            text = body if isinstance(body, (bytes, str)) else json.dumps(body)
            content = text if isinstance(text, bytes) else text.encode()
            return httpx.Response(status, content=content, headers=headers)

        return httpx.MockTransport(handler)


class _NoWait(HostRateLimiter):
    """A limiter that records instead of sleeping."""

    def __init__(self) -> None:
        super().__init__(1.0, sleep=lambda _s: None)


class _ParsingImporter:
    """Parses each fetched artifact with the adapter it names, and returns one item per remote id."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, connector, candidate, document, item_row, actor_id):
        adapter = get_import_source(resolve_import_source_key(document.import_kind))
        assert adapter is not None, document.import_kind
        model = adapter.normalize(adapter.parse(document.content.decode("utf-8"), source_label=document.filename))
        self.calls.append(
            {
                "remote_id": candidate.remote_id,
                "kind": document.import_kind,
                "revision": document.revision,
                "format": model.format,
                "provenance": connector_provenance_metadata(
                    connector,
                    remote_id=candidate.remote_id,
                    remote_revision=document.revision,
                    remote_name=candidate.name,
                    source_uri=document.source_uri,
                ),
            }
        )
        return item_row.get("project_id") or f"proj-{len(self.calls)}"


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)
    monkeypatch.setenv("APIOME_SSRF_ALLOW_PRIVATE", "0")


_RESOLVED = {"address": "93.184.216.34"}


def _fake_getaddrinfo(host, *args, **kwargs):
    return [(2, 1, 6, "", (_RESOLVED["address"], 0))]


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    """Resolve every test host to a public address so the SSRF guard lets the fake through."""
    import socket

    _RESOLVED["address"] = "93.184.216.34"
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)


@pytest.fixture
def store(monkeypatch) -> FakeConnectorStore:
    return FakeConnectorStore().install(monkeypatch)


@pytest.fixture
def registry() -> FakeRegistry:
    fake = FakeRegistry()
    register_connector_source(
        rc.KIND,
        lambda connector, credentials: RegistryConnectorSource(
            connector, credentials, transport=fake.transport(), limiter=_NoWait()
        ),
        scope_validator=validate_registry_scope,
    )
    yield fake
    restore_builtin_sources()


def _sync(store, base_url: str, scope: Dict[str, Any], importer: _ParsingImporter, connector=None):
    connector = connector or store.add_connector(
        TENANT, kind=rc.KIND, name="Registry", base_url=base_url, scope=scope, created_by=ACTOR
    )
    result = run_connector_sync(FakeDb(), store.connectors[connector["id"]], actor_id=ACTOR, importer=importer)
    return connector, result


# ---------------------------------------------------------------------------
# The SPI
# ---------------------------------------------------------------------------


def test_three_crawls_are_registered_and_declared_by_their_adapters() -> None:
    assert registry_crawl_protocols() == ["a2a-registry", "fhir-metadata", "xregistry"]
    declared = {d.key: d.registry_crawl for d in describe_import_sources() if d.registry_crawl}
    assert declared == {"a2a": "a2a-registry", "cloudevents": "xregistry", "fhir": "fhir-metadata"}
    for adapter_key, protocol in declared.items():
        assert get_registry_crawl(protocol).import_source == adapter_key


def test_every_declared_crawl_exists() -> None:
    for descriptor in describe_import_sources():
        if descriptor.registry_crawl:
            assert get_registry_crawl(descriptor.registry_crawl) is not None, descriptor.key


def test_the_registry_kind_is_a_syncable_connector_kind() -> None:
    assert rc.KIND in KINDS
    assert rc.KIND in syncable_kinds()


@pytest.mark.parametrize(
    ("scope", "base", "message"),
    [
        ({"protocol": "a2a-registry"}, None, "base URL"),
        ({}, "https://r.example", "protocol"),
        ({"protocol": "nope"}, "https://r.example", "protocol"),
        ({"protocol": "a2a-registry", "groups": ["x"]}, "https://r.example", "Unknown scope"),
        ({"protocol": "xregistry", "groups": []}, "https://r.example", "groups"),
        ({"protocol": "xregistry", "include": []}, "https://r.example", "include"),
        ({"protocol": "xregistry", "include": ["schemas", "nope"]}, "https://r.example", "include"),
        ({"protocol": "fhir-metadata", "includeProfiles": "yes"}, "https://r.example", "includeProfiles"),
        ({"protocol": "a2a-registry", "requestsPerSecond": 0}, "https://r.example", "requestsPerSecond"),
        ({"protocol": "a2a-registry", "requestsPerSecond": 50}, "https://r.example", "requestsPerSecond"),
    ],
)
def test_scope_validation(scope: Dict[str, Any], base: Optional[str], message: str) -> None:
    with pytest.raises(ConnectorError, match=message):
        validate_registry_scope(scope, base)


def test_valid_scopes_pass() -> None:
    validate_registry_scope({"protocol": "xregistry", "groups": ["orders"], "requestsPerSecond": 2}, "https://r.example")
    validate_registry_scope({"protocol": "xregistry", "include": ["messages", "endpoints"]}, "https://r.example")
    validate_registry_scope({"protocol": "fhir-metadata", "includeProfiles": True}, "https://r.example")


def test_paginate_follows_tokens_and_guards_repeats_and_limits() -> None:
    pages = {None: Page(items=[1, 2], next_token="b"), "b": Page(items=[3], next_token="c"), "c": Page(items=[4])}
    assert list(paginate(lambda t: pages[t])) == [1, 2, 3, 4]
    looping = {None: Page(items=[1], next_token="a"), "a": Page(items=[2], next_token="a")}
    assert list(paginate(lambda t: looping[t])) == [1, 2]
    with pytest.raises(RefreshSourceError, match="more than 3 pages"):
        list(paginate(lambda t: Page(items=[0], next_token=f"{t}x"), max_pages=3))


def test_the_rate_limiter_spaces_requests_per_host() -> None:
    now = [0.0]
    slept: List[float] = []

    def sleep(seconds: float) -> None:
        slept.append(round(seconds, 3))
        now[0] += seconds

    limiter = HostRateLimiter(4.0, clock=lambda: now[0], sleep=sleep)
    for host in ("a", "a", "a", "b"):
        limiter.wait(host)
    assert slept == [0.25, 0.25]  # the third request to "a" waits twice; "b" is independent


def test_http_budget_size_cap_and_ssrf(monkeypatch) -> None:
    fake = FakeRegistry()
    fake.routes["https://r.example/x"] = {"ok": True}
    with RegistryHttp(transport=fake.transport(), limiter=_NoWait(), max_requests=1) as http:
        assert http.get_json("https://r.example/x") == {"ok": True}
        with pytest.raises(RefreshSourceError) as excinfo:
            http.get_json("https://r.example/x")
        assert excinfo.value.error_class == rc.ERROR_CLASS_BUDGET
    monkeypatch.setattr(rc, "MAX_RESPONSE_BYTES", 10)
    with RegistryHttp(transport=fake.transport(), limiter=_NoWait()) as http:
        fake.routes["https://r.example/big"] = "x" * 50
        with pytest.raises(RefreshSourceError, match="more than 10 bytes"):
            http.get("https://r.example/big")
    _RESOLVED["address"] = "10.0.0.5"
    with RegistryHttp(transport=fake.transport(), limiter=_NoWait()) as http:
        with pytest.raises(RefreshSourceError) as excinfo:
            http.get("https://r.example/x")
    assert excinfo.value.error_class == rc.ERROR_CLASS_ADDRESS_REFUSED


def test_a_non_2xx_answer_carries_its_status() -> None:
    fake = FakeRegistry()
    fake.routes["https://r.example/x"] = (503, "down")
    with RegistryHttp(transport=fake.transport(), limiter=_NoWait()) as http:
        with pytest.raises(RefreshSourceError) as excinfo:
            http.get("https://r.example/x")
    assert excinfo.value.http_status == 503 and "down" in str(excinfo.value)


# ---------------------------------------------------------------------------
# A2A registry
# ---------------------------------------------------------------------------

_A2A = "https://agents.example"


def _a2a_registry(
    registry: FakeRegistry, *, concierge_version: str = "2.4.0", concierge_card: Optional[Dict[str, Any]] = None
) -> None:
    registry.routes[_A2A] = {
        "agents": [
            {"url": "https://concierge.example", "name": "Concierge", "version": concierge_version},
            "https://echo.example/.well-known/agent-card.json",
        ],
        "nextPageToken": "p2",
    }
    registry.routes[f"{_A2A}?pageToken=p2"] = {"agents": [{"card": _ECHO | {"name": "Inline Echo"}}]}
    # Served on the legacy path only.
    registry.routes["https://concierge.example/.well-known/agent.json"] = concierge_card or _CARD
    registry.routes["https://echo.example/.well-known/agent-card.json"] = _ECHO


def test_an_a2a_registry_imports_each_agent_as_its_own_catalog_item(store, registry) -> None:
    _a2a_registry(registry)
    importer = _ParsingImporter()
    connector, result = _sync(store, _A2A, {"protocol": "a2a-registry"}, importer)
    assert result.status == "succeeded"
    assert sorted(c["remote_id"] for c in importer.calls) == [
        "Inline Echo",
        "https://concierge.example/.well-known/agent-card.json",
        "https://echo.example/.well-known/agent-card.json",
    ]
    assert {c["format"] for c in importer.calls} == {"a2a"}
    projects = {store.item(connector["id"], c["remote_id"])["project_id"] for c in importer.calls}
    assert len(projects) == 3  # individually versioned: one catalog item each
    # The origin URL fell back to the legacy well-known card path after a 404.
    assert "https://concierge.example/.well-known/agent.json" in registry.requests


def test_a_recrawl_imports_only_the_changed_agent(store, registry) -> None:
    _a2a_registry(registry)
    first = _ParsingImporter()
    connector, _ = _sync(store, _A2A, {"protocol": "a2a-registry"}, first)
    card_id = "https://concierge.example/.well-known/agent-card.json"
    item_before = store.item(connector["id"], card_id)["project_id"]
    edited = json.loads(json.dumps(_CARD))
    edited["description"] = "Plans trips, now with rail."
    _a2a_registry(registry, concierge_version="2.5.0", concierge_card=edited)
    again = _ParsingImporter()
    _, result = _sync(store, _A2A, {"protocol": "a2a-registry"}, again, connector=connector)
    assert [c["remote_id"] for c in again.calls] == ["https://concierge.example/.well-known/agent-card.json"]
    assert again.calls[0]["revision"] == "2.5.0"
    assert result.summary["unchanged"] == 2
    # A new revision of the same catalog item, not a second item.
    assert store.item(connector["id"], card_id)["project_id"] == item_before


def test_a_new_revision_with_unchanged_content_is_not_reimported(store, registry) -> None:
    _a2a_registry(registry)
    connector, _ = _sync(store, _A2A, {"protocol": "a2a-registry"}, _ParsingImporter())
    _a2a_registry(registry, concierge_version="2.4.1")  # the registry bumped the version only
    again = _ParsingImporter()
    _, result = _sync(store, _A2A, {"protocol": "a2a-registry"}, again, connector=connector)
    # Concierge (revision moved) and Echo (no revision: always compared by content) are fetched;
    # neither content changed, so nothing is imported.
    assert again.calls == [] and result.summary["fetched"] == 2 and result.summary["unchanged"] == 3


def test_an_unchanged_registry_imports_nothing(store, registry) -> None:
    _a2a_registry(registry)
    connector, _ = _sync(store, _A2A, {"protocol": "a2a-registry"}, _ParsingImporter())
    again = _ParsingImporter()
    _, result = _sync(store, _A2A, {"protocol": "a2a-registry"}, again, connector=connector)
    assert again.calls == [] and result.summary["unchanged"] == 3


def test_each_revision_records_its_registry_provenance(store, registry) -> None:
    _a2a_registry(registry)
    importer = _ParsingImporter()
    connector, _ = _sync(store, _A2A, {"protocol": "a2a-registry"}, importer)
    concierge = next(c for c in importer.calls if "concierge" in c["remote_id"])
    assert concierge["provenance"] == {
        "inputKind": "connector",
        "connectorId": connector["id"],
        "connectorKind": "registry",
        "connectorName": "Registry",
        "remoteId": "https://concierge.example/.well-known/agent-card.json",
        "remoteRevision": "2.4.0",
        "remoteName": "Concierge",
        "sourceUri": "https://concierge.example/.well-known/agent.json",
        "registryProtocol": "a2a-registry",
    }


def test_a_registry_without_an_agents_list_fails_the_run(store, registry) -> None:
    registry.routes[_A2A] = {"servers": []}
    _, result = _sync(store, _A2A, {"protocol": "a2a-registry"}, _ParsingImporter())
    assert result.status == "failed" and "agents list" in result.error_message


def test_one_missing_card_does_not_stop_the_others(store, registry) -> None:
    registry.routes[_A2A] = ["https://gone.example", "https://echo.example/.well-known/agent-card.json"]
    registry.routes["https://echo.example/.well-known/agent-card.json"] = _ECHO
    importer = _ParsingImporter()
    _, result = _sync(store, _A2A, {"protocol": "a2a-registry"}, importer)
    assert [c["remote_id"] for c in importer.calls] == ["https://echo.example/.well-known/agent-card.json"]
    assert result.status == "succeeded" and result.summary["failed"] == 1


# ---------------------------------------------------------------------------
# xRegistry
# ---------------------------------------------------------------------------

_XR = "https://xreg.example/reg"
_ORDER_AVRO = {
    "type": "record",
    "name": "Order",
    "namespace": "com.example",
    "fields": [{"name": "id", "type": "string"}],
}
_PAYMENT_JSON = {"$schema": "http://json-schema.org/draft-07/schema#", "title": "Payment", "type": "object",
                 "properties": {"amount": {"type": "number"}}}


def _xregistry(registry: FakeRegistry, *, order_epoch: int = 1, order_doc: Optional[Dict[str, Any]] = None) -> None:
    registry.routes[f"{_XR}/schemagroups"] = (
        200,
        {"orders": {"schemagroupid": "orders"}},
        {"Link": f'<{_XR}/schemagroups?page=2>; rel="next"'},
    )
    registry.routes[f"{_XR}/schemagroups?page=2"] = {
        "payments": {"schemagroupid": "payments", "schemasurl": f"{_XR}/schemagroups/payments/schemas"},
        "legal": {"schemagroupid": "legal"},
    }
    registry.routes[f"{_XR}/schemagroups/orders/schemas"] = {
        # xRegistry moves epoch and modifiedat together on every change.
        "order": {"schemaid": "order", "format": "Avro/1.11.0", "versionid": "1", "epoch": order_epoch,
                  "modifiedat": f"2026-10-0{order_epoch}T00:00:00Z"},
    }
    registry.routes[f"{_XR}/schemagroups/payments/schemas"] = {
        "payment": {"schemaid": "payment", "format": "JsonSchema/draft-07", "defaultversionid": "3", "epoch": 7,
                    "schema": _PAYMENT_JSON},
        "ledger": {"schemaid": "ledger", "format": "JsonStructure/draft-04", "epoch": 1},
    }
    registry.routes[f"{_XR}/schemagroups/legal/schemas"] = {}
    registry.routes[f"{_XR}/schemagroups/orders/schemas/order"] = order_doc or _ORDER_AVRO


def test_an_xregistry_imports_each_schema_with_the_adapter_its_format_names(store, registry) -> None:
    _xregistry(registry)
    importer = _ParsingImporter()
    connector, result = _sync(store, _XR, {"protocol": "xregistry"}, importer)
    assert result.status == "succeeded"
    by_id = {c["remote_id"]: c for c in importer.calls}
    assert set(by_id) == {"schemagroups/orders/schemas/order", "schemagroups/payments/schemas/payment"}
    assert by_id["schemagroups/orders/schemas/order"]["kind"] == "avro"
    assert by_id["schemagroups/orders/schemas/order"]["revision"] == "1+e1"
    assert by_id["schemagroups/payments/schemas/payment"]["kind"] == "json-schema"
    assert by_id["schemagroups/payments/schemas/payment"]["revision"] == "3+e7"
    # The inline schema was not fetched; the Avro one was read from its document view.
    assert f"{_XR}/schemagroups/payments/schemas/payment" not in registry.requests
    assert f"{_XR}/schemagroups/orders/schemas/order" in registry.requests
    # A format with no adapter is reported, not imported.
    assert result.summary["findings"] == [
        {"remoteId": "schemagroups/payments/schemas/ledger", "reason": "unsupported-format: JsonStructure/draft-04"}
    ]


def test_an_xregistry_recrawl_imports_only_the_schema_whose_epoch_moved(store, registry) -> None:
    _xregistry(registry)
    connector, _ = _sync(store, _XR, {"protocol": "xregistry"}, _ParsingImporter())
    grown = json.loads(json.dumps(_ORDER_AVRO))
    grown["fields"].append({"name": "total", "type": "double"})
    _xregistry(registry, order_epoch=2, order_doc=grown)
    again = _ParsingImporter()
    _sync(store, _XR, {"protocol": "xregistry"}, again, connector=connector)
    assert [c["remote_id"] for c in again.calls] == ["schemagroups/orders/schemas/order"]


def test_the_groups_scope_limits_the_crawl(store, registry) -> None:
    _xregistry(registry)
    importer = _ParsingImporter()
    _sync(store, _XR, {"protocol": "xregistry", "groups": ["orders"]}, importer)
    assert [c["remote_id"] for c in importer.calls] == ["schemagroups/orders/schemas/order"]


def _xregistry_messages(registry: FakeRegistry, *, created_description: str = "An order was placed.") -> None:
    """A message registry (one group, messages listed separately) and an endpoint registry."""
    registry.routes[f"{_XR}/messagegroups"] = {
        "orders": {"messagegroupid": "orders", "envelope": "CloudEvents/1.0", "epoch": 3,
                   "self": f"{_XR}/messagegroups/orders"},
        "audit": {"messagegroupid": "audit", "messages": {
            "audit.logged": {"messageid": "audit.logged", "envelopemetadata": {"type": {"value": "com.example.audit"}}},
        }},
    }
    registry.routes[f"{_XR}/messagegroups/orders/messages"] = {
        "orders.created": {
            "messageid": "orders.created",
            "description": created_description,
            "epoch": 1,
            "envelopemetadata": {"type": {"value": "com.example.orders.created"}, "source": {"value": "/orders"}},
            "dataschemaxid": "/schemagroups/payments/schemas/payment",
        },
    }
    registry.routes[f"{_XR}/endpoints"] = {
        "orders.mqtt": {
            "endpointid": "orders.mqtt",
            "usage": ["producer"],
            "protocol": "MQTT/5.0",
            "protocoloptions": {"endpoints": [{"uri": "mqtts://broker.example.com"}]},
            "messagegroups": ["/messagegroups/orders"],
            "epoch": 2,
        },
    }
    registry.routes[f"{_XR}/endpoints/orders.mqtt/messages"] = {
        "orders.ping": {"messageid": "orders.ping", "envelopemetadata": {"type": {"value": "com.example.ping"}}},
    }


def test_an_xregistry_imports_each_message_group_and_endpoint_as_an_xregistry_item(store, registry) -> None:
    _xregistry(registry)
    _xregistry_messages(registry)
    importer = _ParsingImporter()
    _, result = _sync(store, _XR, {"protocol": "xregistry"}, importer)
    assert result.status == "succeeded"
    by_id = {c["remote_id"]: c for c in importer.calls}
    assert {"messagegroups/orders", "messagegroups/audit", "endpoints/orders.mqtt"} <= set(by_id)
    for remote_id in ("messagegroups/orders", "messagegroups/audit", "endpoints/orders.mqtt"):
        assert by_id[remote_id]["kind"] == "xregistry" and by_id[remote_id]["format"] == "xregistry"
        assert by_id[remote_id]["revision"] is None  # compared by content digest
    # The audit group carried its messages inline, so they were not fetched.
    assert f"{_XR}/messagegroups/audit/messages" not in registry.requests
    assert by_id["endpoints/orders.mqtt"]["provenance"]["registryProtocol"] == "xregistry"


def test_an_endpoint_item_resolves_its_referenced_groups_on_its_own(store, registry) -> None:
    _xregistry(registry)
    _xregistry_messages(registry)
    captured: Dict[str, bytes] = {}

    class _Capture(_ParsingImporter):
        def __call__(self, connector, candidate, document, item_row, actor_id):
            captured[candidate.remote_id] = document.content
            return super().__call__(connector, candidate, document, item_row, actor_id)

    _sync(store, _XR, {"protocol": "xregistry"}, _Capture())
    adapter = get_import_source("xregistry")
    endpoint = json.loads(captured["endpoints/orders.mqtt"])
    assert set(endpoint["messagegroups"]) == {"orders"}
    assert "epoch" not in endpoint["endpoints"]["orders.mqtt"]  # bookkeeping is dropped
    model = adapter.normalize(adapter.parse(captured["endpoints/orders.mqtt"].decode()))
    assert {op.key for op in model.operations()} == {"orders.mqtt.orders.orders.created", "orders.mqtt.orders.ping"}
    group = json.loads(captured["messagegroups/orders"])
    assert "self" not in group["messagegroups"]["orders"]
    assert "epoch" not in group["messagegroups"]["orders"]["messages"]["orders.created"]


def test_an_xregistry_recrawl_reimports_only_the_message_group_that_changed(store, registry) -> None:
    _xregistry(registry)
    _xregistry_messages(registry)
    connector, _ = _sync(store, _XR, {"protocol": "xregistry", "include": ["messages"]}, _ParsingImporter())
    _xregistry_messages(registry, created_description="An order was placed online.")
    again = _ParsingImporter()
    _sync(store, _XR, {"protocol": "xregistry", "include": ["messages"]}, again, connector=connector)
    assert [c["remote_id"] for c in again.calls] == ["messagegroups/orders"]


def test_include_and_groups_narrow_the_xregistry_crawl(store, registry) -> None:
    _xregistry(registry)
    _xregistry_messages(registry)
    importer = _ParsingImporter()
    _sync(store, _XR, {"protocol": "xregistry", "include": ["messages"], "groups": ["orders"]}, importer)
    assert [c["remote_id"] for c in importer.calls] == ["messagegroups/orders"]
    assert f"{_XR}/schemagroups" not in registry.requests and f"{_XR}/endpoints" not in registry.requests


def test_a_message_only_xregistry_crawls_without_a_schema_registry(store, registry) -> None:
    _xregistry_messages(registry)  # /schemagroups answers 404
    importer = _ParsingImporter()
    _, result = _sync(store, _XR, {"protocol": "xregistry"}, importer)
    assert result.status == "succeeded"
    assert {c["remote_id"] for c in importer.calls} == {
        "messagegroups/orders", "messagegroups/audit", "endpoints/orders.mqtt",
    }


def test_an_empty_message_group_is_reported_not_imported(store, registry) -> None:
    _xregistry_messages(registry)
    registry.routes[f"{_XR}/messagegroups"]["empty"] = {"messagegroupid": "empty"}
    registry.routes[f"{_XR}/messagegroups/empty/messages"] = {}
    importer = _ParsingImporter()
    _, result = _sync(store, _XR, {"protocol": "xregistry", "include": ["messages"]}, importer)
    assert result.status == "succeeded"
    assert "messagegroups/empty" not in {c["remote_id"] for c in importer.calls}
    assert {"remoteId": "messagegroups/empty", "reason": "no-messages"} in result.summary["findings"]


def test_a_root_that_serves_no_xregistry_collection_fails_the_sync(store, registry) -> None:
    _, result = _sync(store, _XR, {"protocol": "xregistry"}, _ParsingImporter())
    assert result.status == "failed" and "does not look like an xRegistry" in result.error_message


def test_a_failing_xregistry_collection_is_not_mistaken_for_an_absent_one(store, registry) -> None:
    _xregistry(registry)
    registry.routes[f"{_XR}/messagegroups"] = (503, "down")
    _, result = _sync(store, _XR, {"protocol": "xregistry"}, _ParsingImporter())
    assert result.status == "failed" and "503" in result.error_message


# ---------------------------------------------------------------------------
# FHIR /metadata
# ---------------------------------------------------------------------------

_FHIR = "https://fhir.example/r4"
_PROFILE = "https://fhir.example/StructureDefinition/acme-patient"


def _capability(date: str = "2026-10-01") -> Dict[str, Any]:
    return {
        "resourceType": "CapabilityStatement",
        "status": "active",
        "date": date,
        "kind": "instance",
        "fhirVersion": "4.0.1",
        "format": ["json"],
        "software": {"name": "Acme FHIR", "version": "7.0"},
        "rest": [
            {
                "mode": "server",
                "resource": [
                    {"type": "Patient", "profile": _PROFILE, "interaction": [{"code": "read"}]},
                    {"type": "Observation", "supportedProfile": [_PROFILE]},
                ],
            }
        ],
    }


_STRUCTURE = {
    "resourceType": "StructureDefinition",
    "url": _PROFILE,
    "name": "AcmePatient",
    "status": "active",
    "kind": "resource",
    "abstract": False,
    "type": "Patient",
    "snapshot": {"element": [{"path": "Patient", "min": 0, "max": "*"},
                             {"path": "Patient.id", "min": 0, "max": "1", "type": [{"code": "string"}]}]},
}


def _fhir(registry: FakeRegistry, *, date: str = "2026-10-01") -> None:
    registry.routes[f"{_FHIR}/metadata"] = _capability(date)
    from urllib.parse import quote

    registry.routes[f"{_FHIR}/StructureDefinition?url={quote(_PROFILE, safe='')}"] = {
        "resourceType": "Bundle",
        "entry": [{"resource": _STRUCTURE}],
    }


def test_fhir_metadata_imports_the_capability_statement(store, registry) -> None:
    _fhir(registry)
    importer = _ParsingImporter()
    _, result = _sync(store, _FHIR, {"protocol": "fhir-metadata"}, importer)
    assert result.status == "succeeded"
    assert [(c["remote_id"], c["kind"], c["revision"]) for c in importer.calls] == [
        ("CapabilityStatement", "fhir", "7.0+2026-10-01")
    ]


def test_fhir_metadata_with_profiles_imports_each_declared_profile_once(store, registry) -> None:
    _fhir(registry)
    importer = _ParsingImporter()
    _sync(store, _FHIR, {"protocol": "fhir-metadata", "includeProfiles": True}, importer)
    assert sorted(c["remote_id"] for c in importer.calls) == ["CapabilityStatement", _PROFILE]


def test_a_fhir_recrawl_skips_unchanged_profiles_by_content(store, registry) -> None:
    _fhir(registry)
    scope = {"protocol": "fhir-metadata", "includeProfiles": True}
    connector, _ = _sync(store, _FHIR, scope, _ParsingImporter())
    _fhir(registry, date="2026-11-01")
    again = _ParsingImporter()
    _, result = _sync(store, _FHIR, scope, again, connector=connector)
    # The statement's date moved; the profile carries no revision and its content is unchanged.
    assert [c["remote_id"] for c in again.calls] == ["CapabilityStatement"]
    assert result.summary["unchanged"] == 1


def test_a_server_whose_metadata_is_not_a_capability_statement_fails(store, registry) -> None:
    registry.routes[f"{_FHIR}/metadata"] = {"resourceType": "OperationOutcome"}
    _, result = _sync(store, _FHIR, {"protocol": "fhir-metadata"}, _ParsingImporter())
    assert result.status == "failed" and "CapabilityStatement" in result.error_message


# ---------------------------------------------------------------------------
# The source wrapper
# ---------------------------------------------------------------------------


def test_the_source_closes_its_client_and_describes_the_crawl(registry) -> None:
    _a2a_registry(registry)
    source = RegistryConnectorSource(
        {"id": "c1", "kind": "registry", "base_url": _A2A + "/", "scope": {"protocol": "a2a-registry"}},
        transport=registry.transport(),
        limiter=_NoWait(),
    )
    candidates = source.list_candidates()
    assert len(candidates) == 3 and all(c.raw["protocol"] == "a2a-registry" for c in candidates)
    described = source.describe()
    assert described["registryUrl"] == _A2A and described["importSource"] == "a2a"
    assert described["requests"] == 2
    source.close()
    assert source.describe()["requests"] == 0


def test_bearer_and_api_key_credentials_are_sent(registry) -> None:
    seen: List[httpx.Headers] = []
    base: Callable = registry.transport().handle_request

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return base(request)

    _a2a_registry(registry)
    source = RegistryConnectorSource(
        {"id": "c1", "kind": "registry", "base_url": _A2A, "scope": {"protocol": "a2a-registry"}},
        {"token": "t0k", "apiKey": "k3y"},
        transport=httpx.MockTransport(handler),
        limiter=_NoWait(),
    )
    source.list_candidates()
    assert seen[0]["authorization"] == "Bearer t0k" and seen[0]["x-api-key"] == "k3y"

