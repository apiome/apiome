"""Zod schemas → canonical model normalizer — FMT-8.2 (#5463).

The Zod extractor hands over a JSON Schema (draft 2020-12) document: one ``$defs`` entry per
exported schema, constraints in JSON Schema's own vocabulary, and two vendor keywords for what
JSON Schema cannot say — ``x-zod-limits`` (a construct whose shape is still modelled, such as a
``refine``) and ``x-zod-unsupported`` (a construct with no shape at all, such as
``z.function()``).

Rather than re-deriving canonical types from JSON Schema, this module translates the document
into the *neutral AST* FMT-8.1's TypeScript reader produces and reuses that reader's model
builder (:mod:`app.typescript_types_normalizer`). A Zod schema and a TypeScript type are the
same family of shapes — inline objects, discriminated unions, intersections, tuples, records,
recursion through named definitions — so they share one set of naming and projection rules,
and a module modelled as Zod types reads the same as one modelled as TypeScript types. What
Zod adds is carried on the AST: JSON Schema constraints (``minLength``, ``pattern``, ``format``,
``minimum``, ``multipleOf``, …) become canonical :class:`~app.canonical_model.Constraints`
through the shared :func:`app.normalizer.coerce_constraints`, and defaults become field
defaults.

Declared limits use the Zod vocabulary (:data:`app.zod_parser.LIMIT_DETAILS`) and land in
``extras['zod']['capability_limits']``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .canonical_model import ApiIdentity, ApiParadigm, CanonicalApi
from .normalizer import Keys, Normalizer, normalize_ordering
from .typescript_types_normalizer import _limits_payload, _Model
from .typescript_types_parser import TsDocument
from .zod_parser import ZodDocument, zod_limit_recorder

__all__ = ["ZOD_EXTRAS_KEY", "ZOD_FORMAT", "ZodNormalizer", "translate_schema"]

#: The format key the normalizer registers under.
ZOD_FORMAT = "zod"

#: The key the projection record sits under in ``CanonicalApi.extras``.
ZOD_EXTRAS_KEY = "zod"

#: The id prefix every translated declaration carries (``zod#Order``).
_ID_PREFIX = "zod#"

#: JSON Schema keywords that are constraints on a use site, copied onto the AST node for
#: :func:`app.normalizer.coerce_constraints`.
_CONSTRAINT_KEYWORDS = (
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minItems",
    "maxItems",
    "uniqueItems",
)

#: JSON Schema scalar types → the AST primitive name.
_SCALARS = {
    "string": "string",
    "number": "number",
    "integer": "integer",
    "boolean": "boolean",
    "null": "null",
}


def _ref_name(ref: str) -> str:
    """The definition name a local ``#/$defs/<name>`` reference points at."""
    return ref.rsplit("/", 1)[-1]


