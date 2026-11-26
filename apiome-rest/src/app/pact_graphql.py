"""Recognise a GraphQL-over-HTTP pact interaction — PFX-3.7 (#6937).

Pact has no GraphQL transport: a consumer test (pact-js ``GraphQLInteraction``, or any client
recording its calls) writes a GraphQL operation as an ordinary HTTP interaction — a ``POST`` of
``{"query", "variables", "operationName"}``, or a ``GET`` with those as query parameters, or a
``POST`` of an ``application/graphql`` body. Replayed as plain HTTP it still works, but two things
the XPC-1.2 GraphQL adapter (:mod:`app.contract_suite_graphql`) knows are lost:

* **The verb says nothing about writes.** Every GraphQL operation travels as ``POST``, so the
  mutating-method gate would hold back a harmless ``query`` and treat it like a write. The
  operation *type* decides instead — a ``mutation`` is mutating, a ``query`` is not — exactly as
  :func:`app.contract_runner.is_mutating_case` reads a GraphQL case.
* **The verdict is in the envelope.** A GraphQL server answers a failed operation with ``200`` and
  an ``errors`` array; a pact body match lets extra members through, so ``errors`` would pass
  unnoticed unless the consumer recorded it.

:func:`read_graphql_request` reads the operation so the compiler can attach a
:class:`~app.contract_suite.ContractGraphqlRequest` to the case. Detection is by the document
itself: a request is GraphQL when its ``query`` parses as an executable GraphQL document. A
``query`` member that does not parse is ordinary data (a search box sends one too) unless the
path ends in ``graphql``, where it is reported as unreadable.

Pure: :mod:`graphql` parses in memory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from graphql import GraphQLError, parse
from graphql.language import FieldNode, OperationDefinitionNode

__all__ = [
    "GRAPHQL_MEDIA_TYPE",
    "GraphqlPactOperation",
    "read_graphql_request",
]

#: The media type of a raw GraphQL document body.
GRAPHQL_MEDIA_TYPE = "application/graphql"


@dataclass(frozen=True)
class GraphqlPactOperation:
    """The GraphQL operation an HTTP interaction carries.

    Attributes:
        query: The document, as recorded.
        variables: The variable values (``{}`` when none were recorded).
        operation_name: The operation executed; ``""`` for a lone anonymous one.
        operation_type: ``query``, ``mutation`` or ``subscription``.
        field: The first root field the operation selects (``""`` when it selects through a
            fragment).
    """

    query: str
    variables: Dict[str, Any] = field(default_factory=dict)
    operation_name: str = ""
    operation_type: str = "query"
    field: str = ""


def _members(
    method: str, body: Any, media_type: Optional[str], query: Mapping[str, Sequence[str]]
) -> Optional[Tuple[str, Any, Any]]:
    """The ``(query, variables, operationName)`` an HTTP request carries, if it carries one.

    Args:
        method: The upper-cased HTTP method.
        body: The decoded request body (``None`` when there is none).
        media_type: The body's media type.
        query: The request's query parameters (name → values).

    Returns:
        The three members, or ``None`` when the request has no ``query`` string.
    """
    if isinstance(body, dict) and isinstance(body.get("query"), str):
        return body["query"], body.get("variables"), body.get("operationName")
    if isinstance(body, str) and (media_type or "").lower() == GRAPHQL_MEDIA_TYPE:
        return body, None, None
    if method == "GET" and query.get("query"):
        variables = (query.get("variables") or [None])[0]
        name = (query.get("operationName") or [None])[0]
        return query["query"][0], variables, name
    return None


def read_graphql_request(
    method: str,
    path: str,
    body: Any,
    media_type: Optional[str],
    query: Mapping[str, Sequence[str]],
) -> Tuple[Optional[GraphqlPactOperation], Optional[str]]:
    """Read the GraphQL operation an HTTP interaction's request carries.

    Args:
        method: The upper-cased HTTP method.
        path: The recorded request path.
        body: The decoded request body.
        media_type: The body's media type.
        query: The request's query parameters (name → values, as recorded).

    Returns:
        ``(operation, None)`` for a GraphQL request; ``(None, None)`` for a request that is not
        GraphQL; ``(None, why)`` for one that carries a GraphQL request this module cannot read —
        a document that does not parse on a ``…/graphql`` path, several operations and no
        ``operationName``, or variables that are not an object.
    """
    members = _members(method, body, media_type, query)
    if members is None:
        return None, None
    text, variables, name = members
    graphql_path = path.rstrip("/").lower().endswith("graphql")
    try:
        document = parse(text)
    except GraphQLError as exc:
        if graphql_path:
            return None, f"its query is not a GraphQL document ({exc.message})"
        return None, None
    operations = [item for item in document.definitions if isinstance(item, OperationDefinitionNode)]
    if not operations:
        return (None, "its GraphQL document defines no operation") if graphql_path else (None, None)

    if isinstance(variables, str) and variables.strip():
        try:
            variables = json.loads(variables)
        except ValueError:
            return None, "its GraphQL variables are not JSON"
    if variables is not None and not isinstance(variables, dict):
        return None, "its GraphQL variables are not an object"

    wanted = name.strip() if isinstance(name, str) and name.strip() else None
    if wanted is not None:
        chosen = next((item for item in operations if item.name and item.name.value == wanted), None)
        if chosen is None:
            return None, f"its operationName '{wanted}' names no operation of the document"
    elif len(operations) == 1:
        chosen = operations[0]
    else:
        return None, "its GraphQL document defines several operations and the request names none (operationName)"

    root = next((item for item in chosen.selection_set.selections if isinstance(item, FieldNode)), None)
    return (
        GraphqlPactOperation(
            query=text,
            variables=dict(variables or {}),
            operation_name=chosen.name.value if chosen.name else "",
            operation_type=chosen.operation.value,
            field=root.name.value if root is not None else "",
        ),
        None,
    )
