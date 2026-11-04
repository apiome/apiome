"""Discovery schemas from canonical types — MFX-29.2 (#4174).

A Google API Discovery document describes its bodies with a **draft-03-style JSON Schema subset**
(https://developers.google.com/discovery/v1/type-format): ``id``, ``type``, ``$ref`` (a bare schema id),
``properties`` with a boolean ``required``, ``items``, ``additionalProperties``, ``enum`` (strings) with
``enumDescriptions``, ``pattern``, ``minimum`` / ``maximum`` and ``default`` (all strings), ``format``,
``readOnly``, ``deprecated``, and for parameters ``location`` and ``repeated``.

This module writes it in two steps, reusing the JSON Schema export (MFX-21.1):

1. the canonical types are projected to a draft 2020-12 bundle (:func:`app.canonical_json_schema.build_bundle_schemas`)
   and **downgraded to draft-04** by :func:`app.jsonschema_drafts.downgrade_schema` — the 21.1 mapping
   (``$defs`` → ``definitions``, ``const`` → ``enum``, exclusive bounds as flags, newer keywords dropped);
   ``deprecated``, ``readOnly`` and ``contentEncoding``, which Discovery has but draft-04 does not, are kept
   through the downgrade;
2. :class:`DiscoverySchemaWriter` spells each draft-04 schema in the Discovery subset, recording on the
   :class:`~app.emitter.LossTracker` every keyword it cannot carry, under the JSON Pointer
   ``#/schemas/<id>/…`` of the schema it was in.

**Types and formats.** ``integer`` is ``int32`` (a narrower or unformatted integer too); a 64-bit integer is
``type: string, format: int64``, as Discovery sends it; ``number`` is ``double`` or ``float``; base64 text is
``format: byte``; ``date`` and ``date-time`` are kept, any other string ``format`` is dropped. A nullable
type is written as its non-null type (Discovery has no null-or-T); a union is ``type: any``.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, Optional

from .canonical_json_schema import CANONICAL_SCALAR_SCHEMAS, CanonicalSchemaBundle, build_bundle_schemas
from .canonical_model import CanonicalApi, Type, TypeKind, TypeRef
from .emitter import LossKind, LossTracker
from .jsonschema_drafts import downgrade_schema

__all__ = [
    "DISCOVERY_STRING_FORMATS",
    "DISCOVERY_TYPE_FORMATS",
    "DiscoverySchemaWriter",
    "identifier",
]

#: The type / format pairs of the Discovery type-and-format summary (``None``: no format).
DISCOVERY_TYPE_FORMATS: Dict[str, frozenset] = {
    "any": frozenset({None, "google.protobuf.Value"}),
    "array": frozenset({None, "google.protobuf.ListValue"}),
    "boolean": frozenset({None}),
    "integer": frozenset({"int32", "uint32"}),
    "number": frozenset({"double", "float"}),
    "object": frozenset({None, "google.protobuf.Struct", "google.protobuf.Any"}),
    "string": frozenset({None, "byte", "date", "date-time", "google-datetime", "google-duration",
                         "google-fieldmask", "int64", "uint64"}),
    "null": frozenset({None}),
}
#: The string formats a JSON Schema ``format`` keeps as it is.
DISCOVERY_STRING_FORMATS = frozenset({"byte", "date", "date-time"})

#: Keywords Discovery has that draft-04 does not: renamed around the downgrade so it keeps them.
_KEPT = {"deprecated": "x-discovery-deprecated", "readOnly": "x-discovery-readOnly",
         "contentEncoding": "x-discovery-contentEncoding"}
#: Downgrade losses that are not losses here, or that :class:`DiscoverySchemaWriter` reports itself.
_SUPERSEDED = frozenset({"exclusive-bound-boolean", "exclusive-bound-merged", "prefix-items-as-tuple"})
#: Keywords Discovery has no counterpart for: dropped, each recorded.
_DROPPED = ("minLength", "maxLength", "minItems", "maxItems", "multipleOf", "uniqueItems", "minProperties",
            "maxProperties", "not", "dependencies", "patternProperties", "additionalItems", "title")
#: Schema positions the keyword-protection walk descends into.
_SCHEMA_MAPS = ("properties", "$defs", "patternProperties", "dependentSchemas")
_SCHEMA_LISTS = ("allOf", "anyOf", "oneOf", "prefixItems")
_SCHEMA_VALUES = ("items", "additionalProperties", "not", "contains", "if", "then", "else")
_REF_PREFIX = "#/definitions/"


class DiscoverySchemaWriter:
    """Write the Discovery ``schemas`` of a model, and schemas for parameter and body type references.

    Args:
        api: The canonical model.
        losses: Where every keyword Discovery cannot carry is recorded.
    """

    def __init__(self, api: CanonicalApi, losses: LossTracker) -> None:
        self._api = api
        self._losses = losses
        self.bundle: CanonicalSchemaBundle = build_bundle_schemas(api)
        #: Schema id → the canonical type it was written from.
        self.types_by_id: Dict[str, Type] = {
            schema_id: type_ for type_ in api.types
            if (schema_id := self.bundle.defs_keys.get(type_.key)) is not None
        }

    # ------------------------------------------------------------------
    # Whole model
    # ------------------------------------------------------------------

    def schemas(self) -> Dict[str, Dict[str, Any]]:
        """Schema id → its Discovery schema (``id`` first), one per canonical type, in declaration order."""
        out: Dict[str, Dict[str, Any]] = {}
        for schema_id, schema in self.bundle.defs.items():
            pointer = f"#/schemas/{schema_id}"
            written = self.convert(self.downgrade(schema, pointer), pointer)
            type_ = self.types_by_id.get(schema_id)
            if type_ is not None and type_.kind is TypeKind.ENUM and "enum" in written:
                descriptions = [value.description or "" for value in type_.enum_values]
                if any(descriptions) and len(descriptions) == len(written["enum"]):
                    written["enumDescriptions"] = descriptions
            out[schema_id] = {"id": schema_id, **written}
        return out

    def ref_schema(self, ref: TypeRef, pointer: str) -> Dict[str, Any]:
        """The Discovery schema of a type reference (a parameter's or body's type): a ``$ref`` or a scalar."""
        return self.convert(self.downgrade(self._ref_fragment(ref), pointer), pointer)

    def raw_schema(self, schema: Dict[str, Any], pointer: str) -> Dict[str, Any]:
        """The Discovery schema of an inline JSON Schema (a body the source declares in place)."""
        return self.convert(self.downgrade(copy.deepcopy(schema), pointer), pointer)

    def schema_id(self, ref: TypeRef) -> Optional[str]:
        """The schema id a reference names when it is one named type (not a list), else ``None``."""
        if ref.is_list() or not ref.name:
            return None
        if ref.name in self.bundle.defs_keys:
            return self.bundle.defs_keys[ref.name]
        by_name = [key for key, type_ in self.types_by_id.items() if type_.name == ref.name]
        return by_name[0] if len(by_name) == 1 else None

    # ------------------------------------------------------------------
    # The draft-04 step
    # ------------------------------------------------------------------

    def downgrade(self, schema: Dict[str, Any], pointer: str) -> Dict[str, Any]:
        """``schema`` (2020-12) downgraded to draft-04, keeping the keywords Discovery has.

        The downgrade's own losses are recorded, except those :meth:`convert` reports in Discovery terms.
        """
        scratch = LossTracker()
        rewritten = downgrade_schema(_protect(copy.deepcopy(schema)), "draft-04", scratch, pointer=pointer)
        rewritten.pop("$schema", None)
        for loss in scratch.records():
            if loss.subject not in _SUPERSEDED:
                detail = loss.detail.replace("draft-04", "Discovery")
                self._losses.record(loss.kind, loss.subject, detail, pointer=loss.pointer)
        return rewritten

    # ------------------------------------------------------------------
    # The Discovery step
    # ------------------------------------------------------------------

    def convert(self, schema: Any, pointer: str) -> Dict[str, Any]:
        """One draft-04 schema in the Discovery subset; what it cannot carry is recorded under ``pointer``."""
        if not isinstance(schema, dict):
            return {"type": "any"}
        schema = dict(schema)
        out: Dict[str, Any] = {}
        all_of = schema.pop("allOf", None)
        if isinstance(all_of, list) and all_of:
            # The downgrade wraps a `$ref` that has siblings as `allOf: [{"$ref"}]`; Discovery keeps the siblings.
            first, rest = all_of[0], all_of[1:]
            if isinstance(first, dict) and set(first) == {"$ref"} and not rest:
                schema["$ref"] = first["$ref"]
            else:
                self._record(LossKind.NA, "all-of-dropped", "Discovery has no `allOf`; the combined schema is "
                             f"written as `any` at {pointer}.", pointer)
                schema["type"] = "any"
        if "$ref" in schema:
            ref = self._schema_ref(str(schema.pop("$ref")))
            if ref is not None:
                out["$ref"] = ref
            else:
                self._record(LossKind.NA, "ref-unresolved", "The reference at "
                             f"{pointer} names no type of the item; it is written as `type: any`.", pointer)
                schema["type"] = "any"
        for keyword in ("oneOf", "anyOf"):
            alternatives = schema.pop(keyword, None)
            if isinstance(alternatives, list):
                names = ", ".join(_alternative_name(a) for a in alternatives) or "none"
                self._record(LossKind.INFERRED, "union-as-any",
                             f"Discovery has no `{keyword}`; the union at {pointer} is written as `type: any` "
                             f"(one of: {names}).", pointer)
                schema.setdefault("type", "any")
                schema.setdefault("description", f"One of: {names}.")
        if "description" in schema:
            out["description"] = str(schema.pop("description"))
        if "$ref" not in out:
            self._type(schema, out, pointer)
        self._properties(schema, out, pointer)
        self._containers(schema, out, pointer)
        self._facets(schema, out, pointer)
        for keyword, kept in _KEPT.items():
            value = schema.pop(kept, None)
            if keyword != "contentEncoding" and value is not None:
                out[keyword] = bool(value)
        for keyword in _DROPPED:
            if keyword in schema:
                value = schema.pop(keyword)
                self._record(LossKind.NA, "keyword-dropped", f"Discovery has no `{keyword}` keyword; "
                             f"{keyword} {_short(value)} is dropped at {pointer}.", pointer)
        return out

    def _type(self, schema: Dict[str, Any], out: Dict[str, Any], pointer: str) -> None:
        """``type`` and ``format``, by the Discovery type-and-format summary."""
        raw = schema.pop("type", None)
        fmt = schema.pop("format", None)
        encoding = schema.get(_KEPT["contentEncoding"])
        kinds = raw if isinstance(raw, list) else [raw] if raw else []
        if "null" in kinds and len(kinds) > 1:
            kinds = [k for k in kinds if k != "null"]
            self._record(LossKind.INFERRED, "null-dropped", "Discovery has no nullable types; the value at "
                         f"{pointer} is written as {kinds[0] if len(kinds) == 1 else 'any'} without null.", pointer)
        if len(kinds) != 1:
            if len(kinds) > 1:
                self._record(LossKind.INFERRED, "union-as-any", f"Discovery has one type per schema; "
                             f"{'/'.join(kinds)} at {pointer} is written as `any`.", pointer)
            out["type"] = "any"
            return
        kind = kinds[0]
        if kind == "integer":
            if fmt in ("int64", "uint64"):
                out["type"], out["format"] = "string", fmt
                self._record(LossKind.INFERRED, "int64-as-string", f"Discovery sends a 64-bit integer as a "
                             f"string; the value at {pointer} is `type: string, format: {fmt}`.", pointer)
                return
            out["type"], out["format"] = "integer", fmt if fmt in ("int32", "uint32") else "int32"
            if fmt not in ("int32", "uint32"):
                self._record(LossKind.INFERRED, "integer-as-int32", "Discovery integers are 32-bit; the integer "
                             f"at {pointer} is written `format: int32`.", pointer)
            return
        if kind == "number":
            out["type"], out["format"] = "number", fmt if fmt in ("double", "float") else "double"
            return
        out["type"] = kind
        if kind == "string":
            if encoding == "base64" or fmt == "byte":
                out["format"] = "byte"
            elif fmt in DISCOVERY_STRING_FORMATS:
                out["format"] = fmt
            elif fmt:
                self._record(LossKind.NA, "format-dropped", f"Discovery has no `{fmt}` format; the value at "
                             f"{pointer} is written as a plain string.", pointer)

    def _properties(self, schema: Dict[str, Any], out: Dict[str, Any], pointer: str) -> None:
        """``properties``, each with a boolean ``required`` (Discovery's draft-03 spelling)."""
        properties = schema.pop("properties", None)
        required = set(schema.pop("required", None) or [])
        if not isinstance(properties, dict):
            return
        written: Dict[str, Any] = {}
        for name, sub in properties.items():
            child = self.convert(sub, f"{pointer}/properties/{name}")
            if name in required:
                child["required"] = True
            written[name] = child
        out["properties"] = written

    def _containers(self, schema: Dict[str, Any], out: Dict[str, Any], pointer: str) -> None:
        """``items`` (one schema) and ``additionalProperties`` (a schema; ``false`` cannot be said)."""
        items = schema.pop("items", None)
        if isinstance(items, list):
            self._record(LossKind.INFERRED, "tuple-as-array", "Discovery arrays have one item schema; the tuple "
                         f"at {pointer} is written as an array of `any`.", pointer)
            out["items"] = {"type": "any"}
        elif isinstance(items, dict):
            out["items"] = self.convert(items, f"{pointer}/items")
        elif out.get("type") == "array":
            out["items"] = {"type": "any"}
        extra = schema.pop("additionalProperties", None)
        if isinstance(extra, dict):
            out["additionalProperties"] = self.convert(extra, f"{pointer}/additionalProperties")
        elif extra is False:
            self._record(LossKind.NA, "closed-object-dropped", "Discovery cannot close an object; "
                         f"`additionalProperties: false` at {pointer} is dropped.", pointer)

    def _facets(self, schema: Dict[str, Any], out: Dict[str, Any], pointer: str) -> None:
        """``enum`` (strings only), ``pattern``, ``minimum`` / ``maximum`` and ``default`` (as strings)."""
        values = schema.pop("enum", None)
        if isinstance(values, list):
            if all(isinstance(v, str) for v in values):
                out["enum"] = list(values)
            else:
                self._record(LossKind.NA, "enum-dropped", "Discovery enums list strings; the values "
                             f"{_short(values)} at {pointer} are dropped.", pointer)
        if isinstance(schema.get("pattern"), str):
            out["pattern"] = schema.pop("pattern")
        for bound, flag in (("minimum", "exclusiveMinimum"), ("maximum", "exclusiveMaximum")):
            exclusive = schema.pop(flag, None)
            if bound in schema:
                out[bound] = _string(schema.pop(bound))
                if exclusive is True:
                    self._record(LossKind.INFERRED, "exclusive-bound-inclusive", f"Discovery bounds are inclusive; "
                                 f"the exclusive {bound} {out[bound]} at {pointer} is written inclusive.", pointer)
        if "default" in schema:
            default = schema.pop("default")
            if isinstance(default, (dict, list)) or default is None:
                self._record(LossKind.NA, "default-dropped", "Discovery defaults are strings; the default "
                             f"{_short(default)} at {pointer} is dropped.", pointer)
            else:
                out["default"] = _string(default)

    def _ref_fragment(self, ref: TypeRef) -> Dict[str, Any]:
        """The 2020-12 fragment of a type reference, as the bundle writes a field of that type."""
        if ref.is_list():
            return {"type": "array", "items": self._ref_fragment(ref.item or TypeRef(name="string"))}
        schema_id = self.schema_id(ref)
        if schema_id is not None:
            return {"$ref": f"#/$defs/{schema_id}"}
        return dict(CANONICAL_SCALAR_SCHEMAS.get((ref.name or "").strip().lower(), {}))

    def _schema_ref(self, ref: str) -> Optional[str]:
        """The schema id a ``$ref`` names: a ``#/definitions/<id>`` of the bundle, or (in an inline schema of
        the source, such as ``#/components/schemas/Item``) the type its last segment names; else ``None``."""
        if ref.startswith(_REF_PREFIX):
            return ref[len(_REF_PREFIX):]
        name = ref.rsplit("/", 1)[-1]
        if name in self.types_by_id:
            return name
        return self.schema_id(TypeRef(name=name))

    def _record(self, kind: LossKind, subject: str, detail: str, pointer: str) -> None:
        self._losses.record(kind, subject, detail, pointer=pointer)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _protect(schema: Any) -> Any:
    """Rename the keywords Discovery keeps but draft-04 drops, at schema positions only (in place)."""
    if not isinstance(schema, dict):
        return schema
    for keyword, kept in _KEPT.items():
        if keyword in schema:
            schema[kept] = schema.pop(keyword)
    for keyword in _SCHEMA_MAPS:
        if isinstance(schema.get(keyword), dict):
            for sub in schema[keyword].values():
                _protect(sub)
    for keyword in _SCHEMA_LISTS:
        if isinstance(schema.get(keyword), list):
            for sub in schema[keyword]:
                _protect(sub)
    for keyword in _SCHEMA_VALUES:
        _protect(schema.get(keyword))
    return schema


def _alternative_name(schema: Any) -> str:
    """How a union alternative is named in a message: its schema id, else its type."""
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if isinstance(ref, str):
            return ref.rsplit("/", 1)[-1]
        if schema.get("type"):
            return str(schema["type"])
    return "any"


def _string(value: Any) -> str:
    """A scalar as Discovery writes it in ``default`` / ``minimum`` / ``maximum``: JSON text, unquoted."""
    if isinstance(value, str):
        return value
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return json.dumps(value)


def _short(value: Any) -> str:
    """A value for a loss message, cut to a readable length."""
    text = json.dumps(value, default=str)
    return text if len(text) <= 60 else text[:57] + "..."


_IDENTIFIER_PARTS = re.compile(r"[A-Za-z0-9]+")


def identifier(text: str, *, fallback: str) -> str:
    """``text`` as a lowerCamel Discovery identifier (``list-pets`` → ``listPets``); ``fallback`` when empty."""
    parts = _IDENTIFIER_PARTS.findall(text or "")
    if not parts:
        return fallback
    head, *rest = parts
    name = head[:1].lower() + head[1:] + "".join(p[:1].upper() + p[1:] for p in rest)
    return name if name[:1].isalpha() else f"{fallback}{name[:1].upper()}{name[1:]}"
