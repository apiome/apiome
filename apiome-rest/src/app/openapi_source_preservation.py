"""Preserve an imported OpenAPI document through the canonical model — COA-2.1 (#7044).

The canonical model (:mod:`app.canonical_model`) is paradigm-neutral by design: it keeps
operations, parameters, messages and named types, but not OpenAPI-only constructs such as
``callbacks``, ``links``, ``webhooks``, ``discriminator``, ``x-`` extensions, ``$self``,
``jsonSchemaDialect``, ``$dynamicRef`` or a 3.2 ``itemSchema``. Before this module, an OpenAPI
document normalized and emitted back to OpenAPI silently lost all of them.

The fix is a *source preservation* bag, written by the OpenAPI normalizer and read back by the
OpenAPI emitter:

* **capture** (:func:`capture_source`) — after normalization the source objects are stored,
  verbatim, under :data:`OPENAPI_SOURCE_EXTRA` in the ``extras`` of the entity that owns them:
  the API (document root, ``components`` sections other than ``schemas``, path-item fields),
  each :class:`~app.canonical_model.Operation` (its whole Operation Object) and each named
  :class:`~app.canonical_model.Type` (its whole Schema Object). Each entry carries a **digest**
  of the entity as the canonical model holds it at import time.
* **restore** (:func:`restore_source`) — when the emitter writes an entity whose digest still
  matches, the entity is unedited and its source object is written back verbatim. When the
  digest differs, the entity was edited after import: the emitter's own output stands, only the
  source keys the canonical model has no field for are added back, and a loss is recorded
  naming what could not be re-applied. Nothing is dropped without a loss.
* **version gates** (:func:`gate_constructs`) — a construct the target version cannot carry
  (``$self`` or ``itemSchema`` at 3.1, ``webhooks`` at 3.0, …) is removed and recorded as a loss.
  A 3.0 source written at 3.1 / 3.2 has its schemas rewritten into the JSON Schema 2020-12
  forms (:func:`upgrade_schema_30_to_31`): ``nullable`` becomes a ``"null"`` type and boolean
  ``exclusiveMinimum`` / ``exclusiveMaximum`` become numeric. Each rewrite is recorded
  (COA-2.3): as a provenance note when faithful, as a loss when not.
* **dialect** — the source's JSON Schema dialect (``jsonSchemaDialect``, or the version's
  default) is kept in the bag as ``schemaDialect`` (COA-2.3,
  :mod:`app.openapi_schema_dialect`).

The bag is opaque to everything else: the canonical diff ignores ``extras``, and both
fingerprints exclude :data:`OPENAPI_SOURCE_EXTRA` exactly as they exclude ``raw`` (it is the
same information), so stored fingerprints are unchanged. All functions are pure apart from the
documented in-place updates of the emitter's working document.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from .canonical_model import CanonicalApi, Operation
from .emitter import LossKind, LossTracker
from .openapi_document_walk import HTTP_METHODS, Node, join_pointer, walk_document
from .openapi_schema_dialect import document_dialect

__all__ = [
    "OPENAPI_SOURCE_EXTRA",
    "capture_source",
    "entity_digest",
    "gate_constructs",
    "json_safe",
    "preserved_source",
    "restore_source",
    "source_family",
    "strip_source_extra",
    "upgrade_document_30_to_31",
    "upgrade_schema_30_to_31",
    "without_source_extra",
]

#: ``extras`` key holding an entity's preserved OpenAPI source object and digest.
OPENAPI_SOURCE_EXTRA = "openapiSource"

# Root keys the emitter always writes itself (never copied from the source).
_ROOT_REGENERATED = frozenset({"openapi", "paths", "components"})
# Root keys the canonical model holds (title / version / description / servers); an edited
# root keeps the emitter's values for these.
_ROOT_MODELLED = frozenset({"info", "servers"})
_INFO_MODELLED = frozenset({"title", "version", "description"})

# Operation Object fields the canonical model holds; an edited operation keeps the emitter's
# values for these and gets every other source field back.
_OPERATION_MODELLED = frozenset(
    {
        "operationId",
        "summary",
        "description",
        "deprecated",
        "tags",
        "parameters",
        "requestBody",
        "responses",
    }
)

# Schema keywords :class:`~app.normalizer.SchemaCoercer` turns into canonical fields; an edited
# named type keeps the emitter's values for these and gets every other keyword back.
_SCHEMA_MODELLED = frozenset(
    {
        "type",
        "properties",
        "required",
        "items",
        "additionalProperties",
        "enum",
        "oneOf",
        "anyOf",
        "description",
        "deprecated",
        "default",
        "format",
        "nullable",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
        "$ref",
    }
)

# Path Item keys that are operations (placed by the emitter from the canonical operations).
_PATH_OPERATION_KEYS = frozenset(HTTP_METHODS) | {"additionalOperations"}

_REF_PREFIX = "#/components/schemas/"

#: OpenAPI version family → ordinal, for "is this construct available at the target?".
_FAMILY_ORDER = {"2.0": 0, "3.0": 1, "3.1": 2, "3.2": 3}

# (object kind, key, first version family that has it). A key of a newer family than the
# target is removed by :func:`gate_constructs` and recorded as a loss.
_VERSION_GATES: Tuple[Tuple[str, str, str], ...] = (
    ("root", "$self", "3.2"),
    ("root", "jsonSchemaDialect", "3.1"),
    ("root", "webhooks", "3.1"),
    ("info", "summary", "3.1"),
    ("license", "identifier", "3.1"),
    ("components", "pathItems", "3.1"),
    ("components", "mediaTypes", "3.2"),
    ("tag", "parent", "3.2"),
    ("tag", "kind", "3.2"),
    ("tag", "summary", "3.2"),
    ("server", "name", "3.2"),
    ("response", "summary", "3.2"),
    ("media_type", "itemSchema", "3.2"),
    ("media_type", "itemEncoding", "3.2"),
    ("media_type", "prefixEncoding", "3.2"),
    ("encoding", "encoding", "3.2"),
    ("encoding", "itemEncoding", "3.2"),
    ("encoding", "prefixEncoding", "3.2"),
    ("example", "dataValue", "3.2"),
    ("example", "serializedValue", "3.2"),
    ("security_scheme", "deprecated", "3.2"),
    ("security_scheme", "oauth2MetadataUrl", "3.2"),
)


# ======================================================================================
# Digests
# ======================================================================================


def strip_source_extra(node: Any) -> Any:
    """Return a copy of a dumped model ``node`` with every :data:`OPENAPI_SOURCE_EXTRA` removed.

    Used for digests here and by both canonical fingerprints, so the preserved source never
    changes a model's identity.
    """
    if isinstance(node, dict):
        return {
            key: (
                {k: strip_source_extra(v) for k, v in value.items() if k != OPENAPI_SOURCE_EXTRA}
                if key == "extras" and isinstance(value, dict)
                else strip_source_extra(value)
            )
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [strip_source_extra(value) for value in node]
    return node


def without_source_extra(extras: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """An entity's ``extras`` without :data:`OPENAPI_SOURCE_EXTRA`.

    For emitters that report "source-specific details are not written" whenever ``extras``
    is non-empty: the bag is only for the OpenAPI target, so it is not such a detail.
    """
    return {key: value for key, value in (extras or {}).items() if key != OPENAPI_SOURCE_EXTRA}


def _digest(payload: Any) -> str:
    """SHA-256 of ``payload`` as compact, key-sorted JSON."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def entity_digest(entity: Any) -> str:
    """Digest of a canonical entity as the model holds it, ignoring its preserved source.

    Args:
        entity: An :class:`~app.canonical_model.Operation` or :class:`~app.canonical_model.Type`.

    Returns:
        A hex SHA-256 that changes whenever any modelled field of the entity changes.
    """
    return _digest(strip_source_extra(entity.model_dump(mode="json")))


