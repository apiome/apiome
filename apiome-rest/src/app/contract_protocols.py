"""The wire protocols a contract suite can be executed over — XPC-1.2 (#5730).

One closed vocabulary, shared by the three places that must agree on it:

* :mod:`app.contract_suite` — each protocol adapter stamps its protocol on the manifest and on
  every case it compiles;
* :mod:`app.verification_target` — a target declares the protocol it speaks, so the runner never
  guesses it from a URL;
* :mod:`app.verification_evidence` — a run records the protocol it was executed over.

The database enforces the same list with a CHECK constraint on ``verification_target.protocol``
and ``verification_run.protocol`` (V371). Adding a protocol means adding it here, adding its
adapter, and widening those constraints in a new migration.
"""

from __future__ import annotations

from typing import Tuple

__all__ = [
    "CONTRACT_PROTOCOLS",
    "PROTOCOL_GRAPHQL",
    "PROTOCOL_HTTP",
]

#: Plain HTTP request/response — the REST adapter's protocol, and the default everywhere.
PROTOCOL_HTTP = "http"

#: GraphQL over HTTP: every case is a ``POST`` of a ``{query, variables, operationName}``
#: document to the target URL, and the verdict is read from the response envelope.
PROTOCOL_GRAPHQL = "graphql"

#: Every protocol an adapter exists for, in the order they were added.
CONTRACT_PROTOCOLS: Tuple[str, ...] = (PROTOCOL_HTTP, PROTOCOL_GRAPHQL)
