"""The Kafka broker adapter (``aiokafka``) — XPC-2.2 (#5736).

One :class:`KafkaAdapter` per bound broker: a lazily started ``AIOKafkaProducer`` (and, for
:meth:`KafkaAdapter.consume`, a short-lived consumer) configured from a
:class:`~apiome_mock.broker_adapter.BrokerConnection`.

**The address rule holds at connect time and after.** The binding's bootstrap hosts were checked
when it was stored (XPC-2.1); they are checked again here before the producer starts, using the same
rule (:func:`app.mock_broker_addresses.check_bootstrap`: public addresses only, the dev broker's
exact ``host:port`` exempt, ``APIOME_MOCK_BROKER_ALLOW_PRIVATE`` the local escape hatch). A Kafka
client then connects to the brokers the *cluster metadata advertises*, which the broker controls —
so every advertised ``host:port`` is checked too, after start and whenever the advertised set
changes. A cluster that advertises a non-public address is refused (``address-disallowed``) and
nothing is sent.

**Failures are categories.** Errors are mapped to the XPC-2.1 probe's reasons
(:func:`app.mock_broker_probe.classify_error`) by exception type; broker text is never surfaced.
"""

from __future__ import annotations

import asyncio
import ssl
from typing import Any, Callable

import structlog
from app.mock_broker_addresses import (
    BootstrapAddressError,
    BootstrapEntry,
    check_bootstrap,
    normalize_bootstrap,
)
from app.mock_broker_probe import classify_error, security_protocol

from apiome_mock.broker_adapter import (
    BrokerConnection,
    BrokerError,
    ConsumedRecord,
    PublishReceipt,
    PublishRecord,
)

__all__ = ["KafkaAdapter"]

_log = structlog.get_logger(__name__)

#: Budget for one produce (connect + metadata + ack).
_PUBLISH_TIMEOUT_SECONDS = 10.0

#: Most records one :meth:`KafkaAdapter.consume` call returns.
_CONSUME_MAX_MESSAGES = 1_000


def _ssl_context(verify: bool) -> ssl.SSLContext:
    """The TLS context: system trust store and hostname check, unless ``verify`` is off."""
    context = ssl.create_default_context()
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def _client_kwargs(connection: BrokerConnection) -> dict[str, Any]:
    """The ``aiokafka`` keyword arguments shared by the producer and the consumer."""
    credential = connection.credential
    kwargs: dict[str, Any] = {
        "bootstrap_servers": list(connection.bootstrap),
        "client_id": connection.client_id,
        "security_protocol": security_protocol(connection.tls_enabled, connection.sasl_mechanism),
        "request_timeout_ms": int(_PUBLISH_TIMEOUT_SECONDS * 1000),
    }
    if connection.tls_enabled:
        kwargs["ssl_context"] = _ssl_context(connection.tls_verify)
    if connection.sasl_mechanism:
        kwargs["sasl_mechanism"] = connection.sasl_mechanism
        kwargs["sasl_plain_username"] = credential.username if credential else None
        kwargs["sasl_plain_password"] = credential.password if credential else None
    return kwargs


