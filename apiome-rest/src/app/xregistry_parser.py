"""CNCF xRegistry document parser — MFI-19.2 (#3980).

`xRegistry <https://xregistry.io>`_ is the CloudEvents project's catalog model: one JSON
document (or the same model served over its REST binding) that holds three registries side by
side:

* ``schemagroups`` → ``schemas`` — schema documents (JSON Schema, Avro, Protobuf, XSD …), each
  with a ``format`` and, optionally, ``versions``;
* ``messagegroups`` → ``messages`` — message definitions: the envelope (``CloudEvents/1.0``),
  its metadata (the CloudEvents ``type`` / ``source`` / ``subject`` attributes), the protocol
  binding and the payload schema (``dataschemauri`` / ``dataschemaxid`` or an inline
  ``dataschema``);
* ``endpoints`` — where messages flow: ``usage`` (producer / consumer / subscriber), the
  ``protocol`` (MQTT, AMQP, Kafka, NATS, HTTP), its URIs, the message groups it carries
  (``messagegroups``) and messages it declares inline.

:func:`parse_xregistry` reads such a document into a typed :class:`XRegistryDocument`. It is
tolerant of the spec's earlier drafts: ``definitiongroups`` / ``definitions`` stand for
``messagegroups`` / ``messages``, ``metadata`` for ``envelopemetadata``, ``format`` for
``envelope`` on a message, and ``schemaurl`` / ``dataschemaurl`` for their ``…uri`` forms.
Every failure raises :class:`XRegistryParseError` with an intake-taxonomy ``code``.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

import yaml

from .intake_resource_guard import IntakeLimitError, guard_document_text, guard_parsed_document
from .mcp_manifest_parser import is_unclosed_json

__all__ = [
    "XRegistryDocument",
    "XRegistryEndpoint",
    "XRegistryMessage",
    "XRegistryMessageGroup",
    "XRegistryParseError",
    "XRegistrySchema",
    "group_refs",
    "is_xregistry",
    "is_xregistry_document",
    "parse_xregistry",
]

#: Top-level collections that make a document an xRegistry document (current names first).
_MESSAGE_GROUP_KEYS = ("messagegroups", "definitiongroups")
_MESSAGE_KEYS = ("messages", "definitions")
_COLLECTION_KEYS = ("schemagroups", "endpoints") + _MESSAGE_GROUP_KEYS

#: Markers of other formats an xRegistry document never carries at its root.
_FOREIGN_FORMAT_MARKERS: Tuple[str, ...] = (
    "openapi",
    "swagger",
    "asyncapi",
    "arazzo",
    "openrpc",
    "protocolVersion",
    "skills",
)


class XRegistryParseError(ValueError):
    """Raised when content cannot be parsed as an xRegistry document.

    Attributes:
        code: The intake-taxonomy code (``INPUT_MALFORMED``, ``FORMAT_MISMATCH`` …), when known.
    """

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class XRegistrySchema:
    """One schema of a schema group, resolved to its default version.

    Attributes:
        group_id: The owning schema group id.
        schema_id: The schema's id (its map key).
        name: Display name (``name``), when given.
        description: ``description``, when given.
        format: ``format`` of the default version (``JsonSchema/draft-07``, ``Avro/1.11.0`` …).
        version_id: The default version's id, when known.
        document: The schema document — a parsed JSON value, a text (Protobuf, XSD), or ``None``
            when only a ``schemauri`` was given.
        schema_uri: ``schemauri`` / ``schemaurl``, when the document lives elsewhere.
        deprecated: Whether the schema carries a ``deprecated`` marker.
    """

    group_id: str
    schema_id: str
    name: Optional[str]
    description: Optional[str]
    format: Optional[str]
    version_id: Optional[str]
    document: Any
    schema_uri: Optional[str]
    deprecated: bool = False

    @property
    def xid(self) -> str:
        """The schema's xRegistry path, ``/schemagroups/<gid>/schemas/<sid>``."""
        return f"/schemagroups/{self.group_id}/schemas/{self.schema_id}"


