"""LwM2M / IPSO object definitions → canonical model normalizer — FMT-9.5 (#5472).

Maps a parsed :class:`~app.lwm2m_parser.Lwm2mDocument` onto the **data_schema** paradigm:

.. code-block:: text

    Object 3303 "Temperature"          → RECORD    Temperature
    Item 5700 "Sensor Value" (R)       → field     Temperature.SensorValue  (field_number 5700)
    Item 5605 "Reset Min and Max …" (E) → operation TemperatureService.ResetMinAndMaxMeasuredValues (one_way)

* **Resources** with ``R``, ``W`` or ``RW`` become fields; the access mode is declared metadata in
  ``extras['lwm2m_resource']['access']`` (``read``, ``write``, ``read-write``). **Executable** (``E``)
  resources are not data: each becomes a ``one_way`` operation of the object's service
  (``<Object>Service``, so a record and a service never share a name in an emitted IDL).
* ``Mandatory`` → a non-nullable reference (canonical ``nullable`` means "null or absent");
  ``MultipleInstances = Multiple`` → a list.
* ``Type`` → canonical scalar (:data:`RESOURCE_TYPE_TO_CANONICAL`). ``Time`` is Unix seconds
  (``format: unix-time``), ``Corelnk`` a CoRE link-format string (``format: core-link``), and
  ``Objlnk`` — the LwM2M reference type — the synthesized ``Objlnk`` record (object id + instance
  id). The definition never says which object an ``Objlnk`` points at, so the link target is a
  declared limit.
* ``RangeEnumeration`` → ``minimum`` / ``maximum`` for a numeric resource, ``min_length`` /
  ``max_length`` for a ``String`` or ``Opaque`` one, ``enum`` for a value list; on a multi-instance
  resource the same facets apply to each instance (``item_*`` keys in the constraints' extras).
  ``Units`` → ``constraints.extras['unit']``. A range that reads as neither is kept as text and
  declared.

Names become identifiers (``Sensor Value`` → ``SensorValue``); the written name, id and every
attribute of the definition stay in the extras. Declared limits are counted in
``extras['lwm2m']['capability_limits']``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from .device_model_xml import identifier
from .inference_provenance import SYNTHESIZED, provenance_extras
from .lwm2m_parser import FORMAT_KEY, Lwm2mDocument, Lwm2mObject, Lwm2mRange, Lwm2mResource, raw_record
from .normalizer import Keys, Normalizer, normalize_ordering
from .typescript_types_normalizer import _limits_payload
from .typescript_types_parser import LimitRecorder

__all__ = [
    "LIMIT_DETAILS",
    "LWM2M_EXTRAS_KEY",
    "OBJLNK_TYPE",
    "PARTIAL_LIMITS",
    "RESOURCE_TYPE_TO_CANONICAL",
    "Lwm2mNormalizer",
]

#: Root extras key of the projection record.
LWM2M_EXTRAS_KEY = "lwm2m"

#: The transport the canonical model names for LwM2M.
LWM2M_PROTOCOL = "lwm2m"

#: The synthesized record an ``Objlnk`` resource is typed as.
OBJLNK_TYPE = "Objlnk"

#: LwM2M resource type → canonical scalar name (``Objlnk`` is the synthesized record).
RESOURCE_TYPE_TO_CANONICAL: Dict[str, str] = {
    "String": "string",
    "Integer": "int64",
    "Unsigned Integer": "uint64",
    "Float": "double",
    "Boolean": "boolean",
    "Opaque": "bytes",
    "Time": "int64",
    "Corelnk": "string",
    "Objlnk": OBJLNK_TYPE,
}

#: Resource types whose ``RangeEnumeration`` bounds a length rather than a value.
_LENGTH_TYPES = frozenset({"String", "Opaque", "Corelnk"})

#: Semantic format hints for types the canonical scalar does not say enough about.
_TYPE_FORMATS: Dict[str, str] = {"Time": "unix-time", "Corelnk": "core-link"}

#: Operations → the declared access mode of a data resource.
_ACCESS: Dict[str, str] = {"R": "read", "W": "write", "RW": "read-write"}

#: The declared-limit vocabulary (stable keys → reviewed sentence).
LIMIT_DETAILS: Dict[str, str] = {
    "lwm2m.object_link_target": (
        "An Objlnk resource links to an instance of another object, but an object definition does "
        "not say which object. The field is typed as the generic Objlnk record (object id and "
        "instance id); the object it is meant to point at is only in its description."
    ),
    "lwm2m.unparsed_range": (
        "A RangeEnumeration reads as neither a numeric range (a..b) nor a list of values, so it "
        "sets no constraint; the text is kept in extras['lwm2m_resource']['range']."
    ),
}

#: Limits whose construct is still modelled, with only a detail lost — every LwM2M limit is.
PARTIAL_LIMITS = frozenset(LIMIT_DETAILS)

_OBJLNK_EVIDENCE = (
    "LwM2M writes an object link as ObjectID:ObjectInstanceID; the record that holds the two ids is named by Apiome."
)


def _unique(name: str, taken: Dict[str, Any], suffix: int) -> str:
    """``name`` when free, else ``name_<suffix>`` (two sources whose identifiers collide)."""
    return name if name not in taken else f"{name}_{suffix}"


class _Builder:
    """Accumulates types and limits while one document is normalized."""

    def __init__(self) -> None:
        self.types: Dict[str, Type] = {}
        self.limits = LimitRecorder(details=LIMIT_DETAILS)

    def objlnk(self) -> str:
        """Define the synthesized ``Objlnk`` record (once) and return its key."""
        if OBJLNK_TYPE not in self.types:
            self.types[OBJLNK_TYPE] = Type(
                key=OBJLNK_TYPE,
                name=OBJLNK_TYPE,
                kind=TypeKind.RECORD,
                description="A link to an LwM2M object instance (ObjectID:ObjectInstanceID).",
                fields=[
                    CanonicalField(
                        key=Keys.field(OBJLNK_TYPE, name),
                        name=name,
                        type=TypeRef(name="uint16", nullable=False),
                        field_number=number,
                        description=description,
                    )
                    for number, name, description in (
                        (0, "ObjectID", "The id of the linked object."),
                        (1, "ObjectInstanceID", "The id of the linked object instance."),
                    )
                ],
                extras=provenance_extras(SYNTHESIZED, _OBJLNK_EVIDENCE),
            )
        return OBJLNK_TYPE

    def constraints(self, resource: Lwm2mResource, location: str) -> Optional[Constraints]:
        """The canonical constraints of a resource's range, units and type format."""
        values: Dict[str, Any] = {}
        extras: Dict[str, Any] = {}
        assert resource.type is not None
        if resource.type in _TYPE_FORMATS:
            values["format"] = _TYPE_FORMATS[resource.type]
        if resource.units:
            extras["unit"] = resource.units
        facets = self._range_facets(resource.range, resource.type, location)
        if resource.multiple:
            extras.update({f"item_{name}": value for name, value in facets.items()})
        else:
            values.update(facets)
        if not values and not extras:
            return None
        return Constraints(**values, extras=extras)

    def _range_facets(self, written: Optional[Lwm2mRange], resource_type: str, location: str) -> Dict[str, Any]:
        """The constraint facets one ``RangeEnumeration`` sets."""
        if written is None:
            return {}
        if not written.is_parsed:
            self.limits.record("lwm2m.unparsed_range", location=location)
            return {}
        if written.values:
            return {"enum": list(written.values)}
        assert written.minimum is not None and written.maximum is not None
        if resource_type in _LENGTH_TYPES:
            return {"min_length": int(written.minimum), "max_length": int(written.maximum)}
        return {"minimum": written.minimum, "maximum": written.maximum}

    def field(self, resource: Lwm2mResource, type_key: str, name: str) -> CanonicalField:
        """One data resource as a field."""
        key = Keys.field(type_key, name)
        assert resource.type is not None
        canonical = RESOURCE_TYPE_TO_CANONICAL[resource.type]
        if resource.type == "Objlnk":
            canonical = self.objlnk()
            self.limits.record("lwm2m.object_link_target", location=key)
        element = TypeRef(name=canonical, nullable=False)
        type_ref = (
            TypeRef(item=element, nullable=not resource.mandatory)
            if resource.multiple
            else TypeRef(name=canonical, nullable=not resource.mandatory)
        )
        return CanonicalField(
            key=key,
            name=name,
            type=type_ref,
            field_number=resource.id,
            constraints=self.constraints(resource, key),
            description=resource.description,
            extras={"lwm2m_resource": _resource_record(resource)},
        )

    def object_record(self, obj: Lwm2mObject, key: str) -> Tuple[Type, List[Tuple[str, Lwm2mResource]]]:
        """The record of one object and its executable resources (with their identifiers)."""
        fields: List[CanonicalField] = []
        executables: List[Tuple[str, Lwm2mResource]] = []
        taken: Dict[str, Any] = {}
        for resource in obj.resources:
            name = _unique(identifier(resource.name, fallback=f"Resource{resource.id}"), taken, resource.id)
            taken[name] = resource
            if resource.is_executable:
                executables.append((name, resource))
            else:
                fields.append(self.field(resource, key, name))
        record = Type(
            key=key,
            name=key,
            kind=TypeKind.RECORD,
            description=obj.description,
            fields=fields,
            extras={"lwm2m_object": _object_record(obj)},
        )
        return record, executables


