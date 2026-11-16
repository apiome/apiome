"""The Kafka adapter: publish, consume, health, and the address rule — XPC-2.2 (#5736).

``aiokafka`` is replaced by fakes and the address checker is injected, so these run offline.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from aiokafka import errors as kafka_errors
from app.mock_broker_addresses import BootstrapAddressError

from apiome_mock.broker_adapter import BrokerAdapter, BrokerConnection, BrokerCredential, BrokerError, PublishRecord
from apiome_mock.kafka_adapter import KafkaAdapter

_PASSWORD = "PRODUCER-secret-55"


class FakeProducer:
    """Records what the adapter does; ``advertised`` is what the cluster metadata lists."""

    def __init__(self, *, advertised=(("broker.example.com", 9092),), start_error=None, send_error=None, **kwargs):
        self.kwargs = kwargs
        self.sent: list[dict[str, Any]] = []
        self.started = self.stopped = False
        self.start_error = start_error
        self.send_error = send_error
        brokers = [SimpleNamespace(host=h, port=p) for h, p in advertised]
        self.client = SimpleNamespace(cluster=SimpleNamespace(brokers=lambda: brokers))

    async def start(self):
        if self.start_error:
            raise self.start_error
        self.started = True

    async def stop(self):
        self.stopped = True

    async def send_and_wait(self, topic, value=None, key=None, headers=None):
        if self.send_error:
            raise self.send_error
        self.sent.append({"topic": topic, "value": value, "key": key, "headers": headers})
        return SimpleNamespace(topic=topic, partition=2, offset=len(self.sent) - 1)


def _connection(**overrides):
    data = dict(
        binding_id="b-1",
        protocol="kafka",
        bootstrap=("broker.example.com:9092",),
        sasl_mechanism="SCRAM-SHA-512",
        credential=BrokerCredential("svc", _PASSWORD),
        tls_enabled=True,
        client_id="acme-producer",
    )
    data.update(overrides)
    return BrokerConnection(**data)


class Checker:
    """An address checker: refuses entries whose host is in ``refused``."""

    def __init__(self, *refused: str):
        self.refused = set(refused)
        self.calls: list[list[str]] = []

    def __call__(self, entries):
        self.calls.append([entry.render() for entry in entries])
        if any(entry.host in self.refused for entry in entries):
            raise BootstrapAddressError("refused", disallowed=True)


def _adapter(checker=None, **producer_kwargs):
    made: list[FakeProducer] = []

    def factory(**kwargs):
        producer = FakeProducer(**producer_kwargs, **kwargs)
        made.append(producer)
        return producer

    return KafkaAdapter(_connection(), producer_factory=factory, address_checker=checker or Checker()), made


def test_it_satisfies_the_broker_adapter_protocol():
    adapter, _ = _adapter()
    assert isinstance(adapter, BrokerAdapter)


def test_publish_sends_the_record_and_returns_the_receipt():
    adapter, made = _adapter()
    record = PublishRecord(topic="user.signedup", value=b"{}", key=b"k", headers=(("h", b"v"),))
    receipt = asyncio.run(adapter.publish(record))
    assert (receipt.topic, receipt.partition, receipt.offset) == ("user.signedup", 2, 0)
    (producer,) = made
    assert producer.sent == [{"topic": "user.signedup", "value": b"{}", "key": b"k", "headers": [("h", b"v")]}]


def test_the_producer_is_configured_from_the_binding():
    adapter, made = _adapter()
    asyncio.run(adapter.publish(PublishRecord(topic="t", value=b"x")))
    kwargs = made[0].kwargs
    assert kwargs["bootstrap_servers"] == ["broker.example.com:9092"]
    assert kwargs["security_protocol"] == "SASL_SSL"
    assert kwargs["sasl_mechanism"] == "SCRAM-SHA-512"
    assert kwargs["sasl_plain_password"] == _PASSWORD
    assert kwargs["client_id"] == "acme-producer"
    assert kwargs["ssl_context"] is not None
    assert _PASSWORD not in repr(adapter.connection)


def test_the_producer_starts_once_and_is_reused():
    adapter, made = _adapter()
    for _ in range(3):
        asyncio.run(adapter.publish(PublishRecord(topic="t", value=b"x")))
    assert len(made) == 1 and len(made[0].sent) == 3


def test_a_disallowed_bootstrap_host_is_refused_before_connecting():
    adapter, made = _adapter(Checker("broker.example.com"))
    with pytest.raises(BrokerError) as caught:
        asyncio.run(adapter.publish(PublishRecord(topic="t", value=b"x")))
    assert caught.value.reason == "address-disallowed"
    assert made == []


def test_a_cluster_advertising_a_private_broker_is_refused_and_nothing_is_sent():
    checker = Checker("10.0.0.7")
    adapter, made = _adapter(checker, advertised=(("broker.example.com", 9092), ("10.0.0.7", 9092)))
    with pytest.raises(BrokerError) as caught:
        asyncio.run(adapter.publish(PublishRecord(topic="t", value=b"x")))
    assert caught.value.reason == "address-disallowed"
    assert made[0].sent == [] and made[0].stopped
    assert ["10.0.0.7:9092", "broker.example.com:9092"] in checker.calls


def test_a_wrong_password_is_auth_and_rebuilds_the_session():
    adapter, made = _adapter(start_error=kafka_errors.SaslAuthenticationFailed(f"bad {_PASSWORD}"))
    with pytest.raises(BrokerError) as caught:
        asyncio.run(adapter.publish(PublishRecord(topic="t", value=b"x")))
    assert caught.value.reason == "auth"
    assert _PASSWORD not in str(caught.value)
    assert asyncio.run(adapter.healthcheck()) == "unreachable: auth"


def test_a_send_failure_is_categorised():
    adapter, _ = _adapter(send_error=kafka_errors.KafkaTimeoutError())
    with pytest.raises(BrokerError) as caught:
        asyncio.run(adapter.publish(PublishRecord(topic="t", value=b"x")))
    assert caught.value.reason == "timeout"


def test_healthcheck_reports_reachable():
    adapter, _ = _adapter()
    assert asyncio.run(adapter.healthcheck()) == "reachable"


def test_close_stops_the_producer_and_a_new_one_starts_after():
    adapter, made = _adapter()
    asyncio.run(adapter.publish(PublishRecord(topic="t", value=b"x")))
    asyncio.run(adapter.close())
    assert made[0].stopped
    asyncio.run(adapter.publish(PublishRecord(topic="t", value=b"x")))
    assert len(made) == 2


def test_consume_reads_bounded_records_without_a_group():
    seen: dict[str, Any] = {}

    class FakeConsumer:
        def __init__(self, *topics, **kwargs):
            seen["topics"], seen["kwargs"] = topics, kwargs

        async def start(self):
            pass

        async def stop(self):
            seen["stopped"] = True

        async def getmany(self, timeout_ms, max_records):
            seen["max_records"] = max_records
            message = SimpleNamespace(topic="t", partition=0, offset=5, value=b"v", key=None, headers=[("h", b"1")])
            return {"tp": [message]}

    adapter = KafkaAdapter(_connection(), consumer_factory=FakeConsumer, address_checker=Checker())
    records = asyncio.run(adapter.consume(("t",), max_messages=5, timeout_seconds=1))
    assert [(r.topic, r.offset, r.value) for r in records] == [("t", 5, b"v")]
    assert seen["kwargs"]["group_id"] is None and seen["kwargs"]["enable_auto_commit"] is False
    assert seen["max_records"] == 5 and seen["stopped"]