@dataclass(frozen=True)
class XRegistryMessage:
    """One message definition.

    Attributes:
        container: ``messagegroups/<gid>`` or ``endpoints/<eid>`` — where it is declared.
        message_id: The message's id (its map key).
        name: Display name, when given.
        description: ``description``, when given.
        envelope: ``envelope`` (``CloudEvents/1.0``), inherited from the group when absent.
        envelope_metadata: The envelope attributes (``type``, ``source``, ``subject`` …), each a
            mapping that may carry ``value``, ``type``, ``required`` and ``description``.
        protocol: ``protocol`` (``MQTT/5.0``, ``KAFKA``), inherited from the group when absent.
        protocol_binding: ``protocolbinding`` / ``protocoloptions``.
        data_schema_format: ``dataschemaformat``.
        data_schema_ref: ``dataschemaxid`` / ``dataschemauri`` / ``dataschemaurl``, or a string
            ``dataschema``.
        data_schema_inline: An inline ``dataschema`` object.
        data_content_type: ``datacontenttype``.
        deprecated: Whether the message carries a ``deprecated`` marker.
    """

    container: str
    message_id: str
    name: Optional[str]
    description: Optional[str]
    envelope: Optional[str]
    envelope_metadata: Tuple[Tuple[str, Mapping[str, Any]], ...]
    protocol: Optional[str]
    protocol_binding: Mapping[str, Any]
    data_schema_format: Optional[str]
    data_schema_ref: Optional[str]
    data_schema_inline: Optional[Mapping[str, Any]]
    data_content_type: Optional[str]
    deprecated: bool = False

    @property
    def event_type(self) -> Optional[str]:
        """The CloudEvents ``type`` the message pins (``envelopemetadata.type.value``), if any."""
        for name, attribute in self.envelope_metadata:
            if name == "type" and isinstance(attribute.get("value"), str) and attribute["value"].strip():
                return attribute["value"].strip()
        return None


@dataclass(frozen=True)
class XRegistryMessageGroup:
    """A message group: a named set of message definitions.

    Attributes:
        group_id: The group's id.
        name: Display name, when given.
        description: ``description``, when given.
        envelope: The group-wide ``envelope``, when given.
        protocol: The group-wide ``protocol``, when given.
        messages: The group's message definitions, in document order.
    """

    group_id: str
    name: Optional[str]
    description: Optional[str]
    envelope: Optional[str]
    protocol: Optional[str]
    messages: Tuple[XRegistryMessage, ...]


@dataclass(frozen=True)
class XRegistryEndpoint:
    """An endpoint: where messages are produced or consumed.

    Attributes:
        endpoint_id: The endpoint's id.
        name: Display name, when given.
        description: ``description``, when given.
        usage: ``usage`` values (``producer``, ``consumer``, ``subscriber``), lower-cased.
        protocol: ``protocol`` (``MQTT/5.0``, ``AMQP/1.0`` …), when given.
        uris: The endpoint URIs (``protocoloptions.endpoints[].uri`` and the older forms).
        protocol_options: ``protocoloptions`` minus its URI list.
        envelope: ``envelope``, when given.
        message_group_refs: The message groups it carries, as group ids.
        messages: Messages it declares inline.
        deprecated: Whether the endpoint carries a ``deprecated`` marker.
    """

    endpoint_id: str
    name: Optional[str]
    description: Optional[str]
    usage: Tuple[str, ...]
    protocol: Optional[str]
    uris: Tuple[str, ...]
    protocol_options: Mapping[str, Any]
    envelope: Optional[str]
    message_group_refs: Tuple[str, ...]
    messages: Tuple[XRegistryMessage, ...]
    deprecated: bool = False


@dataclass(frozen=True)
class XRegistryDocument:
    """A parsed xRegistry document.

    Attributes:
        spec_version: ``specversion`` (the xRegistry spec version), when given.
        registry_id: ``registryid``, when given.
        name: ``name``, when given.
        description: ``description``, when given.
        schemas: Every schema of every schema group, in document order.
        message_groups: The message groups, in document order.
        endpoints: The endpoints, in document order.
        raw: The original text.
    """

    spec_version: Optional[str]
    registry_id: Optional[str]
    name: Optional[str]
    description: Optional[str]
    schemas: Tuple[XRegistrySchema, ...]
    message_groups: Tuple[XRegistryMessageGroup, ...]
    endpoints: Tuple[XRegistryEndpoint, ...]
    raw: str


# ===========================================================================
# Detection
# ===========================================================================