def _root_digest(api: CanonicalApi) -> str:
    """Digest of the document-level fields the canonical model holds."""
    return _digest(
        {
            "title": api.title,
            "version": api.version,
            "description": api.description,
            "servers": strip_source_extra([s.model_dump(mode="json") for s in api.servers]),
        }
    )


# ======================================================================================
# Capture (normalizer side)
# ======================================================================================


def source_family(version: Any) -> str:
    """The OpenAPI version family of a version string: ``3.0`` / ``3.1`` / ``3.2`` / ``2.0``."""
    text = str(version or "")
    for family in ("3.0", "3.1", "3.2", "2.0"):
        if text.startswith(family):
            return family
    return "3.2" if text.startswith("3.") else "3.1"


def capture_source(api: CanonicalApi, source: Dict[str, Any]) -> CanonicalApi:
    """Store ``source``'s objects on ``api`` so the emitter can write them back verbatim.

    Must run on the final, order-normalized model (digests are taken over it). Mutates and
    returns ``api``.

    Args:
        api: The model the OpenAPI normalizer just built from ``source``.
        source: The parsed OpenAPI 3.x document.

    Returns:
        ``api``, with :data:`OPENAPI_SOURCE_EXTRA` set on the API, on every operation that came
        from a path, and on every named type (``{"synthesized": true}`` for types the coercer
        invented, which the emitter drops again when nothing references them).
    """
    # ``json_safe`` returns a fresh copy, and no two entries below share an object, so the
    # pieces are stored as they are.
    source = json_safe(source)
    components = source.get("components") if isinstance(source.get("components"), dict) else {}
    schemas = components.get("schemas") if isinstance(components.get("schemas"), dict) else {}

    root = {
        key: value for key, value in source.items() if key not in ("openapi", "paths", "components")
    }
    other_sections = {key: value for key, value in components.items() if key != "schemas"}
    path_items: Dict[str, Dict[str, Any]] = {}
    paths = source.get("paths") if isinstance(source.get("paths"), dict) else {}
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        residue = {k: v for k, v in item.items() if k not in _PATH_OPERATION_KEYS}
        has_operations = any(k in item for k in _PATH_OPERATION_KEYS)
        if residue or not has_operations:
            path_items[str(path)] = residue

    for service in api.services:
        for operation in service.operations:
            op_obj = _source_operation(paths, operation)
            if op_obj is not None:
                operation.extras[OPENAPI_SOURCE_EXTRA] = {
                    "object": op_obj,
                    "digest": entity_digest(operation),
                }

    for type_ in api.types:
        schema = schemas.get(type_.key)
        if isinstance(schema, dict):
            type_.extras[OPENAPI_SOURCE_EXTRA] = {
                "object": schema,
                "digest": entity_digest(type_),
            }
        else:
            type_.extras[OPENAPI_SOURCE_EXTRA] = {"synthesized": True}

    api.extras[OPENAPI_SOURCE_EXTRA] = {
        "version": str(source.get("openapi") or ""),
        "object": root,
        "digest": _root_digest(api),
        "rootOrder": [str(key) for key in source],
        "components": other_sections,
        "hasComponents": isinstance(source.get("components"), dict),
        "schemaOrder": [str(name) for name in schemas],
        # Component schemas the coercer cannot model (a boolean schema) are kept verbatim.
        "unmodelledSchemas": {
            str(name): schema for name, schema in schemas.items() if not isinstance(schema, dict)
        },
        "pathOrder": [str(path) for path in paths],
        "pathItems": path_items,
        # COA-2.3: the JSON Schema dialect the source's schemas are written in, and whether the
        # author declared it (``jsonSchemaDialect``) or it is the version's default.
        "schemaDialect": document_dialect(source),
    }
    return api


