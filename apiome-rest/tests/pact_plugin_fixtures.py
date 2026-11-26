"""Pact protobuf-plugin fixtures for the PFX-3.7 tests (#6937).

Pacts in the shape the Pact protobuf plugin writes — a Pact 4 ``Synchronous/Messages`` interaction
with ``transport: grpc`` and base64 binary contents, and the ``FileDescriptorSet`` under
``metadata.plugins[name=protobuf].configuration[descriptorKey]`` — built from the XPC-3.2 orders
fixture (:mod:`tests.rpc_contract_fixtures`), so no ``protoc`` or plugin binary is needed.
"""

from __future__ import annotations

import base64
import copy
from typing import Any, Dict, List, Optional

from google.protobuf import json_format, message_factory

from tests.rpc_contract_fixtures import PACKAGE, orders_descriptor_set, orders_pool

#: The descriptor key every fixture interaction names.
DESCRIPTOR_KEY = "5cd5a4c3f5d0bd3c1ad6c2f6f7d1b9a1"

_POOL = orders_pool()


def encode(type_name: str, message: Dict[str, Any]) -> str:
    """Encode a protobuf-JSON message as the base64 binary content the plugin records.

    Args:
        type_name: The message type, without the package (``GetOrderRequest``).
        message: The message, protobuf-JSON.

    Returns:
        Base64 of the serialized message.
    """
    cls = message_factory.GetMessageClass(_POOL.FindMessageTypeByName(f"{PACKAGE}.{type_name}"))
    instance = cls()
    json_format.ParseDict(message, instance)
    return base64.b64encode(instance.SerializePartialToString()).decode("ascii")


def contents(type_name: str, message: Dict[str, Any]) -> Dict[str, Any]:
    """A plugin ``contents`` block holding ``message``."""
    return {
        "content": encode(type_name, message),
        "contentType": f"application/protobuf;message=.{PACKAGE}.{type_name}",
        "contentTypeHint": "BINARY",
        "encoded": "base64",
    }


def grpc_interaction(
    description: str = "get order 1042",
    *,
    service: str = "Orders/GetOrder",
    request: Optional[Dict[str, Any]] = None,
    response: Optional[List[Dict[str, Any]]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """A protobuf-plugin gRPC interaction; by default ``GetOrder`` answered with order 1042.

    Args:
        description: The interaction's description.
        service: The plugin configuration's ``service``.
        request: The ``request`` object (default: ``{orderId: "1042"}``).
        response: The ``response`` list (default: an order with a ``number`` rule on its total).
        **extra: More interaction members (``providerStates``, ``pending``, ``key`` …).

    Returns:
        The interaction.
    """
    interaction: Dict[str, Any] = {
        "type": "Synchronous/Messages",
        "transport": "grpc",
        "description": description,
        "pluginConfiguration": {"protobuf": {"descriptorKey": DESCRIPTOR_KEY, "service": service}},
        "interactionMarkup": {"markup": "```protobuf\nmessage Order {}\n```", "markupType": "COMMON_MARK"},
        "request": request
        if request is not None
        else {
            "contents": contents("GetOrderRequest", {"orderId": "1042"}),
            "metadata": {"contentType": f"application/protobuf;message=.{PACKAGE}.GetOrderRequest"},
        },
        "response": response
        if response is not None
        else [
            {
                "contents": contents("Order", {"id": "1042", "totalCents": "1200", "status": "OPEN"}),
                "matchingRules": {"body": {"$.total_cents": {"combine": "AND", "matchers": [{"match": "integer"}]}}},
                "metadata": {"contentType": f"application/protobuf;message=.{PACKAGE}.Order"},
            }
        ],
    }
    interaction.update(extra)
    return interaction


def grpc_pact(
    interactions: List[Dict[str, Any]],
    *,
    descriptors: Optional[str] = None,
    key: str = DESCRIPTOR_KEY,
) -> Dict[str, Any]:
    """A Pact 4 document filing the orders descriptors under ``key``.

    Args:
        interactions: The interactions.
        descriptors: The base64 ``protoDescriptors`` to file (default: the orders file).
        key: The descriptor key to file them under.

    Returns:
        The pact document.
    """
    encoded = (
        descriptors
        if descriptors is not None
        else base64.b64encode(orders_descriptor_set().SerializeToString()).decode("ascii")
    )
    return {
        "consumer": {"name": "orders-web"},
        "provider": {"name": "orders-grpc"},
        "interactions": copy.deepcopy(interactions),
        "metadata": {
            "pactSpecification": {"version": "4.0"},
            "plugins": [
                {
                    "name": "protobuf",
                    "version": "0.5.4",
                    "configuration": {key: {"protoDescriptors": encoded, "protoFile": 'syntax = "proto2";'}},
                }
            ],
        },
    }


def graphql_interaction(
    description: str = "a user by id",
    *,
    query: str = "query UserById($id: ID!) { user(id: $id) { id name } }",
    variables: Optional[Dict[str, Any]] = None,
    operation_name: Optional[str] = "UserById",
    response_body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A GraphQL-over-HTTP interaction, the shape pact-js ``GraphQLInteraction`` writes.

    Args:
        description: The interaction's description.
        query: The GraphQL document.
        variables: Its variables (default ``{"id": "7"}``).
        operation_name: The ``operationName`` member, or ``None`` to leave it out.
        response_body: The recorded response body.

    Returns:
        The Pact 3 HTTP interaction.
    """
    body: Dict[str, Any] = {"query": query, "variables": variables if variables is not None else {"id": "7"}}
    if operation_name is not None:
        body["operationName"] = operation_name
    return {
        "description": description,
        "request": {
            "method": "POST",
            "path": "/graphql",
            "headers": {"Content-Type": "application/json"},
            "body": body,
        },
        "response": {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "body": response_body if response_body is not None else {"data": {"user": {"id": "7", "name": "Ada"}}},
        },
    }
