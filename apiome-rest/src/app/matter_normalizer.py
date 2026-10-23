"""Matter cluster and device-type definitions → canonical model normalizer — FMT-9.5 (#5472).

Maps a parsed :class:`~app.matter_parser.MatterDocument` onto the **rpc** paradigm:

.. code-block:: text

    cluster "On/Off" (0x0006)              → RECORD    OnOff            (attributes as fields)
                                             SERVICE   OnOffService
    attribute OnTime (0x4001)              → field     OnOff.OnTime     (field_number 0x4001)
    command source="client" OffWithEffect  → operation OnOffService.OffWithEffect (request_response)
                                             RECORD    OnOff.OffWithEffectRequest (its arguments)
    command source="server" XResponse      → RECORD    <Cluster>.XResponse (the reply a client
                                             command's ``response`` names)
    event StartUp                          → operation <Cluster>Service.StartUp (subscribe)
                                             RECORD    <Cluster>.StartUpEvent (its fields)
    enum / bitmap                          → ENUM      (a bitmap's members are its flag masks)
    struct                                 → RECORD
    deviceType "Matter Dimmable Light"     → RECORD    MatterDimmableLight (one field per
                                             included cluster, typed as that cluster's record)

* Attribute **access** is declared metadata: ``extras['matter_attribute']['access']`` is ``read``
  or ``read-write`` (``writable``), with the ``access`` privileges beside it; a command's invoke
  privilege rides on its operation.
* ``optional`` / ``isNullable`` → a nullable reference (canonical ``nullable`` means "null or
  absent"); ``array`` / ``entryType`` → a list.
* ``min`` / ``max`` → ``minimum`` / ``maximum``; ``length`` / ``minLength`` → string length or list
  size; ``default`` → the field default. Semantic types keep their base scalar
  (:data:`~app.matter_parser.BASE_TYPES`) with the written type in ``extras['matter_type']``.
* A type the import does not declare, on a standard cluster, keeps the ``any`` type and names the
  type in ``extras['matter_unresolved']``; a device type's included cluster outside the import
  likewise. Both are declared limits, counted in ``extras['matter']['capability_limits']``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    EnumValue,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from .device_model_xml import identifier
from .matter_parser import (
    BASE_TYPES,
    FORMAT_KEY,
    MatterAttribute,
    MatterCluster,
    MatterCommand,
    MatterDataType,
    MatterDeviceType,
    MatterDocument,
    MatterEvent,
    MatterField,
    MatterTypeUse,
    parse_code,
    raw_record,
)
from .normalizer import Keys, Normalizer, normalize_ordering
from .typescript_types_normalizer import _limits_payload
from .typescript_types_parser import LimitRecorder

__all__ = [
    "LIMIT_DETAILS",
    "MATTER_EXTRAS_KEY",
    "PARTIAL_LIMITS",
    "MatterNormalizer",
]

#: Root extras key of the projection record.
MATTER_EXTRAS_KEY = "matter"

#: The transport the canonical model names for Matter.
MATTER_PROTOCOL = "matter"

#: The declared-limit vocabulary (stable keys → reviewed sentence).
LIMIT_DETAILS: Dict[str, str] = {
    "matter.standard_type_reference": (
        "A member of a standard cluster uses a data type the import does not declare; the Matter "
        "specification defines it for that cluster. The member keeps the any type and names the "
        "type in extras['matter_unresolved']; import the file that declares it to resolve it."
    ),
    "matter.external_cluster": (
        "A device type includes a cluster whose definition is not in the import. The device's "
        "field for it keeps the any type and names the cluster in extras['matter_unresolved']; "
        "import the cluster definition beside the device type to resolve it."
    ),
    "matter.bitmap_flags": (
        "A bitmap is projected to an enum of its flag masks; a value may combine several flags, "
        "which the enum does not express. The bitmap's base type is kept in extras['matter_bitmap']."
    ),
    "matter.feature_conformance": (
        "A cluster declares features whose conformance (which attributes and commands each feature "
        "enables) is kept in extras['matter_cluster']['features'] but not evaluated, so "
        "feature-gated members are modelled as the definition writes them."
    ),
}

#: Limits whose construct is still modelled, with only a detail lost — every Matter limit is.
PARTIAL_LIMITS = frozenset(LIMIT_DETAILS)

#: Canonical scalars whose defaults and bounds read as numbers.
_NUMERIC_PREFIXES = ("int", "uint", "float", "double")


def _number(text: Optional[str]) -> Optional[float]:
    """A written bound (``0x10``, ``-40``, ``1.5``) as a number, or ``None``."""
    if text is None or not text.strip():
        return None
    value = parse_code(text.strip().lstrip("-"))
    if value is not None:
        return float(-value if text.strip().startswith("-") else value)
    try:
        return float(text)
    except ValueError:
        return None


def _privileges(access: Tuple[Tuple[str, str], ...]) -> Dict[str, str]:
    return {op: privilege for op, privilege in access if op and privilege}


class _Builder:
    """Accumulates types and limits while one document is normalized."""

    def __init__(self, document: MatterDocument) -> None:
        self.document = document
        self.types: Dict[str, Type] = {}
        self.limits = LimitRecorder(details=LIMIT_DETAILS)
        self.cluster_keys: Dict[int, str] = {}
        taken: Dict[str, Any] = {}
        for cluster in document.clusters:
            key = identifier(cluster.name, fallback=f"Cluster{cluster.code:04X}")
            key = key if key not in taken else f"{key}_{cluster.code:04X}"
            taken[key] = cluster
            self.cluster_keys[cluster.code] = key
        self.data_type_keys: Dict[int, str] = {}
        names: Dict[str, int] = {}
        for data_type in document.data_types:
            names[data_type.name] = names.get(data_type.name, 0) + 1
        for data_type in document.data_types:
            namespace = None
            if names[data_type.name] > 1:
                namespace = next(
                    (self.cluster_keys[code] for code in data_type.clusters if code in self.cluster_keys),
                    f"Cluster{data_type.clusters[0]:04X}" if data_type.clusters else None,
                )
            self.data_type_keys[id(data_type)] = Keys.type(data_type.name, namespace)

    # --- references ----------------------------------------------------------

    def _element(self, name: str, cluster: Optional[MatterCluster], location: str) -> Tuple[TypeRef, Dict[str, Any]]:
        """The reference of one element type and the constraint facets its base type implies."""
        base = BASE_TYPES.get(name.lower())
        if base is not None:
            return TypeRef(name=base[0], nullable=False), dict(base[1])
        declared = self.document.resolve(name, cluster.code if cluster else None)
        if declared is not None:
            return TypeRef(name=self.data_type_keys[id(declared)], nullable=False), {}
        self.limits.record("matter.standard_type_reference", location=location)
        return TypeRef(name="any", nullable=False, extras={"matter_unresolved": name}), {}

    def member(
        self,
        *,
        key: str,
        name: str,
        number: int,
        use: MatterTypeUse,
        cluster: Optional[MatterCluster],
        source: Any,
        extras: Dict[str, Any],
        description: Optional[str] = None,
    ) -> CanonicalField:
        """A struct item, argument, event field or attribute as a canonical field."""
        element, facets = self._element(use.name, cluster, key)
        nullable = bool(source.optional or source.nullable)
        values: Dict[str, Any] = {}
        constraint_extras: Dict[str, Any] = {}
        minimum, maximum = _number(source.minimum), _number(source.maximum)
        if minimum is not None:
            facets["minimum"] = minimum
        if maximum is not None:
            facets["maximum"] = maximum
        if use.is_list:
            type_ref = TypeRef(item=element, nullable=nullable)
            if source.length is not None:
                values["max_items"] = source.length
            if source.min_length is not None:
                values["min_items"] = source.min_length
            constraint_extras.update({f"item_{facet}": value for facet, value in facets.items()})
        else:
            type_ref = TypeRef(name=element.name, nullable=nullable, extras=element.extras)
            values.update(facets)
            if source.length is not None:
                values["max_length"] = source.length
            if source.min_length is not None:
                values["min_length"] = source.min_length
        written = f"array<{use.name}>" if use.is_list else use.name
        field_extras: Dict[str, Any] = {"matter_type": written, **extras}
        default = self._default(source.default, element.name)
        if source.default is not None and default != source.default:
            field_extras["matter_default"] = source.default
        return CanonicalField(
            key=key,
            name=name,
            type=type_ref,
            field_number=number,
            default=default,
            constraints=Constraints(**values, extras=constraint_extras) if values or constraint_extras else None,
            description=description,
            extras=field_extras,
        )

    @staticmethod
    def _default(text: Optional[str], scalar: Optional[str]) -> Any:
        """A written default as a value of the member's canonical scalar."""
        if text is None:
            return None
        if scalar == "boolean" and text.strip().lower() in ("true", "false"):
            return text.strip().lower() == "true"
        if scalar and scalar.startswith(_NUMERIC_PREFIXES):
            number = _number(text)
            if number is not None:
                return int(number) if number.is_integer() and not scalar.startswith(("float", "double")) else number
        return text

    def fields(
        self, members: Tuple[MatterField, ...], type_key: str, cluster: Optional[MatterCluster]
    ) -> List[CanonicalField]:
        """The fields of a struct, an argument list or an event."""
        return [
            self.member(
                key=Keys.field(type_key, item.name),
                name=item.name,
                number=item.id,
                use=item.type,
                cluster=cluster,
                source=item,
                extras={},
            )
            for item in members
        ]

    # --- types ---------------------------------------------------------------

    def data_type(self, data_type: MatterDataType) -> None:
        """Define one declared enum, bitmap or struct."""
        key = self.data_type_keys[id(data_type)]
        namespace = key.rsplit(".", 1)[0] if "." in key else None
        clusters = [f"0x{code:04X}" for code in data_type.clusters]
        cluster = next((item for item in self.document.clusters if item.code in data_type.clusters), None)
        if data_type.kind == "struct":
            self.types[key] = Type(
                key=key,
                name=data_type.name,
                kind=TypeKind.RECORD,
                namespace=namespace,
                fields=self.fields(data_type.fields, key, cluster),
                extras={"matter_struct": {"clusters": clusters}},
            )
            return
        extras: Dict[str, Any] = {f"matter_{data_type.kind}": {"base": data_type.base, "clusters": clusters}}
        if data_type.kind == "bitmap":
            self.limits.record("matter.bitmap_flags", location=key)
        self.types[key] = Type(
            key=key,
            name=data_type.name,
            kind=TypeKind.ENUM,
            namespace=namespace,
            description="A flag set: a value combines any of these masks." if data_type.kind == "bitmap" else None,
            enum_values=[
                EnumValue(key=Keys.enum_value(key, name), name=name, value=value) for name, value in data_type.members
            ],
            extras=extras,
        )

    def attribute(self, attribute: MatterAttribute, cluster: MatterCluster, type_key: str) -> CanonicalField:
        """One attribute as a field of its cluster's record."""
        name = identifier(attribute.name, fallback=f"Attribute{attribute.code:04X}")
        record: Dict[str, Any] = {
            "code": f"0x{attribute.code:04X}",
            "side": attribute.side,
            "access": "read-write" if attribute.writable else "read",
            "optional": attribute.optional,
            "nullable": attribute.nullable,
            "reportable": attribute.reportable,
        }
        if attribute.define:
            record["define"] = attribute.define
        privileges = _privileges(attribute.access)
        if privileges:
            record["privileges"] = privileges
        return self.member(
            key=Keys.field(type_key, name),
            name=name,
            number=attribute.code,
            use=attribute.type,
            cluster=cluster,
            source=attribute,
            extras={"matter_attribute": record},
            description=attribute.description,
        )

    def command_record(self, command: MatterCommand, cluster: MatterCluster, name: str) -> str:
        """Define the record of a command's arguments and return its key."""
        cluster_key = self.cluster_keys[cluster.code]
        key = Keys.type(name, cluster_key)
        self.types[key] = Type(
            key=key,
            name=name,
            kind=TypeKind.RECORD,
            namespace=cluster_key,
            description=command.description,
            fields=self.fields(command.args, key, cluster),
            extras={"matter_command": {"code": f"0x{command.code:02X}", "source": command.source}},
        )
        return key

    def cluster(self, cluster: MatterCluster) -> Optional[Service]:
        """Define a cluster's record, command and event records; return its service."""
        key = self.cluster_keys[cluster.code]
        record: Dict[str, Any] = {"name": cluster.name, "code": cluster.code_text}
        for attr, value in (("define", cluster.define), ("domain", cluster.domain), ("file", cluster.path)):
            if value:
                record[attr] = value
        if cluster.features:
            record["features"] = [dict(item) for item in cluster.features]
            self.limits.record("matter.feature_conformance", location=key)
        self.types[key] = Type(
            key=key,
            name=key,
            kind=TypeKind.RECORD,
            description=cluster.description,
            fields=[self.attribute(item, cluster, key) for item in cluster.attributes],
            extras={"matter_cluster": record},
        )
        responses = {
            item.name: self.command_record(item, cluster, identifier(item.name, fallback=item.name))
            for item in cluster.commands
            if item.source == "server"
        }
        service_key = f"{key}Service"
        operations = [
            self._command_operation(item, cluster, service_key, responses)
            for item in cluster.commands
            if item.source == "client"
        ]
        taken = {operation.name for operation in operations}
        operations.extend(self._event_operation(item, cluster, service_key, taken) for item in cluster.events)
        if not operations:
            return None
        return Service(
            key=service_key,
            name=service_key,
            description=f"The commands and events of the {cluster.name} cluster.",
            operations=operations,
        )

    def _command_operation(
        self, command: MatterCommand, cluster: MatterCluster, service_key: str, responses: Dict[str, str]
    ) -> Operation:
        """A client command as a request/response operation of the cluster's service."""
        name = identifier(command.name, fallback=f"Command{command.code:02X}")
        key = Keys.operation_rpc(service_key, name)
        messages: List[Message] = []
        if command.args:
            request = self.command_record(command, cluster, f"{name}Request")
            messages.append(
                Message(
                    key=Keys.request_message(key),
                    role=MessageRole.REQUEST,
                    required=True,
                    payload=TypeRef(name=request, nullable=False),
                )
            )
        if command.response:
            messages.append(
                Message(
                    key=f"{key}#response",
                    role=MessageRole.RESPONSE,
                    name=command.response,
                    payload=TypeRef(name=responses[command.response], nullable=False),
                )
            )
        extras: Dict[str, Any] = {
            "matter_command": {
                "code": f"0x{command.code:02X}",
                "optional": command.optional,
                **({"response": command.response} if command.response else {"response": "default"}),
                **({"privileges": _privileges(command.access)} if _privileges(command.access) else {}),
            }
        }
        return Operation(
            key=key,
            name=name,
            kind=OperationKind.REQUEST_RESPONSE,
            description=command.description,
            messages=messages,
            extras=extras,
        )

    def _event_operation(self, event: MatterEvent, cluster: MatterCluster, service_key: str, taken: set) -> Operation:
        """An event as a subscribe operation of the cluster's service, carrying the event's fields."""
        name = identifier(event.name, fallback=f"Event{event.code:02X}")
        operation_name = name if name not in taken else f"{name}Event"
        key = Keys.operation_rpc(service_key, operation_name)
        cluster_key = self.cluster_keys[cluster.code]
        payload_key = Keys.type(f"{name}Event", cluster_key)
        self.types[payload_key] = Type(
            key=payload_key,
            name=f"{name}Event",
            kind=TypeKind.RECORD,
            namespace=cluster_key,
            description=event.description,
            fields=self.fields(event.fields, payload_key, cluster),
            extras={"matter_event": {"code": f"0x{event.code:02X}", "priority": event.priority}},
        )
        record: Dict[str, Any] = {"code": f"0x{event.code:02X}", "priority": event.priority, "optional": event.optional}
        if _privileges(event.access):
            record["privileges"] = _privileges(event.access)
        return Operation(
            key=key,
            name=operation_name,
            kind=OperationKind.SUBSCRIBE,
            description=event.description,
            messages=[
                Message(
                    key=Keys.event_message(key, f"{name}Event"),
                    role=MessageRole.EVENT,
                    name=event.name,
                    payload=TypeRef(name=payload_key, nullable=False),
                )
            ],
            extras={"matter_event": record},
        )

    def device_type(self, device_type: MatterDeviceType) -> None:
        """Define a device type as the record of the clusters it includes."""
        key = identifier(device_type.type_name or device_type.name, fallback="DeviceType")
        key = key if key not in self.types else f"{key}Device"
        fields: List[CanonicalField] = []
        for include in device_type.includes:
            cluster = self.document.cluster_named(include.cluster)
            name = identifier(include.cluster, fallback="Cluster")
            field_key = Keys.field(key, name)
            if cluster is not None:
                type_ref = TypeRef(name=self.cluster_keys[cluster.code], nullable=False)
            else:
                self.limits.record("matter.external_cluster", location=field_key)
                type_ref = TypeRef(name="any", nullable=False, extras={"matter_unresolved": include.cluster})
            fields.append(
                CanonicalField(
                    key=field_key,
                    name=name,
                    type=type_ref,
                    field_number=cluster.code if cluster else None,
                    extras={
                        "matter_include": {
                            "cluster": include.cluster,
                            "client": include.client,
                            "server": include.server,
                            "required_attributes": list(include.required_attributes),
                            "required_commands": list(include.required_commands),
                        }
                    },
                )
            )
        record: Dict[str, Any] = {"name": device_type.name}
        for attr in ("type_name", "device_id", "profile_id", "domain", "device_class", "scope"):
            value = getattr(device_type, attr)
            if value:
                record[attr] = value
        if device_type.path:
            record["file"] = device_type.path
        self.types[key] = Type(
            key=key,
            name=key,
            kind=TypeKind.RECORD,
            description=f"The {device_type.type_name or device_type.name} device type: the clusters it is composed of.",
            fields=fields,
            extras={"matter_device_type": record},
        )


