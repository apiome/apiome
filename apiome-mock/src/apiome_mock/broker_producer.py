"""The hosted mock's broker producer — XPC-2.2 (#5736).

Two ways a mock event reaches a version's bound Kafka broker:

* **Periodic.** :class:`PeriodicBrokerProducer` runs in the server's lifespan. Every
  ``APIOME_MOCK_BROKER_REFRESH_SECONDS`` it lists the mock-enabled versions with a Kafka binding,
  starts one loop per version, and stops loops whose version lost its mock or its binding. Each
  loop publishes one record per outbound message of every publishable channel, then waits the
  channel interval (``periodic_interval_seconds``). Before every round it re-checks that the
  version's mock is still on, so turning the mock off stops the producer within one interval.
* **On demand.** ``POST /{tenant}/{project}/{version}/__channels__/{channel}/publish`` calls
  :meth:`BrokerPublisher.publish_channel` once (:mod:`apiome_mock.channel_routes`).

Both go through :meth:`BrokerPublisher.publish_channel`, which enforces, in order: the tenant's rate
caps (:mod:`apiome_mock.tenant_limits`, a ``broker`` bucket at the tenant's ``mock_rps`` and the
shared monthly quota); a publishable channel; a payload that builds and validates
(:func:`apiome_mock.event_payloads.build_event` — a refused record is never sent); then the send.
Every outcome is counted in ``mock_event_publish_usage`` (V373) with the encoding used, and a sent
record also counts as one mock request in ``mock_usage``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from uuid import UUID

import structlog
from psycopg_pool import AsyncConnectionPool

from apiome_mock.broker_adapter import BrokerAdapter, BrokerConnection, BrokerError, PublishRecord
from apiome_mock.broker_bindings import (
    BindingUnavailableError,
    BoundVersion,
    connection_from_row,
    list_bound_versions,
    load_kafka_binding,
    version_mock_enabled,
)
from apiome_mock.canonical_compiler import CompiledCanonicalSpec, EventChannelRoute
from apiome_mock.event_payloads import NO_PAYLOAD, EncodedEvent, EventRejectedError, build_event, encoding_for
from apiome_mock.fixture_packs import merged_template_data, parse_fixture_packs
from apiome_mock.guard import enforce_mock_limits_for_context, record_mock_transport_event, resolve_limits_for_tenant
from apiome_mock.kafka_adapter import KafkaAdapter
from apiome_mock.scenarios import Scenario, parse_active_scenario, parse_scenarios
from apiome_mock.settings import Settings, get_settings

__all__ = [
    "STATUS_NO_BROKER",
    "STATUS_PUBLISHED",
    "STATUS_RATE_LIMITED",
    "STATUS_REJECTED",
    "STATUS_UNPUBLISHABLE",
    "STATUS_UNREACHABLE",
    "TRIGGER_ON_DEMAND",
    "TRIGGER_PERIODIC",
    "BrokerPublisher",
    "PeriodicBrokerProducer",
    "PublishOutcome",
    "scenario_for",
]

_log = structlog.get_logger(__name__)

TRIGGER_PERIODIC = "periodic"
TRIGGER_ON_DEMAND = "on-demand"

STATUS_PUBLISHED = "published"
STATUS_REJECTED = "rejected"
STATUS_UNREACHABLE = "unreachable"
STATUS_NO_BROKER = "no-broker-bound"
STATUS_UNPUBLISHABLE = "unpublishable"
STATUS_RATE_LIMITED = "rate-limited"

#: The pseudo client host the broker producer's rate bucket is keyed by.
_BROKER_CLIENT = "broker"


@dataclass(frozen=True)
class PublishOutcome:
    """What one publish attempt did.

    Attributes:
        status: One of the ``STATUS_*`` values.
        channel: The channel key.
        topic: The topic written to (when one was resolved).
        partition: Where the record landed (published only).
        offset: Its offset (published only).
        encoding: ``json`` / ``avro`` / ``protobuf`` (when a record was built).
        source: Where the payload came from (when a record was built).
        message: The canonical message key.
        reason: Why it was not published, as a category.
        detail: A field-level explanation for a rejected payload (never the payload itself).
    """

    status: str
    channel: str
    topic: str | None = None
    partition: int | None = None
    offset: int | None = None
    encoding: str | None = None
    source: str | None = None
    message: str | None = None
    reason: str | None = None
    detail: str | None = None

    def as_json(self) -> dict[str, Any]:
        """The outcome as a JSON object (``None`` fields omitted)."""
        return {key: value for key, value in self.__dict__.items() if value is not None}


def scenario_for(compiled: CompiledCanonicalSpec, requested: str | None) -> Scenario | None:
    """The scenario that shapes payloads: the requested one, else the version's active one."""
    settings = compiled.loaded.mock_settings
    scenarios = parse_scenarios(settings)
    name = requested or parse_active_scenario(settings)
    return scenarios.get(name) if name else None


