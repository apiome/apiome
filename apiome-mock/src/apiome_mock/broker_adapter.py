"""The broker adapter contract — XPC-2.2 (#5736).

The hosted mock reaches a message broker through one small interface, so Kafka today and MQTT /
AMQP later (XPC-2.5) plug in the same way. An adapter owns one connection to one bound broker
(one ``mock_broker_bindings`` row) and offers three operations:

* :meth:`BrokerAdapter.publish` — send one record and say where it landed;
* :meth:`BrokerAdapter.consume` — read a bounded number of records (XPC-2.3's conformance runs);
* :meth:`BrokerAdapter.healthcheck` — ``reachable`` or ``unreachable: <reason>``.

Records are bytes on the wire: encoding (JSON, Avro, Protobuf) happens before an adapter sees a
record (:mod:`apiome_mock.event_payloads`), so adapters stay protocol plumbing only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = [
    "BrokerAdapter",
    "BrokerConnection",
    "BrokerCredential",
    "BrokerError",
    "ConsumedRecord",
    "PublishReceipt",
    "PublishRecord",
]


class BrokerError(RuntimeError):
    """A broker operation failed.

    Attributes:
        reason: A category, never broker-supplied text (which can quote the username):
            ``auth``, ``address-disallowed``, ``tls``, ``timeout``, ``connect`` or ``protocol``.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"broker unreachable: {reason}")


@dataclass(frozen=True)
class BrokerCredential:
    """An opened SASL credential, in memory for one connection. ``repr`` hides both values."""

    username: str = field(repr=False)
    password: str = field(repr=False)


@dataclass(frozen=True)
class BrokerConnection:
    """Everything an adapter needs to connect to one bound broker.

    Attributes:
        binding_id: The ``mock_broker_bindings`` row this came from.
        protocol: ``kafka``.
        bootstrap: Normalized ``host:port`` entries.
        tls_enabled: Connect over TLS.
        tls_verify: Verify the broker certificate and hostname.
        sasl_mechanism: ``PLAIN`` / ``SCRAM-SHA-256`` / ``SCRAM-SHA-512``, or ``None``.
        credential: The opened credential, or ``None`` without SASL.
        client_id: The ``client.id`` Apiome's producer presents.
    """

    binding_id: str
    protocol: str
    bootstrap: tuple[str, ...]
    tls_enabled: bool = False
    tls_verify: bool = True
    sasl_mechanism: str | None = None
    credential: BrokerCredential | None = field(default=None, repr=False)
    client_id: str = "apiome-mock"


@dataclass(frozen=True)
class PublishRecord:
    """One record to send.

    Attributes:
        topic: The resolved topic.
        value: The encoded payload.
        key: The encoded partition key, or ``None`` (the broker picks the partition).
        headers: Record headers, in order.
    """

    topic: str
    value: bytes
    key: bytes | None = None
    headers: tuple[tuple[str, bytes], ...] = ()


@dataclass(frozen=True)
class PublishReceipt:
    """Where a published record landed."""

    topic: str
    partition: int
    offset: int


@dataclass(frozen=True)
class ConsumedRecord:
    """One record read back from a topic."""

    topic: str
    partition: int
    offset: int
    value: bytes | None
    key: bytes | None
    headers: tuple[tuple[str, bytes], ...]


@runtime_checkable
class BrokerAdapter(Protocol):
    """One connection to one bound broker."""

    async def publish(self, record: PublishRecord) -> PublishReceipt:
        """Send ``record``; raise :class:`BrokerError` when it cannot be delivered."""
        ...

    async def consume(
        self, topics: tuple[str, ...], *, max_messages: int, timeout_seconds: float
    ) -> list[ConsumedRecord]:
        """Read up to ``max_messages`` records from ``topics`` within ``timeout_seconds``."""
        ...

    async def healthcheck(self) -> str:
        """Return ``reachable`` or ``unreachable: <reason>``."""
        ...

    async def close(self) -> None:
        """Release the connection. Safe to call more than once."""
        ...