def json_safe(value: Any) -> Any:
    """Return a JSON-compatible deep copy of a parsed YAML/JSON ``value``.

    YAML loaders turn an unquoted ``2024-01-01`` into a :class:`datetime.date`; JSON (and so
    every emitted document) has no such type, so dates and times become their ISO 8601 text —
    the value a JSON consumer of the same document reads.
    """
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    return value


def _source_operation(paths: Dict[str, Any], operation: Operation) -> Optional[Dict[str, Any]]:
    """Find the source Operation Object a canonical operation was normalized from."""
    if not operation.http_path or not operation.http_method:
        return None
    item = paths.get(operation.http_path)
    if not isinstance(item, dict):
        return None
    method = operation.http_method.lower()
    if method in HTTP_METHODS and isinstance(item.get(method), dict):
        return item[method]
    additional = item.get("additionalOperations")
    if isinstance(additional, dict):
        for name, op_obj in additional.items():
            if isinstance(name, str) and name.lower() == method and isinstance(op_obj, dict):
                return op_obj
    return None


def preserved_source(api: CanonicalApi) -> Optional[Dict[str, Any]]:
    """The document-level preservation bag on ``api``, or ``None`` when it has none."""
    bag = (api.extras or {}).get(OPENAPI_SOURCE_EXTRA)
    return bag if isinstance(bag, dict) and isinstance(bag.get("object"), dict) else None


