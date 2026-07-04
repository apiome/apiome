"""Reference normalizer: OpenAPI → canonical model — MFI-2.3 (#3740).

The reference implementation of the :class:`app.normalizer.Normalizer` SPI. It
maps a parsed **OpenAPI 3.0 / 3.1 / 3.2** document (a ``dict``, already ``$ref``-merged
for any *remote* refs — local ``#/components/schemas`` refs are preserved as
keyed references) into a :class:`~app.canonical_model.CanonicalApi`:

* ``info`` → :class:`~app.canonical_model.ApiIdentity` + title/version/description;
* ``servers`` → :class:`~app.canonical_model.Server` (URL templates + variables);
* ``components.schemas`` → :class:`~app.canonical_model.Type` (via
  :class:`app.normalizer.SchemaCoercer`, which reuses the JSON-Schema vocabulary —
  OpenAPI 3.1 schemas *are* JSON Schema);
* ``paths`` → :class:`~app.canonical_model.Operation` (one per path+method),
  grouped into :class:`~app.canonical_model.Service` by their first ``tag``;
* parameters → :class:`~app.canonical_model.Parameter`; ``requestBody`` and each
  ``responses`` entry → :class:`~app.canonical_model.Message`.

Every entity is keyed via :class:`app.normalizer.Keys` so the output diffs by
identity, and the whole model is run through
:func:`app.normalizer.normalize_ordering` before return so it is byte-stable
regardless of how the source orders its paths and schemas. The normalizer is pure
(no I/O); it is the inverse, eventually, of the MFI-22.1 ``OpenApiEmitter``.

This module *self-registers* three format keys — ``openapi-3.0``, ``openapi-3.1``,
and ``openapi-3.2`` — so :func:`app.normalizer.get_normalizer` resolves an OpenAPI
document to this class.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Server,
    ServerVariable,
    Service,
)
from .normalizer import Keys, Normalizer, SchemaCoercer, coerce_constraints, normalize_ordering

__all__ = ["OpenApiNormalizer"]

# The HTTP methods an OpenAPI Path Item may carry, lower-cased as they appear in
# the document. ``trace`` is included for completeness (rare but valid). OpenAPI
# 3.2 adds ``query`` (the QUERY HTTP method) as a first-class operation key.
_HTTP_METHODS: Tuple[str, ...] = (
    "get",
    "put",
    "post",
    "delete",
    "options",
    "head",
    "patch",
    "trace",
    "query",
)

# OpenAPI parameter ``in`` value → canonical :class:`ParameterLocation`.
_PARAM_LOCATIONS: Dict[str, ParameterLocation] = {
    "path": ParameterLocation.PATH,
    "query": ParameterLocation.QUERY,
    "header": ParameterLocation.HEADER,
    "cookie": ParameterLocation.COOKIE,
}

# Service key used for operations that declare no tag, so every operation lives
# under exactly one service.
_DEFAULT_SERVICE = "default"


class OpenApiNormalizer(Normalizer, register=True):
    """Normalize a parsed OpenAPI 3.x document into a :class:`CanonicalApi`.

    Self-registers under ``openapi-3.1``; :class:`_OpenApi30Normalizer` adds the
    ``openapi-3.0`` alias. Both versions share this one implementation.
    """

    format = "openapi-3.1"  # registry key reported on the produced model
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a parsed OpenAPI document.

        Args:
            source: The parsed OpenAPI document as a ``dict`` (the object a YAML/
                JSON loader produces). Local ``$ref``s into
                ``#/components/schemas`` are kept as references by name; remote
                refs are expected to have been merged in by the parser.
            include_raw: When ``True`` the source document is preserved on
                :attr:`CanonicalApi.raw` for full-fidelity round-tripping.

        Returns:
            The order-normalized :class:`CanonicalApi`. ``format`` reflects the
            document's declared OpenAPI version (``openapi-3.0`` / ``openapi-3.1`` /
            ``openapi-3.2``).

        Raises:
            ValueError: If ``source`` is not a mapping or is not an OpenAPI 3.x
                document (no ``openapi: 3.x`` version string).
        """
        if not isinstance(source, dict):
            raise ValueError("OpenAPI source must be a parsed mapping (dict)")
        format_key = self._detect_format(source)

        info = source.get("info") or {}
        components = (source.get("components") or {}).get("schemas") or {}
        coercer = SchemaCoercer(components=components)

        tag_metadata = self._tag_hierarchy(source.get("tags") or [])
        extras: Dict[str, Any] = {}
        if tag_metadata:
            extras["tagHierarchy"] = tag_metadata

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=format_key,
            protocol="http",
            identity=ApiIdentity(name=info.get("title") or "Untitled API"),
            version=info.get("version"),
            title=info.get("title"),
            description=info.get("description"),
            servers=self._servers(source.get("servers") or []),
            services=self._services(source, coercer),
            types=coercer.named_types_from_components(),
            raw=source if include_raw else None,
            extras=extras,
        )
        return normalize_ordering(api)

    # --- format detection ---------------------------------------------------

    @staticmethod
    def _detect_format(source: Dict[str, Any]) -> str:
        """Return the canonical format key for the document's OpenAPI version.

        Args:
            source: The parsed document.

        Returns:
            ``openapi-3.0``, ``openapi-3.1``, or ``openapi-3.2`` (newer 3.x minors
            without a dedicated key normalize under ``openapi-3.2``).

        Raises:
            ValueError: If the document has no ``openapi: 3.x`` version string.
        """
        version = source.get("openapi")
        if not isinstance(version, str) or not version.startswith("3."):
            raise ValueError(
                "not an OpenAPI 3.x document (missing or unsupported `openapi` version)"
            )
        if version.startswith("3.0"):
            return "openapi-3.0"
        if version.startswith("3.1"):
            return "openapi-3.1"
        if version.startswith("3.2"):
            return "openapi-3.2"
        return "openapi-3.2"

    # --- servers ------------------------------------------------------------

    @staticmethod
    def _servers(servers: List[Dict[str, Any]]) -> List[Server]:
        """Coerce the document's ``servers`` array into canonical :class:`Server`s."""
        result: List[Server] = []
        for entry in servers:
            if not isinstance(entry, dict) or "url" not in entry:
                continue
            variables = [
                ServerVariable(
                    name=name,
                    default=spec.get("default"),
                    enum=spec.get("enum"),
                    description=spec.get("description"),
                )
                for name, spec in (entry.get("variables") or {}).items()
                if isinstance(spec, dict)
            ]
            result.append(
                Server(
                    url=entry["url"],
                    description=entry.get("description"),
                    variables=variables,
                )
            )
        return result

    @staticmethod
    def _tag_hierarchy(tags: List[Any]) -> Dict[str, Dict[str, Any]]:
        """Collect OpenAPI 3.2 hierarchical tag metadata keyed by tag name."""
        result: Dict[str, Dict[str, Any]] = {}
        for tag in tags:
            if not isinstance(tag, dict) or "name" not in tag:
                continue
            meta: Dict[str, Any] = {}
            for key in ("parent", "summary", "kind"):
                if tag.get(key) is not None:
                    meta[key] = tag[key]
            if meta:
                result[str(tag["name"])] = meta
        return result

    @staticmethod
    def _path_operations(item: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
        """Return every operation on a path item as ``(method, op_obj)`` pairs.

        Includes standard HTTP methods, the OpenAPI 3.2 ``query`` operation key,
        and any custom methods declared under ``additionalOperations``.
        """
        result: List[Tuple[str, Dict[str, Any]]] = []
        for method in _HTTP_METHODS:
            op_obj = item.get(method)
            if isinstance(op_obj, dict):
                result.append((method, op_obj))
        additional = item.get("additionalOperations")
        if isinstance(additional, dict):
            for method, op_obj in additional.items():
                if isinstance(method, str) and isinstance(op_obj, dict):
                    result.append((method.lower(), op_obj))
        return result

    # --- services / operations ---------------------------------------------

    def _services(
        self, source: Dict[str, Any], coercer: SchemaCoercer
    ) -> List[Service]:
        """Build operations from ``paths`` and group them into services by tag.

        Args:
            source: The parsed document.
            coercer: The shared :class:`SchemaCoercer` for payload/parameter types.

        Returns:
            One :class:`Service` per distinct first-tag (and a ``default`` service
            for untagged operations), each holding its operations. Tag
            descriptions from the top-level ``tags`` array are attached when present.
        """
        tag_descriptions = {
            t["name"]: t.get("description")
            for t in (source.get("tags") or [])
            if isinstance(t, dict) and "name" in t
        }
        by_service: Dict[str, List[Operation]] = {}

        for path, item in (source.get("paths") or {}).items():
            if not isinstance(item, dict):
                continue
            # Path-level parameters are shared by every method on the path.
            shared_params = item.get("parameters") or []
            for method, op_obj in self._path_operations(item):
                operation = self._operation(method, path, op_obj, shared_params, coercer)
                service_key = operation.tags[0] if operation.tags else _DEFAULT_SERVICE
                by_service.setdefault(service_key, []).append(operation)

        return [
            Service(
                key=key,
                name=key,
                description=tag_descriptions.get(key),
                operations=ops,
            )
            for key, ops in by_service.items()
        ]

    def _operation(
        self,
        method: str,
        path: str,
        op_obj: Dict[str, Any],
        shared_params: List[Dict[str, Any]],
        coercer: SchemaCoercer,
    ) -> Operation:
        """Coerce one ``paths[path][method]`` Operation Object.

        Args:
            method: HTTP method (lower-case, as it appears in the document).
            path: Route template, e.g. ``/pets/{id}``.
            op_obj: The OpenAPI Operation Object.
            shared_params: Path-level parameters merged in (operation-level
                parameters of the same name+location override these).
            coercer: The shared :class:`SchemaCoercer`.

        Returns:
            The canonical :class:`Operation`, with parameters, request/response
            messages, tags, and ``operationId``/``summary`` preserved in ``extras``.
        """
        op_key = Keys.operation_http(method, path)
        tags = [t for t in (op_obj.get("tags") or []) if isinstance(t, str)]

        extras: Dict[str, Any] = {}
        if op_obj.get("operationId"):
            extras["operationId"] = op_obj["operationId"]
        if op_obj.get("summary"):
            extras["summary"] = op_obj["summary"]

        return Operation(
            key=op_key,
            name=op_obj.get("operationId") or op_key,
            kind=OperationKind.REQUEST_RESPONSE,
            description=op_obj.get("description") or op_obj.get("summary"),
            deprecated=bool(op_obj.get("deprecated", False)),
            http_method=method.upper(),
            http_path=path,
            parameters=self._parameters(op_key, op_obj, shared_params, coercer),
            messages=self._messages(op_key, op_obj, coercer),
            tags=tags,
            extras=extras,
        )

    @staticmethod
    def _merge_parameters(
        shared: List[Dict[str, Any]], own: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Merge path-level and operation-level parameters.

        Per the OpenAPI spec an operation-level parameter overrides a path-level
        one with the same ``name`` + ``in``. Returns the effective parameter list.
        """
        merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for param in list(shared) + list(own):
            if isinstance(param, dict) and "name" in param and "in" in param:
                merged[(param["name"], param["in"])] = param
        return list(merged.values())

    def _parameters(
        self,
        op_key: str,
        op_obj: Dict[str, Any],
        shared_params: List[Dict[str, Any]],
        coercer: SchemaCoercer,
    ) -> List[Parameter]:
        """Coerce an operation's effective parameters into canonical :class:`Parameter`s."""
        result: List[Parameter] = []
        for param in self._merge_parameters(shared_params, op_obj.get("parameters") or []):
            location = _PARAM_LOCATIONS.get(param["in"])
            if location is None:
                continue  # unknown `in` value — skip rather than mis-model
            schema = param.get("schema") if isinstance(param.get("schema"), dict) else {}
            # Path parameters are always required per the spec.
            required = bool(param.get("required", False)) or location is ParameterLocation.PATH
            result.append(
                Parameter(
                    key=Keys.parameter(op_key, location.value, param["name"]),
                    name=param["name"],
                    location=location,
                    type=coercer.type_ref(schema, required=required),
                    required=required,
                    default=schema.get("default"),
                    constraints=coerce_constraints(schema),
                    description=param.get("description"),
                    deprecated=bool(param.get("deprecated", False)),
                )
            )
        return result

    def _messages(
        self, op_key: str, op_obj: Dict[str, Any], coercer: SchemaCoercer
    ) -> List[Message]:
        """Coerce an operation's ``requestBody`` and ``responses`` into messages."""
        messages: List[Message] = []

        request_body = op_obj.get("requestBody")
        if isinstance(request_body, dict):
            content_types, schema = self._select_content(request_body.get("content"))
            payload, payload_schema = self._payload(schema, coercer)
            messages.append(
                Message(
                    key=Keys.request_message(op_key),
                    role=MessageRole.REQUEST,
                    payload=payload,
                    payload_schema=payload_schema,
                    content_types=content_types,
                    description=request_body.get("description"),
                )
            )

        for status_code, response in (op_obj.get("responses") or {}).items():
            if not isinstance(response, dict):
                continue
            content_types, schema = self._select_content(response.get("content"))
            payload, payload_schema = self._payload(schema, coercer)
            messages.append(
                Message(
                    key=Keys.response_message(op_key, str(status_code)),
                    role=self._response_role(str(status_code)),
                    payload=payload,
                    payload_schema=payload_schema,
                    headers=self._headers(response.get("headers"), op_key, status_code, coercer),
                    content_types=content_types,
                    status_code=str(status_code),
                    description=response.get("description"),
                )
            )

        return messages

    @staticmethod
    def _response_role(status_code: str) -> MessageRole:
        """Classify a response status code as a success RESPONSE or an ERROR.

        ``4XX``/``5XX`` (and their wildcard ranges) are errors; everything else —
        ``1XX``/``2XX``/``3XX`` and ``default`` — is a success/normal response.
        """
        return MessageRole.ERROR if status_code[:1] in {"4", "5"} else MessageRole.RESPONSE

    @staticmethod
    def _select_content(
        content: Optional[Dict[str, Any]],
    ) -> Tuple[List[str], Dict[str, Any]]:
        """Pick a representative schema from a ``content`` map + list its media types.

        JSON media types are preferred for the representative schema (most APIs are
        JSON-first); otherwise the alphabetically-first media type is used, so the
        choice is deterministic. All media types are returned as ``content_types``.

        Returns:
            ``(content_types, schema)`` where ``schema`` is the chosen media type's
            schema (``{}`` when there is no content).
        """
        if not isinstance(content, dict) or not content:
            return [], {}
        content_types = sorted(content)
        json_types = [ct for ct in content_types if "json" in ct.lower()]
        chosen = json_types[0] if json_types else content_types[0]
        media = content.get(chosen) or {}
        schema = media.get("schema") if isinstance(media, dict) else {}
        return content_types, schema if isinstance(schema, dict) else {}

    @staticmethod
    def _payload(
        schema: Dict[str, Any], coercer: SchemaCoercer
    ) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        """Resolve a body schema to either a named payload ref or an inline schema.

        A ``$ref``, array, or scalar body becomes a :class:`TypeRef` payload (a
        reference by key / a typed wrapper); an inline object body with no name is
        kept verbatim as ``payload_schema`` so nothing is lost.

        Returns:
            ``(payload, payload_schema)`` — exactly one is non-``None`` for a
            non-empty body; both are ``None`` for an empty body.
        """
        if not schema:
            return None, None
        type_ = schema.get("type")
        is_typed_use_site = (
            "$ref" in schema
            or type_ in {"array", "string", "number", "integer", "boolean"}
            or isinstance(type_, list)  # OpenAPI 3.1 ["T", "null"] form
        )
        if is_typed_use_site:
            return coercer.type_ref(schema, required=True), None
        # Inline object (or other inline shape) — preserve the raw schema.
        return None, schema

    @staticmethod
    def _headers(
        headers: Optional[Dict[str, Any]],
        op_key: str,
        status_code: Any,
        coercer: SchemaCoercer,
    ) -> List[CanonicalField]:
        """Coerce a response's ``headers`` map into header fields on the message."""
        if not isinstance(headers, dict):
            return []
        msg_key = Keys.response_message(op_key, str(status_code))
        result: List[CanonicalField] = []
        for name, spec in headers.items():
            if not isinstance(spec, dict):
                continue
            schema = spec.get("schema") if isinstance(spec.get("schema"), dict) else {}
            result.append(
                CanonicalField(
                    key=Keys.field(msg_key, name),
                    name=name,
                    type=coercer.type_ref(schema, required=bool(spec.get("required", False))),
                    constraints=coerce_constraints(schema),
                    description=spec.get("description"),
                    deprecated=bool(spec.get("deprecated", False)),
                )
            )
        return result


class _OpenApi32Normalizer(OpenApiNormalizer, register=True):
    """Alias registration of :class:`OpenApiNormalizer` under the ``openapi-3.2`` key."""

    format = "openapi-3.2"


class _OpenApi30Normalizer(OpenApiNormalizer, register=True):
    """Alias registration of :class:`OpenApiNormalizer` under the ``openapi-3.0`` key.

    OpenAPI 3.0 and 3.1 share one normalizer (the coercer accepts both the 3.0
    ``nullable``/boolean-``exclusiveMinimum`` forms and the 3.1 JSON-Schema
    forms); this thin subclass only changes the registry key.
    """

    format = "openapi-3.0"
