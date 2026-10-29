"""JSON Type Definition (RFC 8927) output for the JSON Schema export — MFX-21.3 (#4128).

The JSON Schema emitter's ``mode="jtd"`` writes the same model as one JTD document. JTD is the
strict, codegen-friendly sibling of JSON Schema: :func:`jtd_from_bundle` rewrites the draft 2020-12
bundle the emitter builds (:func:`app.canonical_json_schema.build_bundle_schemas`) form by form:

* ``$defs`` → root ``definitions``; ``{"$ref": "#/$defs/X"}`` → ``{"ref": "X"}``; the root ``$ref`` →
  the root ``ref``;
* a record (``type: object`` with ``properties``) → the properties form: ``required`` members in
  ``properties``, the others in ``optionalProperties``; a map (``additionalProperties`` only) →
  ``values``; an array → ``elements``;
* ``string`` → ``string`` (``format: date-time`` → ``timestamp``); ``integer`` with ``format: int32``
  → ``int32``; ``number`` → ``float64`` (``format: float`` → ``float32``); ``boolean`` → ``boolean``;
  a ``null`` in a ``type`` list → ``nullable: true``;
* a string ``enum`` (or ``const``) → the enum form;
* ``description`` → ``metadata.description`` (the one ``metadata`` key ajv's strict mode and the JTD
  code generators read).

JTD is far less expressive, and every rewrite that changes meaning is recorded on a
:class:`~app.emitter.LossTracker` with the JSON Pointer of the 2020-12 schema it happened in (the
pointer :class:`app.jsonschema_emitter.JsonSchemaFidelityRulePack` files it by):

* ``jtd-keyword-dropped`` (``NA``) — a validation keyword JTD has no form for: ``pattern``, the
  numeric bounds, ``multipleOf``, the length and item-count bounds, ``uniqueItems``, a ``format``
  other than ``date-time``, ``contentEncoding``…;
* ``jtd-annotation-dropped`` (``NA``) — an annotation JTD has no place for (``title``,
  ``deprecated``, ``default``, ``examples``, ``$comment``…);
* ``jtd-widened`` (``INFERRED``) — a schema JTD cannot state, written as the empty form ``{}``
  (any value): ``oneOf`` / ``anyOf`` / ``allOf`` across shapes, ``not``, several JSON types, ``null``
  alone, an unknown ``type``;
* ``jtd-integer-as-float`` (``INFERRED``) — an integer that is not ``int32``: JTD has no 64-bit or
  unbounded integer, so it is written ``float64`` (integer-ness and precision above 2^53 unchecked);
* ``jtd-enum-as-type`` (``INFERRED``) — an ``enum`` of non-string values: JTD enums are strings, so
  only the values' type is kept;
* ``jtd-closed-records`` (``INFERRED``, at ``#``) — JTD rejects a property a record does not declare,
  where the JSON Schema export allows it.

:func:`check_jtd_schema` checks a document against the schema rules of RFC 8927 §2.2 (the forms,
their keywords, ``ref`` targets, ``definitions`` only at the root), so the export can be validated
without a JTD library.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .emitter import LossKind, LossTracker

__all__ = ["JTD_LOSS_SUBJECTS", "JTD_TYPES", "check_jtd_schema", "jtd_from_bundle"]

#: The ``type`` values RFC 8927 defines.
JTD_TYPES = frozenset({
    "boolean", "string", "timestamp", "float32", "float64",
    "int8", "uint8", "int16", "uint16", "int32", "uint32",
})

#: Loss subjects this module records → whether the loss keeps the data's shape (``INFO``) or loosens
#: what is checked (``WARN``) — read by the fidelity pack.
JTD_LOSS_SUBJECTS: Dict[str, str] = {
    "jtd-keyword-dropped": "warn",
    "jtd-annotation-dropped": "info",
    "jtd-widened": "warn",
    "jtd-integer-as-float": "warn",
    "jtd-enum-as-type": "warn",
    "jtd-closed-records": "info",
}

#: Keywords consumed by the rewrite itself (never reported).
_HANDLED = frozenset({
    "type", "properties", "required", "additionalProperties", "items", "$ref", "enum", "const",
    "format", "description",
})
#: Annotations JTD has no place for (dropped as ``jtd-annotation-dropped``). RFC 8927 lets ``metadata``
#: hold anything, but ajv's strict mode rejects a ``metadata`` key other than ``description``.
_ANNOTATIONS = frozenset({
    "title", "deprecated", "default", "examples", "$comment", "readOnly", "writeOnly", "$id", "$anchor",
})
#: Composition keywords JTD cannot state (the schema is widened to ``{}``).
_COMPOSITION = ("oneOf", "anyOf", "allOf", "not", "if")

#: Keywords each form may carry beside ``nullable`` and ``metadata`` (RFC 8927 §2.2).
_FORMS: Tuple[Tuple[str, frozenset], ...] = (
    ("ref", frozenset({"ref"})),
    ("type", frozenset({"type"})),
    ("enum", frozenset({"enum"})),
    ("elements", frozenset({"elements"})),
    ("properties", frozenset({"properties", "optionalProperties", "additionalProperties"})),
    ("values", frozenset({"values"})),
    ("discriminator", frozenset({"discriminator", "mapping"})),
)


def jtd_from_bundle(document: Dict[str, Any], losses: LossTracker) -> Dict[str, Any]:
    """Rewrite a draft 2020-12 bundle (root ``$ref`` + ``$defs``) as one JTD document.

    Args:
        document: The 2020-12 bundle the JSON Schema emitter builds (not mutated). Its ``$schema`` and
            ``$id`` identify the document, not a rule, and are left out.
        losses: Where each keyword JTD drops or approximates is recorded.

    Returns:
        The JTD document: ``definitions`` (one per ``$defs`` entry), the root form (``ref`` to the root
        type, else the empty form) and the description as root ``metadata``. The title names the file
        and is not written.
    """
    defs = document.get("$defs") or {}
    out: Dict[str, Any] = {}
    if defs:
        out["definitions"] = {key: _schema(sub, losses, f"#/$defs/{key}") for key, sub in defs.items()}
    ref = document.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        out["ref"] = ref[len("#/$defs/"):]
    if document.get("description"):
        out["metadata"] = {"description": document["description"]}
    if any(_is_record(sub) for sub in defs.values()):
        losses.record(
            LossKind.INFERRED, "jtd-closed-records",
            "JTD rejects a property a record does not declare (unless `additionalProperties: true`); "
            "the JSON Schema export allows it, so an instance with extra properties fails the JTD schema.",
            pointer="#",
        )
    return out


def _schema(schema: Any, losses: LossTracker, pointer: str) -> Dict[str, Any]:
    """Rewrite one 2020-12 schema position as a JTD schema (``definitions`` never nested)."""
    if not isinstance(schema, dict):
        # `true` / `false` schemas: `true` is the empty form; JTD cannot reject everything.
        if schema is False:
            _widened(losses, pointer, "`false` (nothing matches)")
        return {}
    out, nullable = _form(schema, losses, pointer)
    if nullable:
        out["nullable"] = True
    if schema.get("description"):
        out["metadata"] = {"description": schema["description"]}
    for keyword in schema:
        if keyword in _HANDLED or keyword in _COMPOSITION:
            continue
        if keyword in _ANNOTATIONS:
            _dropped(losses, "jtd-annotation-dropped", keyword, pointer, "JTD has no place for the annotation")
        else:
            _dropped(losses, "jtd-keyword-dropped", keyword, pointer, "JTD has no form for")
    return out


def _form(schema: Dict[str, Any], losses: LossTracker, pointer: str) -> Tuple[Dict[str, Any], bool]:
    """The JTD form of one schema (without ``nullable`` / ``metadata``), and whether it accepts ``null``."""
    composition = next((keyword for keyword in _COMPOSITION if keyword in schema), None)
    if composition is not None:
        _widened(losses, pointer, f"`{composition}` (JTD can only tag a union of records with a discriminator)")
        return {}, False
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        return {"ref": ref[len("#/$defs/"):]}, False
    types, nullable = _types(schema.get("type"))
    if "const" in schema and "enum" not in schema:
        schema = {**schema, "enum": [schema["const"]]}
    if "enum" in schema:
        return _enum(schema, types, losses, pointer), nullable or None in (schema.get("enum") or [])
    if len(types) > 1:
        _widened(losses, pointer, f"`type: {sorted(types)}` (a JTD schema has one type)")
        return {}, nullable
    kind = types[0] if types else _implied_type(schema)
    if kind == "object":
        return _object(schema, losses, pointer), nullable
    if kind == "array":
        items = schema.get("items", {})
        return {"elements": _schema(items, losses, f"{pointer}/items")}, nullable
    if kind is None:
        return {}, nullable
    return _scalar(kind, schema, losses, pointer), nullable


def _types(value: Any) -> Tuple[List[str], bool]:
    """The JSON types a ``type`` keyword names, and whether ``null`` is one of several.

    ``["string", "null"]`` → ``(["string"], True)``; ``"null"`` alone → ``(["null"], False)`` (JTD has no
    null type, so it is widened); no ``type`` → ``([], False)``.
    """
    if isinstance(value, str):
        names = [value]
    elif isinstance(value, list):
        names = [name for name in value if isinstance(name, str)]
    else:
        names = []
    rest = [name for name in names if name != "null"]
    if not rest:
        return (["null"] if names else []), False
    return rest, len(rest) < len(names)


def _implied_type(schema: Dict[str, Any]) -> Optional[str]:
    """The JSON type a schema without ``type`` implies by its keywords (``None`` when it implies none)."""
    if "properties" in schema or "additionalProperties" in schema:
        return "object"
    if "items" in schema:
        return "array"
    return None


def _is_record(schema: Any) -> bool:
    return isinstance(schema, dict) and isinstance(schema.get("properties"), dict)


def _object(schema: Dict[str, Any], losses: LossTracker, pointer: str) -> Dict[str, Any]:
    """A record → the properties form; a map (no ``properties``) → the values form."""
    additional = schema.get("additionalProperties")
    if not _is_record(schema):
        values = additional if isinstance(additional, dict) else {}
        return {"values": _schema(values, losses, f"{pointer}/additionalProperties")}
    required = set(schema.get("required") or [])
    properties: Dict[str, Any] = {}
    optional: Dict[str, Any] = {}
    for name, sub in schema["properties"].items():
        target = properties if name in required else optional
        target[name] = _schema(sub, losses, f"{pointer}/properties/{name}")
    out: Dict[str, Any] = {"properties": properties} if properties or not optional else {}
    if optional:
        out["optionalProperties"] = optional
    if additional is True or isinstance(additional, dict):
        out["additionalProperties"] = True
        if isinstance(additional, dict) and additional:
            _widened(losses, f"{pointer}/additionalProperties",
                     "an `additionalProperties` schema (JTD only allows or rejects extra properties)")
    return out


def _enum(schema: Dict[str, Any], types: List[str], losses: LossTracker, pointer: str) -> Dict[str, Any]:
    """A string ``enum`` → the enum form; any other ``enum`` keeps only its values' type."""
    values = [value for value in schema.get("enum") or [] if value is not None]
    strings = [value for value in values if isinstance(value, str)]
    if values and len(strings) == len(values):
        return {"enum": list(dict.fromkeys(strings))}
    kind = types[0] if len(types) == 1 else _value_type(values)
    losses.record(
        LossKind.INFERRED, "jtd-enum-as-type",
        f"JTD enums are strings; the values {values!r} at {pointer} are not checked, only their "
        f"type ({kind or 'any'}).",
        pointer=pointer,
    )
    return _scalar(kind, schema, LossTracker(), pointer) if kind else {}


