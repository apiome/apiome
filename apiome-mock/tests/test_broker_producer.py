"""The broker publisher, the periodic producer and the channel routes — XPC-2.2 (#5736).

The database reads, limits and usage writes are patched, and the adapter is a fake, so these assert
the producer's contract: what is published where, what is refused and never sent, what is counted
with which encoding, that rate caps apply, and that turning the mock off stops the producer within
one interval.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from starlette.requests import Request

from apiome_mock import broker_producer as producer_module
from apiome_mock import channel_routes
from apiome_mock.broker_adapter import BrokerError, PublishReceipt
from apiome_mock.broker_bindings import BoundVersion
from apiome_mock.broker_producer import (
    STATUS_NO_BROKER,
    STATUS_PUBLISHED,
    STATUS_RATE_LIMITED,
    STATUS_REJECTED,
    STATUS_UNPUBLISHABLE,
    STATUS_UNREACHABLE,
    TRIGGER_ON_DEMAND,
    TRIGGER_PERIODIC,
    BrokerPublisher,
    PeriodicBrokerProducer,
)
from apiome_mock.canonical_spec_cache import CanonicalSpecCache
from kafka_fixtures import compiled_kafka_spec, route

_TENANT_ID = uuid4()
_BINDING_ROW = {"id": "b-1", "protocol": "kafka", "bootstrap": ["broker.example.com:9092"], "tls_enabled": False,
                "tls_verify": True, "sasl_mechanism": None, "credential_ciphertext": None, "key_version": None,
                "client_id_prefix": "acme", "rotated_at": None}


class FakeAdapter:
    """Records published records; raises ``error`` when set."""

    instances: list["FakeAdapter"] = []

    def __init__(self, connection):
        self.connection = connection
        self.records = []
        self.error: BrokerError | None = None
        self.closed = False
        FakeAdapter.instances.append(self)

    async def publish(self, record):
        if self.error:
            raise self.error
        self.records.append(record)
        return PublishReceipt(topic=record.topic, partition=0, offset=len(self.records) - 1)

    async def consume(self, topics, *, max_messages, timeout_seconds):
        return []

    async def healthcheck(self):
        return "reachable"

    async def close(self):
        self.closed = True


@pytest.fixture
def env(monkeypatch, mock_pool):
    """Patch the producer's database, limits and usage seams; return the captured state."""
    monkeypatch.setenv("APIOME_MOCK_DATABASE_URL", "postgresql://localhost/db")
    from apiome_mock.settings import Settings

    FakeAdapter.instances = []
    state: dict[str, Any] = {"binding": dict(_BINDING_ROW), "blocked": False, "counts": [], "events": [],
                             "enabled": True}

    async def load_binding(pool, version_id):
        return state["binding"]

    async def limits(pool, tenant, settings=None):
        return SimpleNamespace(tenant_id=_TENANT_ID, mock_rps=10, mock_requests_per_month=0)

    async def enforce(**kwargs):
        state.setdefault("limit_calls", []).append(kwargs["client_host"])
        return MagicMock() if state["blocked"] else None

    async def enabled(pool, version_id):
        return state["enabled"]

    monkeypatch.setattr(producer_module, "load_kafka_binding", load_binding)
    monkeypatch.setattr(channel_routes, "load_kafka_binding", load_binding)
    monkeypatch.setattr(producer_module, "resolve_limits_for_tenant", limits)
    monkeypatch.setattr(producer_module, "enforce_mock_limits_for_context", enforce)
    monkeypatch.setattr(producer_module, "record_mock_transport_event", lambda **kw: state["events"].append(kw))
    monkeypatch.setattr(producer_module, "version_mock_enabled", enabled)
    monkeypatch.setattr(BrokerPublisher, "_count",
                        lambda self, compiled, tenant_id, channel, encoding, trigger, published:
                        state["counts"].append((channel, encoding, trigger, published)))
    publisher = BrokerPublisher(pool=mock_pool, settings=Settings(), adapter_factory=FakeAdapter)
    state["publisher"] = publisher
    return state


def _publish(env, prefix, **kwargs):
    compiled = compiled_kafka_spec()
    channel = route(compiled, prefix)
    kwargs.setdefault("trigger", TRIGGER_ON_DEMAND)
    return asyncio.run(env["publisher"].publish_channel(compiled, channel, **kwargs))


