"""Connect-RPC ``FileDescriptorSet`` → canonical model normalizer — MFI-12.2 / MFI-19.5.

Connect-RPC speaks a Protobuf service contract (the same ``.proto`` surface gRPC uses), so this
normalizer delegates to :class:`app.proto_normalizer.ProtoNormalizer` and re-labels the emitted
:class:`~app.canonical_model.CanonicalApi` as ``connectrpc``. The canonical RPC shape is
identical; the persisted ``format`` / provenance differ so catalog items imported as Connect stay
distinct from generic gRPC/Protobuf imports.

What Connect adds on top of gRPC is a fixed HTTP/JSON transcoding (MFI-19.5): every method is
served as ``POST /{package.Service}/{Method}`` on the HTTP listener, with JSON or binary protobuf
bodies for unary calls and the Connect streaming envelope for streams. That binding is recorded on
each operation as ``extras["http"]`` — the shape :mod:`app.projection` honours, so an OpenAPI
conversion of a Connect item uses the real route instead of synthesizing one — and the content
types under ``extras["connect"]``. The API-level ``extras["connect"]`` names the route template
and ``extras["rpc_stack"]`` tags the protocol facet.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .canonical_model import ApiParadigm, CanonicalApi, Operation, Service, StreamingMode
from .normalizer import Normalizer, normalize_ordering
from .proto_normalizer import ProtoNormalizer

__all__ = [
    "CONNECT_ROUTE_TEMPLATE",
    "CONNECT_STREAMING_CONTENT_TYPES",
    "CONNECT_UNARY_CONTENT_TYPES",
    "ConnectRpcNormalizer",
    "connect_route",
]

_FORMAT_KEY = "connectrpc"

#: How every Connect method is reached over HTTP (the Connect protocol, section "Unary requests").
CONNECT_ROUTE_TEMPLATE = "/{package.Service}/{Method}"

#: Request and response bodies a unary Connect call accepts: protobuf JSON or binary protobuf.
CONNECT_UNARY_CONTENT_TYPES = ("application/json", "application/proto")

#: The enveloped bodies a streaming Connect call uses (``application/connect+<codec>``).
CONNECT_STREAMING_CONTENT_TYPES = ("application/connect+json", "application/connect+proto")


def connect_route(service_key: str, method_name: str) -> str:
    """The Connect HTTP route of one method: ``/{package.Service}/{Method}``.

    Args:
        service_key: The canonical service key, already package-qualified (``greet.v1.GreetService``).
        method_name: The rpc method name as declared (``Greet``).

    Returns:
        The absolute route the Connect protocol serves the method on
        (``/greet.v1.GreetService/Greet``).
    """
    return f"/{service_key.strip('/')}/{method_name}"


def _bind_operation(operation: Operation, service_key: str) -> Operation:
    """Return *operation* with its Connect HTTP/JSON binding recorded in ``extras``.

    ``extras["http"]`` carries the ``{"method", "path"}`` mapping the projection reads
    (:func:`app.projection._http_binding_from_extras`), so the binding is honoured as declared
    rather than synthesized. ``extras["connect"]`` names the content types the call accepts,
    which differ between unary calls and streams.

    Args:
        operation: The operation the Protobuf normalizer produced.
        service_key: The owning service's canonical key.

    Returns:
        A copy of *operation* with the binding merged into its existing ``extras``.
    """
    streaming = operation.streaming is not StreamingMode.NONE
    extras: Dict[str, Any] = dict(operation.extras)
    extras["http"] = {"method": "post", "path": connect_route(service_key, operation.name)}
    extras["connect"] = {
        "content_types": list(
            CONNECT_STREAMING_CONTENT_TYPES if streaming else CONNECT_UNARY_CONTENT_TYPES
        ),
        "streaming": streaming,
    }
    return operation.model_copy(update={"extras": extras})


def _bind_service(service: Service) -> Service:
    """Return *service* with every operation bound to its Connect route."""
    operations: List[Operation] = [_bind_operation(op, service.key) for op in service.operations]
    return service.model_copy(update={"operations": operations})


class ConnectRpcNormalizer(Normalizer, register=True):
    """Normalize a compiled protobuf descriptor set imported as Connect-RPC."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.RPC

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map *source* through the Protobuf normalizer, then add the Connect binding.

        Args:
            source: The :class:`~app.proto_descriptor.CompiledDescriptorSet` the gRPC adapter
                compiled (Connect reuses it unchanged).
            include_raw: Whether the canonical ``raw`` bag keeps the native descriptor.

        Returns:
            The canonical model labelled ``connectrpc``: ``extras["rpc_stack"]`` is ``"connect"``,
            ``extras["connect"]`` names the route template and content types, and every operation
            carries its ``POST /{package.Service}/{Method}`` binding.
        """
        api = ProtoNormalizer().normalize(source, include_raw=include_raw)
        extras = dict(api.extras)
        extras["rpc_stack"] = "connect"
        extras["connect"] = {
            "route_template": CONNECT_ROUTE_TEMPLATE,
            "unary_content_types": list(CONNECT_UNARY_CONTENT_TYPES),
            "streaming_content_types": list(CONNECT_STREAMING_CONTENT_TYPES),
        }
        relabeled = api.model_copy(
            update={
                "format": self.format,
                "extras": extras,
                "services": [_bind_service(service) for service in api.services],
            }
        )
        return normalize_ordering(relabeled)
