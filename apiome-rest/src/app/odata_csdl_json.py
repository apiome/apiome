"""Canonical CSDL JSON for OData v4 — MFI-11.1 (#3776).

OData v4 metadata has two standard serializations, CSDL XML (``$metadata``, ``.edmx``) and
**CSDL JSON** (OASIS *OData CSDL JSON Representation 4.01*). This module bridges them:

* :func:`csdl_xml_to_json` turns v4 CSDL XML into the canonical CSDL JSON representation,
  following the OASIS mapping (every schema element becomes a member object with ``$Kind``;
  defaults are written the JSON way, e.g. an XML property with no ``Nullable`` is
  ``"$Nullable": true`` because JSON's default is ``false``). The canonical form is what a v4
  document is validated with (:mod:`app.odata_csdl_schema`) and is kept on the catalog item.
* :func:`parse_csdl_json` reads an uploaded CSDL JSON document into the same
  :class:`~app.odata_parser.ODataDocument` the XML reader produces, so the normalizer, emitter,
  diff and lint treat both inputs alike.

v2/v3 metadata (the ``Association`` model) has no CSDL JSON representation, so it is not
converted or validated.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import replace
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .odata_csdl_schema import validate_csdl_json
from .odata_csdl_versions import ODATA_V4_EDM_NS, ODATA_V4_EDMX_NS, resolve_dialect
from .odata_parser import (
    ODataComplexType,
    ODataDocument,
    ODataEntityContainer,
    ODataEntitySet,
    ODataEntityType,
    ODataEnumMember,
    ODataEnumType,
    ODataNavigationProperty,
    ODataParseError,
    ODataProperty,
    ODataSchema,
)
from .secure_xml import parse_xml

__all__ = [
    "csdl_xml_to_json",
    "is_csdl_json",
    "is_csdl_json_document",
    "parse_csdl_json",
    "with_csdl_validation",
]

_EDM_STRING = "Edm.String"
_INT_TYPES = frozenset({"Edm.Byte", "Edm.SByte", "Edm.Int16", "Edm.Int32", "Edm.Int64"})
_FLOAT_TYPES = frozenset({"Edm.Single", "Edm.Double", "Edm.Decimal"})

#: Constant-expression attributes and how their value is written in JSON.
_CONSTANT_KINDS = (
    "String", "Bool", "Int", "Float", "Decimal", "Date", "DateTimeOffset", "Duration", "Guid",
    "TimeOfDay", "Binary", "EnumMember", "Path", "PropertyPath", "NavigationPropertyPath",
    "AnnotationPath", "ModelElementPath", "UrlRef",
)

#: Dynamic expressions with two operands (``{"$And": [a, b]}``).
_BINARY_EXPRESSIONS = frozenset(
    {"And", "Or", "Eq", "Ne", "Gt", "Ge", "Lt", "Le", "Has", "In", "Add", "Sub", "Mul", "Div", "DivBy", "Mod"}
)


# ===========================================================================
# Small helpers
# ===========================================================================


def _local(tag: str) -> str:
    """An ElementTree tag without its namespace."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _children(element: ET.Element, *names: str) -> List[ET.Element]:
    """The children of ``element`` with one of the given local names."""
    return [child for child in element if _local(child.tag) in names]


def _bool(value: Optional[str]) -> Optional[bool]:
    """``"true"``/``"false"`` as a bool; anything else as ``None``."""
    if value is None:
        return None
    lowered = value.strip().lower()
    return True if lowered == "true" else False if lowered == "false" else None


def _number(value: str) -> Any:
    """A numeric literal as ``int`` / ``float``, or the string when it is neither (``INF``)."""
    try:
        return int(value)
    except ValueError:
        pass
    try:
        number = float(value)
    except ValueError:
        return value
    return value if number in (float("inf"), float("-inf")) or number != number else number


def _type_parts(type_expr: Optional[str]) -> Tuple[str, bool]:
    """``Collection(T)`` → ``(T, True)``; ``T`` → ``(T, False)``; ``None`` → ``(Edm.String, False)``."""
    if not type_expr:
        return _EDM_STRING, False
    if type_expr.startswith("Collection(") and type_expr.endswith(")"):
        return type_expr[len("Collection("):-1], True
    return type_expr, False