# ======================================================================================
# Restore (emitter side)
# ======================================================================================

#: Locates the emitted Operation Object for a canonical operation in a path item:
#: ``(path_item, http_method_lowercase) → (container, key)``, or ``None``.
OperationSlot = Callable[[Dict[str, Any], str], Optional[Tuple[Dict[str, Any], str]]]


def restore_source(
    document: Dict[str, Any],
    api: CanonicalApi,
    *,
    operation_slot: OperationSlot,
    losses: LossTracker,
) -> List[str]:
    """Write ``api``'s preserved OpenAPI source objects back into the emitted ``document``.

    Updates ``document`` in place. Unedited entities are written verbatim; edited ones keep
    the emitter's output plus the source keys the canonical model does not hold, with a loss
    recorded when that is not the whole source object (see the module docstring).

    Args:
        document: The emitter's working document (OpenAPI 3.x shape).
        api: The canonical model being emitted.
        operation_slot: Where the emitter placed each operation (see :data:`OperationSlot`).
        losses: Tracker the edited-entity losses are recorded on.

    Returns:
        The JSON Pointers of the objects written from the preserved source (for provenance).
    """
    bag = preserved_source(api)
    if bag is None:
        return []
    restored: List[str] = []
    _restore_root(document, api, bag, losses, restored)
    _restore_paths(document, bag, restored)
    _restore_operations(document, api, operation_slot, losses, restored)
    _restore_components(document, api, bag, losses, restored)
    _order_like(document, bag.get("rootOrder") or [])
    return restored


def _restore_root(
    document: Dict[str, Any],
    api: CanonicalApi,
    bag: Dict[str, Any],
    losses: LossTracker,
    restored: List[str],
) -> None:
    """Write the root fields (info, servers, tags, webhooks, ``$self``, extensions…)."""
    source_root: Dict[str, Any] = bag["object"]
    unedited = bag.get("digest") == _root_digest(api)
    for key, value in source_root.items():
        if key in _ROOT_REGENERATED:
            continue
        if unedited or key not in _ROOT_MODELLED:
            document[key] = copy.deepcopy(value)
            restored.append(join_pointer("", key))
            continue
        if key == "info" and isinstance(value, dict) and isinstance(document.get("info"), dict):
            for info_key, info_value in value.items():
                if info_key not in _INFO_MODELLED:
                    document["info"].setdefault(info_key, copy.deepcopy(info_value))
    if not unedited:
        losses.record(
            LossKind.INFERRED,
            "openapi-edited-document",
            "the document title, version, description or servers changed after import; "
            "the emitted values come from the canonical model and the source info and servers "
            "objects were not written back verbatim",
            pointer="#/info",
        )


def _restore_paths(document: Dict[str, Any], bag: Dict[str, Any], restored: List[str]) -> None:
    """Write path-item fields (summary, servers, shared parameters, ``$ref``, extensions)."""
    paths = document.setdefault("paths", {})
    for path, residue in (bag.get("pathItems") or {}).items():
        item = paths.setdefault(path, {})
        for key, value in residue.items():
            item[key] = copy.deepcopy(value)
        if residue:
            restored.append(join_pointer("/paths", path))
        # Path-item fields first, operations after — the order a reader expects.
        _order_like(item, list(residue))
    _order_like(paths, bag.get("pathOrder") or [])