class KafkaAdapter:
    """A :class:`~apiome_mock.broker_adapter.BrokerAdapter` for Kafka.

    Args:
        connection: The bound broker.
        producer_factory: Builds the producer from keyword arguments (tests inject a fake).
        consumer_factory: Builds a consumer from ``(*topics, **kwargs)`` (tests inject a fake).
        address_checker: Checks normalized entries against the address rule (tests inject one
            that resolves without DNS). Raises ``BootstrapAddressError`` on refusal.
    """

    def __init__(
        self,
        connection: BrokerConnection,
        *,
        producer_factory: Callable[..., Any] | None = None,
        consumer_factory: Callable[..., Any] | None = None,
        address_checker: Callable[[list[BootstrapEntry]], Any] | None = None,
    ) -> None:
        self.connection = connection
        self._producer_factory = producer_factory
        self._consumer_factory = consumer_factory
        self._check = address_checker or check_bootstrap
        self._producer: Any = None
        self._checked_brokers: frozenset[tuple[str, int]] = frozenset()
        self._lock = asyncio.Lock()

    # -- address rule --------------------------------------------------------------------

    async def _check_entries(self, raw: list[str]) -> None:
        """Run the address rule over ``host:port`` strings (off the event loop: it resolves DNS)."""
        try:
            entries = normalize_bootstrap(raw)
            await asyncio.to_thread(self._check, entries)
        except BootstrapAddressError as exc:
            raise BrokerError("address-disallowed") from exc

    async def _check_advertised(self) -> None:
        """Check every broker the cluster metadata advertises, once per distinct set."""
        cluster = getattr(getattr(self._producer, "client", None), "cluster", None)
        brokers = cluster.brokers() if cluster is not None else ()
        advertised = frozenset((str(broker.host), int(broker.port)) for broker in brokers)
        if not advertised or advertised == self._checked_brokers:
            return
        raw = [f"[{host}]:{port}" if ":" in host else f"{host}:{port}" for host, port in sorted(advertised)]
        await self._check_entries(raw)
        self._checked_brokers = advertised

    # -- producer ------------------------------------------------------------------------

    def _new_producer(self) -> Any:
        """Build the producer (``aiokafka.AIOKafkaProducer`` unless a factory was injected)."""
        kwargs = {**_client_kwargs(self.connection), "acks": 1, "enable_idempotence": False}
        if self._producer_factory is not None:
            return self._producer_factory(**kwargs)
        from aiokafka import AIOKafkaProducer

        return AIOKafkaProducer(**kwargs)

    async def _ensure_producer(self) -> Any:
        """Start the producer once, after the bootstrap hosts pass the address rule."""
        if self._producer is not None:
            return self._producer
        await self._check_entries(list(self.connection.bootstrap))
        producer = self._new_producer()
        try:
            await asyncio.wait_for(producer.start(), _PUBLISH_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001 - categorised, never echoed
            await self._stop(producer)
            raise BrokerError(classify_error(exc)) from exc
        self._producer = producer
        try:
            await self._check_advertised()
        except BrokerError:
            await self.close()
            raise
        return producer

    @staticmethod
    async def _stop(producer: Any) -> None:
        """Stop a producer, ignoring errors (it may never have connected)."""
        try:
            await producer.stop()
        except Exception:  # noqa: BLE001 - best-effort shutdown
            pass

    async def publish(self, record: PublishRecord) -> PublishReceipt:
        """Send one record and wait for the leader's acknowledgement.

        Raises:
            BrokerError: The broker is unreachable, refused the credential, advertises a
                disallowed address, or did not acknowledge in time.
        """
        async with self._lock:
            producer = await self._ensure_producer()
            try:
                await self._check_advertised()
            except BrokerError:
                await self.close()
                raise
            try:
                metadata = await asyncio.wait_for(
                    producer.send_and_wait(
                        record.topic,
                        value=record.value,
                        key=record.key,
                        headers=list(record.headers) or None,
                    ),
                    _PUBLISH_TIMEOUT_SECONDS,
                )
            except Exception as exc:  # noqa: BLE001 - categorised, never echoed
                reason = classify_error(exc)
                _log.info("kafka_publish_failed", binding_id=self.connection.binding_id, reason=reason,
                          error_type=type(exc).__name__)
                if reason in {"auth", "connect", "tls"}:
                    # A broken session is rebuilt on the next publish.
                    await self.close()
                raise BrokerError(reason) from exc
        return PublishReceipt(topic=metadata.topic, partition=int(metadata.partition), offset=int(metadata.offset))

    async def consume(
        self, topics: tuple[str, ...], *, max_messages: int, timeout_seconds: float
    ) -> list[ConsumedRecord]:
        """Read up to ``max_messages`` records from the start of ``topics`` (no group, no commit).

        Raises:
            BrokerError: The broker is unreachable or refused the credential.
        """
        await self._check_entries(list(self.connection.bootstrap))
        limit = max(1, min(int(max_messages), _CONSUME_MAX_MESSAGES))
        kwargs = {
            **_client_kwargs(self.connection),
            "group_id": None,
            "enable_auto_commit": False,
            "auto_offset_reset": "earliest",
        }
        if self._consumer_factory is not None:
            consumer = self._consumer_factory(*topics, **kwargs)
        else:
            from aiokafka import AIOKafkaConsumer

            consumer = AIOKafkaConsumer(*topics, **kwargs)
        records: list[ConsumedRecord] = []
        try:
            await asyncio.wait_for(consumer.start(), _PUBLISH_TIMEOUT_SECONDS)
            batches = await consumer.getmany(timeout_ms=int(timeout_seconds * 1000), max_records=limit)
            for messages in batches.values():
                for message in messages:
                    records.append(
                        ConsumedRecord(
                            topic=message.topic,
                            partition=int(message.partition),
                            offset=int(message.offset),
                            value=message.value,
                            key=message.key,
                            headers=tuple(message.headers or ()),
                        )
                    )
        except Exception as exc:  # noqa: BLE001 - categorised, never echoed
            raise BrokerError(classify_error(exc)) from exc
        finally:
            await self._stop(consumer)
        return records[:limit]

    async def healthcheck(self) -> str:
        """Start the producer (if needed) and report ``reachable`` or ``unreachable: <reason>``."""
        try:
            async with self._lock:
                await self._ensure_producer()
        except BrokerError as exc:
            return f"unreachable: {exc.reason}"
        return "reachable"

    async def close(self) -> None:
        """Stop the producer. The next publish starts a new one."""
        producer, self._producer = self._producer, None
        self._checked_brokers = frozenset()
        if producer is not None:
            await self._stop(producer)
