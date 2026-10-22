"""tRPC routers → canonical model normalizer — FMT-8.3 (#5464).

Maps a :class:`~app.trpc_parser.TrpcDocument` onto a :class:`~app.canonical_model.CanonicalApi`
with the :attr:`~app.canonical_model.ApiParadigm.RPC` paradigm.

**Procedures become operations.** Each procedure is an :class:`~app.canonical_model.Operation`
whose kind is its tRPC kind — ``query`` → ``QUERY``, ``mutation`` → ``MUTATION``,
``subscription`` → ``SUBSCRIPTION`` (server-streaming) — and whose ``trpc_path`` is the dotted
path a tRPC client calls (``invoice.list``).

**Routers become services, nested as tRPC nests them.** Every router node — the exported router
and each nested ``t.router({…})`` beneath it — is a :class:`~app.canonical_model.Service` keyed
by its path (``appRouter``, ``appRouter.invoice``, ``appRouter.admin.users``) that records its
parent in ``trpc_parent``, so the hierarchy survives the canonical model's flat service list.
An operation's key is its service key plus its name, the canonical RPC coordinate.

**Schemas resolve through the FMT-8.2 Zod path.** A procedure's input (several chained
``.input()`` calls merge into one object, as tRPC merges them) and output are the JSON Schema
the Zod extractor produced, translated by :func:`app.zod_normalizer.translate_schema` and built
by the shared FMT-8.1 model — so constraints, unions, recursion and declared limits behave
exactly as they do for a Zod import. An input or output that *is* a named schema references
that schema's type; one written inline becomes a type named after the procedure
(``InvoiceListInput``). A hand-written validator has no schema: the operation is kept, its
payload is not, and the gap is declared (``trpc.non_schema_input``) rather than presented as an
empty body. Middleware-derived context is never read, so it can never become a request field.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    StreamingMode,
    TypeRef,
)
from .normalizer import Keys, Normalizer, normalize_ordering
from .trpc_parser import TrpcDocument, trpc_limit_recorder
from .typescript_types_normalizer import _limits_payload, _Model, _sanitize
from .typescript_types_parser import TsDocument
from .zod_normalizer import translate_schema

__all__ = ["TRPC_EXTRAS_KEY", "TRPC_FORMAT", "TrpcNormalizer"]

#: The format key the normalizer registers under.
TRPC_FORMAT = "trpc"

#: The key the projection record sits under in ``CanonicalApi.extras``.
TRPC_EXTRAS_KEY = "trpc"

#: The id prefix of a named schema's declaration (shared with the Zod translation's ``$ref``s).
_SCHEMA_ID_PREFIX = "zod#"

#: The id prefix of a procedure's synthetic input/output declaration.
_IO_ID_PREFIX = "trpc#"

#: tRPC procedure kind → canonical operation kind.
_KINDS: Dict[str, OperationKind] = {
    "query": OperationKind.QUERY,
    "mutation": OperationKind.MUTATION,
    "subscription": OperationKind.SUBSCRIPTION,
}


def _pascal(path: str) -> str:
    """``invoice.list`` → ``InvoiceList``: a readable type-name stem for a procedure."""
    parts = [_sanitize(part) for part in path.replace("-", ".").split(".") if part]
    return "".join(part[:1].upper() + part[1:] for part in parts) or "Procedure"


def _payload_schema(nodes: List[Any]) -> Optional[Dict[str, Any]]:
    """Combine a procedure's schema-backed inputs into one schema (chained inputs merge)."""
    schemas = [node for node in nodes if isinstance(node, dict)]
    if not schemas:
        return None
    if len(schemas) == 1:
        return schemas[0]
    return {"allOf": schemas}


def _declaration(
    declaration_id: str, name: str, schema: Dict[str, Any], *, exported: bool
) -> Dict[str, Any]:
    """A declaration FMT-8.1's model builder reads, holding one translated schema."""
    description = schema.get("description")
    return {
        "id": declaration_id,
        "name": name,
        "module": "",
        "line": None,
        "exported": exported,
        "doc": description if isinstance(description, str) else None,
        "deprecated": False,
        "typeParameters": [],
        "mergedDeclarations": 1,
        "kind": "alias",
        "type": translate_schema(schema),
    }


