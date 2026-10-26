"""AMF JSON-LD model → :class:`~app.raml_parser.RamlDocument` — MFI-15.1 (#3799).

AMF's ``parse`` output is a JSON-LD graph (compacted, with source maps). The pieces this
mapper reads:

* the root ``doc:Document`` (``doc:root: true``): what it ``doc:encodes`` (the
  ``apiContract:WebAPI``) and the shapes it ``doc:declares`` (the root's ``types``, including
  any pulled in with ``!include``);
* each library ``doc:Module``: the shapes it declares, named ``<alias>.<Type>`` with the alias
  taken from the root's ``sourcemaps:aliases-array`` (``alias->…#/references/N::…``);
* the WebAPI's endpoints, operations, parameters, requests, responses and payloads.

In AMF's transformed model a use of a declared type *is* the declared shape (the same
``@id``), so a reference resolves by identity. A reference AMF could not resolve — a missing
include, an unknown type name — appears as a shape whose ``@id`` ends in ``/unresolved``;
the mapper collects those and refuses the import (``INPUT_REFERENCE_UNRESOLVED``) rather
than importing a model with holes in it. The resulting document has the same shape the
YAML reader produces, so :mod:`app.raml_normalizer` is unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .import_source import ImportSourceError
from .raml_parser import RamlDocument, RamlOperation, RamlParameter, RamlType, RamlTypeField

__all__ = ["document_from_amf_model", "XSD_TO_RAML"]

#: ``shacl:datatype`` (XML Schema) → RAML built-in type name.
XSD_TO_RAML: Dict[str, str] = {
    "string": "string",
    "integer": "integer",
    "long": "integer",
    "int": "integer",
    "float": "number",
    "double": "number",
    "number": "number",
    "decimal": "number",
    "boolean": "boolean",
    "date": "date-only",
    "time": "time-only",
    "dateTime": "datetime",
    "dateTimeOnly": "datetime-only",
    "base64Binary": "string",
    "anyType": "any",
}

_XSD_PREFIXES = ("http://www.w3.org/2001/XMLSchema#", "http://a.ml/vocabularies/shapes#")
_PARAMETER_BINDINGS = ("path", "query")
_UNRESOLVED_SUFFIX = "/unresolved"


def _as_list(value: Any) -> List[Any]:
    """A JSON-LD value as a list (single values and missing keys included)."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _ids(value: Any) -> List[str]:
    """The ``@id``\\s of a JSON-LD reference or reference list."""
    return [item["@id"] for item in _as_list(value) if isinstance(item, Mapping) and "@id" in item]


def _text(value: Any) -> Optional[str]:
    """A JSON-LD literal as a trimmed string (``{"@value": ...}`` included)."""
    if isinstance(value, Mapping):
        value = value.get("@value")
    if isinstance(value, list):
        value = value[0] if value else None
        return _text(value)
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        text = str(value).strip()
        return text or None
    return None


def _types(node: Mapping[str, Any]) -> Set[str]:
    """A node's ``@type``\\s."""
    return {str(t) for t in _as_list(node.get("@type"))}