def _typed_default(value: str, type_name: str) -> Any:
    """A ``DefaultValue`` in its JSON form for the given type."""
    if type_name == "Edm.Boolean":
        return _bool(value) if _bool(value) is not None else value
    if type_name in _INT_TYPES - {"Edm.Int64"} or type_name in ("Edm.Single", "Edm.Double"):
        return _number(value)
    return value


# ===========================================================================
# Annotation expressions (XML → JSON)
# ===========================================================================


def _enum_member_value(text: str) -> str:
    """``Ns.Color/Red Ns.Color/Blue`` → ``Red,Blue`` (the JSON spelling)."""
    return ",".join(part.rsplit("/", 1)[-1] for part in text.split() if part)


def _constant(kind: str, value: str) -> Any:
    """A constant or path expression given as an attribute, in its JSON form."""
    if kind == "Bool":
        flag = _bool(value)
        return value if flag is None else flag
    if kind in ("Int", "Float", "Decimal"):
        return _number(value)
    if kind == "EnumMember":
        return _enum_member_value(value)
    if kind == "Path":
        return {"$Path": value}
    if kind == "UrlRef":
        return {"$UrlRef": value}
    return value


def _expression(element: ET.Element) -> Any:
    """A dynamic expression element (``<Collection>``, ``<Record>``, ``<Apply>``…) in JSON."""
    kind = _local(element.tag)
    text = (element.text or "").strip()
    if kind in _CONSTANT_KINDS:
        return _constant(kind, text)
    if kind == "Null":
        return None
    if kind == "Collection":
        return [_expression(child) for child in element if _local(child.tag) != "Annotation"]
    if kind == "Record":
        record: Dict[str, Any] = {}
        if element.get("Type"):
            record["@type"] = element.get("Type")
        for value in _children(element, "PropertyValue"):
            name = value.get("Property")
            if name:
                record[name] = _annotation_value(value)
        _add_annotations(record, element)
        return record
    operands = [_expression(child) for child in element if _local(child.tag) != "Annotation"]
    if kind in _BINARY_EXPRESSIONS:
        return {f"${kind}": operands}
    if kind in ("Not", "Neg", "UrlRef"):
        return {f"${kind}": operands[0] if operands else None}
    if kind == "If":
        return {"$If": operands}
    if kind == "Apply":
        return {"$Apply": operands, "$Function": element.get("Function")}
    if kind in ("Cast", "IsOf"):
        converted: Dict[str, Any] = {f"${kind}": operands[0] if operands else None}
        type_name, collection = _type_parts(element.get("Type"))
        converted["$Type"] = type_name
        if collection:
            converted["$Collection"] = True
        return converted
    if kind == "LabeledElement":
        return {"$LabeledElement": operands[0] if operands else None, "$Name": element.get("Name")}
    if kind == "LabeledElementReference":
        return {"$LabeledElementReference": text}
    return text or None


def _annotation_value(element: ET.Element) -> Any:
    """The value of an ``<Annotation>`` or ``<PropertyValue>``: attribute, child, or ``true``."""
    for kind in _CONSTANT_KINDS:
        if element.get(kind) is not None:
            return _constant(kind, element.get(kind) or "")
    for child in element:
        if _local(child.tag) != "Annotation":
            return _expression(child)
    # An annotation with no value applies the term's default, which for the (boolean) tag
    # terms it is used with is ``true``; CSDL JSON always writes the value explicitly.
    return True


def _add_annotations(target: Dict[str, Any], element: ET.Element, prefix: str = "") -> None:
    """Add ``element``'s ``<Annotation>`` children to ``target`` as ``prefix@Term#Qualifier``."""
    for annotation in _children(element, "Annotation"):
        term = annotation.get("Term")
        if not term:
            continue
        qualifier = annotation.get("Qualifier")
        key = f"{prefix}@{term}" + (f"#{qualifier}" if qualifier else "")
        target[key] = _annotation_value(annotation)


# ===========================================================================
# Model elements (XML → JSON)
# ===========================================================================