def is_xregistry_document(document: Any) -> bool:
    """Return ``True`` when a parsed value looks like an xRegistry document.

    The marker is a JSON object with at least one of ``schemagroups``, ``messagegroups`` (or
    ``definitiongroups``) or ``endpoints`` holding an object, and no other format's root marker.

    Args:
        document: The parsed value.

    Returns:
        Whether the value has the xRegistry shape.
    """
    if not isinstance(document, Mapping):
        return False
    if any(marker in document for marker in _FOREIGN_FORMAT_MARKERS):
        return False
    return any(isinstance(document.get(key), Mapping) for key in _COLLECTION_KEYS)


def is_xregistry(content: str) -> bool:
    """Return ``True`` when ``content`` is JSON text of an xRegistry document.

    Args:
        content: The raw text.

    Returns:
        Whether the text decodes to an xRegistry-shaped object.
    """
    if not isinstance(content, str) or not content.strip():
        return False
    try:
        return is_xregistry_document(json.loads(content))
    except ValueError:
        return False


# ===========================================================================
# Parsing
# ===========================================================================


def parse_xregistry(content: str, *, source_label: Optional[str] = None) -> XRegistryDocument:
    """Parse xRegistry JSON text into an :class:`XRegistryDocument`.

    Args:
        content: The document text.
        source_label: Optional filename / URL for messages.

    Returns:
        The parsed document.

    Raises:
        XRegistryParseError: With a taxonomy ``code`` — ``INPUT_EMPTY``,
            ``INPUT_ENCODING_INVALID``, ``INPUT_TRUNCATED``, ``INPUT_MALFORMED``,
            ``FORMAT_MISMATCH`` for another format, and ``INPUT_SEMANTIC_INVALID`` for a registry
            that defines no schema, message or endpoint, or a collection that is not an object.
    """
    where = f" ({source_label})" if source_label else ""
    document = _load(content, where=where, source_label=source_label)

    schemas = _parse_schema_groups(document.get("schemagroups"), where=where)
    message_groups = _parse_message_groups(_first(document, _MESSAGE_GROUP_KEYS), where=where)
    endpoints = _parse_endpoints(document.get("endpoints"), where=where)
    if not schemas and not endpoints and not any(group.messages for group in message_groups):
        raise XRegistryParseError(
            f"xRegistry document{where} defines no schemas, messages or endpoints",
            code="INPUT_SEMANTIC_INVALID",
        )
    return XRegistryDocument(
        spec_version=_text(document.get("specversion")),
        registry_id=_text(document.get("registryid")),
        name=_text(document.get("name")),
        description=_text(document.get("description")),
        schemas=tuple(schemas),
        message_groups=tuple(message_groups),
        endpoints=tuple(endpoints),
        raw=content,
    )


def _load(content: str, *, where: str, source_label: Optional[str]) -> Mapping[str, Any]:
    """Decode the text to a JSON object, classifying every way that can fail.

    Args:
        content: The raw text.
        where: Pre-formatted ``" (label)"`` suffix for messages.
        source_label: Label passed to the intake resource guards.

    Returns:
        The parsed top-level object.

    Raises:
        XRegistryParseError: With the taxonomy code for the specific failure.
    """
    if not content or not content.strip():
        raise XRegistryParseError(f"xRegistry document is empty{where}", code="INPUT_EMPTY")
    if "\x00" in content or "�" in content[:64]:
        raise XRegistryParseError(
            f"xRegistry document is not UTF-8 text{where} — it looks like UTF-16 or binary content",
            code="INPUT_ENCODING_INVALID",
        )
    try:
        guard_document_text(content, source_label=source_label)
    except IntakeLimitError as exc:
        raise XRegistryParseError(str(exc), code=getattr(exc, "code", None)) from exc

    try:
        document: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise _classify_json_failure(content, exc, where=where) from exc

    try:
        guard_parsed_document(document, source_label=source_label)
    except IntakeLimitError as exc:
        raise XRegistryParseError(str(exc), code=getattr(exc, "code", None)) from exc

    if not isinstance(document, Mapping):
        raise XRegistryParseError(
            f"xRegistry document must be a JSON object{where}, not a {type(document).__name__}",
            code="FORMAT_MISMATCH",
        )
    if any(marker in document for marker in _FOREIGN_FORMAT_MARKERS):
        raise XRegistryParseError(
            f"Content looks like another format (OpenAPI/AsyncAPI/JSON Schema/…){where}, not an "
            "xRegistry document",
            code="FORMAT_MISMATCH",
        )
    present = [key for key in _COLLECTION_KEYS if key in document]
    if not present:
        raise XRegistryParseError(
            f"Content is not an xRegistry document{where}: it has no `schemagroups`, "
            "`messagegroups` or `endpoints`",
            code="FORMAT_MISMATCH",
        )
    for key in present:
        if not isinstance(document[key], Mapping):
            raise XRegistryParseError(
                f"xRegistry `{key}`{where} must be an object keyed by id",
                code="INPUT_SEMANTIC_INVALID",
            )
    return document