class _Payloads:
    """Resolves each procedure's input and output schema to a canonical type reference."""

    def __init__(self, document: TrpcDocument) -> None:
        self.document = document
        self.declarations: List[Dict[str, Any]] = [
            _declaration(f"{_SCHEMA_ID_PREFIX}{name}", name, schema, exported=False)
            for name, schema in document.definitions.items()
            if isinstance(schema, dict)
        ]
        #: (procedure path, "Input" | "Output") → the schema, or the ``$ref`` name it points at.
        self.pending: Dict[Tuple[str, str], Tuple[str, str]] = {}

    def plan(self, path: str, role: str, schema: Optional[Dict[str, Any]], *, stem: str) -> None:
        """Register one payload: a named schema is referenced, an inline one gets a type.

        Args:
            path: The procedure's router-qualified path (the payload's identity).
            role: ``"Input"`` or ``"Output"``.
            schema: The payload schema, or ``None`` when the procedure has none.
            stem: The procedure path the type is named after (``invoice.list`` →
                ``InvoiceListInput``).
        """
        if schema is None:
            return
        ref = schema.get("$ref")
        if isinstance(ref, str) and set(schema) <= {"$ref", "x-zod-limits", "description"}:
            name = ref.rsplit("/", 1)[-1]
            self.pending[(path, role)] = ("ref", name)
            return
        name = f"{_pascal(stem)}{role}"
        self.declarations.append(
            _declaration(f"{_IO_ID_PREFIX}{path}#{role}", name, schema, exported=True)
        )
        self.pending[(path, role)] = ("type", name)