def _fixtures(compiled: CompiledCanonicalSpec) -> Mapping[str, Any]:
    """Merged fixture-pack data of the version."""
    return merged_template_data(parse_fixture_packs(compiled.loaded.mock_settings))


@dataclass
class _AdapterEntry:
    state_key: tuple[Any, ...]
    adapter: BrokerAdapter


@dataclass
class BrokerPublisher:
    """Publishes channel messages through each version's bound broker.

    Attributes:
        pool: The mock's database pool.
        settings: Mock settings.
        adapter_factory: Builds an adapter from a :class:`BrokerConnection` (tests inject one).
    """

    pool: AsyncConnectionPool
    settings: Settings = field(default_factory=get_settings)
    adapter_factory: Callable[[BrokerConnection], BrokerAdapter] = KafkaAdapter
    _adapters: dict[str, _AdapterEntry] = field(default_factory=dict)
    _usage_tasks: set[asyncio.Task[None]] = field(default_factory=set)

    async def adapter_for(self, version_id: UUID | str) -> BrokerAdapter | None:
        """The adapter for a version's Kafka binding, rebuilt when the binding changed.

        Returns:
            The adapter, or ``None`` when the version has no binding.

        Raises:
            BindingUnavailableError: The binding's credential cannot be opened.
        """
        key = str(version_id)
        row = await load_kafka_binding(self.pool, key)
        if row is None:
            await self.drop(key)
            return None
        state = (str(row.get("id")), str(row.get("rotated_at") or ""), row.get("key_version"),
                 tuple(row.get("bootstrap") or ()), bool(row.get("tls_enabled")), bool(row.get("tls_verify", True)))
        entry = self._adapters.get(key)
        if entry is not None and entry.state_key == state:
            return entry.adapter
        await self.drop(key)
        adapter = self.adapter_factory(connection_from_row(row))
        self._adapters[key] = _AdapterEntry(state_key=state, adapter=adapter)
        return adapter

    async def drop(self, version_id: UUID | str) -> None:
        """Close and forget a version's adapter."""
        entry = self._adapters.pop(str(version_id), None)
        if entry is not None:
            await entry.adapter.close()

    async def close(self) -> None:
        """Close every adapter."""
        for key in list(self._adapters):
            await self.drop(key)

    def _count(self, compiled: CompiledCanonicalSpec, tenant_id: UUID | None, channel: str,
               encoding: str, trigger: str, published: bool) -> None:
        """Count one outcome in ``mock_event_publish_usage`` (fire-and-forget, best-effort)."""
        if tenant_id is None:
            return

        async def _run() -> None:
            try:
                async with self.pool.connection() as conn:
                    await conn.execute(
                        "SELECT apiome.record_mock_event_publish(%s::uuid, %s, %s, %s, %s, %s, %s)",
                        (tenant_id, compiled.loaded.project_slug, compiled.loaded.version_label, channel,
                         encoding, trigger, published),
                    )
                    await conn.commit()
            except Exception:  # noqa: BLE001 - usage never fails a publish
                _log.warning("mock_event_publish_usage_failed", channel=channel, exc_info=True)

        task = asyncio.get_running_loop().create_task(_run())
        self._usage_tasks.add(task)
        task.add_done_callback(self._usage_tasks.discard)

    async def publish_channel(
        self,
        compiled: CompiledCanonicalSpec,
        route: EventChannelRoute,
        *,
        trigger: str,
        scenario: Scenario | None = None,
        payload: Any = NO_PAYLOAD,
        message_name: str | None = None,
        seed: int = 0,
        api_key_id: UUID | None = None,
    ) -> list[PublishOutcome]:
        """Publish the channel's outbound message(s) once.

        Args:
            compiled: The version's compiled canonical spec.
            route: The channel.
            trigger: ``periodic`` or ``on-demand``.
            scenario: The scenario shaping payloads.
            payload: An explicit payload (on demand); omit to resolve one.
            message_name: Publish only this message (on demand); default every outbound message
                (periodic) or the first (on demand).
            seed: Synthesis seed.
            api_key_id: The calling key, for the audit sample (on demand).

        Returns:
            One outcome per message attempted.
        """
        tenant, project, version = compiled.cache_key
        channel = route.key
        if not route.kafka.publishable:
            reason = "not-kafka" if route.kafka.support == "not-kafka" else route.kafka.support.split(": ", 1)[-1]
            return [PublishOutcome(status=STATUS_UNPUBLISHABLE, channel=channel, reason=reason)]

        messages = route.outbound_messages()
        if message_name is not None:
            messages = tuple(m for m in messages if message_name in {m.name, m.key})
        elif trigger == TRIGGER_ON_DEMAND:
            messages = messages[:1]
        if not messages:
            return [PublishOutcome(status=STATUS_UNPUBLISHABLE, channel=channel, topic=route.kafka.topic,
                                   reason="no-outbound-message")]

        try:
            adapter = await self.adapter_for(compiled.loaded.revision_id)
        except BindingUnavailableError:
            return [PublishOutcome(status=STATUS_UNREACHABLE, channel=channel, topic=route.kafka.topic,
                                   reason="credential-unavailable")]
        if adapter is None:
            return [PublishOutcome(status=STATUS_NO_BROKER, channel=channel, topic=route.kafka.topic)]

        limits = await resolve_limits_for_tenant(self.pool, tenant, settings=self.settings)
        tenant_id = limits.tenant_id if limits is not None else None
        fixtures = _fixtures(compiled)
        outcomes: list[PublishOutcome] = []
        for message in messages:
            blocked = await enforce_mock_limits_for_context(
                client_host=_BROKER_CLIENT, tenant=tenant, project=project, version=version,
                pool=self.pool, settings=self.settings, transport="kafka",
            )
            if blocked is not None:
                outcomes.append(PublishOutcome(status=STATUS_RATE_LIMITED, channel=channel,
                                               topic=route.kafka.topic, message=message.key))
                break
            try:
                event: EncodedEvent = build_event(
                    compiled.api, channel, message, scenario=scenario, fixtures=fixtures,
                    payload=payload, seed=seed,
                )
            except EventRejectedError as exc:
                self._count(compiled, tenant_id, channel, encoding_for(message), trigger, published=False)
                _log.info("mock_event_rejected", channel=channel, message=message.key, reason=exc.reason)
                outcomes.append(PublishOutcome(status=STATUS_REJECTED, channel=channel, topic=route.kafka.topic,
                                               encoding=encoding_for(message), message=message.key,
                                               reason=exc.reason, detail=exc.detail))
                continue
            assert route.kafka.topic is not None
            record = PublishRecord(topic=route.kafka.topic, value=event.value, key=event.key, headers=event.headers)
            try:
                receipt = await adapter.publish(record)
            except BrokerError as exc:
                outcomes.append(PublishOutcome(status=STATUS_UNREACHABLE, channel=channel, topic=route.kafka.topic,
                                               encoding=event.encoding, source=event.source, message=message.key,
                                               reason=exc.reason))
                break
            self._count(compiled, tenant_id, channel, event.encoding, trigger, published=True)
            record_mock_transport_event(
                pool=self.pool, tenant=tenant, project=project, version=version, transport="kafka",
                channel=channel, direction="outbound", tenant_id=tenant_id, api_key_id=api_key_id,
                settings=self.settings,
            )
            outcomes.append(PublishOutcome(status=STATUS_PUBLISHED, channel=channel, topic=receipt.topic,
                                           partition=receipt.partition, offset=receipt.offset,
                                           encoding=event.encoding, source=event.source, message=message.key))
        return outcomes