class _Graph:
    """Index over an AMF JSON-LD graph with the naming and resolution rules applied."""

    def __init__(self, model: Mapping[str, Any]) -> None:
        graph = model.get("@graph") if isinstance(model, Mapping) else None
        self.nodes: Dict[str, Mapping[str, Any]] = {
            node["@id"]: node for node in _as_list(graph) if isinstance(node, Mapping) and "@id" in node
        }
        roots = [node for node in self.nodes.values() if node.get("doc:root") is True]
        if not roots:
            raise ImportSourceError("AMF returned no root RAML document", code="INPUT_MALFORMED")
        self.root = roots[0]
        self.unresolved: List[str] = []
        self.declared: Dict[str, str] = {}
        self.declaration_order: List[str] = []
        self._declare(self.root, alias=None)
        aliases = self._library_aliases()
        for node_id, node in self.nodes.items():
            if node is self.root or "doc:Module" not in _types(node) or node.get("doc:root") is True:
                continue
            self._declare(node, alias=aliases.get(node_id))
        self.uses = self._uses_of_declarations()

    def _declare(self, unit: Mapping[str, Any], *, alias: Optional[str]) -> None:
        """Register the shapes a unit declares under their RAML names."""
        for shape_id in _ids(unit.get("doc:declares")):
            shape = self.nodes.get(shape_id)
            name = _text(shape.get("shacl:name")) if shape else None
            if shape_id.endswith(_UNRESOLVED_SUFFIX):
                # A declaration whose definition AMF could not load (e.g. a missing include).
                self._note_unresolved(name or shape_id)
                continue
            if not name or shape_id in self.declared:
                continue
            self.declared[shape_id] = f"{alias}.{name}" if alias else name
            self.declaration_order.append(shape_id)

    def _note_unresolved(self, name: str) -> None:
        """Record a reference AMF could not resolve (once)."""
        if name not in self.unresolved:
            self.unresolved.append(name)

    def _uses_of_declarations(self) -> Dict[str, str]:
        """Use-site shape ``@id`` → the declaration it uses, from AMF's id convention.

        When a use adds its own facets (``status: {type: DeviceStatus, description: …}``),
        AMF's transformation merges the declaration into a new shape for the use and keeps
        the declaration one level below it, at ``<use id>/inherits/<kind>/<Name>``. That
        nesting is the only link left, so it is how a use is traced back to its type.
        """
        uses: Dict[str, str] = {}
        for declared_id in self.declaration_order:
            if "/inherits/" not in declared_id:
                continue
            parent, tail = declared_id.rsplit("/inherits/", 1)
            if tail.count("/") == 1 and parent not in self.declared:
                uses.setdefault(parent, declared_id)
        return uses

    def _library_aliases(self) -> Dict[str, str]:
        """Library unit ``@id`` → its ``uses`` alias, from the root's ``aliases-array`` source map."""
        aliases: Dict[str, str] = {}
        for source_map_id in _ids(self.root.get("sourcemaps:sources")):
            source_map = self.nodes.get(source_map_id) or {}
            for element_id in _ids(source_map.get("sourcemaps:aliases-array")):
                value = _text((self.nodes.get(element_id) or {}).get("sourcemaps:value"))
                if not value or "->" not in value:
                    continue
                alias, rest = value.split("->", 1)
                unit_ref = rest.split("::", 1)[0]
                if "#" in unit_ref:
                    aliases["#" + unit_ref.split("#", 1)[1]] = alias.strip()
        return aliases

    def node(self, node_id: Optional[str]) -> Mapping[str, Any]:
        """The node for ``node_id`` (empty when missing)."""
        return self.nodes.get(node_id or "", {})

    def type_expr(self, shape_id: Optional[str], seen: Tuple[str, ...] = ()) -> str:
        """The RAML type expression for a shape (``Pet``, ``common.Error``, ``string``, ``Pet[]``)."""
        if not shape_id:
            return "any"
        if shape_id in self.declared:
            return self.declared[shape_id]
        if shape_id in self.uses:
            return self.declared[self.uses[shape_id]]
        shape = self.node(shape_id)
        if shape_id.endswith(_UNRESOLVED_SUFFIX):
            name = _text(shape.get("shacl:name")) or shape_id
            self._note_unresolved(name)
            return name
        kinds = _types(shape)
        if "raml-shapes:ArrayShape" in kinds:
            items = _ids(shape.get("raml-shapes:items"))
            if not items or shape_id in seen:
                return "any[]"
            return f"{self.type_expr(items[0], seen + (shape_id,))}[]"
        if "raml-shapes:ScalarShape" in kinds:
            return self._scalar(shape)
        if "raml-shapes:FileShape" in kinds:
            return "file"
        if "raml-shapes:NilShape" in kinds:
            return "nil"
        if "shacl:NodeShape" in kinds:
            return "object"
        return "any"

    @staticmethod
    def _scalar(shape: Mapping[str, Any]) -> str:
        """A scalar shape's RAML type, from its ``shacl:datatype``."""
        for datatype in _ids(shape.get("shacl:datatype")):
            for prefix in _XSD_PREFIXES:
                if datatype.startswith(prefix):
                    return XSD_TO_RAML.get(datatype[len(prefix):], "string")
        return "string"

    def body_type(self, shape_id: Optional[str]) -> Optional[str]:
        """A body's type the way the YAML reader reports it: the named or built-in type
        (``Pet``, ``object``), with an array's ``[]`` dropped; ``None`` for an untyped body."""
        if not shape_id:
            return None
        expr = self.type_expr(shape_id)
        if expr.endswith("[]"):
            expr = expr[:-2]
        return None if expr == "any" else expr


