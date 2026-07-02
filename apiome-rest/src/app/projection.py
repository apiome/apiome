"""Paradigm projection strategies: non-REST paradigm → OpenAPI paths — MFI-22.2 (#4003).

OpenAPI is a REST vocabulary: it describes *paths*, *HTTP verbs*, and *status-coded
responses*. A :class:`~app.canonical_model.CanonicalApi` that came from a REST source
maps onto that vocabulary one-to-one, but a model from any *other* paradigm does not
— an RPC method, a GraphQL field, an event channel, or a bare data schema has no
native path/verb/response. Each therefore needs an **explicit, documented
projection** that emits what it can and **declares what it loses**.

This module is that pluggable projection layer. A :class:`ProjectionStrategy` is
selected by :func:`get_projection` from the model's
:class:`~app.canonical_model.ApiParadigm`, and the reference
:class:`app.openapi_emitter.OpenApiEmitter` consults it — once per operation — to
resolve an operation's ``(method, path)`` binding (or to decide the operation has *no*
OpenAPI representation) and to gather any ``x-`` specification extensions and
document-level notes. Every strategy records its losses on a
:class:`~app.emitter.LossTracker` so the fidelity analyzer (MFI-22.3) can show what
each projection dropped or inferred, rather than silently discarding it.

The strategies, one per paradigm:

* **REST** (:class:`RestProjection`) — the identity projection: an operation's own
  ``http_method``/``http_path`` is used verbatim; an operation missing one gets a
  best-effort ``POST`` to a path derived from its key.
* **RPC** (:class:`RpcProjection`, gRPC/Smithy/Thrift/OpenRPC) — an ``http`` binding
  in ``extras`` (``google.api.http`` / Smithy ``http``) is honored when present; else
  a ``POST /{Service}/{Method}`` is synthesized (the gRPC-transcoding/JSON
  convention), with the input message as ``requestBody`` and the output as the
  ``200`` body. Streaming has no OpenAPI representation, so it is flagged as an
  ``x-`` extension plus a loss note.
* **Graph** (:class:`GraphProjection`, GraphQL) — a SOFA-style projection: queries →
  ``GET`` and mutations → ``POST`` under a root path, arguments → parameters;
  **subscriptions are n/a** and reported as losses.
* **Event** (:class:`EventProjection`, AsyncAPI/CloudEvents) — **explicitly
  low-fidelity**: each channel operation is documented as a *non-normative* path with
  a prominent caveat, while pub/sub action, protocol bindings, and correlation ids
  are ``n/a``. Message payloads still reach ``components.schemas``; a "schemas-only"
  mode is recommended.
* **Data-schema** (:class:`DataSchemaProjection`, Avro/Protobuf-schema/JSON-Schema/
  XSD) — **components-only** OpenAPI (types, no ``paths``) unless a service definition
  is also present, in which case its operations get a best-effort binding.

Agent descriptors (A2A/MCP) are normalized into the **RPC** paradigm (a skill/tool is
a request/response method with an input and output schema), so they are projected by
:class:`RpcProjection` and need no separate strategy.

Every strategy is **pure**: given the same model it returns equal bindings and records
equal losses, performs no I/O, and is deterministic.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar, Dict, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    Operation,
    OperationKind,
    Service,
    StreamingMode,
)
from .emitter import LossKind, LossTracker

__all__ = [
    "RouteBinding",
    "ProjectionStrategy",
    "RestProjection",
    "RpcProjection",
    "GraphProjection",
    "EventProjection",
    "DataSchemaProjection",
    "register_projection",
    "get_projection",
]

# ---------------------------------------------------------------------------
# ``x-`` specification-extension keys the projections emit. Each is a vendor
# ``x-apiome-*`` extension so it validates against the OpenAPI 3.1
# meta-schema (which permits ``^x-`` keys) while carrying the paradigm nuance
# OpenAPI itself cannot express.
# ---------------------------------------------------------------------------

#: Streaming cardinality of an RPC operation OpenAPI cannot model (on the operation).
X_STREAMING = "x-apiome-streaming"
#: The pub/sub action (publish/subscribe) an event operation carried (on the operation).
X_EVENT_ACTION = "x-apiome-event-action"
#: Document-level fidelity note for an explicitly low-fidelity projection (on the root).
X_FIDELITY = "x-apiome-fidelity"

# HTTP verbs a projection may bind an operation to; used both to validate an
# ``http`` binding found in ``extras`` and to recognize a ``google.api.http`` style
# ``{verb: path}`` mapping.
_HTTP_VERBS = frozenset(
    {"get", "put", "post", "delete", "patch", "head", "options", "trace"}
)

# Collapses whitespace runs in a synthesized path segment to a single ``_`` so a
# best-effort route stays a valid, single-token URL path (mirrors the emitter's
# former private regex).
_PATH_WS_RE = re.compile(r"\s+")

#: SOFA-style root path GraphQL operations are projected under.
GRAPHQL_ROOT_PATH = "/graphql"

#: The caveat stamped on an event projection's document-level fidelity note.
EVENT_CAVEAT = (
    "Event/message APIs project to OpenAPI only at low fidelity: each channel "
    "operation below is a non-normative documentation stub, not a callable HTTP "
    "endpoint. Pub/sub action, protocol bindings, and correlation ids have no "
    "OpenAPI representation. The message payloads are faithful in "
    "components.schemas — prefer a schemas-only consumption of this document."
)


def synth_path(key: str) -> str:
    """Derive a best-effort single-token URL path from a canonical ``key``.

    Used when an operation carries no HTTP binding: the key (e.g. ``acme.Svc.Do``)
    is turned into an absolute path (``/acme.Svc.Do``) with internal whitespace
    collapsed to ``_`` so the result is a single valid path segment.

    Args:
        key: The operation's canonical key.

    Returns:
        An absolute, single-token path derived from ``key``.
    """
    return "/" + _PATH_WS_RE.sub("_", key.strip()).lstrip("/")


def _http_binding_from_extras(operation: Operation) -> Optional[Tuple[str, str]]:
    """Extract an explicit HTTP binding from an operation's ``extras``, if any.

    Recognizes two shapes an RPC normalizer may record under ``extras["http"]``:

    * a normalized mapping ``{"method": "get", "path"|"uri": "/v1/pets/{id}"}``
      (the Smithy ``http`` trait uses ``uri``); and
    * a ``google.api.http`` style single ``{verb: path}`` mapping, e.g.
      ``{"get": "/v1/{name}"}``.

    Args:
        operation: The operation whose ``extras`` may carry an HTTP binding.

    Returns:
        A ``(method_lower, path)`` tuple when a usable binding is present, else
        ``None`` (the caller then synthesizes a binding).
    """
    http = operation.extras.get("http")
    if not isinstance(http, dict):
        return None
    method = http.get("method")
    path = http.get("path") or http.get("uri")
    if isinstance(method, str) and isinstance(path, str) and method.lower() in _HTTP_VERBS:
        return method.lower(), path
    # ``google.api.http`` style — the verb *is* the key.
    for verb in sorted(_HTTP_VERBS):
        candidate = http.get(verb)
        if isinstance(candidate, str):
            return verb, candidate
    return None


class RouteBinding(BaseModel):
    """The HTTP binding a projection resolves for one operation.

    ``from_source`` distinguishes a binding taken straight from the model (a REST
    operation's own verb/route, or an ``http`` trait on an RPC method) from one the
    projection had to synthesize — the emitter tags the synthesized case
    :attr:`~app.emitter.Provenance.INFERRED`. ``extensions`` are ``x-`` keys merged
    onto the emitted Operation Object (e.g. a streaming or event-action note).
    """

    model_config = ConfigDict(extra="forbid")

    method: str = Field(description="Lower-cased HTTP method the operation binds to.")
    path: str = Field(description="Route template the operation is emitted under.")
    from_source: bool = Field(
        description="True when method+path came from the model; False when synthesized.",
    )
    extensions: Dict[str, Any] = Field(
        default_factory=dict,
        description="``x-`` specification extensions to merge onto the operation.",
    )


class ProjectionStrategy:
    """Base projection: how one paradigm's operations map onto OpenAPI paths.

    The default behavior *is* the REST/best-effort projection — honor an operation's
    own HTTP binding, else synthesize a ``POST`` to a path derived from its key — so
    :class:`RestProjection` and :class:`DataSchemaProjection` need no overrides.
    Paradigms whose operations do not map one-to-one (:class:`RpcProjection`,
    :class:`GraphProjection`, :class:`EventProjection`) override :meth:`route`
    and/or :meth:`document_extensions` to project where they can and record their
    losses.

    A concrete strategy sets :attr:`paradigm` and self-registers with
    :func:`register_projection` via the ``register=True`` flag on
    ``__init_subclass__``. Every strategy is pure: no I/O, deterministic bindings,
    and losses recorded (not raised) on the passed :class:`~app.emitter.LossTracker`.
    """

    #: The paradigm this strategy projects; also its registry key.
    paradigm: ClassVar[ApiParadigm]

    def __init_subclass__(cls, *, register: bool = False, **kwargs: Any) -> None:
        """Optionally self-register a concrete subclass under its :attr:`paradigm`."""
        super().__init_subclass__(**kwargs)
        if register:
            register_projection(cls)

    def route(
        self, operation: Operation, service: Service, losses: LossTracker
    ) -> Optional[RouteBinding]:
        """Resolve ``operation``'s HTTP binding, or ``None`` if it has none.

        The default (REST/best-effort) resolution: an operation with both an
        ``http_method`` and an ``http_path`` uses them verbatim (``from_source``);
        otherwise a ``POST`` to :func:`synth_path` of the operation key is
        synthesized and an :attr:`~app.emitter.LossKind.INFERRED` loss is recorded.

        Returning ``None`` tells the emitter this operation has *no* OpenAPI
        representation (it is dropped from ``paths``); the strategy must record an
        :attr:`~app.emitter.LossKind.NA` loss for it first so the drop is surfaced.

        Args:
            operation: The operation to bind.
            service: The service the operation belongs to (its key names the RPC
                service for a synthesized ``/{Service}/{Method}`` route).
            losses: Tracker the strategy records inferred/n-a losses on.

        Returns:
            A :class:`RouteBinding`, or ``None`` when the operation is not
            projectable onto a path.
        """
        if operation.http_method and operation.http_path:
            return RouteBinding(
                method=operation.http_method.lower(),
                path=operation.http_path,
                from_source=True,
            )
        losses.record(
            LossKind.INFERRED,
            "synthesized-http-binding",
            f"operation {operation.key!r} carries no HTTP method/route; "
            "synthesized a POST binding",
            pointer=operation.key,
        )
        return RouteBinding(method="post", path=synth_path(operation.key), from_source=False)

    def document_extensions(
        self, api: CanonicalApi, losses: LossTracker
    ) -> Dict[str, Any]:
        """Return document-root ``x-`` extensions for this projection (default none).

        Paradigms whose whole-document fidelity warrants a caveat (currently only
        :class:`EventProjection`) override this; it may also record document-level
        losses (e.g. per-channel binding losses) on ``losses``.
        """
        return {}


# Paradigm → projection-class registry, mirroring the emitter/normalizer registries.
_REGISTRY: Dict[ApiParadigm, type[ProjectionStrategy]] = {}


def register_projection(cls: type[ProjectionStrategy]) -> type[ProjectionStrategy]:
    """Register a concrete projection class under its :attr:`ProjectionStrategy.paradigm`.

    Args:
        cls: A concrete :class:`ProjectionStrategy` subclass with a ``paradigm`` set.

    Returns:
        ``cls`` unchanged, so this doubles as a class decorator.

    Raises:
        ValueError: If ``cls`` sets no ``paradigm``, or a *different* class is
            already registered for the same paradigm (re-registering the same class
            is a no-op so module re-import is safe).
    """
    paradigm = getattr(cls, "paradigm", None)
    if paradigm is None:
        raise ValueError(f"{cls.__name__} must set a `paradigm` to register")
    existing = _REGISTRY.get(paradigm)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"paradigm {paradigm!r} already registered to {existing.__name__}; "
            f"cannot re-register to {cls.__name__}"
        )
    _REGISTRY[paradigm] = cls
    return cls


def get_projection(paradigm: ApiParadigm) -> ProjectionStrategy:
    """Return an instance of the projection strategy for ``paradigm``.

    Every :class:`ApiParadigm` has a registered strategy; the base
    :class:`ProjectionStrategy` (best-effort) is returned as a defensive fallback
    should a future paradigm be added without one.

    Args:
        paradigm: The model's paradigm.

    Returns:
        A ready-to-use :class:`ProjectionStrategy` instance.
    """
    cls = _REGISTRY.get(paradigm, ProjectionStrategy)
    return cls()


class RestProjection(ProjectionStrategy, register=True):
    """Identity projection for REST models — the default :meth:`route` suffices."""

    paradigm = ApiParadigm.REST


class DataSchemaProjection(ProjectionStrategy, register=True):
    """Data-schema projection: components-only unless a service is present.

    A pure data-schema model (Avro/Protobuf-schema/JSON-Schema/XSD) has no services,
    so no operations are projected and the emitted document is components-only. When
    a service definition *is* present, its operations get the default best-effort
    binding — the only override needed is the paradigm key.
    """

    paradigm = ApiParadigm.DATA_SCHEMA


class RpcProjection(ProjectionStrategy, register=True):
    """RPC projection (gRPC/Smithy/Thrift/OpenRPC, and A2A/MCP agent descriptors).

    A method becomes an operation. An HTTP binding declared on the method
    (``google.api.http`` / Smithy ``http``, read from ``extras``) is honored; absent
    one, a ``POST /{Service}/{Method}`` is synthesized per the gRPC-transcoding/JSON
    convention (the emitter maps the input message → ``requestBody`` and the output
    message → the ``200`` body). Streaming has no OpenAPI representation, so it is
    surfaced as an ``x-apiome-streaming`` extension plus an
    :attr:`~app.emitter.LossKind.NA` loss rather than being dropped.
    """

    paradigm = ApiParadigm.RPC

    def route(
        self, operation: Operation, service: Service, losses: LossTracker
    ) -> Optional[RouteBinding]:
        binding = _http_binding_from_extras(operation)
        if binding is not None:
            method, path = binding
            result = RouteBinding(method=method, path=path, from_source=True)
        else:
            # gRPC-transcoding convention: POST /{package.Service}/{Method}.
            path = "/" + service.key.strip("/") + "/" + operation.name
            losses.record(
                LossKind.INFERRED,
                "synthesized-http-binding",
                f"RPC method {operation.key!r} has no HTTP annotation; synthesized "
                f"POST {path} (gRPC-transcoding convention)",
                pointer=operation.key,
            )
            result = RouteBinding(method="post", path=path, from_source=False)

        if operation.streaming is not StreamingMode.NONE:
            result.extensions[X_STREAMING] = operation.streaming.value
            losses.record(
                LossKind.NA,
                "rpc-streaming",
                f"{operation.streaming.value} streaming on {operation.key!r} has no "
                f"OpenAPI representation; surfaced via {X_STREAMING}",
                pointer=operation.key,
            )
        return result


class GraphProjection(ProjectionStrategy, register=True):
    """GraphQL projection (SOFA-style): queries → ``GET``, mutations → ``POST``.

    A query or mutation field is projected under :data:`GRAPHQL_ROOT_PATH` with its
    arguments as parameters (the emitter renders the canonical
    :class:`~app.canonical_model.Parameter`\\s). A **subscription has no OpenAPI
    representation** — it is not emitted and is reported as an
    :attr:`~app.emitter.LossKind.NA` loss.
    """

    paradigm = ApiParadigm.GRAPH

    def route(
        self, operation: Operation, service: Service, losses: LossTracker
    ) -> Optional[RouteBinding]:
        if operation.kind is OperationKind.SUBSCRIPTION:
            losses.record(
                LossKind.NA,
                "graphql-subscription",
                f"GraphQL subscription {operation.key!r} has no OpenAPI "
                "representation and is not emitted",
                pointer=operation.key,
            )
            return None

        method = "get" if operation.kind is OperationKind.QUERY else "post"
        path = f"{GRAPHQL_ROOT_PATH}/{operation.name}"
        losses.record(
            LossKind.INFERRED,
            "synthesized-http-binding",
            f"GraphQL {operation.kind.value} {operation.key!r} projected as "
            f"{method.upper()} {path} (SOFA-style)",
            pointer=operation.key,
        )
        return RouteBinding(method=method, path=path, from_source=False)


class EventProjection(ProjectionStrategy, register=True):
    """Event projection (AsyncAPI/CloudEvents): explicitly low-fidelity.

    Each pub/sub operation is documented as a *non-normative* path (a ``POST`` to the
    bound channel address) carrying an ``x-apiome-event-action`` note, so the
    channel topology is visible; the message payloads remain faithful in
    ``components.schemas``. The pub/sub action itself, per-channel protocol bindings,
    and correlation ids have no OpenAPI representation and are recorded as
    :attr:`~app.emitter.LossKind.NA` losses. A document-level fidelity caveat
    (:data:`EVENT_CAVEAT`) recommends schemas-only consumption.
    """

    paradigm = ApiParadigm.EVENT

    def route(
        self, operation: Operation, service: Service, losses: LossTracker
    ) -> Optional[RouteBinding]:
        path = self._event_path(operation)
        losses.record(
            LossKind.NA,
            "event-pubsub-action",
            f"pub/sub action {operation.kind.value!r} on {operation.key!r} is "
            "non-normative in OpenAPI; the path below is documentation only",
            pointer=operation.key,
        )
        return RouteBinding(
            method="post",
            path=path,
            from_source=False,
            extensions={X_EVENT_ACTION: operation.kind.value},
        )

    @staticmethod
    def _event_path(operation: Operation) -> str:
        """Derive a unique, readable documentation path for an event operation.

        When the operation is bound to a channel, the path is the channel address
        (readable) plus the operation name as a trailing segment, so several
        operations on the *same* channel (a publish and a subscribe, say) get
        distinct paths instead of silently colliding on one ``POST /{channel}``.
        Absent a channel binding, the operation key — already unique — is used.
        """
        if operation.channel_ref:
            base = synth_path(operation.channel_ref)
            if operation.name:
                return f"{base}/{_PATH_WS_RE.sub('_', operation.name.strip())}"
            return base
        return synth_path(operation.key)

    def document_extensions(
        self, api: CanonicalApi, losses: LossTracker
    ) -> Dict[str, Any]:
        for channel in sorted(api.channels, key=lambda c: c.key):
            if channel.bindings:
                losses.record(
                    LossKind.NA,
                    "event-channel-bindings",
                    f"protocol bindings on channel {channel.key!r} have no OpenAPI "
                    "representation",
                    pointer=channel.key,
                )
        return {
            X_FIDELITY: {
                "paradigm": ApiParadigm.EVENT.value,
                "fidelity": "low",
                "recommended-mode": "schemas-only",
                "caveat": EVENT_CAVEAT,
            }
        }