def _typed(element: ET.Element, *, nullable_default: bool = True, allow_nullable: bool = True) -> Dict[str, Any]:
    """``$Type``/``$Collection``/``$Nullable`` and facets of a type-bearing element."""
    member: Dict[str, Any] = {}
    type_name, collection = _type_parts(element.get("Type"))
    if collection:
        member["$Collection"] = True
    if type_name != _EDM_STRING:
        member["$Type"] = type_name
    nullable = _bool(element.get("Nullable"))
    # XML's default is nullable, JSON's is not, so an XML default becomes an explicit `true`.
    # For a collection the facet is about its items and must not be written for a collection
    # of entities, so it is carried over only when the XML says so explicitly.
    implied = nullable_default and not collection
    if allow_nullable and (nullable if nullable is not None else implied):
        member["$Nullable"] = True
    max_length = element.get("MaxLength")
    if max_length and max_length.lower() != "max":
        member["$MaxLength"] = _number(max_length)
    if element.get("Precision"):
        member["$Precision"] = _number(element.get("Precision") or "")
    scale = element.get("Scale")
    if scale and scale.lower() != "variable":  # `variable` is JSON's default
        member["$Scale"] = "floating" if scale.lower() == "floating" else _number(scale)
    if element.get("SRID"):
        member["$SRID"] = element.get("SRID")
    if _bool(element.get("Unicode")) is False:
        member["$Unicode"] = False
    if element.get("DefaultValue") is not None:
        member["$DefaultValue"] = _typed_default(element.get("DefaultValue") or "", type_name)
    return member


def _structured(element: ET.Element, kind: str) -> Dict[str, Any]:
    """An ``EntityType`` / ``ComplexType`` as a CSDL JSON member."""
    member: Dict[str, Any] = {"$Kind": kind}
    if element.get("BaseType"):
        member["$BaseType"] = element.get("BaseType")
    for attribute in ("Abstract", "OpenType", "HasStream"):
        if _bool(element.get(attribute)):
            member[f"${attribute}"] = True
    for key in _children(element, "Key"):
        member["$Key"] = [
            {ref.get("Alias"): ref.get("Name")} if ref.get("Alias") else ref.get("Name")
            for ref in _children(key, "PropertyRef")
            if ref.get("Name")
        ]
    for prop in _children(element, "Property"):
        if prop.get("Name"):
            value = _typed(prop)
            _add_annotations(value, prop)
            member[prop.get("Name")] = value
    for nav in _children(element, "NavigationProperty"):
        if not nav.get("Name"):
            continue
        type_name, collection = _type_parts(nav.get("Type"))
        value: Dict[str, Any] = {"$Kind": "NavigationProperty"}
        if collection:
            value["$Collection"] = True
        value["$Type"] = type_name
        if not collection and _bool(nav.get("Nullable")) is not False:
            value["$Nullable"] = True
        if nav.get("Partner"):
            value["$Partner"] = nav.get("Partner")
        if _bool(nav.get("ContainsTarget")):
            value["$ContainsTarget"] = True
        constraints = {
            rc.get("Property"): rc.get("ReferencedProperty")
            for rc in _children(nav, "ReferentialConstraint")
            if rc.get("Property")
        }
        if constraints:
            value["$ReferentialConstraint"] = constraints
        for on_delete in _children(nav, "OnDelete"):
            value["$OnDelete"] = on_delete.get("Action")
        _add_annotations(value, nav)
        member[nav.get("Name")] = value
    _add_annotations(member, element)
    return member


def _enum(element: ET.Element) -> Dict[str, Any]:
    """An ``EnumType`` as a CSDL JSON member (implicit values made explicit)."""
    member: Dict[str, Any] = {"$Kind": "EnumType"}
    if element.get("UnderlyingType") and element.get("UnderlyingType") != "Edm.Int32":
        member["$UnderlyingType"] = element.get("UnderlyingType")
    if _bool(element.get("IsFlags")):
        member["$IsFlags"] = True
    for index, enum_member in enumerate(_children(element, "Member")):
        name = enum_member.get("Name")
        if not name:
            continue
        value = _number(enum_member.get("Value") or str(index))
        member[name] = value
        _add_annotations(member, enum_member, prefix=name)
    _add_annotations(member, element)
    return member


def _operation(element: ET.Element, kind: str) -> Dict[str, Any]:
    """One ``Action`` / ``Function`` overload."""
    overload: Dict[str, Any] = {"$Kind": kind}
    if _bool(element.get("IsBound")):
        overload["$IsBound"] = True
    if element.get("EntitySetPath"):
        overload["$EntitySetPath"] = element.get("EntitySetPath")
    if kind == "Function" and _bool(element.get("IsComposable")):
        overload["$IsComposable"] = True
    parameters = []
    for parameter in _children(element, "Parameter"):
        value = {"$Name": parameter.get("Name"), **_typed(parameter)}
        _add_annotations(value, parameter)
        parameters.append(value)
    if parameters:
        overload["$Parameter"] = parameters
    for return_type in _children(element, "ReturnType"):
        value = _typed(return_type)
        _add_annotations(value, return_type)
        overload["$ReturnType"] = value
    _add_annotations(overload, element)
    return overload