def _restore_operations(
    document: Dict[str, Any],
    api: CanonicalApi,
    operation_slot: OperationSlot,
    losses: LossTracker,
    restored: List[str],
) -> None:
    """Write each operation's source Operation Object (verbatim when unedited)."""
    paths = document.get("paths") or {}
    for service in api.services:
        for operation in service.operations:
            entry = operation.extras.get(OPENAPI_SOURCE_EXTRA)
            if not isinstance(entry, dict) or not isinstance(entry.get("object"), dict):
                continue
            item = paths.get(operation.http_path or "")
            slot = (
                operation_slot(item, (operation.http_method or "").lower())
                if isinstance(item, dict)
                else None
            )
            if slot is None:
                continue
            container, key = slot
            emitted = container[key]
            source_op: Dict[str, Any] = entry["object"]
            pointer = join_pointer("/paths", operation.http_path or "", key)
            if entry.get("digest") == entity_digest(operation):
                # Verbatim: not even a synthesized operationId is added, so a re-import names
                # the operation exactly as the source did.
                container[key] = copy.deepcopy(source_op)
            else:
                merged = dict(emitted)
                for field, value in source_op.items():
                    if field not in _OPERATION_MODELLED:
                        merged[field] = copy.deepcopy(value)
                container[key] = merged
                _record_edited(losses, "operation", operation.key, pointer)
            restored.append(pointer)


def _restore_components(
    document: Dict[str, Any],
    api: CanonicalApi,
    bag: Dict[str, Any],
    losses: LossTracker,
    restored: List[str],
) -> None:
    """Write component schemas (verbatim when unedited) and the other component sections."""
    sections: Dict[str, Any] = bag.get("components") or {}
    components = document.get("components")
    if not isinstance(components, dict):
        components = {}
    schemas = components.get("schemas") if isinstance(components.get("schemas"), dict) else {}

    for type_ in api.types:
        entry = type_.extras.get(OPENAPI_SOURCE_EXTRA)
        if not isinstance(entry, dict) or not isinstance(entry.get("object"), dict):
            continue
        source_schema: Dict[str, Any] = entry["object"]
        pointer = join_pointer("/components/schemas", type_.key)
        if entry.get("digest") == entity_digest(type_):
            schemas[type_.key] = copy.deepcopy(source_schema)
        else:
            merged = dict(schemas.get(type_.key) or {})
            for keyword, value in source_schema.items():
                if keyword not in _SCHEMA_MODELLED:
                    merged[keyword] = copy.deepcopy(value)
            schemas[type_.key] = merged
            _record_edited(losses, "schema", type_.key, pointer)
        restored.append(pointer)
    for name, schema in (bag.get("unmodelledSchemas") or {}).items():
        schemas[name] = copy.deepcopy(schema)
        restored.append(join_pointer("/components/schemas", name))

    _drop_unreferenced_synthesized(document, schemas, api)
    _order_like(schemas, bag.get("schemaOrder") or [])

    rebuilt: Dict[str, Any] = {}
    if schemas or "schemas" in components:
        rebuilt["schemas"] = schemas
    for section, entries in sections.items():
        current = components.get(section)
        if isinstance(current, dict) and isinstance(entries, dict):
            rebuilt[section] = {**current, **copy.deepcopy(entries)}
        else:
            rebuilt[section] = copy.deepcopy(entries)
        restored.append(join_pointer("/components", section))
    for section, entries in components.items():
        rebuilt.setdefault(section, entries)
    if rebuilt or bag.get("hasComponents"):
        document["components"] = rebuilt
    else:
        document.pop("components", None)


def _drop_unreferenced_synthesized(
    document: Dict[str, Any], schemas: Dict[str, Any], api: CanonicalApi
) -> None:
    """Remove coercer-invented types that no ``$ref`` in the document points at any more.

    The normalizer lifts inline enums into named types so they diff by identity; once the
    source objects are written back verbatim, nothing refers to those names and writing them
    would add components the source never had.
    """
    synthesized = {
        type_.key
        for type_ in api.types
        if isinstance(type_.extras.get(OPENAPI_SOURCE_EXTRA), dict)
        and type_.extras[OPENAPI_SOURCE_EXTRA].get("synthesized")
    }
    while synthesized:
        referenced = _referenced_schema_names(document)
        unused = {name for name in synthesized if name in schemas and name not in referenced}
        if not unused:
            return
        for name in unused:
            del schemas[name]
        synthesized -= unused


