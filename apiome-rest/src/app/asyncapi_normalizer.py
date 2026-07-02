"""AsyncAPI → canonical model normalizer — MFI-8.2 (#3760).

Maps a parsed, **already-dereferenced** AsyncAPI document (the
:attr:`app.asyncapi_parser.AsyncApiParseResult.document` MFI-8.1 produces) into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.EVENT`. It implements the
:class:`app.normalizer.Normalizer` SPI and handles both major AsyncAPI families,
whose document shapes differ substantially:

* **servers → :class:`~app.canonical_model.Server`** — a host the API is served
  from. v2 servers carry a ``url``; v3 servers split it into ``host`` + optional
  ``pathname`` (recombined into the canonical ``url``). The transport ``protocol``
  is preserved, and the first server's protocol becomes the artifact's primary
  :attr:`~app.canonical_model.CanonicalApi.protocol`.
* **channels → :class:`~app.canonical_model.Channel`** — the wire address (the
  channel's stable key), its address-template ``parameters``, and its protocol
  ``bindings``. In v2 the channel map key *is* the address; in v3 the address is
  an explicit field and the map key is a name.
* **operations → :class:`~app.canonical_model.Operation`** — the action drives the
  canonical :class:`~app.canonical_model.OperationKind` (``send``/``publish`` →
  :attr:`~app.canonical_model.OperationKind.PUBLISH`, ``receive``/``subscribe`` →
  :attr:`~app.canonical_model.OperationKind.SUBSCRIBE`); the bound channel becomes
  :attr:`~app.canonical_model.Operation.channel_ref`; the original action verb and
  any request/reply ``reply`` are kept in ``extras``. v3 operations are top-level
  and named; v2 operations are ``publish``/``subscribe`` members of a channel.
* **messages → :class:`~app.canonical_model.Message`** (role
  :attr:`~app.canonical_model.MessageRole.EVENT`) — the ``payload`` schema (kept
  inline as :attr:`~app.canonical_model.Message.payload_schema`, since the parser
  has already inlined every ``$ref``), the ``headers`` schema (coerced into header
  fields), the content type, and ``correlationId`` (in ``extras``).

Because the parser dereferences in-document ``$ref``\\s, payloads and referenced
channels/messages arrive *inlined*. The normalizer therefore keeps payload schemas
verbatim on the message rather than synthesizing named ``types`` (an event API's
contract is its channels/operations/messages, and the inline schema still flips
the fingerprint on any structural change). A v3 operation's dereferenced channel
is matched back to its declaring channel by address (with a ``$ref``/structural
fallback) so :attr:`~app.canonical_model.Operation.channel_ref` resolves.

The normalizer is **pure** (no I/O): it maps an in-memory tree and finishes with
:func:`app.normalizer.normalize_ordering`, so output is byte-stable regardless of
how the source ordered its servers/channels/operations — which is what the
MFI-3.1 fingerprint relies on. It self-registers under both ``asyncapi-2`` and
``asyncapi-3`` (the format keys :mod:`app.format_detection` emits).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

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
    ServerVariable,
    Service,
    TypeRef,
)
from .normalizer import (
    Keys,
    Normalizer,
    SchemaCoercer,
    coerce_constraints,
    normalize_ordering,
)

__all__ = ["AsyncApiNormalizer"]


# AsyncAPI 3 operation ``action`` → canonical :class:`OperationKind`. v3 actions are
# from the application's own perspective: it *sends* to (publishes) or *receives*
# from (subscribes to) a channel.
_V3_ACTION_KIND: Dict[str, OperationKind] = {
    "send": OperationKind.PUBLISH,
    "receive": OperationKind.SUBSCRIBE,
}

# AsyncAPI 2 channel operation slot → canonical :class:`OperationKind`. The verb is
# preserved literally; the original action is also kept in the operation's
# ``extras`` so the v2 perspective is never lost.
_V2_ACTION_KIND: Dict[str, OperationKind] = {
    "publish": OperationKind.PUBLISH,
    "subscribe": OperationKind.SUBSCRIBE,
}

# The two channel operation slots an AsyncAPI 2 channel may carry, in a stable
# order so two imports of the same document emit operations identically.
_V2_ACTIONS: Tuple[str, ...] = ("publish", "subscribe")

# Service key for operations that declare no tag, so every operation lives under
# exactly one service (mirrors the OpenAPI normalizer's grouping).
_DEFAULT_SERVICE = "default"

# Message-object keys captured verbatim into a message's ``extras`` for fidelity —
# everything the canonical :class:`Message` fields do not already model. ``name`` /
# ``summary`` / ``description`` / ``payload`` / ``headers`` / ``contentType`` are
# mapped to first-class fields and so are deliberately excluded here.
_MESSAGE_EXTRA_KEYS: Tuple[str, ...] = (
    "title",
    "messageId",
    "correlationId",
    "schemaFormat",
    "bindings",
    "traits",
    "examples",
    "externalDocs",
)

# Server-object keys captured verbatim into a server's ``extras`` (beyond the
# canonical ``url`` / ``protocol`` / ``description`` / ``variables`` fields).
_SERVER_EXTRA_KEYS: Tuple[str, ...] = (
    "host",
    "pathname",
    "protocolVersion",
    "security",
    "bindings",
    "tags",
    "externalDocs",
    "title",
    "summary",
)

# Operation-object keys captured verbatim into an operation's ``extras`` (beyond
# the canonical ``kind`` / ``channel_ref`` / ``messages`` / ``tags`` /
# ``description`` and the synthesized ``action``).
_OPERATION_EXTRA_KEYS: Tuple[str, ...] = (
    "reply",
    "bindings",
    "traits",
    "security",
    "externalDocs",
    "title",
)


class AsyncApiNormalizer(Normalizer, register=True):
    """Normalize a parsed AsyncAPI 2.x/3.x document into a :class:`CanonicalApi`.

    Self-registers under ``asyncapi-3``; :class:`_AsyncApi2Normalizer` adds the
    ``asyncapi-2`` alias. Both registry keys resolve to this one implementation,
    which dispatches on the document's own ``asyncapi`` version (so the result is
    correct regardless of which key was used to look the normalizer up).
    """

    format = "asyncapi-3"  # registry key; the emitted ``format`` is per-document
    paradigm = ApiParadigm.EVENT

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a parsed, dereferenced AsyncAPI document.

        Args:
            source: The parsed AsyncAPI document as a ``dict`` — the dereferenced,
                canonical JSON :func:`app.asyncapi_parser.parse_asyncapi` returns.
                In-document ``$ref``\\s are expected to be inlined already.
            include_raw: When ``True`` (default) the source document is preserved
                on :attr:`CanonicalApi.raw` for full-fidelity round-tripping.

        Returns:
            The order-normalized :class:`CanonicalApi`; ``format`` is
            ``asyncapi-2`` or ``asyncapi-3`` per the document's declared version.

        Raises:
            ValueError: If ``source`` is not a mapping or is not an AsyncAPI 2.x/3.x
                document (no ``asyncapi: 2.x|3.x`` version string).
        """
        if not isinstance(source, dict):
            raise ValueError("AsyncAPI source must be a parsed mapping (dict)")
        major, format_key = self._detect_format(source)

        info = source.get("info") if isinstance(source.get("info"), dict) else {}
        default_content_type = source.get("defaultContentType")
        if not isinstance(default_content_type, str):
            default_content_type = None

        if major == "3":
            servers = self._servers_v3(source.get("servers"))
            channels, operations = self._build_v3(source, default_content_type)
        else:
            servers = self._servers_v2(source.get("servers"))
            channels, operations = self._build_v2(source, default_content_type)

        doc_id = source.get("id")
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=format_key,
            protocol=servers[0].protocol if servers else None,
            identity=ApiIdentity(
                name=info.get("title") or "Untitled API",
                id=doc_id if isinstance(doc_id, str) else None,
            ),
            version=info.get("version"),
            title=info.get("title"),
            description=info.get("description"),
            servers=servers,
            services=self._group_services(operations),
            channels=channels,
            raw=source if include_raw else None,
        )
        return normalize_ordering(api)

    # --- format detection ---------------------------------------------------

    @staticmethod
    def _detect_format(source: Dict[str, Any]) -> Tuple[str, str]:
        """Return ``(major, format_key)`` for the document's AsyncAPI version.

        Args:
            source: The parsed document.

        Returns:
            ``("2", "asyncapi-2")`` or ``("3", "asyncapi-3")`` (a newer minor of an
            accepted major still normalizes under that major's key).

        Raises:
            ValueError: If the document has no ``asyncapi: 2.x|3.x`` version string.
        """
        version = source.get("asyncapi")
        if isinstance(version, str):
            major = version.split(".", 1)[0]
            if major in {"2", "3"}:
                return major, f"asyncapi-{major}"
        raise ValueError(
            "not an AsyncAPI 2.x/3.x document (missing or unsupported `asyncapi` version)"
        )

    # --- servers ------------------------------------------------------------

    def _servers_v3(self, servers: Any) -> List[Server]:
        """Coerce a v3 ``servers`` map into canonical :class:`Server`s.

        A v3 server splits the address into ``host`` and an optional ``pathname``;
        both are recombined into the canonical ``url`` and also retained verbatim
        in ``extras`` so the split round-trips.
        """
        result: List[Server] = []
        for name, spec in self._items(servers):
            host = spec.get("host")
            pathname = spec.get("pathname")
            url = host if isinstance(host, str) else ""
            if isinstance(pathname, str):
                url = f"{url}{pathname}"
            result.append(
                Server(
                    url=url or name,
                    name=name,
                    description=spec.get("description"),
                    protocol=spec.get("protocol"),
                    variables=self._server_variables(spec.get("variables")),
                    extras=self._collect(spec, _SERVER_EXTRA_KEYS),
                )
            )
        return result

    def _servers_v2(self, servers: Any) -> List[Server]:
        """Coerce a v2 ``servers`` map into canonical :class:`Server`s.

        A v2 server already carries a single ``url`` (which may be a template with
        ``{variables}``).
        """
        result: List[Server] = []
        for name, spec in self._items(servers):
            url = spec.get("url")
            result.append(
                Server(
                    url=url if isinstance(url, str) and url else name,
                    name=name,
                    description=spec.get("description"),
                    protocol=spec.get("protocol"),
                    variables=self._server_variables(spec.get("variables")),
                    extras=self._collect(spec, _SERVER_EXTRA_KEYS),
                )
            )
        return result

    @staticmethod
    def _server_variables(variables: Any) -> List[ServerVariable]:
        """Coerce a server ``variables`` map into canonical :class:`ServerVariable`s."""
        result: List[ServerVariable] = []
        if not isinstance(variables, dict):
            return result
        for name, spec in variables.items():
            if not isinstance(spec, dict):
                continue
            enum = spec.get("enum")
            result.append(
                ServerVariable(
                    name=name,
                    default=spec.get("default"),
                    enum=enum if isinstance(enum, list) else None,
                    description=spec.get("description"),
                )
            )
        return result

    # --- v3: channels + operations -----------------------------------------

    def _build_v3(
        self, source: Dict[str, Any], default_content_type: Optional[str]
    ) -> Tuple[List[Channel], List[Operation]]:
        """Build channels and operations from a v3 document.

        v3 names its channels and carries operations at the top level, each bound
        to a channel by reference.
        """
        coercer = SchemaCoercer(components={})
        channels_map = source.get("channels")

        channels: List[Channel] = []
        channel_key_by_name: Dict[str, str] = {}
        for name, spec in self._items(channels_map):
            channel = self._channel_v3(name, spec, coercer)
            channels.append(channel)
            channel_key_by_name[name] = channel.key

        operations: List[Operation] = []
        for op_name, op_spec in self._items(source.get("operations")):
            operations.append(
                self._operation_v3(
                    op_name,
                    op_spec,
                    channels_map if isinstance(channels_map, dict) else {},
                    channel_key_by_name,
                    coercer,
                    default_content_type,
                )
            )
        return channels, operations

    def _channel_v3(
        self, name: str, spec: Dict[str, Any], coercer: SchemaCoercer
    ) -> Channel:
        """Coerce one v3 channel (its ``address``, parameters, and bindings)."""
        address = spec.get("address")
        key = address if isinstance(address, str) and address else name
        bindings = spec.get("bindings")
        return Channel(
            key=key,
            address=address if isinstance(address, str) and address else name,
            name=name,
            description=spec.get("description") or spec.get("summary"),
            parameters=self._channel_parameters_v3(key, spec.get("parameters"), coercer),
            bindings=bindings if isinstance(bindings, dict) else {},
            extras=self._collect(spec, ("title", "tags", "externalDocs")),
        )

    def _channel_parameters_v3(
        self, channel_key: str, parameters: Any, coercer: SchemaCoercer
    ) -> List[CanonicalField]:
        """Coerce a v3 channel ``parameters`` map into address-parameter fields.

        v3 parameters are always string-valued; an ``enum``/``default`` constrains
        them, and ``location`` (where the value is taken from) is kept in ``extras``.
        """
        result: List[CanonicalField] = []
        for name, spec in self._items(parameters):
            result.append(
                CanonicalField(
                    key=Keys.channel_parameter(channel_key, name),
                    name=name,
                    type=TypeRef(name="string", nullable=False),
                    default=spec.get("default"),
                    constraints=coerce_constraints(spec),
                    description=spec.get("description"),
                    extras=self._collect(spec, ("location", "examples")),
                )
            )
        return result

    def _operation_v3(
        self,
        op_name: str,
        op_spec: Dict[str, Any],
        channels_map: Dict[str, Any],
        channel_key_by_name: Dict[str, str],
        coercer: SchemaCoercer,
        default_content_type: Optional[str],
    ) -> Operation:
        """Coerce one top-level v3 operation.

        The ``action`` selects the canonical kind, the (dereferenced) ``channel``
        is matched back to its declaring channel for ``channel_ref``, and the
        operation's messages are taken from its ``messages`` subset or, when it
        lists none, from the bound channel's full message set.
        """
        action = op_spec.get("action")
        kind = _V3_ACTION_KIND.get(action, OperationKind.PUBLISH)
        channel_name, channel_ref = self._resolve_channel_v3(
            op_spec.get("channel"), channels_map, channel_key_by_name
        )
        channel_spec = (
            channels_map.get(channel_name) if channel_name is not None else None
        )

        op_key = Keys.operation_event(str(action), channel_ref or "", op_name)
        extras: Dict[str, Any] = {"action": action} if isinstance(action, str) else {}
        extras.update(self._collect(op_spec, _OPERATION_EXTRA_KEYS))

        return Operation(
            key=op_key,
            name=op_name,
            kind=kind,
            channel_ref=channel_ref,
            description=op_spec.get("description") or op_spec.get("summary"),
            messages=self._messages_v3(
                op_key, op_spec, channel_spec, coercer, default_content_type
            ),
            tags=self._tags(op_spec.get("tags")),
            extras=extras,
        )

    @staticmethod
    def _resolve_channel_v3(
        channel_field: Any,
        channels_map: Dict[str, Any],
        channel_key_by_name: Dict[str, str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Resolve a v3 operation's ``channel`` to ``(channel_name, channel_key)``.

        The parser inlines the channel ``$ref``, so ``channel_field`` is normally
        the channel object itself; it is matched back to a declaring channel by
        ``address`` (then by structural equality). A still-present ``$ref`` is also
        honored. Returns ``(None, None)`` when nothing resolves.
        """
        if not isinstance(channel_field, dict):
            return None, None

        ref = channel_field.get("$ref")
        if isinstance(ref, str):
            name = ref.rstrip("/").rsplit("/", 1)[-1]
            return name, channel_key_by_name.get(name)

        address = channel_field.get("address")
        if isinstance(address, str) and address:
            for name, spec in channels_map.items():
                if isinstance(spec, dict) and spec.get("address") == address:
                    return name, channel_key_by_name.get(name)
            # Address present but no declaring channel matched: the address is the key.
            return None, address

        for name, spec in channels_map.items():
            if spec == channel_field:
                return name, channel_key_by_name.get(name)
        return None, None

    def _messages_v3(
        self,
        op_key: str,
        op_spec: Dict[str, Any],
        channel_spec: Optional[Dict[str, Any]],
        coercer: SchemaCoercer,
        default_content_type: Optional[str],
    ) -> List[Message]:
        """Resolve a v3 operation's messages into canonical :class:`Message`s.

        Uses the operation's ``messages`` list when present (a subset of the
        channel's messages), otherwise every message declared on the bound channel.
        """
        channel_messages = (
            channel_spec.get("messages") if isinstance(channel_spec, dict) else None
        )
        channel_messages = channel_messages if isinstance(channel_messages, dict) else {}

        named: List[Tuple[str, Dict[str, Any]]] = []
        op_messages = op_spec.get("messages")
        if isinstance(op_messages, list) and op_messages:
            for index, entry in enumerate(op_messages):
                if not isinstance(entry, dict):
                    continue
                obj, fallback = entry, f"message{index}"
                ref = entry.get("$ref")
                if isinstance(ref, str):
                    fallback = ref.rstrip("/").rsplit("/", 1)[-1]
                    if isinstance(channel_messages.get(fallback), dict):
                        obj = channel_messages[fallback]
                named.append((self._message_name(obj, fallback), obj))
        else:
            for msg_name, obj in channel_messages.items():
                if isinstance(obj, dict):
                    named.append((self._message_name(obj, msg_name), obj))

        return [
            self._message(op_key, name, obj, coercer, default_content_type)
            for name, obj in named
        ]

    # --- v2: channels + operations -----------------------------------------

    def _build_v2(
        self, source: Dict[str, Any], default_content_type: Optional[str]
    ) -> Tuple[List[Channel], List[Operation]]:
        """Build channels and operations from a v2 document.

        v2 keys channels by address and carries each operation as a
        ``publish``/``subscribe`` member of its channel.
        """
        coercer = SchemaCoercer(components={})
        channels: List[Channel] = []
        operations: List[Operation] = []

        for address, spec in self._items(source.get("channels")):
            channel_key = address
            channels.append(self._channel_v2(address, spec, coercer))
            for action in _V2_ACTIONS:
                op_spec = spec.get(action)
                if isinstance(op_spec, dict):
                    operations.append(
                        self._operation_v2(
                            action,
                            address,
                            channel_key,
                            op_spec,
                            coercer,
                            default_content_type,
                        )
                    )
        return channels, operations

    def _channel_v2(
        self, address: str, spec: Dict[str, Any], coercer: SchemaCoercer
    ) -> Channel:
        """Coerce one v2 channel (its address parameters and protocol bindings)."""
        bindings = spec.get("bindings")
        return Channel(
            key=address,
            address=address,
            description=spec.get("description"),
            parameters=self._channel_parameters_v2(address, spec.get("parameters"), coercer),
            bindings=bindings if isinstance(bindings, dict) else {},
            extras=self._collect(spec, ("servers",)),
        )

    def _channel_parameters_v2(
        self, channel_key: str, parameters: Any, coercer: SchemaCoercer
    ) -> List[CanonicalField]:
        """Coerce a v2 channel ``parameters`` map into address-parameter fields.

        v2 parameters carry a JSON-Schema ``schema``; its type/constraints are
        coerced, and ``location`` is kept in ``extras``.
        """
        result: List[CanonicalField] = []
        for name, spec in self._items(parameters):
            schema = spec.get("schema") if isinstance(spec.get("schema"), dict) else {}
            result.append(
                CanonicalField(
                    key=Keys.channel_parameter(channel_key, name),
                    name=name,
                    type=(
                        coercer.type_ref(schema, required=True)
                        if schema
                        else TypeRef(name="string", nullable=False)
                    ),
                    default=schema.get("default"),
                    constraints=coerce_constraints(schema) if schema else None,
                    description=spec.get("description"),
                    extras=self._collect(spec, ("location",)),
                )
            )
        return result

    def _operation_v2(
        self,
        action: str,
        address: str,
        channel_key: str,
        op_spec: Dict[str, Any],
        coercer: SchemaCoercer,
        default_content_type: Optional[str],
    ) -> Operation:
        """Coerce one v2 ``publish``/``subscribe`` channel operation."""
        operation_id = op_spec.get("operationId")
        name = operation_id if isinstance(operation_id, str) and operation_id else None
        op_key = Keys.operation_event(action, address, name)

        extras: Dict[str, Any] = {"action": action}
        extras.update(self._collect(op_spec, _OPERATION_EXTRA_KEYS))

        return Operation(
            key=op_key,
            name=name or op_key,
            kind=_V2_ACTION_KIND[action],
            channel_ref=channel_key,
            description=op_spec.get("description") or op_spec.get("summary"),
            messages=self._messages_v2(
                op_key, op_spec.get("message"), coercer, default_content_type
            ),
            tags=self._tags(op_spec.get("tags")),
            extras=extras,
        )

    def _messages_v2(
        self,
        op_key: str,
        message_field: Any,
        coercer: SchemaCoercer,
        default_content_type: Optional[str],
    ) -> List[Message]:
        """Resolve a v2 operation's ``message`` (single or ``oneOf``) into messages."""
        if not isinstance(message_field, dict):
            return []
        one_of = message_field.get("oneOf")
        objects = (
            [m for m in one_of if isinstance(m, dict)]
            if isinstance(one_of, list)
            else [message_field]
        )
        return [
            self._message(
                op_key,
                self._message_name(obj, f"message{index}"),
                obj,
                coercer,
                default_content_type,
            )
            for index, obj in enumerate(objects)
        ]

    # --- shared message/header coercion ------------------------------------

    def _message(
        self,
        op_key: str,
        message_name: str,
        spec: Dict[str, Any],
        coercer: SchemaCoercer,
        default_content_type: Optional[str],
    ) -> Message:
        """Coerce one AsyncAPI message object into a canonical :class:`Message`.

        The payload schema is kept inline (the parser has already inlined any
        ``$ref``), headers become header fields, the content type falls back to the
        document's ``defaultContentType``, and ``correlationId`` and other
        format-specific attributes are retained in ``extras``.
        """
        message_key = Keys.event_message(op_key, message_name)
        payload = spec.get("payload")
        content_type = spec.get("contentType") or default_content_type
        return Message(
            key=message_key,
            role=MessageRole.EVENT,
            name=spec.get("name") or message_name,
            payload_schema=payload if isinstance(payload, dict) else None,
            headers=self._headers(message_key, spec.get("headers"), coercer),
            content_types=[content_type] if isinstance(content_type, str) else [],
            description=spec.get("summary") or spec.get("description"),
            extras=self._collect(spec, _MESSAGE_EXTRA_KEYS),
        )

    def _headers(
        self, message_key: str, headers_schema: Any, coercer: SchemaCoercer
    ) -> List[CanonicalField]:
        """Coerce an AsyncAPI message ``headers`` schema into header fields.

        AsyncAPI models headers as a single (object) schema; its ``properties``
        become the canonical message :attr:`Message.headers` fields.
        """
        if not isinstance(headers_schema, dict):
            return []
        properties = headers_schema.get("properties")
        if not isinstance(properties, dict):
            return []
        required = set(headers_schema.get("required") or [])
        result: List[CanonicalField] = []
        for name, schema in properties.items():
            if not isinstance(schema, dict):
                continue
            result.append(
                CanonicalField(
                    key=Keys.field(message_key, name),
                    name=name,
                    type=coercer.type_ref(schema, required=name in required),
                    default=schema.get("default"),
                    constraints=coerce_constraints(schema),
                    description=schema.get("description"),
                    deprecated=bool(schema.get("deprecated", False)),
                )
            )
        return result

    # --- shared helpers -----------------------------------------------------

    def _group_services(self, operations: List[Operation]) -> List[Service]:
        """Group operations into services by first tag (``default`` when untagged).

        AsyncAPI has no service construct, so — like the OpenAPI normalizer — an
        operation is filed under its first tag, with all untagged operations in a
        single ``default`` service.
        """
        by_service: Dict[str, List[Operation]] = {}
        for operation in operations:
            key = operation.tags[0] if operation.tags else _DEFAULT_SERVICE
            by_service.setdefault(key, []).append(operation)
        return [
            Service(key=key, name=key, operations=ops)
            for key, ops in by_service.items()
        ]

    @staticmethod
    def _message_name(spec: Dict[str, Any], fallback: str) -> str:
        """Return a message's source ``name``, or ``fallback`` when anonymous."""
        name = spec.get("name")
        return name if isinstance(name, str) and name else fallback

    @staticmethod
    def _tags(raw: Any) -> List[str]:
        """Extract tag names from an AsyncAPI ``tags`` array of ``{name, …}`` objects."""
        if not isinstance(raw, list):
            return []
        return [
            tag["name"]
            for tag in raw
            if isinstance(tag, dict) and isinstance(tag.get("name"), str)
        ]

    @staticmethod
    def _items(mapping: Any) -> List[Tuple[str, Dict[str, Any]]]:
        """Yield ``(key, value)`` pairs of a mapping, skipping non-dict members.

        Centralizes the "is it a populated map of objects" guard the AsyncAPI shape
        needs everywhere (servers, channels, operations, parameters, messages).
        """
        if not isinstance(mapping, dict):
            return []
        return [
            (name, spec) for name, spec in mapping.items() if isinstance(spec, dict)
        ]

    @staticmethod
    def _collect(spec: Dict[str, Any], keys: Tuple[str, ...]) -> Dict[str, Any]:
        """Copy the present, non-empty ``keys`` of ``spec`` into a fidelity ``extras`` bag."""
        extras: Dict[str, Any] = {}
        for key in keys:
            value = spec.get(key)
            if value is not None and value != [] and value != {}:
                extras[key] = value
        return extras


class _AsyncApi2Normalizer(AsyncApiNormalizer, register=True):
    """Alias registration of :class:`AsyncApiNormalizer` under the ``asyncapi-2`` key.

    AsyncAPI 2 and 3 share one implementation (which branches on the document's own
    ``asyncapi`` version); this thin subclass only changes the registry key.
    """

    format = "asyncapi-2"
