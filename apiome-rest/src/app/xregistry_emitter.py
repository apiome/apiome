"""xRegistry document emitter: canonical model → CNCF xRegistry — MFX-34.1 (#4306).

`xRegistry <https://xregistry.io>`_ is the CloudEvents project's catalog model. This module writes
one xRegistry JSON document holding two of its registries, in the shape the xRegistry importer
(:mod:`app.xregistry_parser` / :mod:`app.xregistry_normalizer`, MFI-19.2) reads, so an export
imports straight back:

* **a schema registry** — ``schemagroups`` → one group (the registry id) → one schema per
  canonical type. Each schema is a JSON Schema (``JsonSchema/draft/2020-12``) projected with the
  MFX-21.1 mapping (:func:`app.canonical_json_schema.build_bundle_schemas`); a reference to another
  type is ``#/definitions/<schema id>``, and the schema carries the types it reaches under
  ``definitions``, so every schema is valid on its own. A schema the source kept as an opaque
  document (an Avro or Protobuf schema an xRegistry import could not read) is written back as it was;
* **a message-definitions registry** — ``messagegroups`` → one group per service → one message per
  event (publish / subscribe) operation. Each message has the ``CloudEvents/1.0`` envelope and its
  CloudEvents attributes in ``envelopemetadata``: ``type`` and ``source`` (each with a ``value``),
  then the message's other headers; ``datacontenttype``; and the payload schema —
  ``dataschemaformat`` + ``dataschemaxid`` (``/schemagroups/<group>/schemas/<schema>``) for a named
  type, or an inline ``dataschema``.

**CloudEvents attributes.** ``type``: the operation's ``cloudevents_type``, else the channel's
address, else the operation's name. ``source``: the operation's or channel's ``cloudevents_source``,
else a ``source`` header's default, else the ``source`` option (default ``/<registry id>``).
``datacontenttype``: the event message's first content type, else ``application/json``. A value the
source did not state is recorded as synthesized.

Request/response operations have no message form and are not written (an xRegistry message is an
event); xRegistry ``endpoints`` are not written either (the API's servers are reported dropped).
Every document is checked (:func:`xregistry_document_problems`) before it is returned, so an
invalid document cannot ship.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple, Union

from jsonschema import Draft7Validator, Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import Field, ValidationError

from .canonical_json_schema import build_bundle_schemas, build_ref_json_schema
from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    Type,
)
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitOptionsError,
    EmitPreconditionError,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
)
from .export_viz_modes import ExportVizModeKind
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict
from .lossiness import LossinessKind, LossinessReport, LossinessSeverity

__all__ = [
    "XREGISTRY_FORMAT_KEY",
    "XRegistryEmitOptions",
    "XRegistryEmitter",
    "XRegistryFidelityRulePack",
    "EVENT_REGISTRY_MAPPING",
    "build_xregistry_document",
    "event_registry_advisory",
    "xregistry_document_problems",
    "xregistry_schema_violations",
]

#: Registry key and format — the same key as the xRegistry importer, so ``xregistry -> xregistry``
#: pairs in the round-trip matrix without an alias.
XREGISTRY_FORMAT_KEY = "xregistry"
#: The xRegistry ``specversion`` written (the one the corpus and the importer use).
SPEC_VERSION = "1.0-rc1"
#: The ``format`` of every schema Apiome projects, and its ``$schema`` dialect.
SCHEMA_FORMAT = "JsonSchema/draft/2020-12"
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
#: The envelope of every message.
ENVELOPE = "CloudEvents/1.0"
#: The ``datacontenttype`` written when the source states none.
DEFAULT_CONTENT_TYPE = "application/json"
OUTPUT_MEDIA_TYPE = "application/json"
#: Suffix of the emitted document.
DOCUMENT_SUFFIX = ".xregistry.json"
#: The one version every projected schema has.
VERSION_ID = "1"

#: The official xRegistry CloudEvents registry document schema, vendored at a pinned commit (MFX-34.3).
_DOCUMENT_SCHEMA_PATH = Path(__file__).parent / "data" / "xregistry_cloudevents_document_schema.json"
#: ``target_mapping`` of the critical advisory a source with request/response operations gets (MFX-34.3).
EVENT_REGISTRY_MAPPING = "event-registry-only"

#: Loss subjects this emitter records.
LOSS_NOT_AN_EVENT = "xregistry-operation-not-an-event"
LOSS_ATTRIBUTE_SYNTHESIZED = "xregistry-cloudevents-attribute-synthesized"
LOSS_ID_SYNTHESIZED = "xregistry-id-synthesized"
LOSS_ENDPOINTS_NOT_WRITTEN = "xregistry-endpoints-not-written"
LOSS_BINDINGS_NOT_WRITTEN = "xregistry-bindings-not-written"

#: The operation kinds an xRegistry message stands for.
_EVENT_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
#: The CloudEvents attributes the emitter writes itself (a header of the same name supplies its value).
_DERIVED_ATTRIBUTES = ("type", "source")
#: Canonical scalar → xRegistry attribute ``type`` (everything else is a ``string``).
_ATTRIBUTE_TYPES = {"integer": "integer", "int": "integer", "int32": "integer", "int64": "integer",
                    "boolean": "boolean", "bool": "boolean", "number": "decimal", "float": "decimal",
                    "double": "decimal"}
#: An xRegistry id: letters, digits and ``_ . - ~ @``, not starting with ``.``, ``-``, ``~`` or ``@``.
_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-~@]{0,127}$")
_ID_BAD = re.compile(r"[^A-Za-z0-9_.\-~@]+")
_REF_DEFS = "#/$defs/"
_REF_DEFINITIONS = "#/definitions/"


class XRegistryEmitOptions(EmitOptions):
    """Per-target options for :class:`XRegistryEmitter`."""

    registry_id: Optional[str] = Field(
        default=None,
        description="The document's `registryid`, which also names the schema group. Empty means a "
        "slug of the item's name.",
    )
    source: Optional[str] = Field(
        default=None,
        description="The CloudEvents `source` written for a message whose source states none. Empty "
        "means `/<registry id>`.",
    )
    indent: int = Field(default=2, ge=0, le=8, description="JSON indentation width (0 for compact output).")


# ===========================================================================
# Ids
# ===========================================================================


def _xid(text: str, fallback: str) -> str:
    """``text`` as a legal xRegistry id: other characters become ``_``, a bad first one is prefixed."""
    cleaned = _ID_BAD.sub("_", text.strip())[:128] or fallback
    if not _ID_RE.match(cleaned):
        cleaned = f"_{cleaned}"[:128]
    return cleaned


def _unique(candidate: str, taken: Set[str]) -> str:
    """``candidate``, or ``candidate_2``, ``_3`` … — the first not in ``taken`` (which it joins)."""
    name, index = candidate, 2
    while name in taken:
        name = f"{candidate}_{index}"
        index += 1
    taken.add(name)
    return name


def _registry_id(api: CanonicalApi, options: XRegistryEmitOptions) -> Tuple[str, bool]:
    """The registry id and whether it was synthesized (not the option, nor the source's own id)."""
    if options.registry_id:
        return _xid(options.registry_id, "registry"), False
    # An imported xRegistry document keeps its ``registryid`` as the identity id.
    own = api.identity.id if (api.format or "").startswith(XREGISTRY_FORMAT_KEY) else None
    if isinstance(own, str) and own.strip():
        return _xid(own, "registry"), False
    base = api.identity.name or api.title or "registry"
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-") or "registry"
    return _xid(slug, "registry"), True


# ===========================================================================
# The plan: what goes where
# ===========================================================================


@dataclass
class _Plan:
    """The document being assembled, and what it cost.

    Attributes:
        document: The xRegistry document.
        schema_of: Canonical type key → the schema id it was written as.
        message_of: Operation key → ``(message group id, message id)``.
        synthesized: ``(pointer, reason)`` per value invented because the source lacked it.
        not_written: Operation key → why the operation has no message.
        dropped_types: Type key → why the type has no schema (MFX-34.3).
    """

    document: Dict[str, Any]
    schema_of: Dict[str, str] = field(default_factory=dict)
    message_of: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    synthesized: List[Tuple[str, str]] = field(default_factory=list)
    not_written: Dict[str, str] = field(default_factory=dict)
    dropped_types: Dict[str, str] = field(default_factory=dict)


def _rewrite_refs(node: Any, keys: Mapping[str, str]) -> Any:
    """A copy of ``node`` whose ``#/$defs/<key>`` references read ``#/definitions/<schema id>``."""
    if isinstance(node, list):
        return [_rewrite_refs(item, keys) for item in node]
    if not isinstance(node, dict):
        return node
    out: Dict[str, Any] = {}
    for key, value in node.items():
        if key == "$ref" and isinstance(value, str) and value.startswith(_REF_DEFS):
            target = value[len(_REF_DEFS):]
            out[key] = _REF_DEFINITIONS + keys.get(target, target)
        else:
            out[key] = _rewrite_refs(value, keys)
    return out


def _dedupe_required(node: Any) -> Any:
    """``node`` with each ``required`` list de-duplicated in place (first occurrence kept).

    A record that repeats a field name (a SEPA ``CdtTrfTxInf`` occurring several times) projects to a
    ``required`` list with repeats, which JSON Schema rejects; its ``properties`` already hold the name once.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "required" and isinstance(value, list):
                node[key] = list(dict.fromkeys(value))
            else:
                _dedupe_required(value)
    elif isinstance(node, list):
        for item in node:
            _dedupe_required(item)
    return node


def _refs(node: Any) -> Iterable[str]:
    """Every ``#/definitions/<name>`` target ``node`` references."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str) and value.startswith(_REF_DEFINITIONS):
                yield value[len(_REF_DEFINITIONS):]
            else:
                yield from _refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _refs(item)


def _reached(root: Any, schemas: Mapping[str, Any]) -> List[str]:
    """The schema ids ``root`` reaches through references, transitively, in first-reached order."""
    order: List[str] = []
    stack = list(_refs(root))
    while stack:
        name = stack.pop(0)
        if name in order or name not in schemas:
            continue
        order.append(name)
        stack.extend(_refs(schemas[name]))
    return order


def _opaque_schema(type_: Type) -> Optional[Dict[str, Any]]:
    """The schema entry of a type an xRegistry import kept opaque, written back as it was read."""
    extras = type_.extras or {}
    if not extras.get("xregistry_opaque"):
        return None
    entry: Dict[str, Any] = {}
    fmt = extras.get("xregistry_format") if isinstance(extras.get("xregistry_format"), str) else None
    if fmt:
        entry["format"] = fmt
    if type_.description:
        entry["description"] = type_.description
    version: Dict[str, Any] = {"versionid": str(extras.get("xregistry_version") or VERSION_ID)}
    if fmt:
        version["format"] = fmt  # an xRegistry schema version carries its own format (MFX-34.3)
    if isinstance(extras.get("xregistry_document"), str):
        version["schema"] = extras["xregistry_document"]
    elif isinstance(extras.get("xregistry_schema_uri"), str):
        version["schemaurl"] = extras["xregistry_schema_uri"]
    else:
        return {}  # neither a document nor a URL: no valid schema version can be written
    entry["defaultversionid"] = version["versionid"]
    entry["versions"] = {version["versionid"]: version}
    return entry


def _schemas(api: CanonicalApi, group_id: str, plan: _Plan) -> Dict[str, Any]:
    """The schema group's ``schemas``: one per canonical type."""
    bundle = build_bundle_schemas(api)
    taken: Set[str] = set()
    ids: Dict[str, str] = {}  # $defs key → schema id
    for type_ in api.types:
        defs_key = bundle.defs_keys.get(type_.key)
        if defs_key is None:
            continue
        schema_id = _unique(_xid(defs_key, "schema"), taken)
        ids[defs_key] = schema_id
        plan.schema_of[type_.key] = schema_id
        if schema_id != defs_key:
            plan.synthesized.append((f"/schemagroups/{group_id}/schemas/{schema_id}",
                                     f"type {type_.key!r} is written as schema {schema_id!r} (a legal, unique id)"))
    bodies = {ids[key]: _dedupe_required(_rewrite_refs(body, ids)) for key, body in bundle.defs.items() if key in ids}
    schemas: Dict[str, Any] = {}
    for type_ in api.types:
        schema_id = plan.schema_of.get(type_.key)
        if schema_id is None:
            continue
        opaque = _opaque_schema(type_)
        if opaque == {}:
            plan.dropped_types[type_.key] = (
                "the source schema has neither a document nor a URL, and an xRegistry schema version needs one"
            )
            del plan.schema_of[type_.key]
            continue
        if opaque is not None:
            schemas[schema_id] = {"schemaid": schema_id, **opaque}
            continue
        body = copy.deepcopy(bodies[schema_id])
        document: Dict[str, Any] = {"$schema": SCHEMA_DIALECT, **body}
        reached = _reached(body, bodies)
        if reached:
            document["definitions"] = {name: copy.deepcopy(bodies[name]) for name in reached}
        entry: Dict[str, Any] = {"schemaid": schema_id, "format": SCHEMA_FORMAT}
        if type_.description:
            entry["description"] = type_.description
        if type_.deprecated:
            entry["deprecated"] = {}
        entry["defaultversionid"] = VERSION_ID
        entry["versions"] = {VERSION_ID: {"versionid": VERSION_ID, "format": SCHEMA_FORMAT, "schema": document}}
        schemas[schema_id] = entry
    return schemas


def _event_message(operation: Operation) -> Optional[Message]:
    """The operation's event payload message (else its first message)."""
    for message in operation.messages:
        if message.role is MessageRole.EVENT:
            return message
    return operation.messages[0] if operation.messages else None


def _header_default(message: Optional[Message], name: str) -> Optional[str]:
    """A string default of the header named ``name``, when the message has one."""
    for header in message.headers if message is not None else []:
        if header.name == name and isinstance(header.default, str) and header.default.strip():
            return header.default.strip()
    return None


def _attribute(header: CanonicalField) -> Dict[str, Any]:
    """One header as an xRegistry ``envelopemetadata`` attribute."""
    attribute: Dict[str, Any] = {}
    scalar = (header.type.name or "").lower() if header.type is not None else ""
    attribute["type"] = _ATTRIBUTE_TYPES.get(scalar, "string")
    if header.type is not None and header.type.nullable is False:
        attribute["required"] = True
    if header.description:
        attribute["description"] = header.description
    if header.default is not None:
        attribute["value"] = header.default
    return attribute


class _MessageWriter:
    """Builds the message groups, deriving each message's CloudEvents attributes."""

    def __init__(self, api: CanonicalApi, options: XRegistryEmitOptions, plan: _Plan, group_id: str) -> None:
        self._api = api
        self._plan = plan
        self._group_id = group_id
        self._channels = {channel.key: channel for channel in api.channels}
        self._default_source = options.source or f"/{group_id}"
        self._from_option = bool(options.source)

    def groups(self) -> Dict[str, Any]:
        """``messagegroups``: one group per service that has an event operation."""
        groups: Dict[str, Any] = {}
        group_ids: Set[str] = set()
        for service in self._api.services:
            events = []
            for operation in service.operations:
                if operation.kind in _EVENT_KINDS:
                    events.append(operation)
                else:
                    self._plan.not_written[operation.key] = (
                        f"a {operation.kind.value} operation is not an event; an xRegistry message "
                        "definition describes an event"
                    )
            if not events:
                continue
            gid = _unique(_xid(service.key or service.name, "messages"), group_ids)
            if gid != (service.key or service.name):
                self._plan.synthesized.append((f"/messagegroups/{gid}",
                                               f"service {service.key!r} is written as message group {gid!r}"))
            taken: Set[str] = set()
            messages = {}
            for operation in events:
                mid = _unique(_xid(operation.name or operation.key, "message"), taken)
                messages[mid] = self._message(operation, gid, mid)
                self._plan.message_of[operation.key] = (gid, mid)
            group: Dict[str, Any] = {"messagegroupid": gid, "envelope": ENVELOPE}
            if service.name and service.name != gid:
                group["name"] = service.name
            if service.description:
                group["description"] = service.description
            group["messages"] = messages
            groups[gid] = group
        return groups

    def _message(self, operation: Operation, gid: str, mid: str) -> Dict[str, Any]:
        """One message definition, with its CloudEvents attributes and payload schema."""
        pointer = f"/messagegroups/{gid}/messages/{mid}"
        channel = self._channels.get(operation.channel_ref or "")
        message = _event_message(operation)
        metadata: Dict[str, Any] = {
            "type": {"value": self._event_type(operation, channel, pointer)},
            "source": {"value": self._source(operation, channel, message, pointer)},
        }
        for header in message.headers if message is not None else []:
            if header.name in _DERIVED_ATTRIBUTES:
                attribute = _attribute(header)
                attribute.pop("value", None)
                metadata[header.name].update({k: v for k, v in attribute.items() if k != "type"})
            elif header.name and header.name not in metadata:
                metadata[header.name] = _attribute(header)
        entry: Dict[str, Any] = {"messageid": mid}
        if message is not None and message.name and message.name != mid:
            entry["name"] = message.name
        description = operation.description or (message.description if message is not None else None)
        if description:
            entry["description"] = description
        if operation.deprecated:
            entry["deprecated"] = {}
        entry["envelope"] = ENVELOPE
        entry["envelopemetadata"] = metadata
        content_types = message.content_types if message is not None else []
        if content_types:
            entry["datacontenttype"] = content_types[0]
        else:
            entry["datacontenttype"] = DEFAULT_CONTENT_TYPE
            self._plan.synthesized.append((f"{pointer}/datacontenttype",
                                           f"{operation.key!r} states no content type; "
                                           f"{DEFAULT_CONTENT_TYPE} is written"))
        entry.update(self._payload(message))
        return entry

    def _event_type(self, operation: Operation, channel: Optional[Channel], pointer: str) -> str:
        """The CloudEvents ``type``: the operation's, else the channel address, else the operation name."""
        stated = (operation.extras or {}).get("cloudevents_type")
        if isinstance(stated, str) and stated.strip():
            return stated.strip()
        if channel is not None and channel.address:
            return channel.address
        self._plan.synthesized.append((f"{pointer}/envelopemetadata/type",
                                       f"{operation.key!r} has no CloudEvents type or channel; its name is the type"))
        return operation.name or operation.key

    def _source(
        self, operation: Operation, channel: Optional[Channel], message: Optional[Message], pointer: str
    ) -> str:
        """The CloudEvents ``source``: stated by the operation, channel or a header, else the default."""
        for extras in ((operation.extras or {}), (channel.extras or {}) if channel is not None else {}):
            stated = extras.get("cloudevents_source")
            if isinstance(stated, str) and stated.strip():
                return stated.strip()
        header = _header_default(message, "source")
        if header is not None:
            return header
        if not self._from_option:
            self._plan.synthesized.append((f"{pointer}/envelopemetadata/source",
                                           f"{operation.key!r} states no CloudEvents source; "
                                           f"{self._default_source!r} is written"))
        return self._default_source

    def _payload(self, message: Optional[Message]) -> Dict[str, Any]:
        """The payload schema: a ``dataschemaxid`` to a written schema, else an inline ``dataschema``."""
        if message is None:
            return {}
        ref = message.payload
        if ref is not None and ref.item is None and ref.name:
            schema_id = self._schema_for(ref.name)
            if schema_id is not None:
                return {"dataschemaformat": SCHEMA_FORMAT,
                        "dataschemaxid": f"/schemagroups/{self._group_id}/schemas/{schema_id}"}
        if isinstance(message.payload_schema, Mapping):
            return {"dataschemaformat": SCHEMA_FORMAT, "dataschema": dict(message.payload_schema)}
        if ref is not None:
            projection = build_ref_json_schema(self._api, ref)
            keys = dict(self._plan_ids())
            document = _dedupe_required(_rewrite_refs(projection.document, keys))
            document.pop("$defs", None)
            return {"dataschemaformat": SCHEMA_FORMAT, "dataschema": document}
        return {}

    def _plan_ids(self) -> Iterable[Tuple[str, str]]:
        """``$defs`` key → schema id, for references inside an inline payload schema."""
        bundle = build_bundle_schemas(self._api)
        for type_key, defs_key in bundle.defs_keys.items():
            schema_id = self._plan.schema_of.get(type_key)
            if schema_id is not None:
                yield defs_key, schema_id

    def _schema_for(self, name: str) -> Optional[str]:
        """The schema id of the type ``name`` (a key, else a unique name)."""
        if name in self._plan.schema_of:
            return self._plan.schema_of[name]
        matches = [t.key for t in self._api.types if t.name == name]
        return self._plan.schema_of.get(matches[0]) if len(matches) == 1 else None


def build_xregistry_document(api: CanonicalApi, options: XRegistryEmitOptions) -> _Plan:
    """Plan the xRegistry document for ``api``.

    Args:
        api: The canonical model.
        options: The emit options.

    Returns:
        The plan: the document plus what each construct became and what was synthesized.

    Raises:
        EmitPreconditionError: When the model has neither a type nor an event operation.
    """
    if not api.types and not any(op.kind in _EVENT_KINDS for op in api.operations()):
        raise EmitPreconditionError(
            "An xRegistry document holds schemas and event message definitions, and this model has "
            "neither a type nor an event (publish / subscribe) operation."
        )
    registry_id, synthesized = _registry_id(api, options)
    plan = _Plan(document={"specversion": SPEC_VERSION, "registryid": registry_id})
    if synthesized:
        plan.synthesized.append(("/registryid", f"the registry id {registry_id!r} is a slug of the item's name"))
    if api.title or api.identity.name:
        plan.document["name"] = api.title or api.identity.name
    if api.description:
        plan.document["description"] = api.description
    schemas = _schemas(api, registry_id, plan)
    if schemas:
        plan.document["schemagroups"] = {registry_id: {"schemagroupid": registry_id, "schemas": schemas}}
    groups = _MessageWriter(api, options, plan, registry_id).groups()
    if groups:
        plan.document["messagegroups"] = groups
    return plan


# ===========================================================================
# Checking a document
# ===========================================================================


def _check_id(problems: List[Dict[str, str]], pointer: str, key: str, entry: Mapping[str, Any], id_field: str) -> None:
    """The map key is a legal id and equals the entry's own ``<x>id``."""
    if not _ID_RE.match(key):
        problems.append({"rule": "xregistry-id", "path": pointer, "message": f"{key!r} is not a legal xRegistry id"})
    if entry.get(id_field) not in (None, key):
        problems.append({"rule": "xregistry-id", "path": f"{pointer}/{id_field}",
                         "message": f"{id_field} {entry.get(id_field)!r} differs from its key {key!r}"})


def _check_json_schema(problems: List[Dict[str, str]], pointer: str, document: Any) -> None:
    """A JSON Schema is a valid draft 2020-12 schema whose ``#/definitions`` references resolve."""
    if not isinstance(document, Mapping):
        problems.append({"rule": "xregistry-schema", "path": pointer, "message": "a JSON Schema must be an object"})
        return
    try:
        Draft202012Validator.check_schema(document)
    except SchemaError as exc:
        problems.append({"rule": "json-schema", "path": pointer, "message": exc.message})
    defined = set((document.get("definitions") or {}).keys())
    for name in sorted(set(_refs(document)) - defined):
        problems.append({"rule": "json-schema-ref", "path": pointer,
                         "message": f"#/definitions/{name} does not resolve inside the schema"})


def xregistry_document_problems(document: Any) -> List[Dict[str, str]]:
    """Check an emitted xRegistry document's structure.

    Args:
        document: The parsed document.

    Returns:
        ``{"rule", "path", "message"}`` per problem; empty when the document is valid: string
        ``specversion`` and ``registryid``; legal ids that match their keys; a ``format`` and a
        default version on every schema, every projected JSON Schema valid with its references
        resolving; and on every message the ``CloudEvents/1.0`` envelope, a ``type`` and a
        ``source`` value, a ``datacontenttype``, and a ``dataschemaxid`` that names a schema of the
        document.
    """
    problems: List[Dict[str, str]] = []
    if not isinstance(document, Mapping):
        return [{"rule": "xregistry-document", "path": "/", "message": "the document must be a JSON object"}]
    for key in ("specversion", "registryid"):
        if not isinstance(document.get(key), str) or not document[key]:
            problems.append({"rule": "xregistry-document", "path": f"/{key}", "message": f"{key} must be a string"})
    xids: Set[str] = set()
    for gid, group in (document.get("schemagroups") or {}).items():
        _check_id(problems, f"/schemagroups/{gid}", gid, group, "schemagroupid")
        for sid, schema in (group.get("schemas") or {}).items():
            pointer = f"/schemagroups/{gid}/schemas/{sid}"
            xids.add(pointer)
            _check_id(problems, pointer, sid, schema, "schemaid")
            if not isinstance(schema.get("format"), str):
                problems.append({"rule": "xregistry-schema", "path": f"{pointer}/format",
                                 "message": "format is missing"})
            versions = schema.get("versions") or {}
            default = schema.get("defaultversionid")
            if default not in versions:
                problems.append({"rule": "xregistry-schema", "path": f"{pointer}/defaultversionid",
                                 "message": f"default version {default!r} is not among the versions"})
                continue
            body = versions[default].get("schema")
            if body is None and isinstance(versions[default].get("schemaurl"), str):
                continue  # the schema lives elsewhere (an opaque source schema written back as read)
            if str(schema.get("format", "")).lower().startswith("jsonschema"):
                _check_json_schema(problems, f"{pointer}/versions/{default}/schema", body)
    for gid, group in (document.get("messagegroups") or {}).items():
        _check_id(problems, f"/messagegroups/{gid}", gid, group, "messagegroupid")
        for mid, message in (group.get("messages") or {}).items():
            pointer = f"/messagegroups/{gid}/messages/{mid}"
            _check_id(problems, pointer, mid, message, "messageid")
            if (message.get("envelope") or group.get("envelope")) != ENVELOPE:
                problems.append({"rule": "cloudevents-envelope", "path": f"{pointer}/envelope",
                                 "message": f"the envelope must be {ENVELOPE}"})
            metadata = message.get("envelopemetadata") or {}
            for attribute in _DERIVED_ATTRIBUTES:
                value = (metadata.get(attribute) or {}).get("value")
                if not isinstance(value, str) or not value:
                    problems.append({"rule": "cloudevents-attribute", "path": f"{pointer}/envelopemetadata/{attribute}",
                                     "message": f"the CloudEvents {attribute} has no value"})
            if not isinstance(message.get("datacontenttype"), str):
                problems.append({"rule": "cloudevents-attribute", "path": f"{pointer}/datacontenttype",
                                 "message": "datacontenttype is missing"})
            xid = message.get("dataschemaxid")
            if xid is not None and xid not in xids:
                problems.append({"rule": "xregistry-dataschema", "path": f"{pointer}/dataschemaxid",
                                 "message": f"{xid!r} names no schema of this document"})
            if isinstance(message.get("dataschema"), Mapping):
                _check_json_schema(problems, f"{pointer}/dataschema", message["dataschema"])
    return problems


@lru_cache(maxsize=1)
def _document_validator() -> Draft7Validator:
    """The vendored official xRegistry document schema (draft-07)."""
    return Draft7Validator(json.loads(_DOCUMENT_SCHEMA_PATH.read_text(encoding="utf-8")))


def xregistry_schema_violations(document: Any) -> List[Dict[str, str]]:
    """Check a document against the official xRegistry CloudEvents registry schema — MFX-34.3 (#4308).

    Args:
        document: The parsed document.

    Returns:
        ``{"rule": "xregistry-spec", "path", "message"}`` per violation (the innermost reason of a
        ``oneOf`` / ``anyOf`` when there is one); empty when the document is valid.
    """
    problems: List[Dict[str, str]] = []
    for error in sorted(_document_validator().iter_errors(document), key=lambda e: list(e.absolute_path)):
        reason = min(error.context, key=lambda c: len(list(c.relative_schema_path))) if error.context else error
        pointer = "".join(f"/{part}" for part in error.absolute_path) or "/"
        problems.append({"rule": "xregistry-spec", "path": pointer, "message": reason.message[:300]})
    return problems


def _round_trip_problems(document: Mapping[str, Any], api: CanonicalApi) -> List[Dict[str, str]]:
    """Every schema and message the document writes must read back through the MFI-19.2 importer."""
    problems: List[Dict[str, str]] = []
    type_names = {t.name for t in api.types} | {t.key for t in api.types}
    for gid, group in (document.get("schemagroups") or {}).items():
        for sid in group.get("schemas") or {}:
            if sid not in type_names and f"{gid}.{sid}" not in type_names:
                problems.append({"rule": "reimport-lost", "path": f"/schemagroups/{gid}/schemas/{sid}",
                                 "message": f"schema {sid!r} does not read back as a type"})
    operation_keys = {op.key for op in api.operations()}
    for gid, group in (document.get("messagegroups") or {}).items():
        for mid in group.get("messages") or {}:
            if f"{gid}.{mid}" not in operation_keys:
                problems.append({"rule": "reimport-lost", "path": f"/messagegroups/{gid}/messages/{mid}",
                                 "message": f"message {mid!r} does not read back as an operation"})
    return problems


def check_emitted_xregistry(emit_result: EmitResult) -> List[Dict[str, str]]:
    """The export gate's check (MFX-34.1; official schema and round trip MFX-34.3).

    In order: the document's structure (:func:`xregistry_document_problems`), the official xRegistry
    CloudEvents registry schema (:func:`xregistry_schema_violations`), and a re-import through the
    MFI-19.2 importer in which every schema and message reads back.

    Args:
        emit_result: The emitter's output.

    Returns:
        ``{"rule", "path", "message", "file"}`` per problem; empty when the document passes.
    """
    from .import_source import ImportSourceError, get_import_source

    problems: List[Dict[str, str]] = []
    for emitted in emit_result.files:
        text = str(emitted.content)
        try:
            document = json.loads(text)
        except ValueError as exc:
            problems.append({"rule": "json", "path": "/", "message": str(exc), "file": emitted.path})
            continue
        problems += [{**p, "file": emitted.path} for p in xregistry_document_problems(document)]
        problems += [{**p, "file": emitted.path} for p in xregistry_schema_violations(document)]
        source = get_import_source(XREGISTRY_FORMAT_KEY)
        if source is None:
            continue
        try:
            back = source.normalize(source.parse(text, source_label=emitted.path), include_raw=False)
        except (ImportSourceError, ValueError) as exc:
            problems.append({"rule": "reimport", "path": "/", "message": f"the document does not import: {exc}",
                             "file": emitted.path})
            continue
        if isinstance(document, Mapping):
            problems += [{**p, "file": emitted.path} for p in _round_trip_problems(document, back)]
    return problems


# ===========================================================================
# Fidelity
# ===========================================================================


def event_registry_advisory(api: CanonicalApi, *, target_label: str = "xRegistry") -> Optional[FidelityVerdict]:
    """The critical root advisory of a source with request/response operations — MFX-34.3 (#4308).

    An xRegistry document is an event registry: it keeps types (as schemas) and events (as message
    definitions), so every REST, RPC or GraphQL operation is dropped. Said once and loudly, with counts,
    in the same tier as the types-only advisory (MFX-19.2,
    :func:`app.fidelity_rulepack.types_only_advisory`); the per-operation verdicts drop each one.

    Args:
        api: The source model.
        target_label: The target's label.

    Returns:
        A critical ``DROP`` (``target_mapping`` :data:`EVENT_REGISTRY_MAPPING`), or ``None`` when every
        operation is an event.
    """
    calls = [op for op in api.operations() if op.kind not in _EVENT_KINDS]
    if not calls:
        return None
    services = len({service.key for service in api.services for op in service.operations if op in calls})
    return FidelityVerdict.drop(
        message=f"{target_label} is an event registry — only types (as schemas) and events (as CloudEvents "
        f"message definitions) are exported: {len(calls)} request/response operation(s) in {services} "
        "service(s) are not exported. Export to OpenAPI or AsyncAPI as well to keep them",
        severity=LossinessSeverity.CRITICAL,
        target_mapping=EVENT_REGISTRY_MAPPING,
    )


class XRegistryFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for xRegistry export.

    * an event (publish / subscribe) operation becomes a message definition — ``OK``, or ``SYNTH``
      when its CloudEvents ``type``, ``source`` or ``datacontenttype`` was not in the source; a
      request/response operation has no message form and is ``DROP``ped. A message reads back keyed
      ``<message group>.<message id>``, so an operation whose key differs is reported re-keyed: its
      own key is ``DROP``ped (``info``) and the key it reads back as is ``SYNTH``;
    * a service with no event operation is ``DROP``ped; an xRegistry endpoint is written as a message
      group (``APPROX``: its usage, protocol and URIs are not written);
    * a channel read from an xRegistry message is ``OK``; any other channel is ``APPROX`` (it is
      re-read from its messages' CloudEvents ``type``, and its bindings, protocol and parameters are
      not written);
    * a type of an xRegistry source is ``OK``; any other type is ``APPROX`` — it is projected to JSON
      Schema (MFX-21.1) and reads back as JSON Schema (the profile's rules apply to its fields);
    * the API's servers are ``DROP``ped (no ``endpoints`` are written), and a synthesized registry,
      group, schema or message id is ``SYNTH``.
    """

    target_label = "xRegistry"

    def apply_options(self, options: Mapping[str, Any]) -> None:
        """Compute the report for these options (invalid options fall back to the defaults)."""
        try:
            self._options = XRegistryEmitOptions.model_validate(dict(options))
        except ValidationError:
            self._options = XRegistryEmitOptions()

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Plan the document once to learn what each construct became, then walk the model."""
        options = getattr(self, "_options", None) or XRegistryEmitOptions()
        try:
            self._plan: Optional[_Plan] = build_xregistry_document(api, options)
        except EmitPreconditionError:
            self._plan = None
        self._xregistry_source = (api.format or "").startswith(XREGISTRY_FORMAT_KEY)
        return super().evaluate(api)

    def _read_back_key(self, operation_key: str) -> Optional[str]:
        """The key the xRegistry importer gives the operation's message, when it differs from its own."""
        if self._plan is None or operation_key not in self._plan.message_of:
            return None
        gid, mid = self._plan.message_of[operation_key]
        key = f"{gid}.{mid}"
        return key if key != operation_key else None

    def _synthesized_for(self, operation_key: str) -> List[str]:
        """The synthesized-value reasons that concern one operation's message."""
        plan = self._plan
        if plan is None or operation_key not in plan.message_of:
            return []
        gid, mid = plan.message_of[operation_key]
        prefix = f"/messagegroups/{gid}/messages/{mid}/"
        return [reason for pointer, reason in plan.synthesized if pointer.startswith(prefix)]

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """The event-registry advisory, servers (no endpoints are written) and synthesized ids."""
        verdicts: List[FidelityVerdict] = []
        advisory = event_registry_advisory(api, target_label=self.target_label)
        if advisory is not None:
            verdicts.append(advisory)
        if api.servers:
            verdicts.append(FidelityVerdict.drop(
                message=f"{self.target_label}: the document holds schema and message registries, not "
                f"endpoints; the {len(api.servers)} declared server(s) are dropped",
                severity=LossinessSeverity.WARN,
                target_mapping="servers → dropped (no endpoints)",
            ))
        if self._plan is not None:
            for pointer, reason in self._plan.synthesized:
                if pointer.startswith("/messagegroups/") and "/messages/" in pointer:
                    continue  # reported on the operation
                verdicts.append(FidelityVerdict.synth(
                    message=f"{self.target_label}: {reason}",
                    severity=LossinessSeverity.INFO,
                    target_mapping=f"{pointer} → synthesized",
                ))
        return verdicts

    def operation_verdicts(self, operation: Operation) -> List[FidelityVerdict]:
        """The message verdict, or — for a re-keyed message — a re-key ``DROP`` and its attribute verdict."""
        verdict = self.operation_verdict(operation)
        new_key = self._read_back_key(operation.key)
        if new_key is None:
            return [verdict]
        rekey = FidelityVerdict.drop(
            message=f"{self.target_label}: the message is keyed by its message group and id, so "
            f"{operation.key!r} reads back as {new_key!r}",
            severity=LossinessSeverity.INFO,
            target_mapping=f"operation key → {new_key}",
        )
        return [rekey] if verdict.kind is LossinessKind.OK else [rekey, verdict]

    def _type_read_back_key(self, type_key: str) -> Optional[str]:
        """The key the importer gives a type's schema (its schema id), when it differs from the type's key."""
        if self._plan is None or type_key not in self._plan.schema_of:
            return None
        schema_id = self._plan.schema_of[type_key]
        return schema_id if schema_id != type_key else None

    def type_verdicts(self, type_: Type) -> List[FidelityVerdict]:
        """The type's verdict, plus a re-key ``DROP`` when its schema id is not its key."""
        dropped = self._plan.dropped_types.get(type_.key) if self._plan is not None else None
        if dropped is not None:
            return [FidelityVerdict.drop(
                message=f"{self.target_label}: {dropped}; schema {type_.key!r} is not written",
                severity=LossinessSeverity.WARN,
                target_mapping="schema → dropped (no content)",
            )]
        verdicts = [self.type_verdict(type_)]
        new_key = self._type_read_back_key(type_.key)
        if new_key is not None:
            verdicts.insert(0, FidelityVerdict.drop(
                message=f"{self.target_label}: a schema is keyed by its schema id, so type {type_.key!r} reads "
                f"back as {new_key!r}",
                severity=LossinessSeverity.INFO,
                target_mapping=f"type key → {new_key}",
            ))
        return verdicts

    def synthesized_verdicts(self, api: CanonicalApi) -> List[Tuple[str, FidelityVerdict]]:
        """The key each re-keyed message and type reads back under."""
        pairs: List[Tuple[str, FidelityVerdict]] = []
        own_keys = {type_.key for type_ in api.types}
        for type_ in api.types:
            new_key = self._type_read_back_key(type_.key)
            if new_key is not None and new_key not in own_keys:
                pairs.append((new_key, FidelityVerdict.synth(
                    message=f"{self.target_label}: type {type_.key!r} reads back as {new_key!r} (its schema id)",
                    severity=LossinessSeverity.INFO,
                    target_mapping=f"{type_.key} → {new_key}",
                )))
        for operation in api.operations():
            new_key = self._read_back_key(operation.key)
            if new_key is not None:
                pairs.append((new_key, FidelityVerdict.synth(
                    message=f"{self.target_label}: {operation.key!r} reads back as {new_key!r} "
                    "(message group . message id)",
                    severity=LossinessSeverity.INFO,
                    target_mapping=f"{operation.key} → {new_key}",
                )))
        return pairs

    def service_verdicts(self, service: Service) -> List[FidelityVerdict]:
        """A service without events is not written; an xRegistry endpoint becomes a message group."""
        written = self._plan is not None and any(op.key in self._plan.message_of for op in service.operations)
        if not written:
            return [FidelityVerdict.drop(
                message=f"{self.target_label}: service {service.key!r} has no event operation, so it has no "
                "message group",
                severity=LossinessSeverity.WARN,
                target_mapping="service → dropped",
            )]
        if (service.extras or {}).get("xregistry_kind") == "endpoint":
            return [FidelityVerdict.approx(
                message=f"{self.target_label}: endpoint {service.key!r} is written as a message group; its "
                "usage, protocol and URIs are not written (no endpoints are emitted)",
                target_mapping="endpoint → message group",
            )]
        if not self._xregistry_source:
            return [FidelityVerdict.approx(
                message=f"{self.target_label}: service {service.key!r} is written as a message group of its "
                "event operations",
                severity=LossinessSeverity.INFO,
                target_mapping="service → message group",
            )]
        return []

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        """OK (or SYNTH) for an event written as a message; DROP otherwise."""
        plan = self._plan
        if plan is None or operation.key not in plan.message_of:
            reason = (plan.not_written.get(operation.key) if plan is not None else None) or (
                "only event (publish / subscribe) operations become message definitions"
            )
            return FidelityVerdict.drop(
                message=f"{self.target_label}: {reason}; {operation.key!r} is dropped",
                severity=LossinessSeverity.WARN,
                target_mapping="operation → no message",
            )
        gid, mid = plan.message_of[operation.key]
        mapping = f"operation → message {gid}/{mid}"
        synthesized = self._synthesized_for(operation.key)
        if synthesized:
            return FidelityVerdict.synth(
                message=f"{self.target_label}: written as message {mid!r}; " + "; ".join(synthesized),
                severity=LossinessSeverity.INFO,
                target_mapping=mapping,
            )
        return FidelityVerdict.ok(message=f"operation carried to the xRegistry message {mid!r}", target_mapping=mapping)

    def channel_verdict(self, channel: Channel) -> FidelityVerdict:
        """The channel's address is the messages' CloudEvents ``type``; its bindings are not written."""
        if not self._xregistry_source:
            return FidelityVerdict.approx(
                message=f"{self.target_label}: channel {channel.key!r} is re-read from its messages' CloudEvents "
                "type; its protocol, bindings, parameters and description are not written",
                target_mapping="channel → CloudEvents type",
            )
        if channel.bindings:
            return FidelityVerdict.approx(
                message=f"{self.target_label}: channel {channel.key!r} becomes its messages' CloudEvents type; "
                f"its protocol bindings ({', '.join(sorted(channel.bindings))}) are not written",
                target_mapping="channel → CloudEvents type (bindings dropped)",
            )
        return FidelityVerdict.ok(
            message=f"channel carried as its messages' CloudEvents type in {self.target_label}",
            target_mapping="channel → CloudEvents type",
        )

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        """A type is a JSON Schema in the schema registry (an opaque one is written back as read)."""
        base = super().type_verdict(type_)
        if base.kind.value != "ok":
            return base
        schema_id = self._plan.schema_of.get(type_.key) if self._plan is not None else None
        if not self._xregistry_source:
            return FidelityVerdict.approx(
                message=f"{self.target_label}: type {type_.key!r} is projected to the JSON Schema "
                f"{schema_id or type_.name!r} and reads back as JSON Schema",
                severity=LossinessSeverity.INFO,
                target_mapping=f"type → JSON Schema {schema_id}",
            )
        return FidelityVerdict.ok(
            message=f"type carried to the {self.target_label} schema {schema_id or type_.name!r}",
            target_mapping=f"type → schema {schema_id}" if schema_id else None,
        )


# ===========================================================================
# Emitter
# ===========================================================================


class XRegistryEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an xRegistry document (schemas + message definitions)."""

    key = XREGISTRY_FORMAT_KEY
    #: Offered greyed out with the reason when the source has neither a type nor an event.
    requires_source = ("event-or-type",)
    format = XREGISTRY_FORMAT_KEY
    label = "xRegistry"
    description = (
        "Export as a CNCF xRegistry document: the types as a JSON Schema registry and the event "
        "operations as CloudEvents message definitions (type, source, datacontenttype, payload schema)."
    )
    icon = "cloud"
    paradigm = ApiParadigm.EVENT
    multi_file = False
    options_model = XRegistryEmitOptions
    #: How the Review step can draw the output besides its text (MFX-45.4).
    viz_modes = (ExportVizModeKind.CHANNEL_TOPOLOGY,)

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """Events and JSON Schema types; no request/response operations and no field identity."""
        return CapabilityProfile(
            operations=False,
            events=True,
            unions=True,
            nullability=True,
            constraints=True,
            field_identity=False,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        """Return the xRegistry rules."""
        return XRegistryFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[XRegistryEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        """Emit ``api`` as one ``<registry id>.xregistry.json`` document.

        Args:
            api: The canonical model to export.
            opts: Per-target options; the defaults name the registry after the item.

        Returns:
            An :class:`~app.emitter.EmitResult` with the one document.

        Raises:
            EmitOptionsError: When ``opts`` names an unknown option value.
            EmitPreconditionError: When the model has neither a type nor an event operation.
            ValueError: When the document fails :func:`xregistry_document_problems`.
        """
        options = _coerce_options(opts)
        plan = build_xregistry_document(api, options)
        problems = xregistry_document_problems(plan.document)
        if problems:
            raise ValueError("The xRegistry document is not valid: "
                             + "; ".join(f"{p['path']}: {p['message']}" for p in problems))
        losses = LossTracker()
        tracker = ProvenanceTracker()
        for key, reason in plan.not_written.items():
            losses.record(LossKind.NA, LOSS_NOT_AN_EVENT, f"{key!r}: {reason}", pointer=key)
        for pointer, reason in plan.synthesized:
            attribute = "/envelopemetadata/" in pointer or pointer.endswith("/datacontenttype")
            subject = LOSS_ATTRIBUTE_SYNTHESIZED if attribute else LOSS_ID_SYNTHESIZED
            losses.record(LossKind.INFERRED, subject, reason, pointer=pointer)
            tracker.record(pointer, Provenance.INFERRED, reason)
        if api.servers:
            losses.record(LossKind.NA, LOSS_ENDPOINTS_NOT_WRITTEN,
                          f"the {len(api.servers)} server(s) are not written: no xRegistry endpoints are emitted",
                          pointer="servers")
        for channel in api.channels:
            if channel.bindings:
                losses.record(LossKind.NA, LOSS_BINDINGS_NOT_WRITTEN,
                              f"channel {channel.key!r}'s protocol bindings are not written", pointer=channel.key)
        indent = options.indent or None
        content = json.dumps(plan.document, indent=indent, ensure_ascii=False) + "\n"
        path = f"{plan.document['registryid']}{DOCUMENT_SUFFIX}"
        return EmitResult(
            files=[EmittedFile(path=path, content=content, media_type=OUTPUT_MEDIA_TYPE)],
            media_type=OUTPUT_MEDIA_TYPE,
            provenance=tracker.records(),
            losses=losses.records(),
        )


def _coerce_options(opts: Optional[Union[XRegistryEmitOptions, EmitOptions]]) -> XRegistryEmitOptions:
    """Validate caller-supplied options into :class:`XRegistryEmitOptions`."""
    if isinstance(opts, XRegistryEmitOptions):
        return opts
    try:
        return XRegistryEmitOptions.model_validate(opts.model_dump() if opts else {})
    except ValueError as exc:
        raise EmitOptionsError(f"Invalid xRegistry emit options: {exc}") from exc