def _value_type(values: List[Any]) -> Optional[str]:
    """The one JSON type every value has (``None`` when they mix or there are none)."""
    kinds = {
        "boolean" if isinstance(v, bool) else "integer" if isinstance(v, int)
        else "number" if isinstance(v, float) else "string" if isinstance(v, str) else "other"
        for v in values
    }
    return next(iter(kinds)) if len(kinds) == 1 and "other" not in kinds else None


def _scalar(kind: str, schema: Dict[str, Any], losses: LossTracker, pointer: str) -> Dict[str, Any]:
    """A JSON scalar type (with its ``format``) → its JTD ``type``."""
    fmt = schema.get("format")
    if kind == "string":
        if fmt == "date-time":
            return {"type": "timestamp"}
        if fmt:
            _dropped(losses, "jtd-keyword-dropped", "format", pointer, f"JTD has no form for `format: {fmt}`;")
        return {"type": "string"}
    if kind == "boolean":
        return {"type": "boolean"}
    if kind == "number":
        return {"type": "float32" if fmt == "float" else "float64"}
    if kind == "integer":
        if fmt == "int32":
            return {"type": "int32"}
        losses.record(
            LossKind.INFERRED, "jtd-integer-as-float",
            f"JTD has no 64-bit or unbounded integer; the {fmt or 'integer'} at {pointer} is written `float64`, "
            "which does not check that a value is whole or exact above 2^53.",
            pointer=pointer,
        )
        return {"type": "float64"}
    _widened(losses, pointer, f"`type: {kind}`")
    return {}


