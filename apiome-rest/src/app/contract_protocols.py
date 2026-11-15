"""The wire protocols a contract suite can be executed over — XPC-1.2 (#5730).

One closed vocabulary, shared by the three places that must agree on it:

* :mod:`app.contract_suite` — each protocol adapter stamps its protocol on the manifest and on
  every case it compiles;
* :mod:`app.verification_target` — a target declares the protocol it speaks, so the runner never
  guesses it from a URL;
* :mod:`app.verification_evidence` — a run records the protocol it was executed over.

The database enforces the same list with a CHECK constraint on ``verification_target.protocol``
and ``verification_run.protocol`` (V371, widened by V374). Adding a protocol means adding it here,
adding its adapter, and widening those constraints in a new migration.

A suite's protocol and its target's are usually the same word. The one exception is the gRPC
family (XPC-3.2, #5742): a suite compiled from a Protobuf version is stamped ``grpc`` and runs
against a ``grpc`` target (a native ``grpcio`` channel) **or** a ``connect`` target (the Connect
protocol over the HTTP runner). :func:`target_protocols_for` is the one place that pairing lives.
"""

from __future__ import annotations

from typing import Dict, Tuple

__all__ = [
    "CONTRACT_PROTOCOLS",
    "PROTOCOL_CONNECT",
    "PROTOCOL_GRAPHQL",
    "PROTOCOL_GRPC",
    "PROTOCOL_HTTP",
    "target_protocols_for",
]

#: Plain HTTP request/response — the REST adapter's protocol, and the default everywhere.
PROTOCOL_HTTP = "http"

#: GraphQL over HTTP: every case is a ``POST`` of a ``{query, variables, operationName}``
#: document to the target URL, and the verdict is read from the response envelope.
PROTOCOL_GRAPHQL = "graphql"

#: gRPC: every case calls one unary method. As a suite protocol it names the gRPC family (a
#: Protobuf version's suite); as a target protocol it means a native gRPC channel (HTTP/2,
#: binary protobuf, server reflection) to ``base_url``'s host and port.
PROTOCOL_GRPC = "grpc"

#: The Connect protocol: a gRPC-family suite's cases ``POST``\ed as JSON to
#: ``{base_url}/{package.Service}/{Method}`` over the ordinary HTTP runner — no HTTP/2, no proxy.
#: Only ever a *target* protocol: a suite is compiled ``grpc`` and run over either transport.
PROTOCOL_CONNECT = "connect"

#: Every protocol an adapter exists for, in the order they were added.
CONTRACT_PROTOCOLS: Tuple[str, ...] = (
    PROTOCOL_HTTP,
    PROTOCOL_GRAPHQL,
    PROTOCOL_GRPC,
    PROTOCOL_CONNECT,
)

#: Which target protocols can execute a suite of each protocol. A protocol not listed pairs only
#: with itself.
_TARGET_PROTOCOLS: Dict[str, Tuple[str, ...]] = {
    PROTOCOL_GRPC: (PROTOCOL_GRPC, PROTOCOL_CONNECT),
}


def target_protocols_for(suite_protocol: str) -> Tuple[str, ...]:
    """Return the target protocols that can execute a suite compiled for ``suite_protocol``.

    Args:
        suite_protocol: The manifest's ``protocol``.

    Returns:
        The acceptable target protocols, the suite's own first: ``("grpc", "connect")`` for a
        gRPC-family suite, and just the protocol itself for every other one.
    """
    return _TARGET_PROTOCOLS.get(suite_protocol, (suite_protocol,))
