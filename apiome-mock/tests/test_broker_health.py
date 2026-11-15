"""Dev broker reachability on ``/health`` — XPC-2.1 (#5735).

A real local TCP listener stands in for Redpanda's Kafka port, so "reachable" is a genuine
connection; "absent" is a host that does not resolve, as ``redpanda`` doesn't on a compose network
started without ``--profile broker``.
"""

from __future__ import annotations

import asyncio
import socket
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from apiome_mock.broker_health import DevBrokerHealth, parse_bootstrap
from apiome_mock.spec_cache import SpecCache

#: A name that never resolves (RFC 6761 reserves ``.invalid``).
_ABSENT = "redpanda.invalid"


def _free_port() -> int:
    """A local port nothing listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, []),
        ("", []),
        ("redpanda:9092", [("redpanda", 9092)]),
        ("Redpanda", [("redpanda", 9092)]),
        (" a:1 , b:2 ", [("a", 1), ("b", 2)]),
        ("[::1]:9093", [("::1", 9093)]),
        ("a:0,b:notaport,:9092,c:9094", [("c", 9094)]),
    ],
)
def test_parse_bootstrap(value, expected):
    assert parse_bootstrap(value) == expected


def test_unset_reports_nothing():
    health = DevBrokerHealth(None)
    assert health.configured is False
    assert asyncio.run(health.state()) is None


def test_a_host_that_does_not_resolve_reports_nothing():
    # The compose profile is off: the variable is set, but no `redpanda` container exists.
    assert asyncio.run(DevBrokerHealth(f"{_ABSENT}:9092").state()) is None


def test_a_listening_broker_is_reachable():
    async def scenario():
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            return await DevBrokerHealth(f"127.0.0.1:{port}").state()
        finally:
            server.close()
            await server.wait_closed()

    assert asyncio.run(scenario()) == "reachable"


def test_a_present_but_closed_broker_is_unreachable():
    health = DevBrokerHealth(f"127.0.0.1:{_free_port()}", timeout_seconds=0.5)
    assert asyncio.run(health.state()) == "unreachable"


def test_any_reachable_entry_wins():
    async def scenario():
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            value = f"{_ABSENT}:9092,127.0.0.1:{_free_port()},127.0.0.1:{port}"
            return await DevBrokerHealth(value, timeout_seconds=0.5).state()
        finally:
            server.close()
            await server.wait_closed()

    assert asyncio.run(scenario()) == "reachable"


def test_the_answer_is_cached_briefly():
    health = DevBrokerHealth(f"127.0.0.1:{_free_port()}", timeout_seconds=0.2, cache_seconds=5.0)
    calls = []

    async def fake_check():
        calls.append(1)
        return "unreachable"

    health._check = fake_check  # type: ignore[method-assign]

    async def scenario():
        await health.state(now=100.0)
        await health.state(now=104.0)
        await health.state(now=106.0)

    asyncio.run(scenario())
    assert len(calls) == 2


def _health_json(monkeypatch, mock_pool, bootstrap):
    """Call ``/health`` on a fresh app with ``APIOME_MOCK_DEV_BROKER_BOOTSTRAP`` set (or not)."""
    monkeypatch.setenv("APIOME_MOCK_DATABASE_URL", "postgresql://localhost/db")
    if bootstrap is None:
        monkeypatch.delenv("APIOME_MOCK_DEV_BROKER_BOOTSTRAP", raising=False)
    else:
        monkeypatch.setenv("APIOME_MOCK_DEV_BROKER_BOOTSTRAP", bootstrap)
    from apiome_mock.settings import get_settings

    get_settings.cache_clear()
    try:
        from apiome_mock.server import create_app

        with patch("apiome_mock.server.create_async_pool", return_value=mock_pool):
            app = create_app()
            app.state.db_pool = mock_pool
            app.state.spec_cache = SpecCache(max_entries=8, ttl_seconds=60.0)
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")
        assert response.status_code == 200
        return response.json()
    finally:
        get_settings.cache_clear()


def test_health_reports_a_reachable_dev_broker(monkeypatch, mock_pool):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        port = listener.getsockname()[1]
        body = _health_json(monkeypatch, mock_pool, f"127.0.0.1:{port}")
    assert body == {"status": "ok", "broker": "reachable"}


def test_health_without_the_profile_is_unchanged(monkeypatch, mock_pool):
    assert _health_json(monkeypatch, mock_pool, f"{_ABSENT}:9092") == {"status": "ok"}
    assert _health_json(monkeypatch, mock_pool, None) == {"status": "ok"}