def _enum_values(graph: _Graph, shape: Mapping[str, Any]) -> Tuple[str, ...]:
    """The values of a shape's ``enum`` (``shacl:in``, an RDF list of data scalars)."""
    values: List[str] = []
    for list_id in _ids(shape.get("shacl:in")):
        node = graph.node(list_id)
        members = [key for key in node if key.startswith("rdfs:_")]
        for key in sorted(members, key=lambda k: int(k.split("_", 1)[1]) if k.split("_", 1)[1].isdigit() else 0):
            for member_id in _ids(node[key]):
                value = _text(graph.node(member_id).get("data:value"))
                if value is not None:
                    values.append(value)
    return tuple(values)


def _declared_types(graph: _Graph) -> Tuple[RamlType, ...]:
    """Every declared type (root, its includes and its libraries), in declaration order."""
    types: List[RamlType] = []
    for shape_id in graph.declaration_order:
        shape = graph.node(shape_id)
        fields: List[RamlTypeField] = []
        for property_id in _ids(shape.get("shacl:property")):
            prop = graph.node(property_id)
            name = _text(prop.get("shacl:name"))
            if not name:
                continue
            range_ids = _ids(prop.get("raml-shapes:range"))
            range_node = graph.node(range_ids[0] if range_ids else None)
            min_count = prop.get("shacl:minCount")
            fields.append(
                RamlTypeField(
                    name=name,
                    type_expr=graph.type_expr(range_ids[0] if range_ids else None),
                    required=isinstance(min_count, int) and min_count >= 1,
                    description=_text(range_node.get("core:description")) or _text(prop.get("core:description")),
                )
            )
        types.append(
            RamlType(
                name=graph.declared[shape_id],
                description=_text(shape.get("core:description")),
                fields=tuple(fields),
                enum_values=_enum_values(graph, shape),
            )
        )
    return tuple(types)


def _parameters(graph: _Graph, parameter_ids: Sequence[str]) -> List[RamlParameter]:
    """Path and query parameters, in order."""
    params: List[RamlParameter] = []
    for parameter_id in parameter_ids:
        param = graph.node(parameter_id)
        binding = _text(param.get("apiContract:binding"))
        name = _text(param.get("core:name"))
        if binding not in _PARAMETER_BINDINGS or not name:
            continue
        schema_ids = _ids(param.get("raml-shapes:schema"))
        params.append(
            RamlParameter(
                name=name,
                location=binding,
                type_expr=graph.type_expr(schema_ids[0] if schema_ids else None),
                required=param.get("apiContract:required") is True,
                description=_text(param.get("core:description")),
            )
        )
    return params


def _first_payload_type(graph: _Graph, message: Mapping[str, Any]) -> Optional[str]:
    """The type of a request's / response's first payload that names one."""
    for payload_id in _ids(message.get("apiContract:payload")):
        schema_ids = _ids(graph.node(payload_id).get("raml-shapes:schema"))
        body = graph.body_type(schema_ids[0] if schema_ids else None)
        if body:
            return body
    return None