def _container(element: ET.Element) -> Dict[str, Any]:
    """An ``EntityContainer`` and its sets, singletons and imports."""
    member: Dict[str, Any] = {"$Kind": "EntityContainer"}
    if element.get("Extends"):
        member["$Extends"] = element.get("Extends")
    for child in element:
        kind, name = _local(child.tag), child.get("Name")
        if not name:
            continue
        value: Dict[str, Any] = {}
        if kind == "EntitySet":
            value = {"$Collection": True, "$Type": child.get("EntityType")}
            if _bool(child.get("IncludeInServiceDocument")) is False:
                value["$IncludeInServiceDocument"] = False
        elif kind == "Singleton":
            value = {"$Type": child.get("Type")}
            if _bool(child.get("Nullable")):
                value["$Nullable"] = True
        elif kind == "ActionImport":
            value = {"$Action": child.get("Action")}
            if child.get("EntitySet"):
                value["$EntitySet"] = child.get("EntitySet")
        elif kind == "FunctionImport":
            value = {"$Function": child.get("Function")}
            if child.get("EntitySet"):
                value["$EntitySet"] = child.get("EntitySet")
            if _bool(child.get("IncludeInServiceDocument")):
                value["$IncludeInServiceDocument"] = True
        else:
            continue
        bindings = {
            binding.get("Path"): binding.get("Target")
            for binding in _children(child, "NavigationPropertyBinding")
            if binding.get("Path")
        }
        if bindings:
            value["$NavigationPropertyBinding"] = bindings
        _add_annotations(value, child)
        member[name] = value
    _add_annotations(member, element)
    return member


def _schema(element: ET.Element) -> Tuple[Dict[str, Any], Optional[str]]:
    """A ``Schema`` as a namespace object, and the qualified name of its container (if any)."""
    schema: Dict[str, Any] = {}
    namespace = element.get("Namespace", "")
    if element.get("Alias"):
        schema["$Alias"] = element.get("Alias")
    container_name: Optional[str] = None
    for child in element:
        kind, name = _local(child.tag), child.get("Name")
        if kind in ("EntityType", "ComplexType") and name:
            schema[name] = _structured(child, kind)
        elif kind == "EnumType" and name:
            schema[name] = _enum(child)
        elif kind == "TypeDefinition" and name:
            definition = {"$Kind": "TypeDefinition", **_typed(child, allow_nullable=False)}
            definition["$UnderlyingType"] = child.get("UnderlyingType")
            _add_annotations(definition, child)
            schema[name] = definition
        elif kind == "Term" and name:
            term = {"$Kind": "Term", **_typed(child)}
            if child.get("BaseTerm"):
                term["$BaseTerm"] = child.get("BaseTerm")
            if child.get("AppliesTo"):
                term["$AppliesTo"] = child.get("AppliesTo", "").split()
            _add_annotations(term, child)
            schema[name] = term
        elif kind in ("Action", "Function") and name:
            schema.setdefault(name, []).append(_operation(child, kind))
        elif kind == "EntityContainer" and name:
            schema[name] = _container(child)
            container_name = f"{namespace}.{name}"
        elif kind == "Annotations" and child.get("Target"):
            block = schema.setdefault("$Annotations", {}).setdefault(child.get("Target"), {})
            _add_annotations(block, child)
    _add_annotations(schema, element)
    return schema, container_name