def _widened(losses: LossTracker, pointer: str, what: str) -> None:
    """Record a schema written as the empty form ``{}`` because JTD cannot state it."""
    losses.record(
        LossKind.INFERRED, "jtd-widened",
        f"JTD cannot state {what}; the schema at {pointer} is written as {{}} (any value).",
        pointer=pointer,
    )


def _dropped(losses: LossTracker, subject: str, keyword: str, pointer: str, reason: str) -> None:
    """Record a keyword left out of the JTD schema."""
    if keyword == "format":
        detail = f"{reason} it is dropped at {pointer}."
    else:
        detail = f"{reason} `{keyword}`; it is dropped at {pointer}."
    losses.record(LossKind.NA, subject, detail, pointer=pointer)


# ===========================================================================
# RFC 8927 §2.2 — schema correctness
# ===========================================================================


def check_jtd_schema(document: Any) -> None:
    """Check that ``document`` is a correct JTD schema (RFC 8927 §2.2).

    Args:
        document: The parsed root schema.

    Raises:
        ValueError: The first rule it breaks, with the JSON Pointer of the schema at fault.
    """
    if not isinstance(document, dict):
        raise ValueError("A JTD schema must be a JSON object")
    definitions = document.get("definitions", {})
    if not isinstance(definitions, dict):
        raise ValueError("`definitions` must be an object")
    for name, schema in definitions.items():
        _check(schema, definitions, f"/definitions/{name}")
    _check({k: v for k, v in document.items() if k != "definitions"}, definitions, "")