def _identity(document: MatterDocument) -> Tuple[str, Optional[str]]:
    """The API's name and description."""
    if document.device_types:
        device = document.device_types[0]
        name = device.type_name or device.name
        return name, f"The {name} device type and the clusters it is composed of."
    if len(document.clusters) == 1:
        return document.clusters[0].name, document.clusters[0].description
    return "Matter clusters", "Matter clusters " + ", ".join(cluster.name for cluster in document.clusters) + "."


class MatterNormalizer(Normalizer, register=True):
    """Normalize parsed Matter definitions into an rpc-paradigm :class:`CanonicalApi`."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.RPC

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map a :class:`~app.matter_parser.MatterDocument` to the canonical model.

        Args:
            source: The parsed document.
            include_raw: Whether to keep every file's text on ``raw``.

        Returns:
            The canonical model.

        Raises:
            ValueError: When ``source`` is not a parsed Matter document.
        """
        if not isinstance(source, MatterDocument):
            raise ValueError("Matter source must be a MatterDocument (see app.matter_parser)")
        builder = _Builder(source)
        for data_type in source.data_types:
            builder.data_type(data_type)
        services = [service for service in (builder.cluster(cluster) for cluster in source.clusters) if service]
        for device_type in source.device_types:
            builder.device_type(device_type)
        name, description = _identity(source)
        record = {
            "input": "fileset" if source.is_fileset else "file",
            "clusters": [
                {"name": c.name, "code": c.code_text, **({"file": c.path} if c.path else {})} for c in source.clusters
            ],
            "device_types": [
                {
                    "name": d.name,
                    **({"device_id": d.device_id} if d.device_id else {}),
                    **({"file": d.path} if d.path else {}),
                }
                for d in source.device_types
            ],
            "capability_limits": _limits_payload(builder.limits.limits()),
        }
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol=MATTER_PROTOCOL,
            identity=ApiIdentity(name=name),
            title=name,
            description=description,
            services=services,
            types=list(builder.types.values()),
            raw=raw_record(source) if include_raw else None,
            extras={MATTER_EXTRAS_KEY: record},
        )
        return normalize_ordering(api)
