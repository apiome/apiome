"""The MCP protocol versions the agent runtime serves — a pinned table, not an SDK accident (AAU-4.1, #5714).

``docs/PROTOCOL_VERSIONS.md`` is the human-readable matrix; this module is the same table as code,
and the only place a served version is added or removed. Everything else reads it:

* :mod:`apiome_mcp.protocol_version_gate` refuses an ``MCP-Protocol-Version`` header outside
  :data:`ACCEPTED_PROTOCOL_VERSIONS` with ``400`` and the supported list, and counter-offers
  :data:`LATEST_HANDSHAKE_VERSION` to an ``initialize`` asking for anything the handshake cannot
  serve;
* the self-conformance gate (``tests/test_agent_self_conformance.py``) runs the catalog's
  ``mcp-protocol`` profile against ``/agent/mcp`` once per entry of :data:`SELF_GATE_NEGOTIATION`.

The installed SDK (``mcp`` 1.x) answers whatever *it* supports, which includes 2024-11-05 and
excludes 2026-07-28; the table here overrides it in both directions.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

__all__ = [
    "ACCEPTED_PROTOCOL_VERSIONS",
    "HANDSHAKE_PROTOCOL_VERSIONS",
    "LATEST_HANDSHAKE_VERSION",
    "LEGACY_DEFAULT_PROTOCOL_VERSION",
    "MODERN_PROTOCOL_VERSIONS",
    "PROTOCOL_VERSION_HEADER",
    "SDK_WIRE_VERSION",
    "SELF_GATE_NEGOTIATION",
    "SERVED_PROTOCOL_VERSIONS",
    "UNSUPPORTED_PROTOCOL_VERSION_CODE",
    "is_accepted_header_version",
    "negotiate_handshake_version",
]

#: The revisions ``/agent/mcp`` serves, newest first.
SERVED_PROTOCOL_VERSIONS: tuple[str, ...] = ("2026-07-28", "2025-11-25", "2025-06-18")

#: The version a request without an ``MCP-Protocol-Version`` header is read as. The transports
#: spec says a server without other information SHOULD assume 2025-03-26, so legacy clients that
#: predate the header keep working; a client may also negotiate it explicitly.
LEGACY_DEFAULT_PROTOCOL_VERSION = "2025-03-26"

#: Every version a request header may name: the served set plus the legacy default. Anything
#: else — 2024-11-05 (the HTTP+SSE era) included — is refused with ``400``.
ACCEPTED_PROTOCOL_VERSIONS: tuple[str, ...] = (*SERVED_PROTOCOL_VERSIONS, LEGACY_DEFAULT_PROTOCOL_VERSION)

#: Revisions that use the stateless per-request envelope and have no ``initialize`` handshake.
MODERN_PROTOCOL_VERSIONS: tuple[str, ...] = ("2026-07-28",)

#: Revisions an ``initialize`` may settle on, newest first.
HANDSHAKE_PROTOCOL_VERSIONS: tuple[str, ...] = tuple(
    v for v in ACCEPTED_PROTOCOL_VERSIONS if v not in MODERN_PROTOCOL_VERSIONS
)

#: The newest handshake revision: the counter-offer to an ``initialize`` asking for a version the
#: handshake cannot serve (a 2026-07-28 client falling back, 2024-11-05, or an unknown string).
LATEST_HANDSHAKE_VERSION = HANDSHAKE_PROTOCOL_VERSIONS[0]

#: The header value the SDK is handed for a modern request. ``mcp`` 1.x validates the header
#: against its own list, which lacks 2026-07-28; the gate keeps the real version for middleware
#: and audit and gives the SDK the newest revision its message plane implements.
SDK_WIRE_VERSION = LATEST_HANDSHAKE_VERSION

#: The request header naming the protocol version (lower-case, as ASGI delivers header names).
PROTOCOL_VERSION_HEADER = "mcp-protocol-version"

#: JSON-RPC code of the 2026-07-28 unsupported-protocol-version error. It lies in the
#: implementation-defined server-error band, so the catalog's error-code rule accepts it.
UNSUPPORTED_PROTOCOL_VERSION_CODE = -32022

#: What the self-conformance gate expects ``initialize`` to settle on for each version a client
#: offers. A 2026-07-28 offer is answered with :data:`LATEST_HANDSHAKE_VERSION` until AAU-4.2
#: serves stateless requests: that revision has no handshake, so claiming it there would be the
#: ``protocol.modern-version-via-handshake`` defect.
SELF_GATE_NEGOTIATION: Mapping[str, str] = MappingProxyType(
    {
        "2026-07-28": LATEST_HANDSHAKE_VERSION,
        "2025-11-25": "2025-11-25",
        "2025-06-18": "2025-06-18",
        LEGACY_DEFAULT_PROTOCOL_VERSION: LEGACY_DEFAULT_PROTOCOL_VERSION,
    }
)


def negotiate_handshake_version(requested: object) -> str:
    """The version to answer an ``initialize`` that asked for ``requested``.

    Per the lifecycle spec the server echoes a version it supports and otherwise answers with
    the latest one it supports, leaving the client to disconnect if it cannot speak it.

    Args:
        requested: The ``protocolVersion`` the client offered (any JSON value).

    Returns:
        ``requested`` when it is a handshake revision Apiome serves, else
        :data:`LATEST_HANDSHAKE_VERSION`.
    """
    if isinstance(requested, str) and requested in HANDSHAKE_PROTOCOL_VERSIONS:
        return requested
    return LATEST_HANDSHAKE_VERSION


def is_accepted_header_version(value: str) -> bool:
    """Whether an ``MCP-Protocol-Version`` header value names a version Apiome accepts.

    Args:
        value: The header value, as sent (surrounding whitespace is not trimmed: a client
            sending ``" 2025-06-18"`` is sending a different string).

    Returns:
        ``True`` when ``value`` is in :data:`ACCEPTED_PROTOCOL_VERSIONS`.
    """
    return value in ACCEPTED_PROTOCOL_VERSIONS