def _classify_json_failure(
    content: str, exc: json.JSONDecodeError, *, where: str
) -> XRegistryParseError:
    """Turn a JSON decode failure into the right taxonomy code.

    Text that parses as YAML into a mapping without any xRegistry collection is a different
    format; text left open mid-value is truncated; anything else is malformed.

    Args:
        content: The text that failed to decode.
        exc: The decode error.
        where: Pre-formatted ``" (label)"`` suffix for messages.

    Returns:
        The error to raise.
    """
    try:
        loose = yaml.safe_load(content)
    except Exception:  # noqa: BLE001 - a YAML failure only means "no second opinion"
        loose = None
    if isinstance(loose, Mapping) and not is_xregistry_document(loose):
        return XRegistryParseError(
            f"Content is not an xRegistry document{where}: {exc.msg}", code="FORMAT_MISMATCH"
        )
    if is_unclosed_json(content):
        return XRegistryParseError(
            f"xRegistry document is truncated{where}: {exc.msg} at line {exc.lineno}",
            code="INPUT_TRUNCATED",
        )
    return XRegistryParseError(
        f"xRegistry document is not valid JSON{where}: {exc.msg} at line {exc.lineno} "
        f"column {exc.colno}",
        code="INPUT_MALFORMED",
    )


def _parse_schema_groups(groups: Any, *, where: str) -> List[XRegistrySchema]:
    """Every schema of every schema group, resolved to its default version.

    Args:
        groups: The ``schemagroups`` value (``None`` when absent).
        where: Pre-formatted ``" (label)"`` suffix for messages.

    Returns:
        The schemas, in document order.
    """
    schemas: List[XRegistrySchema] = []
    for gid, group in _entities(groups, what="schema group", where=where):
        for sid, schema in _entities(group.get("schemas"), what=f"schema in `{gid}`", where=where):
            schemas.append(_parse_schema(gid, sid, schema))
    return schemas


def _parse_schema(gid: str, sid: str, schema: Mapping[str, Any]) -> XRegistrySchema:
    """One schema: the schema-level fields over its default version's.

    xRegistry serves a schema as its default version's view (``format``, ``schema`` … at the
    schema level), and may also nest every version under ``versions``. The schema-level view
    wins; otherwise the version named by ``defaultversionid`` (else the last listed) is used.

    Args:
        gid: The group id.
        sid: The schema id.
        schema: The schema entity.

    Returns:
        The resolved schema.
    """
    view: Dict[str, Any] = {}
    versions = schema.get("versions")
    if isinstance(versions, Mapping) and versions:
        default_id = _text(schema.get("defaultversionid"))
        chosen = versions.get(default_id) if default_id else None
        if not isinstance(chosen, Mapping):
            chosen = next(
                (v for v in reversed(list(versions.values())) if isinstance(v, Mapping)), {}
            )
        view.update(chosen)
    view.update({k: v for k, v in schema.items() if k != "versions"})
    return XRegistrySchema(
        group_id=gid,
        schema_id=sid,
        name=_text(view.get("name")),
        description=_text(view.get("description")),
        format=_text(view.get("format")),
        version_id=_text(view.get("versionid")) or _text(view.get("defaultversionid")),
        document=_schema_document(view),
        schema_uri=_text(view.get("schemauri")) or _text(view.get("schemaurl")),
        deprecated=view.get("deprecated") not in (None, False),
    )


def _schema_document(view: Mapping[str, Any]) -> Any:
    """The schema document from ``schema`` or ``schemabase64``; JSON text is decoded.

    Args:
        view: The resolved schema view.

    Returns:
        A parsed JSON value, a text, or ``None`` when the view carries no document.
    """
    document: Any = view.get("schema")
    if document is None and isinstance(view.get("schemabase64"), str):
        try:
            document = base64.b64decode(view["schemabase64"], validate=True).decode("utf-8")
        except (binascii.Error, ValueError):
            document = None
    if isinstance(document, str):
        stripped = document.strip()
        if stripped[:1] in ("{", "["):
            try:
                return json.loads(stripped)
            except ValueError:
                return document
    return document


