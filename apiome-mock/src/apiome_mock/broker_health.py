"""Dev broker reachability for ``/health`` — XPC-2.1 (#5735).

``docker compose --profile broker up`` starts a single-node Redpanda beside the stack, and
``APIOME_MOCK_DEV_BROKER_BOOTSTRAP`` (``redpanda:9092`` in compose) tells the mock where it is.
``/health`` then reports ``"broker": "reachable"`` (or ``"unreachable"``) so the operator can see the
broker came up.

**Without the profile nothing changes.** The variable is pre-wired in compose, but the ``redpanda``
host only resolves on the compose network while the profile's container exists. A bootstrap host
that does not resolve means "no dev broker here", and ``/health`` answers exactly as before, with
no ``broker`` key. The mock never waits on a broker and never fails its health check because of one.

Reachability is a TCP connect to a bootstrap entry, bounded by a short timeout and cached for a few
seconds, so a health probe every five seconds costs at most one connection. The Kafka handshake is
XPC-2.2's producer's business, not the health check's.
"""

from __future__ import annotations

import asyncio
import socket
import time
from typing import List, Literal, Optional, Tuple

__all__ = [
    "BROKER_REACHABLE",
    "BROKER_UNREACHABLE",
    "DevBrokerHealth",
    "parse_bootstrap",
]

#: The two states ``/health`` reports for a present dev broker.
BROKER_REACHABLE = "reachable"
BROKER_UNREACHABLE = "unreachable"

BrokerState = Literal["reachable", "unreachable"]

#: The Kafka port an entry gets when it names none.
_DEFAULT_PORT = 9092


def parse_bootstrap(value: Optional[str]) -> List[Tuple[str, int]]:
    """Parse a ``host[:port]`` list, comma-separated, as ``bootstrap.servers`` is written.

    Args:
        value: The variable's value, e.g. ``"redpanda:9092"`` or ``"[::1]:9092,b:9093"``.

    Returns:
        ``(host, port)`` pairs, in order. Malformed entries are skipped: the variable only adds a
        line to ``/health``, so a typo must never break the endpoint.
    """
    entries: List[Tuple[str, int]] = []
    for raw in (value or "").split(","):
        text = raw.strip()
        if not text:
            continue
        if text.startswith("["):
            host, _, rest = text[1:].partition("]")
            port_text = rest[1:] if rest.startswith(":") else ""
        elif text.count(":") == 1:
            host, _, port_text = text.partition(":")
        else:
            host, port_text = text, ""
        if not host:
            continue
        if port_text and not (port_text.isdigit() and 1 <= int(port_text) <= 65535):
            continue
        entries.append((host.lower(), int(port_text) if port_text else _DEFAULT_PORT))
    return entries


class DevBrokerHealth:
    """Answers "is the dev broker up?" for ``/health``, cheaply.

    Attributes:
        entries: The parsed bootstrap entries.
        timeout_seconds: Budget for one TCP connect.
        cache_seconds: How long one answer is reused.
    """

    def __init__(
        self,
        bootstrap: Optional[str],
        *,
        timeout_seconds: float = 1.0,
        cache_seconds: float = 5.0,
    ) -> None:
        self.entries = parse_bootstrap(bootstrap)
        self.timeout_seconds = timeout_seconds
        self.cache_seconds = cache_seconds
        self._cached: Optional[Tuple[float, Optional[BrokerState]]] = None
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        """Whether ``APIOME_MOCK_DEV_BROKER_BOOTSTRAP`` named at least one usable entry."""
        return bool(self.entries)

    async def _resolves(self, host: str, port: int) -> bool:
        """Return whether ``host`` resolves at all (the compose profile is active)."""
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(
                loop.getaddrinfo(host, port, proto=socket.IPPROTO_TCP), self.timeout_seconds
            )
        except (OSError, asyncio.TimeoutError, UnicodeError):
            return False
        return True

    async def _connects(self, host: str, port: int) -> bool:
        """Return whether a TCP connection to ``host:port`` opens within the timeout."""
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), self.timeout_seconds
            )
        except (OSError, asyncio.TimeoutError):
            return False
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        return True

    async def _check(self) -> Optional[BrokerState]:
        """Probe every entry: ``None`` when none resolves, else reachable / unreachable."""
        present = False
        for host, port in self.entries:
            if not await self._resolves(host, port):
                continue
            present = True
            if await self._connects(host, port):
                return BROKER_REACHABLE
        return BROKER_UNREACHABLE if present else None

    async def state(self, *, now: Optional[float] = None) -> Optional[BrokerState]:
        """Return the dev broker's state, or ``None`` when there is no dev broker to report.

        Args:
            now: The monotonic clock reading (tests).

        Returns:
            ``"reachable"``, ``"unreachable"``, or ``None`` when the variable is unset or no
            bootstrap host resolves (the compose profile is not active).
        """
        if not self.entries:
            return None
        clock = time.monotonic() if now is None else now
        async with self._lock:
            if self._cached is not None and clock - self._cached[0] < self.cache_seconds:
                return self._cached[1]
            result = await self._check()
            self._cached = (clock, result)
            return result