def _referenced_schema_names(node: Any) -> Set[str]:
    """Every ``#/components/schemas/<name>`` a ``$ref`` (or ``$dynamicRef``) points at."""
    names: Set[str] = set()
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                if key in ("$ref", "$dynamicRef") and isinstance(value, str):
                    if value.startswith(_REF_PREFIX):
                        names.add(value[len(_REF_PREFIX) :].split("/", 1)[0])
                else:
                    stack.append(value)
        elif isinstance(current, list):
            stack.extend(current)
    return names


def _record_edited(losses: LossTracker, what: str, key: str, pointer: str) -> None:
    """Record the loss for an entity edited after import (its source is not written verbatim)."""
    losses.record(
        LossKind.INFERRED,
        f"openapi-edited-{what}",
        f"{what} {key} changed after import; it is emitted from the canonical model, and only "
        "the source fields the model has no place for were written back, so source detail "
        "inside the changed fields (schema keywords, examples, serialization) may be missing",
        pointer="#" + pointer,
    )


def _order_like(mapping: Dict[str, Any], order: Iterable[str]) -> None:
    """Reorder ``mapping`` in place: keys in ``order`` first (in that order), then the rest."""
    if not isinstance(mapping, dict):
        return
    ordered = {key: mapping[key] for key in order if key in mapping}
    for key, value in mapping.items():
        ordered.setdefault(key, value)
    mapping.clear()
    mapping.update(ordered)


# ======================================================================================
# Version gates and the 3.0 → 3.1 schema upgrade
# ======================================================================================


def gate_constructs(document: Dict[str, Any], target: str, losses: LossTracker) -> None:
    """Remove every construct newer than the ``target`` version family, recording each loss.

    Updates ``document`` in place. Covers the keys in :data:`_VERSION_GATES`, ``in:
    querystring`` parameters and the device-authorization OAuth flow (both 3.2), and
    ``discriminator.defaultMapping`` (3.2).

    Args:
        document: An emitted OpenAPI 3.x document.
        target: The target version family (``3.0`` / ``3.1`` / ``3.2``).
        losses: Tracker each removal is recorded on.
    """
    level = _FAMILY_ORDER.get(target, _FAMILY_ORDER["3.2"])
    gates = [(kind, key, family) for kind, key, family in _VERSION_GATES if _FAMILY_ORDER[family] > level]
    removals: List[Tuple[Dict[str, Any], str, str, str]] = []
    list_removals: List[Tuple[List[Any], int, str]] = []
    for node in walk_document(document):
        for kind, key, family in gates:
            if node.kind == kind and key in node.value:
                removals.append((node.value, key, join_pointer(node.pointer, key), family))
        if level < _FAMILY_ORDER["3.2"]:
            _collect_32_only(node, document, removals, list_removals)
    for container, key, pointer, family in removals:
        if key in container:
            del container[key]
            _record_gate(losses, key, pointer, family, target)
    for values, index, pointer in sorted(list_removals, key=lambda item: -item[1]):
        del values[index]
        _record_gate(losses, "querystring", pointer, "3.2", target)


def _collect_32_only(
    node: Node,
    document: Dict[str, Any],
    removals: List[Tuple[Dict[str, Any], str, str, str]],
    list_removals: List[Tuple[List[Any], int, str]],
) -> None:
    """Collect the 3.2-only constructs that are not a plain key of one object kind."""
    if node.kind == "security_scheme" and isinstance(node.value.get("flows"), dict):
        if "deviceAuthorization" in node.value["flows"]:
            removals.append(
                (
                    node.value["flows"],
                    "deviceAuthorization",
                    join_pointer(node.pointer, "flows", "deviceAuthorization"),
                    "3.2",
                )
            )
    if node.kind == "schema" and isinstance(node.value.get("discriminator"), dict):
        if "defaultMapping" in node.value["discriminator"]:
            removals.append(
                (
                    node.value["discriminator"],
                    "defaultMapping",
                    join_pointer(node.pointer, "discriminator", "defaultMapping"),
                    "3.2",
                )
            )
    if node.kind in ("path_item", "operation"):
        parameters = node.value.get("parameters")
        if isinstance(parameters, list):
            for index, parameter in enumerate(parameters):
                if isinstance(parameter, dict) and parameter.get("in") == "querystring":
                    list_removals.append(
                        (parameters, index, join_pointer(node.pointer, "parameters", index))
                    )


