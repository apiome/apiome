"""Which protocols a portable deployment serves, as data (#5755, XPC-5.4).

The portable runtime's ``GET /ready`` carries a ``protocols`` object, and the CI action
(``mock-action``) and the serverless preflight read it rather than guessing: a CI step that asks
for a GraphQL mock must either get a URL or fail with the reason, never a URL that 404s.

The contract — one entry per protocol id, always present, never omitted::

    "protocols": {
      "http":    {"served": true,  "path": ""},
      "graphql": {"served": false, "reason": "..."},
      "connect": {"served": false, "reason": "..."},
      "grpc":    {"served": false, "reason": "..."},
      "events":  {"served": false, "reason": "..."}
    }

``served`` is the only field a reader may branch on. ``path`` (served HTTP-carried protocols) is
relative to the runtime's mount — ``""`` means "at the mount itself", as Connect methods are
(``/pkg.Service/Method``) and ``"/graphql"`` is where a GraphQL endpoint answers. ``port`` (served
native gRPC) is the container-side listener. ``reason`` (unserved protocols) is one sentence a
person can act on. XPC-5.2 (#5753) flips the entries it implements to ``served: true``; until then
this runtime serves HTTP only and says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "PROTOCOL_IDS",
    "ProtocolSupport",
    "portable_protocols",
    "protocols_as_dict",
]

#: Every protocol id a deployment reports on, in display order. ``events`` covers both the
#: WebSocket/SSE transports and broker-backed channels (Kafka, MQTT, …).
PROTOCOL_IDS: tuple[str, ...] = ("http", "graphql", "connect", "grpc", "events")

#: Why the portable runtime does not yet carry a protocol (until bundle format v2 and XPC-5.2).
_HOSTED_ONLY = (
    "this runtime serves HTTP only: {name} routes are not in mock bundle format v1, so they are "
    "served by the hosted mock until the portable runtime carries them (XPC-5.1/5.2)."
)

_NAMES = {
    "graphql": "GraphQL",
    "connect": "Connect",
    "grpc": "native gRPC",
    "events": "event-channel (WebSocket/SSE and broker)",
}


@dataclass(frozen=True)
class ProtocolSupport:
    """Whether one protocol is served by a deployment, and how to reach it or why not.

    Attributes:
        served: True when requests in this protocol are answered.
        path: For a served HTTP-carried protocol, the path relative to the mount ("" = the mount).
        port: For a served native listener (gRPC), the port inside the runtime.
        reason: For an unserved protocol, one actionable sentence.
    """

    served: bool
    path: str | None = None
    port: int | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Render the entry for JSON output, leaving out fields that do not apply.

        Returns:
            ``{"served": …}`` plus whichever of ``path``, ``port`` and ``reason`` are set.
        """
        document: dict[str, Any] = {"served": self.served}
        if self.path is not None:
            document["path"] = self.path
        if self.port is not None:
            document["port"] = self.port
        if self.reason is not None:
            document["reason"] = self.reason
        return document


def portable_protocols() -> dict[str, ProtocolSupport]:
    """Report what the portable runtime (and so the serverless adapter wrapping it) serves today.

    Returns:
        One :class:`ProtocolSupport` per id in :data:`PROTOCOL_IDS`: HTTP served at the mount,
        every other protocol unserved with the reason.
    """
    report = {"http": ProtocolSupport(served=True, path="")}
    for protocol in PROTOCOL_IDS[1:]:
        report[protocol] = ProtocolSupport(served=False, reason=_HOSTED_ONLY.format(name=_NAMES[protocol]))
    return report


def protocols_as_dict(report: dict[str, ProtocolSupport]) -> dict[str, dict[str, Any]]:
    """Render a protocol report for JSON output, in :data:`PROTOCOL_IDS` order.

    Args:
        report: Protocol id → support entry.

    Returns:
        Protocol id → rendered entry.
    """
    return {protocol: report[protocol].as_dict() for protocol in PROTOCOL_IDS if protocol in report}