def _check(schema: Any, definitions: Dict[str, Any], pointer: str) -> None:
    """Check one non-root schema (``definitions`` is only allowed at the root)."""
    where = pointer or "/"
    if not isinstance(schema, dict):
        raise ValueError(f"{where}: a JTD schema must be a JSON object")
    if "nullable" in schema and not isinstance(schema["nullable"], bool):
        raise ValueError(f"{where}: `nullable` must be a boolean")
    if "metadata" in schema and not isinstance(schema["metadata"], dict):
        raise ValueError(f"{where}: `metadata` must be an object")
    keywords = set(schema) - {"nullable", "metadata"}
    form = next((name for name, allowed in _FORMS if keywords & allowed), None)
    allowed = dict(_FORMS).get(form, frozenset()) if form else frozenset()
    if keywords - allowed:
        extra = sorted(keywords - allowed)
        raise ValueError(f"{where}: keywords {extra} are not allowed in the {form or 'empty'} form")
    if form == "ref":
        if schema["ref"] not in definitions:
            raise ValueError(f"{where}: `ref` {schema['ref']!r} names no definition")
    elif form == "type":
        if schema["type"] not in JTD_TYPES:
            raise ValueError(f"{where}: `type` {schema['type']!r} is not a JTD type")
    elif form == "enum":
        values = schema["enum"]
        if not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values):
            raise ValueError(f"{where}: `enum` must be a non-empty array of strings")
        if len(set(values)) != len(values):
            raise ValueError(f"{where}: `enum` values must be unique")
    elif form in ("elements", "values"):
        _check(schema[form], definitions, f"{pointer}/{form}")
    elif form == "properties":
        _check_properties(schema, definitions, pointer)
    elif form == "discriminator":
        _check_discriminator(schema, definitions, pointer)


def _check_properties(schema: Dict[str, Any], definitions: Dict[str, Any], pointer: str) -> None:
    where = pointer or "/"
    if "properties" not in schema and "optionalProperties" not in schema:
        raise ValueError(f"{where}: the properties form needs `properties` or `optionalProperties`")
    if not isinstance(schema.get("additionalProperties", False), bool):
        raise ValueError(f"{where}: `additionalProperties` must be a boolean")
    for keyword in ("properties", "optionalProperties"):
        members = schema.get(keyword, {})
        if not isinstance(members, dict):
            raise ValueError(f"{where}: `{keyword}` must be an object")
        for name, sub in members.items():
            _check(sub, definitions, f"{pointer}/{keyword}/{name}")
    common = set(schema.get("properties", {})) & set(schema.get("optionalProperties", {}))
    if common:
        raise ValueError(f"{where}: {sorted(common)} are in both `properties` and `optionalProperties`")


def _check_discriminator(schema: Dict[str, Any], definitions: Dict[str, Any], pointer: str) -> None:
    where = pointer or "/"
    tag, mapping = schema.get("discriminator"), schema.get("mapping")
    if not isinstance(tag, str) or not isinstance(mapping, dict):
        raise ValueError(f"{where}: `discriminator` must be a string and `mapping` an object")
    for name, sub in mapping.items():
        child = f"{pointer}/mapping/{name}"
        _check(sub, definitions, child)
        if not isinstance(sub, dict) or not ({"properties", "optionalProperties"} & set(sub)):
            raise ValueError(f"{child}: a `mapping` value must be of the properties form")
        if sub.get("nullable"):
            raise ValueError(f"{child}: a `mapping` value must not be nullable")
        if tag in sub.get("properties", {}) or tag in sub.get("optionalProperties", {}):
            raise ValueError(f"{child}: a `mapping` value must not declare the discriminator {tag!r}")
