"""Event channel control routes on the hosted mock — XPC-2.2 (#5736).

``GET  /{tenant}/{project}/{version}/__channels__``
    Every event channel of an AsyncAPI version: its address, the Kafka topic it publishes to, its
    broker ``support`` status (``supported``, ``unsupported: unresolved-address-parameter``,
    ``unsupported: invalid-topic``, ``not-kafka``), the encoding of each outbound message, and
    whether the version has a broker bound. This is the per-channel capability report XPC-5.5's
    protocol matrix reads.

``POST /{tenant}/{project}/{version}/__channels__/{channel}/publish``
    Publish one record now. The JSON body, when present, is the payload (it is validated like any
    other; an invalid one is ``422`` and is not sent). ``?message=<name>`` picks one of several
    outbound messages; ``?__seed=`` makes a synthesized payload reproducible; ``X-Mock-Scenario``
    selects the scenario whose ``PUBLISH /<channel>`` override shapes the payload.

    ``200`` with the record's ``topic``, ``partition``, ``offset``, ``encoding`` and payload
    ``source``; ``404`` for an unknown channel; ``409 no-broker-bound`` when the version has no
    broker binding; ``422`` when the channel can't be published (``unpublishable``) or the payload
    is refused (``rejected``); ``429`` when the tenant's rate cap is reached; ``502`` when the broker
    is unreachable (with the category, e.g. ``auth``).

Both answer exactly as the version's other mock routes do for access: a disabled or missing mock is
``404``, and a private draft needs its API key.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.responses import JSONResponse, Response
from psycopg_pool import AsyncConnectionPool
from starlette.requests import Request

from apiome_mock.api_key import ValidatedApiKey
from apiome_mock.broker_bindings import load_kafka_binding
from apiome_mock.broker_producer import (
    STATUS_NO_BROKER,
    STATUS_PUBLISHED,
    STATUS_RATE_LIMITED,
    STATUS_REJECTED,
    STATUS_UNPUBLISHABLE,
    TRIGGER_ON_DEMAND,
    BrokerPublisher,
    scenario_for,
)
from apiome_mock.canonical_compiler import CompiledCanonicalSpec
from apiome_mock.canonical_spec_cache import CanonicalSpecCache
from apiome_mock.event_payloads import encoding_for
from apiome_mock.event_transport import _find_channel, _parse_seed, _resolve_canonical_spec
from apiome_mock.problems import not_found
from apiome_mock.scenarios import MOCK_SCENARIO_HEADER

__all__ = ["CHANNELS_SEGMENT", "handle_channel_publish", "handle_list_channels"]

#: The reserved path segment for channel control routes.
CHANNELS_SEGMENT = "__channels__"

#: Largest on-demand payload accepted (bytes).
_MAX_BODY_BYTES = 1_048_576

_STATUS_HTTP = {
    STATUS_PUBLISHED: 200,
    STATUS_NO_BROKER: 409,
    STATUS_UNPUBLISHABLE: 422,
    STATUS_REJECTED: 422,
    STATUS_RATE_LIMITED: 429,
}


def _describe(compiled: CompiledCanonicalSpec, broker_bound: bool) -> dict[str, Any]:
    """The ``__channels__`` listing body."""
    channels = []
    for route in compiled.event_channels:
        channels.append(
            {
                "key": route.key,
                "address": route.address,
                "kafka": {
                    "support": route.kafka.support,
                    "topic": route.kafka.topic,
                    "unresolvedParameters": list(route.kafka.unresolved),
                },
                "messages": [
                    {"key": message.key, "name": message.name, "encoding": encoding_for(message)}
                    for message in route.outbound_messages()
                ],
                "intervalSeconds": route.periodic_interval_seconds,
                "websocket": route.supports_websocket,
                "sse": route.supports_sse,
            }
        )
    return {"brokerBound": broker_bound, "channels": channels}


async def handle_list_channels(
    *,
    tenant: str,
    project: str,
    version: str,
    pool: AsyncConnectionPool,
    cache: CanonicalSpecCache,
    api_key: ValidatedApiKey | None,
) -> Response:
    """Answer ``GET …/__channels__``."""
    resolved = await _resolve_canonical_spec(
        pool=pool, cache=cache, tenant=tenant, project=project, version=version, api_key=api_key
    )
    if isinstance(resolved, Response):
        return resolved
    bound = await load_kafka_binding(pool, resolved.loaded.revision_id) is not None
    return JSONResponse(_describe(resolved, bound))


async def handle_channel_publish(
    request: Request,
    *,
    tenant: str,
    project: str,
    version: str,
    channel_key: str,
    pool: AsyncConnectionPool,
    cache: CanonicalSpecCache,
    publisher: BrokerPublisher,
    api_key: ValidatedApiKey | None,
) -> Response:
    """Answer ``POST …/__channels__/{channel}/publish``."""
    resolved = await _resolve_canonical_spec(
        pool=pool, cache=cache, tenant=tenant, project=project, version=version, api_key=api_key
    )
    if isinstance(resolved, Response):
        return resolved
    route = _find_channel(resolved, channel_key)
    if route is None:
        return not_found("Event channel not found.", instance=request.url.path)

    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        return JSONResponse({"status": STATUS_REJECTED, "reason": "payload-too-large"}, status_code=413)
    kwargs: dict[str, Any] = {}
    if raw.strip():
        try:
            kwargs["payload"] = json.loads(raw)
        except json.JSONDecodeError:
            return JSONResponse(
                {"status": STATUS_REJECTED, "channel": route.key, "reason": "invalid-json"}, status_code=422
            )

    outcomes = await publisher.publish_channel(
        resolved,
        route,
        trigger=TRIGGER_ON_DEMAND,
        scenario=scenario_for(resolved, request.headers.get(MOCK_SCENARIO_HEADER)),
        message_name=request.query_params.get("message"),
        seed=_parse_seed(request.query_params) or 0,
        api_key_id=api_key.id if api_key is not None else None,
        **kwargs,
    )
    if not outcomes:
        return not_found("No outbound message matches.", instance=request.url.path)
    outcome = outcomes[0]
    return JSONResponse(outcome.as_json(), status_code=_STATUS_HTTP.get(outcome.status, 502))