def csdl_xml_to_json(xml_text: str, *, source_label: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Convert v4 CSDL XML into the canonical CSDL JSON representation.

    Args:
        xml_text: The ``<edmx:Edmx>`` document.
        source_label: Label for parse errors.

    Returns:
        The CSDL JSON document, or ``None`` when the document is not OData v4 (v2/v3 has no
        CSDL JSON representation).
    """
    root = parse_xml(xml_text, source_label=source_label)
    edmx_ns = root.tag[1:].partition("}")[0] if root.tag.startswith("{") else None
    if _local(root.tag) != "Edmx" or edmx_ns != ODATA_V4_EDMX_NS:
        return None
    document: Dict[str, Any] = {"$Version": root.get("Version") or "4.0"}
    references: Dict[str, Any] = {}
    for reference in _children(root, "Reference"):
        uri = reference.get("Uri")
        if not uri:
            continue
        entry: Dict[str, Any] = {}
        includes = []
        for inc in _children(reference, "Include"):
            if not inc.get("Namespace"):
                continue
            item: Dict[str, Any] = {"$Namespace": inc.get("Namespace")}
            if inc.get("Alias"):
                item["$Alias"] = inc.get("Alias")
            _add_annotations(item, inc)
            includes.append(item)
        if includes:
            entry["$Include"] = includes
        annotations = [
            {
                key: value
                for key, value in (
                    ("$TermNamespace", inc.get("TermNamespace")),
                    ("$Qualifier", inc.get("Qualifier")),
                    ("$TargetNamespace", inc.get("TargetNamespace")),
                )
                if value
            }
            for inc in _children(reference, "IncludeAnnotations")
            if inc.get("TermNamespace")
        ]
        if annotations:
            entry["$IncludeAnnotations"] = annotations
        _add_annotations(entry, reference)
        references[uri] = entry
    if references:
        document["$Reference"] = references
    schemas: Dict[str, Any] = {}
    for data_services in _children(root, "DataServices"):
        for element in _children(data_services, "Schema"):
            if element.tag != f"{{{ODATA_V4_EDM_NS}}}Schema" or not element.get("Namespace"):
                continue
            schema, container = _schema(element)
            if container and "$EntityContainer" not in document:
                document["$EntityContainer"] = container
            schemas[element.get("Namespace")] = schema
    document.update(schemas)
    return document


# ===========================================================================
# CSDL JSON → ODataDocument
# ===========================================================================


def is_csdl_json_document(value: Any) -> bool:
    """Whether a parsed JSON value is a CSDL JSON document (``$Version`` 4.x)."""
    return (
        isinstance(value, Mapping)
        and isinstance(value.get("$Version"), str)
        and value["$Version"].startswith("4")
        and any(isinstance(v, Mapping) for k, v in value.items() if not str(k).startswith("$"))
    )


def is_csdl_json(text: str) -> bool:
    """Whether ``text`` is a CSDL JSON document."""
    if not isinstance(text, str) or not text.lstrip().startswith("{") or '"$Version"' not in text:
        return False
    try:
        return is_csdl_json_document(json.loads(text))
    except ValueError:
        return False


def _is_member(name: str) -> bool:
    """Whether a JSON key names a model element (not ``$Kind`` or an ``@`` annotation)."""
    return not name.startswith("$") and "@" not in name


def _type_expr(member: Mapping[str, Any]) -> str:
    """``$Type``/``$Collection`` as the XML reader's type expression (``Collection(T)``)."""
    type_name = member.get("$Type") or _EDM_STRING
    return f"Collection({type_name})" if member.get("$Collection") is True else type_name


def _properties(type_member: Mapping[str, Any]) -> Tuple[ODataProperty, ...]:
    """The structural properties of an entity or complex type."""
    return tuple(
        ODataProperty(name=name, type_expr=_type_expr(value), nullable=value.get("$Nullable") is True)
        for name, value in type_member.items()
        if _is_member(name) and isinstance(value, Mapping) and value.get("$Kind", "Property") == "Property"
    )


def _navigation(type_member: Mapping[str, Any]) -> Tuple[ODataNavigationProperty, ...]:
    """The navigation properties of an entity type."""
    return tuple(
        ODataNavigationProperty(name=name, type_expr=_type_expr(value), partner=value.get("$Partner"))
        for name, value in type_member.items()
        if _is_member(name) and isinstance(value, Mapping) and value.get("$Kind") == "NavigationProperty"
    )


def _key(type_member: Mapping[str, Any]) -> Tuple[str, ...]:
    """``$Key`` as property paths (an aliased key item contributes its path)."""
    names: List[str] = []
    for item in type_member.get("$Key") or []:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, Mapping):
            names.extend(str(path) for path in item.values())
    return tuple(names)