#: Loads a version's compiled spec for the producer: ``(tenant, project, version) -> compiled | None``.
SpecLoader = Callable[[str, str, str], Any]


@dataclass
class PeriodicBrokerProducer:
    """Publishes every bound, mock-enabled version's channels on their interval.

    Attributes:
        publisher: The shared publisher.
        load_spec: Loads a version's compiled spec (awaitable; ``None`` when it can't be served).
        settings: Mock settings.
    """

    publisher: BrokerPublisher
    load_spec: SpecLoader
    settings: Settings = field(default_factory=get_settings)
    _tasks: dict[str, tuple[tuple[Any, ...], asyncio.Task[None]]] = field(default_factory=dict)
    _stop: asyncio.Event = field(default_factory=asyncio.Event)

    async def _version_loop(self, bound: BoundVersion) -> None:
        """Publish one version's channels every interval until its mock is off or it is unbound."""
        version_id = str(bound["version_id"])
        pool = self.publisher.pool
        while not self._stop.is_set():
            if not await version_mock_enabled(pool, version_id):
                _log.info("broker_producer_stopped_mock_disabled", version_id=version_id)
                await self.publisher.drop(version_id)
                return
            compiled = await self.load_spec(bound["tenant_slug"], bound["project_slug"], bound["version_label"])
            routes = [r for r in getattr(compiled, "event_channels", ()) if r.kafka.publishable]
            if not routes:
                return
            scenario = scenario_for(compiled, None)
            for route in routes:
                outcomes = await self.publisher.publish_channel(compiled, route, trigger=TRIGGER_PERIODIC,
                                                                scenario=scenario)
                for outcome in outcomes:
                    if outcome.status != STATUS_PUBLISHED:
                        _log.info("broker_periodic_publish", version_id=version_id, **outcome.as_json())
            interval = min(route.periodic_interval_seconds for route in routes)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except TimeoutError:
                continue

    async def refresh(self) -> None:
        """Start loops for newly bound versions; stop loops for unbound or disabled ones."""
        try:
            bound = await list_bound_versions(self.publisher.pool)
        except Exception:  # noqa: BLE001 - a failed refresh keeps the current loops
            _log.warning("broker_producer_refresh_failed", exc_info=True)
            return
        wanted = {str(row["version_id"]): row for row in bound}
        for version_id, (state, task) in list(self._tasks.items()):
            row = wanted.get(version_id)
            if row is None or row.state_key != state or task.done():
                task.cancel()
                self._tasks.pop(version_id, None)
                if row is None:
                    await self.publisher.drop(version_id)
        for version_id, row in wanted.items():
            if version_id not in self._tasks:
                self._tasks[version_id] = (row.state_key, asyncio.create_task(self._version_loop(row)))

    async def run(self) -> None:
        """Refresh until stopped."""
        while not self._stop.is_set():
            await self.refresh()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.broker_refresh_seconds)
            except TimeoutError:
                continue

    async def stop(self) -> None:
        """Stop every loop and close every adapter."""
        self._stop.set()
        for _state, task in self._tasks.values():
            task.cancel()
        for _state, task in self._tasks.values():
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - shutting down
                pass
        self._tasks.clear()
        await self.publisher.close()