def _parse_message_groups(groups: Any, *, where: str) -> List[XRegistryMessageGroup]:
    """The message groups and their messages.

    Args:
        groups: The ``messagegroups`` value (``None`` when absent).
        where: Pre-formatted ``" (label)"`` suffix for messages.

    Returns:
        The groups, in document order.
    """
    parsed: List[XRegistryMessageGroup] = []
    for gid, group in _entities(groups, what="message group", where=where):
        envelope = _text(group.get("envelope")) or _text(group.get("format"))
        protocol = _text(group.get("protocol"))
        parsed.append(
            XRegistryMessageGroup(
                group_id=gid,
                name=_text(group.get("name")),
                description=_text(group.get("description")),
                envelope=envelope,
                protocol=protocol,
                messages=tuple(
                    _parse_messages(
                        _first(group, _MESSAGE_KEYS),
                        container=f"messagegroups/{gid}",
                        envelope=envelope,
                        protocol=protocol,
                        where=where,
                    )
                ),
            )
        )
    return parsed


def _parse_messages(
    messages: Any,
    *,
    container: str,
    envelope: Optional[str],
    protocol: Optional[str],
    where: str,
) -> List[XRegistryMessage]:
    """The message definitions of one group or endpoint.

    Args:
        messages: The ``messages`` value (``None`` when absent).
        container: ``messagegroups/<gid>`` or ``endpoints/<eid>``.
        envelope: The container's ``envelope``, inherited by messages that set none.
        protocol: The container's ``protocol``, inherited likewise.
        where: Pre-formatted ``" (label)"`` suffix for messages.

    Returns:
        The messages, in document order.
    """
    parsed: List[XRegistryMessage] = []
    for mid, message in _entities(messages, what=f"message in `{container}`", where=where):
        metadata = message.get("envelopemetadata")
        if not isinstance(metadata, Mapping):
            metadata = message.get("metadata") if isinstance(message.get("metadata"), Mapping) else {}
        attributes = tuple(
            (str(name), attribute if isinstance(attribute, Mapping) else {"value": attribute})
            for name, attribute in metadata.items()
        )
        inline = message.get("dataschema")
        binding = message.get("protocolbinding")
        if not isinstance(binding, Mapping):
            binding = message.get("protocoloptions") if isinstance(message.get("protocoloptions"), Mapping) else {}
        parsed.append(
            XRegistryMessage(
                container=container,
                message_id=mid,
                name=_text(message.get("name")),
                description=_text(message.get("description")),
                envelope=_text(message.get("envelope")) or _text(message.get("format")) or envelope,
                envelope_metadata=attributes,
                protocol=_text(message.get("protocol")) or protocol,
                protocol_binding=dict(binding),
                data_schema_format=_text(message.get("dataschemaformat")) or _text(message.get("schemaformat")),
                data_schema_ref=(
                    _text(message.get("dataschemaxid"))
                    or _text(message.get("dataschemauri"))
                    or _text(message.get("dataschemaurl"))
                    or _text(message.get("schemaurl"))
                    or _text(inline)
                ),
                data_schema_inline=dict(inline) if isinstance(inline, Mapping) else None,
                data_content_type=_text(message.get("datacontenttype")),
                deprecated=message.get("deprecated") not in (None, False),
            )
        )
    return parsed


