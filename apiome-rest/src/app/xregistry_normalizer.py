"""xRegistry → canonical model normalizer — MFI-19.2 (#3980).

Maps a parsed :class:`~app.xregistry_parser.XRegistryDocument` onto a
:class:`~app.canonical_model.CanonicalApi` of paradigm :attr:`~app.canonical_model.ApiParadigm.EVENT`:

* **schemas → types.** A JSON Schema becomes a named type keyed by its schema id (group-qualified
  ``<gid>.<sid>`` only when two groups reuse an id); its ``definitions`` / ``$defs`` become types
  too. Avro, Protobuf and XSD schemas are normalized by the adapter their ``format`` names
  (:func:`app.xregistry_crawl.import_kind_for_format`) and their types merged in. A schema that
  cannot be read that way (an unknown format, a parse failure, only a ``schemauri``) is kept as an
  opaque ``SCALAR`` type whose ``extras`` record why, so it still versions and diffs.
* **messages → channels + operations.** Each message definition is an operation carrying one
  ``EVENT`` message on the channel named by its CloudEvents ``type`` (``envelopemetadata.type.value``;
  the message id when it pins none). The envelope attributes become message headers (their
  ``value`` the default), the payload is the referenced or inline schema, and the protocol binding
  is the channel's ``bindings``.
* **endpoints → services.** Each endpoint is a service whose operations are the messages of the
  groups it carries plus the ones it declares inline — ``publish`` for a producer, ``subscribe``
  for a consumer or subscriber — and whose URIs are the model's servers. A message group no
  endpoint carries is a service of its own, so every definition is cataloged once.

Operation keys are container-qualified (``<group>.<message>``, ``<endpoint>.<group>.<message>``,
``<endpoint>.<message>`` for inline ones) so a message re-used by two endpoints stays two diffable
operations. Registry bookkeeping (``epoch``, ``createdat``, ``modifiedat``, ``self`` URLs) never
reaches the model, so a re-served registry fingerprints the same.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Server,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from .normalizer import Keys, Normalizer, SchemaCoercer, normalize_ordering
from .xregistry_parser import (
    XRegistryDocument,
    XRegistryEndpoint,
    XRegistryMessage,
    XRegistryMessageGroup,
    XRegistrySchema,
)

__all__ = ["FORMAT_KEY", "XRegistryNormalizer"]

logger = logging.getLogger(__name__)

#: The format / import-source key.
FORMAT_KEY = "xregistry"

#: ``$ref`` prefix JSON Schema ``definitions`` use; ``$defs`` and remote refs fall back to the
#: last pointer segment (see :meth:`app.normalizer.SchemaCoercer.ref_name`).
_REF_PREFIX = "#/definitions/"

#: xRegistry attribute ``type`` → canonical scalar name (everything else is a string on the wire).
_ATTRIBUTE_TYPES = {"integer": "integer", "boolean": "boolean", "number": "number"}

#: Endpoint ``usage`` values that consume rather than produce.
_CONSUMER_USAGE = frozenset({"consumer", "subscriber"})


class XRegistryNormalizer(Normalizer, register=True):
    """Normalize a parsed xRegistry document into a :class:`CanonicalApi`."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.EVENT

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Build the canonical model (see the module docstring).

        Args:
            source: The parsed :class:`XRegistryDocument`.
            include_raw: Whether to keep the document text in ``raw``.

        Returns:
            The ordered canonical model.

        Raises:
            ValueError: When ``source`` is not an :class:`XRegistryDocument`.
        """
        if not isinstance(source, XRegistryDocument):
            raise ValueError(
                "xRegistry source must be an XRegistryDocument (see app.xregistry_parser.parse_xregistry)"
            )
        schema_types = _SchemaTypes(source.schemas)
        builder = _EventBuilder(schema_types)

        services: List[Service] = []
        carried = {gid for endpoint in source.endpoints for gid in endpoint.message_group_refs}
        groups = {group.group_id: group for group in source.message_groups}
        for endpoint in source.endpoints:
            services.append(builder.endpoint_service(endpoint, groups))
        for group in source.message_groups:
            if group.group_id not in carried and group.messages:
                services.append(builder.group_service(group))

        title = source.name or source.registry_id or "xRegistry"
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol=_single(builder.protocols),
            identity=ApiIdentity(name=title, id=source.registry_id),
            title=title,
            description=source.description,
            servers=_servers(source.endpoints),
            services=services,
            channels=list(builder.channels.values()),
            types=schema_types.types(),
            raw={"xregistry": source.raw} if include_raw else None,
            extras=_document_extras(source),
        )
        return normalize_ordering(api)


# ===========================================================================
# Schemas → types
# ===========================================================================


class _SchemaTypes:
    """The canonical types of a document's schemas, and the type each schema's payload names."""

    def __init__(self, schemas: Iterable[XRegistrySchema]) -> None:
        """Normalize every schema (see the module docstring).

        Args:
            schemas: The document's schemas.
        """
        self._components: Dict[str, Any] = {}
        self._types: Dict[str, Type] = {}
        #: Schema xid → the type key a message payload referencing it names.
        self.root_by_xid: Dict[str, str] = {}
        seen_ids: Dict[str, int] = {}
        schemas = list(schemas)
        for schema in schemas:
            seen_ids[schema.schema_id] = seen_ids.get(schema.schema_id, 0) + 1
        for schema in schemas:
            name = schema.schema_id if seen_ids[schema.schema_id] == 1 else f"{schema.group_id}.{schema.schema_id}"
            root = self._add(name, schema)
            if root is not None:
                self.root_by_xid[schema.xid] = root
        self._coercer = SchemaCoercer(components=self._components, ref_prefix=_REF_PREFIX)

    @property
    def coercer(self) -> SchemaCoercer:
        """The coercer for inline payload schemas (shares the JSON Schema components)."""
        return self._coercer

    def resolve(self, ref: Optional[str]) -> Optional[str]:
        """The type key a ``dataschemaxid`` / ``dataschemauri`` names, when it is in this document.

        Args:
            ref: The reference — an xid (``/schemagroups/g/schemas/s``), a ``#``-prefixed one, a
                URL ending in one, each optionally with ``/versions/<v>``.

        Returns:
            The type key, or ``None`` for a reference outside the document.
        """
        if not ref:
            return None
        marker = ref.find("/schemagroups/")
        if marker < 0:
            return None
        parts = ref[marker:].split("#", 1)[0].strip("/").split("/")
        if len(parts) < 4:
            return None
        return self.root_by_xid.get(f"/{parts[0]}/{parts[1]}/{parts[2]}/{parts[3]}")

    def types(self) -> List[Type]:
        """Every type: JSON Schema components (and their synthesized members) plus delegated ones.

        Returns:
            The types, de-duplicated by key (the first wins).
        """
        merged: Dict[str, Type] = {}
        for type_ in self._coercer.named_types_from_components():
            merged.setdefault(type_.key, type_)
        for key, type_ in self._types.items():
            merged.setdefault(key, type_)
        return list(merged.values())

    def _add(self, name: str, schema: XRegistrySchema) -> Optional[str]:
        """Normalize one schema and return the key of the type its payload names.

        Args:
            name: The type name for a JSON Schema or an opaque schema.
            schema: The schema.

        Returns:
            The root type key, or ``None`` when no single type stands for the schema.
        """
        fmt = (schema.format or "").split("/", 1)[0].strip().lower()
        document = schema.document
        if fmt in ("", "jsonschema") and isinstance(document, Mapping):
            component = dict(document)
            if schema.description and not component.get("description"):
                component["description"] = schema.description
            if schema.deprecated:
                component.setdefault("deprecated", True)
            self._components[name] = component
            for defs_key in ("definitions", "$defs"):
                defs = document.get(defs_key)
                if isinstance(defs, Mapping):
                    for def_name, definition in defs.items():
                        if isinstance(definition, Mapping):
                            self._components.setdefault(str(def_name), dict(definition))
            return name
        if document is not None and fmt not in ("", "jsonschema"):
            delegated = _delegate(schema)
            if delegated:
                for type_ in delegated:
                    self._types.setdefault(type_.key, type_)
                return _root_key(document, delegated)
        reason = "no-document" if document is None else "unsupported-format"
        self._types[name] = _opaque_type(name, schema, reason)
        return name


def _delegate(schema: XRegistrySchema) -> List[Type]:
    """Normalize a non-JSON-Schema schema with the adapter its ``format`` names.

    Args:
        schema: A schema whose ``format`` is Avro, Protobuf or XSD and that carries a document.

    Returns:
        That adapter's types, or ``[]`` when the format has no adapter or the document does not
        parse (the caller then keeps an opaque type).
    """
    # Imported here: the crawl module imports the connector engine, which this module does not need.
    from .import_source import ImportSourceError, get_import_source
    from .xregistry_crawl import import_kind_for_format

    kind = import_kind_for_format(schema.format)
    adapter = get_import_source(kind[0]) if kind else None
    if adapter is None:
        return []
    document = schema.document
    text = document if isinstance(document, str) else _json_text(document)
    try:
        model = adapter.normalize(
            adapter.parse(text, source_label=f"{schema.schema_id}{kind[1]}"), include_raw=False
        )
    except (ImportSourceError, ValueError, TypeError) as exc:
        logger.info("xRegistry schema %s did not normalize as %s: %s", schema.xid, kind[0], exc)
        return []
    return list(model.types)


def _root_key(document: Any, types: List[Type]) -> Optional[str]:
    """The type a delegated schema's payload names: the Avro named root, else the only type.

    Args:
        document: The schema document.
        types: The delegated types.

    Returns:
        The type key, or ``None`` when the schema defines several types and names no root.
    """
    if isinstance(document, Mapping) and isinstance(document.get("name"), str):
        name = document["name"]
        namespace = document.get("namespace") if isinstance(document.get("namespace"), str) else None
        for candidate in (Keys.type(name, namespace), name):
            if any(t.key == candidate for t in types):
                return candidate
        for type_ in types:
            if type_.name == name:
                return type_.key
    return types[0].key if len(types) == 1 else None


def _opaque_type(name: str, schema: XRegistrySchema, reason: str) -> Type:
    """A schema Apiome cannot read structurally, kept so it still versions and diffs.

    Args:
        name: The type name (and key).
        schema: The schema.
        reason: ``no-document`` or ``unsupported-format``.

    Returns:
        A ``SCALAR`` type whose ``extras`` hold the format, the reason and the schema reference.
    """
    extras: Dict[str, Any] = {"xregistry_schema": schema.xid, "xregistry_opaque": reason}
    if schema.format:
        extras["xregistry_format"] = schema.format
    if schema.schema_uri:
        extras["xregistry_schema_uri"] = schema.schema_uri
    if schema.version_id:
        extras["xregistry_version"] = schema.version_id
    if isinstance(schema.document, str):
        extras["xregistry_document"] = schema.document
    return Type(
        key=Keys.type(name),
        name=name,
        kind=TypeKind.SCALAR,
        description=schema.description,
        deprecated=schema.deprecated,
        extras=extras,
    )


def _json_text(value: Any) -> str:
    """Serialize a parsed JSON value back to text for a delegated adapter.

    Args:
        value: The value.

    Returns:
        Compact, key-order-preserving JSON.
    """
    import json

    return json.dumps(value, ensure_ascii=False)


# ===========================================================================
# Messages → channels + operations; endpoints → services
# ===========================================================================


class _EventBuilder:
    """Accumulates channels while building services from message groups and endpoints."""

    def __init__(self, schema_types: _SchemaTypes) -> None:
        """Create a builder.

        Args:
            schema_types: The document's types, for payload resolution.
        """
        self._schemas = schema_types
        #: Channel address → channel.
        self.channels: Dict[str, Channel] = {}
        #: Channel address → ``(container, message id)`` of the message that describes it.
        self._channel_owner: Dict[str, Tuple[str, str]] = {}
        #: Protocol families seen on endpoints and messages (``mqtt``, ``kafka``).
        self.protocols: List[str] = []

    def group_service(self, group: XRegistryMessageGroup) -> Service:
        """A message group no endpoint carries, as a service of ``publish`` operations.

        Args:
            group: The group.

        Returns:
            The service, keyed by the group id.
        """
        operations = [
            self._operation(message, key=f"{group.group_id}.{message.message_id}", kind=OperationKind.PUBLISH)
            for message in group.messages
        ]
        return Service(
            key=group.group_id,
            name=group.name or group.group_id,
            description=group.description,
            operations=operations,
            extras=_clean({"xregistry_kind": "messagegroup", "xregistry_envelope": group.envelope,
                           "xregistry_protocol": group.protocol}),
        )

    def endpoint_service(
        self, endpoint: XRegistryEndpoint, groups: Mapping[str, XRegistryMessageGroup]
    ) -> Service:
        """An endpoint, as a service of the messages it carries.

        Args:
            endpoint: The endpoint.
            groups: The document's message groups by id.

        Returns:
            The service, keyed by the endpoint id. Referenced groups missing from the document are
            listed in its ``extras`` (``xregistry_unresolved_groups``).
        """
        consumer = bool(endpoint.usage) and set(endpoint.usage) <= _CONSUMER_USAGE
        kind = OperationKind.SUBSCRIBE if consumer else OperationKind.PUBLISH
        self._note_protocol(endpoint.protocol)
        operations: List[Operation] = []
        unresolved: List[str] = []
        for gid in endpoint.message_group_refs:
            group = groups.get(gid)
            if group is None:
                unresolved.append(gid)
                continue
            for message in group.messages:
                key = f"{endpoint.endpoint_id}.{gid}.{message.message_id}"
                operations.append(self._operation(message, key=key, kind=kind))
        for message in endpoint.messages:
            key = f"{endpoint.endpoint_id}.{message.message_id}"
            operations.append(self._operation(message, key=key, kind=kind))
        extras = _clean(
            {
                "xregistry_kind": "endpoint",
                "xregistry_usage": list(endpoint.usage) or None,
                "xregistry_protocol": endpoint.protocol,
                "xregistry_envelope": endpoint.envelope,
                "xregistry_protocol_options": dict(endpoint.protocol_options) or None,
                "xregistry_messagegroups": list(endpoint.message_group_refs) or None,
                "xregistry_unresolved_groups": unresolved or None,
                "xregistry_uris": list(endpoint.uris) or None,
                "xregistry_deprecated": endpoint.deprecated or None,
            }
        )
        return Service(
            key=endpoint.endpoint_id,
            name=endpoint.name or endpoint.endpoint_id,
            description=endpoint.description,
            operations=operations,
            extras=extras,
        )

    def _operation(
        self,
        message: XRegistryMessage,
        *,
        key: str,
        kind: OperationKind,
    ) -> Operation:
        """One message definition as an operation on its channel.

        The channel's protocol is the message's own (or its group's): a message carried by an MQTT
        and a Kafka endpoint is one channel, and the endpoints' protocols stay on their services.

        Args:
            message: The message.
            key: The container-qualified operation key.
            kind: ``publish`` or ``subscribe``.

        Returns:
            The operation, carrying one ``EVENT`` message.
        """
        channel = self._channel(message, message.protocol)
        payload, payload_schema = self._payload(message)
        event = Message(
            key=Keys.event_message(key, message.message_id),
            role=MessageRole.EVENT,
            name=message.name or message.message_id,
            payload=payload,
            payload_schema=payload_schema,
            headers=_headers(Keys.event_message(key, message.message_id), message),
            content_types=[message.data_content_type] if message.data_content_type else [],
            required=True,
            description=message.description,
            extras=_clean(
                {
                    "xregistry_message": f"/{message.container}/messages/{message.message_id}",
                    "xregistry_envelope": message.envelope,
                    "xregistry_dataschemaformat": message.data_schema_format,
                    "xregistry_dataschema": message.data_schema_ref,
                }
            ),
        )
        return Operation(
            key=key,
            name=message.message_id,
            kind=kind,
            description=message.description,
            deprecated=message.deprecated,
            channel_ref=channel.key,
            messages=[event],
            extras=_clean({"cloudevents_type": message.event_type}),
        )

    def _channel(self, message: XRegistryMessage, protocol: Optional[str]) -> Channel:
        """The channel a message travels on (one per CloudEvents ``type`` / message id).

        Several messages may share a CloudEvents ``type``; the channel's description, protocol and
        bindings then come from the one first by ``(container, message id)``, so the model does not
        depend on declaration order.

        Args:
            message: The message.
            protocol: Its effective protocol.

        Returns:
            The (possibly shared) channel.
        """
        address = message.event_type or message.message_id
        owner = (message.container, message.message_id)
        self._note_protocol(protocol)
        current = self._channel_owner.get(address)
        if current is not None and current <= owner:
            return self.channels[address]
        self._channel_owner[address] = owner
        family = _family(protocol)
        if family is None and (message.envelope or "").lower().startswith("cloudevents"):
            family = "cloudevents"
        bindings = {family or "xregistry": dict(message.protocol_binding)} if message.protocol_binding else {}
        source = _attribute_value(message, "source")
        channel = Channel(
            key=Keys.channel(address),
            address=address,
            name=address,
            description=message.description,
            protocol=family,
            bindings=bindings,
            extras=_clean({"cloudevents_source": source, "xregistry_envelope": message.envelope}),
        )
        self.channels[address] = channel
        return channel

    def _payload(self, message: XRegistryMessage) -> Tuple[Optional[TypeRef], Optional[Dict[str, Any]]]:
        """The payload type: the referenced schema's type, else the inline ``dataschema``.

        Args:
            message: The message.

        Returns:
            ``(type ref, inline schema)``; both ``None`` when the message names no schema in the
            document (its reference is still on the message's ``extras``).
        """
        root = self._schemas.resolve(message.data_schema_ref)
        if root is not None:
            return TypeRef(name=root, nullable=False), None
        if message.data_schema_inline is not None:
            inline = dict(message.data_schema_inline)
            return self._schemas.coercer.type_ref(inline, required=True), inline
        return None, None

    def _note_protocol(self, protocol: Optional[str]) -> None:
        """Record a protocol family for the model-level ``protocol``.

        Args:
            protocol: A protocol string (``MQTT/5.0``), or ``None``.
        """
        family = _family(protocol)
        if family and family not in self.protocols:
            self.protocols.append(family)


def _headers(message_key: str, message: XRegistryMessage) -> List[CanonicalField]:
    """The envelope attributes as message headers.

    Args:
        message_key: The owning message's key.
        message: The message.

    Returns:
        One field per attribute: its ``type`` mapped to a scalar, its ``value`` the default, and
        non-nullable when ``required``.
    """
    fields: List[CanonicalField] = []
    for name, attribute in message.envelope_metadata:
        attr_type = attribute.get("type")
        scalar = _ATTRIBUTE_TYPES.get(attr_type.lower(), "string") if isinstance(attr_type, str) else "string"
        fields.append(
            CanonicalField(
                key=Keys.field(message_key, name),
                name=name,
                type=TypeRef(name=scalar, nullable=not bool(attribute.get("required"))),
                default=attribute.get("value"),
                description=attribute.get("description") if isinstance(attribute.get("description"), str) else None,
            )
        )
    return fields


def _attribute_value(message: XRegistryMessage, name: str) -> Optional[str]:
    """The pinned ``value`` of an envelope attribute, when it is a string.

    Args:
        message: The message.
        name: The attribute name.

    Returns:
        The value or ``None``.
    """
    for attr_name, attribute in message.envelope_metadata:
        if attr_name == name and isinstance(attribute.get("value"), str):
            return attribute["value"]
    return None


def _servers(endpoints: Iterable[XRegistryEndpoint]) -> List[Server]:
    """One server per endpoint URI.

    Args:
        endpoints: The document's endpoints.

    Returns:
        The servers, named by endpoint id, de-duplicated and sorted by URL.
    """
    servers: List[Server] = []
    seen: set = set()
    for endpoint in sorted(endpoints, key=lambda e: e.endpoint_id):
        for uri in endpoint.uris:
            if uri in seen:
                continue
            seen.add(uri)
            servers.append(
                Server(url=uri, name=endpoint.endpoint_id, description=endpoint.description,
                       protocol=_family(endpoint.protocol))
            )
    servers.sort(key=lambda server: server.url)
    return servers


def _document_extras(source: XRegistryDocument) -> Dict[str, Any]:
    """Model-level ``extras``: the spec version and what the document holds.

    Args:
        source: The document.

    Returns:
        The extras.
    """
    return _clean(
        {
            "xregistry_specversion": source.spec_version,
            "xregistry_schema_count": len(source.schemas),
            "xregistry_message_count": sum(len(g.messages) for g in source.message_groups)
            + sum(len(e.messages) for e in source.endpoints),
            "xregistry_endpoint_count": len(source.endpoints),
        }
    )


def _family(protocol: Optional[str]) -> Optional[str]:
    """``MQTT/5.0`` → ``mqtt``.

    Args:
        protocol: A protocol string, or ``None``.

    Returns:
        The lower-cased family, or ``None``.
    """
    if not protocol:
        return None
    family = protocol.split("/", 1)[0].strip().lower()
    return family or None


def _single(values: List[str]) -> Optional[str]:
    """The only value of a list, else ``None``.

    Args:
        values: The values.

    Returns:
        The single value, or ``None`` for zero or several.
    """
    return values[0] if len(values) == 1 else None


def _clean(extras: Mapping[str, Any]) -> Dict[str, Any]:
    """``extras`` without ``None`` values.

    Args:
        extras: The candidate extras.

    Returns:
        A new dict without the ``None`` entries.
    """
    return {key: value for key, value in extras.items() if value is not None}