class TrpcNormalizer(Normalizer, register=True):
    """Normalize parsed tRPC routers into a :class:`CanonicalApi`."""

    format = TRPC_FORMAT
    paradigm = ApiParadigm.RPC

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map a :class:`~app.trpc_parser.TrpcDocument` to the canonical model.

        Args:
            source: The parsed document.
            include_raw: Whether to keep the module sources and the extracted routers on ``raw``.

        Returns:
            The canonical model: one ``rpc`` API whose services are the router hierarchy.

        Raises:
            ValueError: When ``source`` is not a :class:`TrpcDocument`.
        """
        if not isinstance(source, TrpcDocument):
            raise ValueError("tRPC source must be a TrpcDocument (see app.trpc_parser.parse_trpc)")

        limits = trpc_limit_recorder()
        payloads = _Payloads(source)
        procedures: List[Tuple[str, Dict[str, Any]]] = []
        # One exported router is the common case, and its name adds nothing to a type name; with
        # several, the router name keeps `ping` in one from colliding with `ping` in another.
        qualify = len(source.routers) > 1
        for router in source.routers:
            for procedure in router.get("procedures") or []:
                path = str(procedure.get("path"))
                inputs = list(procedure.get("inputs") or [])
                schema_inputs = [
                    n for n in inputs if isinstance(n, dict) and "x-trpc-unsupported" not in n
                ]
                for node in inputs:
                    if isinstance(node, dict) and "x-trpc-unsupported" in node:
                        limits.record(
                            node["x-trpc-unsupported"], location=f"{router['name']}.{path}"
                        )
                output = procedure.get("output")
                if isinstance(output, dict) and "x-trpc-unsupported" in output:
                    limits.record(output["x-trpc-unsupported"], location=f"{router['name']}.{path}")
                    output = None
                full = f"{router['name']}.{path}"
                stem = full if qualify else path
                payloads.plan(full, "Input", _payload_schema(schema_inputs), stem=stem)
                payloads.plan(
                    full, "Output", output if isinstance(output, dict) else None, stem=stem
                )
                procedures.append((router["name"], procedure))
            for lazy in router.get("lazy") or []:
                limits.record("trpc.lazy_router", location=f"{router['name']}.{lazy}")

        projection = TsDocument(
            root=source.root,
            files=source.files,
            typescript_version="",
            declarations=tuple(payloads.declarations),
            sources={},
        )
        model = _Model(projection, limits)
        for (path, role), (kind, type_name) in payloads.pending.items():
            # FMT-8.6: an inline payload is declared by the procedure, but the named type that
            # holds it is Apiome's — the source never wrote `InvoiceListInput`.
            if kind == "type":
                model.mark_synthesized(
                    type_name, f"Named by Apiome after the {role.lower()} of procedure {path}."
                )
        for declaration in projection.exported():
            model.reserve(declaration["name"])
        for declaration in projection.exported():
            model.declare_exported(declaration)

        def payload_ref(path: str, role: str) -> Optional[TypeRef]:
            planned = payloads.pending.get((path, role))
            if planned is None:
                return None
            kind, name = planned
            if kind == "ref":
                key = model.ensure(
                    f"{_SCHEMA_ID_PREFIX}{name}", (), location=f"{path}#{role.lower()}"
                )
            else:
                key = Keys.type(name) if Keys.type(name) in model.types else None
            return TypeRef(name=key, nullable=False) if key else None

        services = self._services(source, procedures, payload_ref)
        name = source.routers[0]["name"]
        trpc: Dict[str, Any] = {
            "root_module": source.root,
            "modules": list(source.files),
            "routers": [router["name"] for router in source.routers],
            "procedures": sum(len(router.get("procedures") or []) for router in source.routers),
            "capability_limits": _limits_payload(limits.limits()),
        }
        raw: Optional[Dict[str, Any]] = None
        if include_raw:
            raw = {
                "trpc": dict(source.sources),
                "routers": list(source.routers),
                "json_schema": source.schema,
            }

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol="trpc",
            identity=ApiIdentity(name=name),
            title=name,
            services=services,
            types=model.stamped_types(),
            raw=raw,
            extras={TRPC_EXTRAS_KEY: trpc},
        )
        return normalize_ordering(api)

    @staticmethod
    def _services(
        source: TrpcDocument,
        procedures: List[Tuple[str, Dict[str, Any]]],
        payload_ref: Any,
    ) -> List[Service]:
        """Build one service per router node, each holding the procedures directly beneath it."""
        services: Dict[str, Service] = {}

        def service_for(router: str, prefix: Tuple[str, ...]) -> Service:
            key = ".".join((router, *prefix))
            if key not in services:
                parent = ".".join((router, *prefix[:-1])) if prefix else None
                if parent is not None:
                    service_for(router, prefix[:-1])
                services[key] = Service(
                    key=key,
                    name=prefix[-1] if prefix else router,
                    extras={
                        "trpc_router": ".".join(prefix),
                        **({"trpc_parent": parent} if parent else {}),
                    },
                )
            return services[key]

        for router in source.routers:
            service_for(router["name"], ())
        for router_name, procedure in procedures:
            path = str(procedure.get("path"))
            segments = tuple(path.split("."))
            service = service_for(router_name, segments[:-1])
            full = f"{router_name}.{path}"
            op_key = Keys.operation_rpc(service.key, segments[-1])
            kind = _KINDS.get(str(procedure.get("type")), OperationKind.QUERY)
            messages: List[Message] = []
            request = payload_ref(full, "Input")
            if request is not None:
                messages.append(
                    Message(
                        key=Keys.request_message(op_key),
                        role=MessageRole.REQUEST,
                        payload=request,
                        required=True,
                    )
                )
            response = payload_ref(full, "Output")
            if response is not None:
                role = (
                    MessageRole.EVENT
                    if kind is OperationKind.SUBSCRIPTION
                    else MessageRole.RESPONSE
                )
                messages.append(Message(key=f"{op_key}#response", role=role, payload=response))
            extras: Dict[str, Any] = {"trpc_path": path}
            if procedure.get("meta") is not None:
                extras["trpc_meta"] = procedure["meta"]
            operation = Operation(
                key=op_key,
                name=segments[-1],
                kind=kind,
                streaming=StreamingMode.SERVER
                if kind is OperationKind.SUBSCRIPTION
                else StreamingMode.NONE,
                messages=messages,
                extras=extras,
            )
            services[service.key] = service.model_copy(
                update={"operations": [*service.operations, operation]}
            )
        return list(services.values())