def _parse_endpoints(endpoints: Any, *, where: str) -> List[XRegistryEndpoint]:
    """The endpoints, with their URIs, usage and message-group references.

    Args:
        endpoints: The ``endpoints`` value (``None`` when absent).
        where: Pre-formatted ``" (label)"`` suffix for messages.

    Returns:
        The endpoints, in document order.
    """
    parsed: List[XRegistryEndpoint] = []
    for eid, endpoint in _entities(endpoints, what="endpoint", where=where):
        options = endpoint.get("protocoloptions")
        if not isinstance(options, Mapping):
            options = endpoint.get("config") if isinstance(endpoint.get("config"), Mapping) else {}
        uris = _endpoint_uris(options) or _endpoint_uris(endpoint)
        usage = endpoint.get("usage")
        usage_values = [usage] if isinstance(usage, str) else usage if isinstance(usage, list) else []
        envelope = _text(endpoint.get("envelope")) or _text(endpoint.get("format"))
        protocol = _text(endpoint.get("protocol")) or _text(options.get("protocol"))
        parsed.append(
            XRegistryEndpoint(
                endpoint_id=eid,
                name=_text(endpoint.get("name")),
                description=_text(endpoint.get("description")),
                usage=tuple(str(u).strip().lower() for u in usage_values if isinstance(u, str) and u.strip()),
                protocol=protocol,
                uris=tuple(uris),
                protocol_options={k: v for k, v in options.items() if k not in ("endpoints", "protocol")},
                envelope=envelope,
                message_group_refs=tuple(group_refs(endpoint)),
                messages=tuple(
                    _parse_messages(
                        _first(endpoint, _MESSAGE_KEYS),
                        container=f"endpoints/{eid}",
                        envelope=envelope,
                        protocol=protocol,
                        where=where,
                    )
                ),
                deprecated=endpoint.get("deprecated") not in (None, False),
            )
        )
    return parsed


def _endpoint_uris(holder: Mapping[str, Any]) -> List[str]:
    """URIs from an ``endpoints`` list of ``{"uri": …}`` objects or strings.

    Args:
        holder: ``protocoloptions`` (current spec) or the endpoint itself (older drafts).

    Returns:
        The URIs, in order, without duplicates.
    """
    listed = holder.get("endpoints")
    uris: List[str] = []
    if isinstance(listed, list):
        for item in listed:
            uri = _text(item.get("uri")) if isinstance(item, Mapping) else _text(item)
            if uri and uri not in uris:
                uris.append(uri)
    return uris


def group_refs(endpoint: Mapping[str, Any]) -> List[str]:
    """The message-group ids an endpoint references.

    References are xids (``/messagegroups/<gid>``), URLs ending in ``…/messagegroups/<gid>``, or
    bare ids, under ``messagegroups`` (current) or ``definitiongroups`` (earlier drafts).

    Args:
        endpoint: The endpoint entity.

    Returns:
        The referenced group ids, in order, without duplicates.
    """
    refs = _first(endpoint, _MESSAGE_GROUP_KEYS)
    if isinstance(refs, str):
        refs = [refs]
    ids: List[str] = []
    if isinstance(refs, list):
        for ref in refs:
            text = _text(ref)
            if not text:
                continue
            gid = text.rstrip("/").rsplit("/", 1)[-1]
            if gid and gid not in ids:
                ids.append(gid)
    return ids


def _entities(collection: Any, *, what: str, where: str) -> List[Tuple[str, Mapping[str, Any]]]:
    """The ``(id, entity)`` pairs of an xRegistry collection map.

    Args:
        collection: The map (``None`` when absent).
        what: What an entity is, for messages.
        where: Pre-formatted ``" (label)"`` suffix for messages.

    Returns:
        The pairs, in document order.

    Raises:
        XRegistryParseError: ``INPUT_SEMANTIC_INVALID`` when the collection or an entity is not an
            object.
    """
    if collection is None:
        return []
    if not isinstance(collection, Mapping):
        raise XRegistryParseError(
            f"xRegistry {what} collection{where} must be an object keyed by id",
            code="INPUT_SEMANTIC_INVALID",
        )
    pairs: List[Tuple[str, Mapping[str, Any]]] = []
    for key, entity in collection.items():
        if not isinstance(entity, Mapping):
            raise XRegistryParseError(
                f"xRegistry {what} `{key}`{where} is not an object",
                code="INPUT_SEMANTIC_INVALID",
            )
        pairs.append((str(key), entity))
    return pairs


def _first(holder: Mapping[str, Any], keys: Tuple[str, ...]) -> Any:
    """The value of the first of ``keys`` present in ``holder`` (current name before drafts).

    Args:
        holder: The object.
        keys: Candidate keys, in preference order.

    Returns:
        The value, or ``None``.
    """
    for key in keys:
        if key in holder:
            return holder[key]
    return None


def _text(value: Any) -> Optional[str]:
    """A stripped non-empty string, else ``None``.

    Args:
        value: Any value.

    Returns:
        The text or ``None``.
    """
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