def _decorate(node: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    """Attach a schema's constraints, declared limits and description to its AST node."""
    constraints = {key: schema[key] for key in _CONSTRAINT_KEYWORDS if key in schema}
    if constraints:
        node["constraints"] = constraints
    limits = schema.get("x-zod-limits")
    if isinstance(limits, list) and limits:
        node["limits"] = [str(limit) for limit in limits]
    return node


def translate_schema(schema: Any) -> Dict[str, Any]:
    """Translate one JSON Schema node (the extractor's dialect) into a neutral AST node.

    Args:
        schema: The JSON Schema node.

    Returns:
        The AST node FMT-8.1's model builder reads: ``primitive``, ``literal``, ``ref``,
        ``array``, ``tuple``, ``object``, ``union``, ``intersection``, ``lib`` (a map) or
        ``unsupported``, decorated with ``constraints`` and ``limits`` where the schema had them.
    """
    if not isinstance(schema, dict):
        return {"kind": "unsupported", "construct": "zod.unrepresentable", "text": repr(schema)}

    unsupported = schema.get("x-zod-unsupported")
    if isinstance(unsupported, str):
        return {
            "kind": "unsupported",
            "construct": unsupported,
            "text": schema.get("description") or "",
        }

    ref = schema.get("$ref")
    if isinstance(ref, str):
        name = _ref_name(ref)
        return _decorate(
            {"kind": "ref", "target": f"{_ID_PREFIX}{name}", "name": name, "typeArguments": []},
            schema,
        )

    if "const" in schema:
        return _decorate({"kind": "literal", "value": schema["const"]}, schema)

    if isinstance(schema.get("enum"), list):
        members = [{"kind": "literal", "value": value} for value in schema["enum"]]
        return _decorate({"kind": "union", "members": members}, schema)

    for keyword in ("oneOf", "anyOf"):
        if isinstance(schema.get(keyword), list):
            members = [translate_schema(member) for member in schema[keyword]]
            return _decorate({"kind": "union", "members": members}, schema)

    if isinstance(schema.get("allOf"), list):
        members = [translate_schema(member) for member in schema["allOf"]]
        return _decorate({"kind": "intersection", "members": members}, schema)

    type_ = schema.get("type")
    if type_ == "array":
        return _decorate(_array(schema), schema)
    if type_ == "object":
        return _decorate(_object(schema), schema)
    if type_ == "null" and schema.get("x-zod-type") == "undefined":
        return _decorate({"kind": "primitive", "name": "undefined"}, schema)
    if type_ in _SCALARS:
        return _decorate({"kind": "primitive", "name": _SCALARS[type_]}, schema)
    if schema.get("x-zod-type") == "unknown":
        return _decorate({"kind": "primitive", "name": "unknown"}, schema)
    # `{}` is `z.any()`: the author wrote "any value", which is modelled as exactly that.
    return _decorate({"kind": "primitive", "name": "any"}, schema)


def _array(schema: Dict[str, Any]) -> Dict[str, Any]:
    """A JSON Schema array: a tuple when it has ``prefixItems``, else a list."""
    prefix = schema.get("prefixItems")
    if isinstance(prefix, list):
        elements = [
            {"name": None, "type": translate_schema(item), "optional": False, "rest": False}
            for item in prefix
        ]
        rest = schema.get("items")
        if isinstance(rest, dict):
            elements.append(
                {
                    "name": None,
                    "type": {"kind": "array", "element": translate_schema(rest), "readonly": False},
                    "optional": False,
                    "rest": True,
                }
            )
        return {"kind": "tuple", "elements": elements}
    return {
        "kind": "array",
        "element": translate_schema(schema.get("items", {})),
        "readonly": False,
    }


def _object(schema: Dict[str, Any]) -> Dict[str, Any]:
    """A JSON Schema object: a map (``record`` / ``map``) or an object shape."""
    properties = schema.get("properties")
    additional = schema.get("additionalProperties")
    key_node = translate_schema(schema.get("propertyNames", {"type": "string"}))

    if not isinstance(properties, dict):
        if isinstance(additional, dict):
            lib = "Map" if schema.get("x-zod-type") == "map" else "Record"
            return {
                "kind": "lib",
                "name": lib,
                "typeArguments": [key_node, translate_schema(additional)],
            }
        properties = {}

    required = set(schema.get("required") or [])
    props: List[Dict[str, Any]] = []
    for name, member in properties.items():
        member = member if isinstance(member, dict) else {}
        prop: Dict[str, Any] = {
            "name": name,
            "optional": name not in required,
            "readonly": False,
            "type": translate_schema(member),
            "doc": member.get("description")
            if isinstance(member.get("description"), str)
            else None,
            "deprecated": False,
            "line": None,
        }
        if "default" in member:
            prop["default"] = member["default"]
        props.append(prop)

    node: Dict[str, Any] = {
        "kind": "object",
        "properties": props,
        "indexSignatures": [],
        "unsupported": [],
    }
    if isinstance(additional, dict):
        node["indexSignatures"] = [
            {
                "keyName": "key",
                "keyType": key_node,
                "valueType": translate_schema(additional),
                "readonly": False,
            }
        ]
    elif additional is False:
        node["extras"] = {"zod_unknown_keys": "strict"}
    elif additional is True:
        node["extras"] = {"zod_unknown_keys": "passthrough"}
    return node


def to_declarations(document: ZodDocument) -> List[Dict[str, Any]]:
    """Translate every ``$defs`` entry into a declaration FMT-8.1's model builder reads.

    The root module's exports are the exported declarations, in export order; a sibling
    module's schema that an export refers to follows, unexported — so it is modelled only
    because something points at it.
    """
    definitions = document.definitions
    order = list(document.exports) + [name for name in definitions if name not in document.exports]
    declarations: List[Dict[str, Any]] = []
    for name in order:
        schema = definitions.get(name)
        if schema is None:
            continue
        description = schema.get("description") if isinstance(schema, dict) else None
        declarations.append(
            {
                "id": f"{_ID_PREFIX}{name}",
                "name": name,
                "module": document.root,
                "line": None,
                "exported": name in document.exports,
                "doc": description if isinstance(description, str) else None,
                "deprecated": False,
                "typeParameters": [],
                "mergedDeclarations": 1,
                "kind": "alias",
                "type": translate_schema(schema),
            }
        )
    return declarations


def _identity_name(document: ZodDocument) -> str:
    """The model's name: the root module's first exported *object* schema, else its first export.

    An enum or a scalar schema is rarely what a module is about; the first object usually is.
    The filename is not consulted, so a module pasted and the same module uploaded catalog as
    one API.
    """
    definitions = document.definitions
    for name in document.exports:
        schema = definitions.get(name)
        if isinstance(schema, dict) and schema.get("type") == "object" and "properties" in schema:
            return name
    return document.exports[0] if document.exports else "ZodSchemas"


class ZodNormalizer(Normalizer, register=True):
    """Normalize a parsed Zod module (or module set) into a :class:`CanonicalApi`."""

    format = ZOD_FORMAT
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map a :class:`~app.zod_parser.ZodDocument` to the canonical model.

        Args:
            source: The parsed document.
            include_raw: Whether to keep the module sources and the extracted JSON Schema on
                ``raw``.

        Returns:
            The canonical model: one ``data_schema`` API holding every exported schema.

        Raises:
            ValueError: When ``source`` is not a :class:`ZodDocument`.
        """
        if not isinstance(source, ZodDocument):
            raise ValueError("Zod source must be a ZodDocument (see app.zod_parser.parse_zod)")

        declarations = to_declarations(source)
        projection = TsDocument(
            root=source.root,
            files=source.files,
            typescript_version="",
            declarations=tuple(declarations),
            sources={},
        )
        limits = zod_limit_recorder()
        model = _Model(projection, limits)
        exported = projection.exported()
        for declaration in exported:
            model.reserve(declaration["name"])
        for declaration in exported:
            model.declare_exported(declaration)

        name = _identity_name(source)
        zod: Dict[str, Any] = {
            "root_module": source.root,
            "modules": list(source.files),
            "exports": list(source.exports),
            "capability_limits": _limits_payload(limits.limits()),
        }
        root_type = Keys.type(name)
        if root_type in model.types:
            zod["root_type"] = root_type

        raw: Optional[Dict[str, Any]] = None
        if include_raw:
            raw = {"zod": dict(source.sources), "json_schema": source.schema}

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=name),
            title=name,
            types=list(model.types.values()),
            raw=raw,
            extras={ZOD_EXTRAS_KEY: zod},
        )
        return normalize_ordering(api)