def _record_gate(losses: LossTracker, key: str, pointer: str, family: str, target: str) -> None:
    """Record one version-gate removal."""
    losses.record(
        LossKind.NA,
        f"openapi-{family}-only",
        f"{key} exists only in OpenAPI {family} and later; it has no OpenAPI {target} form "
        "and was not written",
        pointer="#" + pointer,
    )


def upgrade_schema_30_to_31(
    schema: Dict[str, Any],
    losses: Optional[LossTracker] = None,
    pointer: str = "",
) -> None:
    """Rewrite one OpenAPI 3.0 Schema Object into its JSON Schema 2020-12 form, in place.

    Only the object's own keywords are rewritten (callers walk subschemas): ``nullable:
    true`` adds ``"null"`` to ``type`` (and to ``enum``), or wraps the schema in ``anyOf``
    with a null schema when it has no ``type``; ``nullable: false`` is dropped; a boolean
    ``exclusiveMinimum`` / ``exclusiveMaximum`` takes the bound's number.

    These rewrites are faithful; the emitter records each one as an inferred provenance note
    (:func:`app.openapi_schema_dialect.record_schema_rewrites`). One is not (COA-2.3): OpenAPI
    3.0 ignores every keyword next to ``$ref``, so ``nullable: true`` there had no effect, while
    the 2020-12 form makes the reference accept ``null``. That rewrite is recorded on
    ``losses`` as ``openapi-30-nullable-ref``.

    Args:
        schema: The Schema Object to rewrite.
        losses: Tracker for the lossy case; ``None`` records nothing.
        pointer: The schema's JSON Pointer in the document (for the loss).
    """
    if "nullable" in schema:
        nullable = schema.pop("nullable")
        if nullable is True:
            if "$ref" in schema and losses is not None:
                losses.record(
                    LossKind.INFERRED,
                    "openapi-30-nullable-ref",
                    "OpenAPI 3.0 ignores nullable next to $ref; the 3.1 form lets the reference "
                    "also accept null, which is what the source most likely meant",
                    pointer="#" + pointer,
                )
            _add_null(schema)
    for exclusive_key, bound_key in (("exclusiveMinimum", "minimum"), ("exclusiveMaximum", "maximum")):
        value = schema.get(exclusive_key)
        if not isinstance(value, bool):
            continue
        if value and isinstance(schema.get(bound_key), (int, float)):
            schema[exclusive_key] = schema.pop(bound_key)
        else:
            del schema[exclusive_key]


def _add_null(schema: Dict[str, Any]) -> None:
    """Make ``schema`` also accept ``null`` (the 2020-12 spelling of ``nullable: true``)."""
    type_ = schema.get("type")
    if isinstance(type_, str):
        schema["type"] = [type_, "null"]
    elif isinstance(type_, list):
        if "null" not in type_:
            schema["type"] = [*type_, "null"]
    else:
        rest = dict(schema)
        schema.clear()
        schema["anyOf"] = [rest, {"type": "null"}]
        return
    enum = schema.get("enum")
    if isinstance(enum, list) and None not in enum:
        schema["enum"] = [*enum, None]


def upgrade_document_30_to_31(
    document: Dict[str, Any], losses: Optional[LossTracker] = None
) -> None:
    """Rewrite every schema of an OpenAPI document from the 3.0 forms to 2020-12, in place.

    Safe on schemas already in the 2020-12 form (nothing to rewrite), so it can run over a
    whole emitted document whose modelled parts are already 3.1.

    Args:
        document: The document to rewrite.
        losses: Tracker for the lossy rewrites (see :func:`upgrade_schema_30_to_31`).
    """
    for node in walk_document(document):
        if node.kind == "schema":
            upgrade_schema_30_to_31(node.value, losses, node.pointer)