# ============================================================================
# publish_channel
# ============================================================================
def test_an_on_demand_publish_sends_a_schema_valid_record_to_the_topic(env):
    (outcome,) = _publish(env, "user/signedup")
    assert outcome.status == STATUS_PUBLISHED
    assert (outcome.topic, outcome.encoding, outcome.source) == ("user.signedup", "json", "example")
    (record,) = FakeAdapter.instances[0].records
    assert record.topic == "user.signedup" and record.key == b"user-42"
    assert json.loads(record.value) == {"userId": "u-1", "email": "ada@example.com"}
    assert env["counts"] == [("user/signedup", "json", "on-demand", True)]
    assert env["events"][0]["transport"] == "kafka"
    assert env["limit_calls"] == ["broker"]


def test_an_avro_publish_is_counted_as_avro(env):
    (outcome,) = _publish(env, "user/{region}", trigger=TRIGGER_PERIODIC)
    assert (outcome.status, outcome.topic, outcome.encoding) == (STATUS_PUBLISHED, "user.eu.updated", "avro")
    assert env["counts"] == [("user/{region}/updated", "avro", "periodic", True)]


def test_an_invalid_payload_is_never_sent_and_is_counted_as_rejected(env):
    (outcome,) = _publish(env, "user/signedup", payload={"userId": "only"})
    assert (outcome.status, outcome.reason) == (STATUS_REJECTED, "invalid-payload")
    assert FakeAdapter.instances[0].records == []
    assert env["counts"] == [("user/signedup", "json", "on-demand", False)]
    assert env["events"] == []


def test_an_unresolved_parameter_channel_publishes_nothing(env):
    (outcome,) = _publish(env, "orders/")
    assert (outcome.status, outcome.reason) == (STATUS_UNPUBLISHABLE, "unresolved-address-parameter")
    assert FakeAdapter.instances == []


def test_an_unbound_version_reports_no_broker(env):
    env["binding"] = None
    (outcome,) = _publish(env, "user/signedup")
    assert outcome.status == STATUS_NO_BROKER


def test_a_rate_capped_tenant_is_not_published(env):
    env["blocked"] = True
    (outcome,) = _publish(env, "user/signedup")
    assert outcome.status == STATUS_RATE_LIMITED
    assert FakeAdapter.instances[0].records == []


def test_an_unreachable_broker_reports_its_category(env):
    compiled = compiled_kafka_spec()
    channel = route(compiled, "user/signedup")
    asyncio.run(env["publisher"].adapter_for(compiled.loaded.revision_id))
    FakeAdapter.instances[0].error = BrokerError("auth")
    (outcome,) = asyncio.run(env["publisher"].publish_channel(compiled, channel, trigger=TRIGGER_ON_DEMAND))
    assert (outcome.status, outcome.reason) == (STATUS_UNREACHABLE, "auth")


def test_an_unopenable_credential_fails_closed(env):
    env["binding"] = {**_BINDING_ROW, "sasl_mechanism": "PLAIN", "credential_ciphertext": b"junk", "key_version": 1}
    (outcome,) = _publish(env, "user/signedup")
    assert (outcome.status, outcome.reason) == (STATUS_UNREACHABLE, "credential-unavailable")


def test_a_changed_binding_rebuilds_the_adapter(env):
    compiled = compiled_kafka_spec()
    publisher = env["publisher"]
    first = asyncio.run(publisher.adapter_for(compiled.loaded.revision_id))
    assert asyncio.run(publisher.adapter_for(compiled.loaded.revision_id)) is first
    env["binding"] = {**_BINDING_ROW, "rotated_at": "2026-11-15"}
    second = asyncio.run(publisher.adapter_for(compiled.loaded.revision_id))
    assert second is not first and first.closed


# ============================================================================
# The periodic producer
# ============================================================================
def test_the_periodic_producer_publishes_every_interval_and_stops_when_the_mock_is_disabled(env):
    compiled = compiled_kafka_spec()
    for channel in compiled.event_channels:
        object.__setattr__(channel, "periodic_interval_seconds", 0.05)

    async def load_spec(tenant, project, version):
        return compiled

    producer = PeriodicBrokerProducer(publisher=env["publisher"], load_spec=load_spec)
    bound = BoundVersion(version_id=compiled.loaded.revision_id, tenant_slug="demo", project_slug="events",
                         version_label="1.0.0", binding_id="b-1", rotated_at=None, key_version=None)

    async def scenario():
        task = asyncio.create_task(producer._version_loop(bound))
        await asyncio.sleep(0.12)
        sent_while_on = len(FakeAdapter.instances[0].records)
        env["enabled"] = False
        await asyncio.wait_for(task, timeout=0.5)  # returns within one interval of the switch
        return sent_while_on

    sent_while_on = asyncio.run(scenario())
    # Two publishable channels per round, at least two rounds in 120 ms at a 50 ms interval.
    assert sent_while_on >= 4
    topics = {record.topic for record in FakeAdapter.instances[0].records}
    assert topics == {"user.signedup", "user.eu.updated"}
    assert FakeAdapter.instances[0].closed