def _resource_record(resource: Lwm2mResource) -> Dict[str, Any]:
    """The written attributes of a resource, kept in its extras."""
    record: Dict[str, Any] = {
        "id": resource.id,
        "name": resource.name,
        "operations": resource.operations,
        "multiple_instances": resource.multiple,
        "mandatory": resource.mandatory,
    }
    if resource.operations in _ACCESS:
        record["access"] = _ACCESS[resource.operations]
    if resource.type:
        record["type"] = resource.type
    if resource.range is not None:
        record["range"] = resource.range.text
    if resource.units:
        record["units"] = resource.units
    return record


def _object_record(obj: Lwm2mObject) -> Dict[str, Any]:
    """The written attributes of an object, kept in its record's extras."""
    record: Dict[str, Any] = {
        "id": obj.object_id,
        "name": obj.name,
        "multiple_instances": obj.multiple,
        "mandatory": obj.mandatory,
    }
    for name, value in (
        ("urn", obj.urn),
        ("lwm2m_version", obj.lwm2m_version),
        ("object_version", obj.object_version),
        ("description2", obj.description2),
        ("file", obj.path),
    ):
        if value:
            record[name] = value
    return record


def _execute_operation(service_key: str, name: str, resource: Lwm2mResource, obj: Lwm2mObject) -> Operation:
    """One executable resource as a ``one_way`` operation."""
    return Operation(
        key=Keys.operation_rpc(service_key, name),
        name=name,
        kind=OperationKind.ONE_WAY,
        description=resource.description,
        extras={"lwm2m_resource": _resource_record(resource), "lwm2m_object": obj.object_id},
    )