def _json_schema(namespace: str, body: Mapping[str, Any]) -> ODataSchema:
    """One namespace object as an :class:`ODataSchema`."""
    entity_types: List[ODataEntityType] = []
    complex_types: List[ODataComplexType] = []
    enum_types: List[ODataEnumType] = []
    container: Optional[ODataEntityContainer] = None
    for name, member in body.items():
        if not _is_member(name) or not isinstance(member, Mapping):
            continue
        kind = member.get("$Kind")
        if kind == "EntityType":
            entity_types.append(
                ODataEntityType(
                    name=name,
                    namespace=namespace,
                    key_properties=_key(member),
                    properties=_properties(member),
                    navigation_properties=_navigation(member),
                )
            )
        elif kind == "ComplexType":
            complex_types.append(ODataComplexType(name=name, namespace=namespace, properties=_properties(member)))
        elif kind == "EnumType":
            enum_types.append(
                ODataEnumType(
                    name=name,
                    namespace=namespace,
                    members=tuple(
                        ODataEnumMember(name=k, value=v if isinstance(v, int) and not isinstance(v, bool) else None)
                        for k, v in member.items()
                        if _is_member(k)
                    ),
                )
            )
        elif kind == "EntityContainer" and container is None:
            container = ODataEntityContainer(
                name=name,
                entity_sets=tuple(
                    ODataEntitySet(name=set_name, entity_type=str(value.get("$Type")))
                    for set_name, value in member.items()
                    if _is_member(set_name)
                    and isinstance(value, Mapping)
                    and value.get("$Collection") is True
                    and value.get("$Type")
                ),
            )
    return ODataSchema(
        namespace=namespace,
        entity_types=tuple(entity_types),
        complex_types=tuple(complex_types),
        enum_types=tuple(enum_types),
        entity_container=container,
    )


def parse_csdl_json(text: str, *, source_label: Optional[str] = None) -> ODataDocument:
    """Read a CSDL JSON document into an :class:`~app.odata_parser.ODataDocument`.

    Args:
        text: The CSDL JSON text.
        source_label: Label used in error messages.

    Returns:
        The document, with the same shape the CSDL XML reader produces for a v4 service.

    Raises:
        ODataParseError: When the text is not CSDL JSON, has no schema, or declares no
            entity container (``INPUT_SEMANTIC_INVALID``).
    """
    label = f" ({source_label})" if source_label else ""
    try:
        document = json.loads(text)
    except ValueError as exc:
        raise ODataParseError(f"Malformed CSDL JSON{label}: {exc}") from exc
    if not is_csdl_json_document(document):
        raise ODataParseError(f"Not a CSDL JSON document{label}: expected `$Version` 4.x and a schema")
    schemas = [
        _json_schema(namespace, body)
        for namespace, body in document.items()
        if not namespace.startswith("$") and isinstance(body, Mapping)
    ]
    if not any(schema.entity_container is not None for schema in schemas):
        raise ODataParseError(
            f"OData document declares no EntityContainer{label}, so it describes no addressable service surface",
            code="INPUT_SEMANTIC_INVALID",
        )
    dialect = resolve_dialect(
        edmx_namespace=ODATA_V4_EDMX_NS,
        edmx_version=document["$Version"],
        edm_namespaces=(ODATA_V4_EDM_NS,),
        data_service_version=None,
    )
    return ODataDocument(version=dialect.version, schemas=tuple(schemas), raw=text, dialect=dialect)


def with_csdl_validation(document: ODataDocument, *, source_label: Optional[str] = None) -> ODataDocument:
    """Attach a document's canonical CSDL JSON and its OASIS schema violations.

    A CSDL JSON upload is validated as written; a v4 CSDL XML document is converted first
    (:func:`csdl_xml_to_json`). v2/v3 documents are returned unchanged. Violations never refuse
    the import: they are recorded for the catalog item and the ``odata.csdl-schema`` lint rule.

    Args:
        document: A parsed document (``raw`` holds its source text).
        source_label: Label for parse errors.

    Returns:
        The document with ``csdl_json``, ``csdl_violations`` and ``csdl_violation_count`` set.
    """
    if is_csdl_json(document.raw):
        csdl = json.loads(document.raw)
    else:
        csdl = csdl_xml_to_json(document.raw, source_label=source_label)
    if csdl is None:
        return document
    violations, total = validate_csdl_json(csdl)
    return replace(
        document,
        csdl_json=csdl,
        csdl_violations=tuple(v.as_dict() for v in violations),
        csdl_violation_count=total,
    )