def test_refresh_starts_and_stops_version_loops(env, monkeypatch):
    rows = [BoundVersion(version_id=uuid4(), tenant_slug="demo", project_slug="events", version_label="1.0.0",
                         binding_id="b-1", rotated_at=None, key_version=None)]

    async def bound(pool):
        return list(rows)

    monkeypatch.setattr(producer_module, "list_bound_versions", bound)

    async def never_ready(tenant, project, version):
        await asyncio.sleep(10)

    producer = PeriodicBrokerProducer(publisher=env["publisher"], load_spec=never_ready)

    async def scenario():
        await producer.refresh()
        started = set(producer._tasks)
        rows.clear()
        await producer.refresh()
        stopped = set(producer._tasks)
        await producer.stop()
        return started, stopped

    started, stopped = asyncio.run(scenario())
    assert len(started) == 1 and stopped == set()


# ============================================================================
# Channel routes
# ============================================================================
def _request(path, body=b"", headers=()):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {"type": "http", "method": "POST", "path": path, "headers": list(headers), "query_string": b""}
    return Request(scope, receive)


def _cache(compiled):
    cache = CanonicalSpecCache(max_entries=8, ttl_seconds=60.0)
    cache.put(compiled)
    return cache


def test_the_channel_listing_reports_each_channels_support(env, mock_pool):
    compiled = compiled_kafka_spec()
    response = asyncio.run(channel_routes.handle_list_channels(
        tenant="demo", project="events", version="1.0.0", pool=mock_pool, cache=_cache(compiled), api_key=None))
    body = json.loads(response.body)
    assert body["brokerBound"] is True
    support = {c["address"]: (c["kafka"]["support"], c["kafka"]["topic"]) for c in body["channels"]}
    assert support["user/signedup"] == ("supported", "user.signedup")
    assert support["orders/{orderId}/placed"] == ("unsupported: unresolved-address-parameter", None)
    assert support["audit log!"] == ("unsupported: invalid-topic", None)
    avro = next(c for c in body["channels"] if c["address"].startswith("user/{region}"))
    assert avro["messages"][0]["encoding"] == "avro"


@pytest.mark.parametrize(
    ("channel", "body", "status"),
    [
        ("user/signedup", b"", 200),
        ("user/signedup", json.dumps({"userId": "r", "email": "r@example.com"}).encode(), 200),
        ("user/signedup", b'{"userId": 1}', 422),
        ("user/signedup", b"not json", 422),
        ("orders/{orderId}/placed", b"", 422),
        ("no/such/channel", b"", 404),
    ],
)
def test_on_demand_publish_maps_outcomes_to_status_codes(env, mock_pool, channel, body, status):
    compiled = compiled_kafka_spec()
    response = asyncio.run(channel_routes.handle_channel_publish(
        _request(f"/demo/events/1.0.0/__channels__/{channel}/publish", body),
        tenant="demo", project="events", version="1.0.0", channel_key=channel, pool=mock_pool,
        cache=_cache(compiled), publisher=env["publisher"], api_key=None))
    assert response.status_code == status, response.body


def test_on_demand_publish_without_a_broker_is_409(env, mock_pool):
    env["binding"] = None
    compiled = compiled_kafka_spec()
    response = asyncio.run(channel_routes.handle_channel_publish(
        _request("/demo/events/1.0.0/__channels__/user/signedup/publish"),
        tenant="demo", project="events", version="1.0.0", channel_key="user/signedup", pool=mock_pool,
        cache=_cache(compiled), publisher=env["publisher"], api_key=None))
    assert response.status_code == 409
    assert json.loads(response.body)["status"] == "no-broker-bound"


def test_the_scenario_header_shapes_an_on_demand_publish(env, mock_pool):
    settings = {"scenarios": {"vip": {"operations": {"PUBLISH /user/signedup": {"responses": [
        {"status": 200, "body": {"userId": "vip", "email": "vip@example.com"}}]}}}}}
    compiled = compiled_kafka_spec(mock_settings=settings)
    response = asyncio.run(channel_routes.handle_channel_publish(
        _request("/demo/events/1.0.0/__channels__/user/signedup/publish", headers=[(b"x-mock-scenario", b"vip")]),
        tenant="demo", project="events", version="1.0.0", channel_key="user/signedup", pool=mock_pool,
        cache=_cache(compiled), publisher=env["publisher"], api_key=None))
    assert json.loads(response.body)["source"] == "scenario"
    assert json.loads(FakeAdapter.instances[0].records[0].value)["userId"] == "vip"