def _identity(document: Lwm2mDocument) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    """The API's name, namespace (the object URN), version and description."""
    if len(document.objects) == 1:
        obj = document.objects[0]
        return obj.name, obj.urn, obj.object_version, obj.description
    root = document.objects[0]
    names = ", ".join(obj.name for obj in document.objects)
    if document.is_fileset:
        return root.name, root.urn, root.object_version, root.description
    return names, None, None, f"LwM2M objects {names}."


class Lwm2mNormalizer(Normalizer, register=True):
    """Normalize parsed LwM2M object definitions into a data_schema :class:`CanonicalApi`."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map an :class:`~app.lwm2m_parser.Lwm2mDocument` to the canonical model.

        Args:
            source: The parsed document.
            include_raw: Whether to keep every file's text on ``raw``.

        Returns:
            The canonical model.

        Raises:
            ValueError: When ``source`` is not a parsed LwM2M document.
        """
        if not isinstance(source, Lwm2mDocument):
            raise ValueError("LwM2M source must be an Lwm2mDocument (see app.lwm2m_parser)")
        builder = _Builder()
        services: List[Service] = []
        taken: Dict[str, Any] = {OBJLNK_TYPE: None}
        for obj in source.objects:
            key = _unique(identifier(obj.name, fallback=f"Object{obj.object_id}"), taken, obj.object_id)
            taken[key] = obj
            record, executables = builder.object_record(obj, key)
            builder.types[key] = record
            if executables:
                service_key = f"{key}Service"
                services.append(
                    Service(
                        key=service_key,
                        name=service_key,
                        description=f"The executable resources of the {obj.name} object ({obj.object_id}).",
                        operations=[
                            _execute_operation(service_key, name, resource, obj) for name, resource in executables
                        ],
                    )
                )
        name, namespace, version, description = _identity(source)
        record = {
            "input": "fileset" if source.is_fileset else "file",
            "objects": [
                {
                    "id": obj.object_id,
                    "name": obj.name,
                    **({"urn": obj.urn} if obj.urn else {}),
                    **({"lwm2m_version": obj.lwm2m_version} if obj.lwm2m_version else {}),
                    **({"file": obj.path} if obj.path else {}),
                }
                for obj in source.objects
            ],
            "capability_limits": _limits_payload(builder.limits.limits()),
        }
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol=LWM2M_PROTOCOL,
            identity=ApiIdentity(name=name, namespace=namespace),
            version=version,
            title=name,
            description=description,
            services=services,
            types=list(builder.types.values()),
            raw=raw_record(source) if include_raw else None,
            extras={LWM2M_EXTRAS_KEY: record},
        )
        return normalize_ordering(api)