def _operations(graph: _Graph, web_api: Mapping[str, Any]) -> Tuple[RamlOperation, ...]:
    """Every operation of every endpoint (AMF gives each endpoint its full path)."""
    operations: List[RamlOperation] = []
    for endpoint_id in _ids(web_api.get("apiContract:endpoint")):
        endpoint = graph.node(endpoint_id)
        path = _text(endpoint.get("apiContract:path"))
        if not path:
            continue
        endpoint_params = _parameters(graph, _ids(endpoint.get("apiContract:parameter")))
        for operation_id in _ids(endpoint.get("apiContract:supportedOperation")):
            operation = graph.node(operation_id)
            method = _text(operation.get("apiContract:method"))
            if not method:
                continue
            requests = [graph.node(i) for i in _ids(operation.get("apiContract:expects"))]
            request_params: List[RamlParameter] = []
            for request in requests:
                request_params.extend(_parameters(graph, _ids(request.get("apiContract:parameter"))))
                request_params.extend(_parameters(graph, _ids(request.get("apiContract:uriParameter"))))
            params = {(p.location, p.name): p for p in endpoint_params}
            params.update({(p.location, p.name): p for p in request_params})
            responses: List[Tuple[str, str]] = []
            for response_id in _ids(operation.get("apiContract:returns")):
                response = graph.node(response_id)
                status = _text(response.get("apiContract:statusCode")) or _text(response.get("core:name"))
                body = _first_payload_type(graph, response)
                if status and body:
                    responses.append((status, body))
            operations.append(
                RamlOperation(
                    path=path,
                    method=method.lower(),
                    description=_text(operation.get("core:description")),
                    parameters=tuple(params.values()),
                    request_type=next((t for t in (_first_payload_type(graph, r) for r in requests) if t), None),
                    response_types=tuple(responses),
                )
            )
    return tuple(operations)


def _raml_version(graph: _Graph) -> str:
    """``1.0`` / ``0.8`` from the root's processing data (``doc:sourceSpec``)."""
    for processing_id in _ids(graph.root.get("doc:processingData")):
        spec = _text(graph.node(processing_id).get("doc:sourceSpec")) or ""
        if spec.upper().startswith("RAML"):
            return spec.split()[-1]
    return "1.0"


def document_from_amf_model(
    model: Mapping[str, Any],
    *,
    raw: str,
    model_sha256: Optional[str] = None,
    source_files: Tuple[str, ...] = (),
    source_label: Optional[str] = None,
) -> RamlDocument:
    """Build a :class:`RamlDocument` from an AMF JSON-LD model.

    Args:
        model: The JSON-LD from ``amf parse`` (compacted, with source maps).
        raw: The root document's text (kept as the document's ``raw``).
        model_sha256: The resolved-model hash (:func:`app.raml_amf.amf_model_sha256`).
        source_files: The set's member paths.
        source_label: Label used in error messages.

    Returns:
        The document.

    Raises:
        ImportSourceError: ``INPUT_REFERENCE_UNRESOLVED`` when AMF left references
            unresolved; ``INPUT_SEMANTIC_INVALID`` when there is no title, or neither types
            nor resources; ``INPUT_MALFORMED`` when the model has no root document.
    """
    graph = _Graph(model)
    web_api = graph.node(next(iter(_ids(graph.root.get("doc:encodes"))), None))
    types = _declared_types(graph)
    operations = _operations(graph, web_api)
    label = f" ({source_label})" if source_label else ""

    if graph.unresolved:
        raise ImportSourceError(
            f"The RAML set{label} references types or files that could not be resolved: "
            f"{', '.join(graph.unresolved)}. Bundle every included file and library into the "
            "upload, and check the type names.",
            code="INPUT_REFERENCE_UNRESOLVED",
        )
    title = _text(web_api.get("core:name"))
    if not title:
        raise ImportSourceError(f"RAML document{label} is missing a `title`", code="INPUT_SEMANTIC_INVALID")
    if not types and not operations:
        raise ImportSourceError(f"No RAML types or resources found{label}", code="INPUT_SEMANTIC_INVALID")

    servers = [graph.node(i) for i in _ids(web_api.get("apiContract:server"))]
    declared_media = _as_list(web_api.get("apiContract:accepts")) + _as_list(web_api.get("apiContract:contentType"))
    media_types = [_text(v) for v in declared_media]
    return RamlDocument(
        raml_version=_raml_version(graph),
        title=title,
        version=_text(web_api.get("core:version")),
        base_uri=next((u for u in (_text(s.get("core:urlTemplate")) for s in servers) if u), None),
        description=_text(web_api.get("core:description")),
        media_type=next((m for m in media_types if m), None),
        types=types,
        operations=operations,
        raw=raw,
        model_sha256=model_sha256,
        source_files=source_files,
    )
