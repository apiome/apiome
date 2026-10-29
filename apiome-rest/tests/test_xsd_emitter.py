"""Standalone XSD emitter — MFX-22.1 (#4132).

Covers, in order:

* types → XSD through the shared writer (:mod:`app.xsd_schema`): records, lists, nullability, unions
  (``xs:choice``), enums, facets (not comments), defaults — validated by ``xmlschema``;
* the target namespace (the source's, an XSD source's own, or none) and XSD 1.0 / 1.1;
* multi-namespace sources: one document per namespace, joined by ``xs:import``;
* an XSD source written back with its own elements, attributes and enum bases (round trip);
* the shared mapping: the WSDL export writes the same types as the XSD export;
* the drop of operations and the fidelity report.
"""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List

import pytest
import xmlschema

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    EnumValue,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import LossKind
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import canonical_diff, get_import_source
from app.lossiness import LossinessKind
from app.roundtrip_matrix import import_source_text, reimport_emitted
from app.wsdl_emitter import WsdlEmitter
from app.xsd_emitter import XsdEmitOptions, XsdEmitter, xsd_namespaces

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_XSD = "{http://www.w3.org/2001/XMLSchema}"
_NS = "http://example.com/pets"


# ===========================================================================
# Helpers
# ===========================================================================


def _field(name: str, ref: TypeRef, *, owner: str = "Pet", **kw) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=ref, **kw)


def _api(types: List[Type], services: List[Service] = (), **identity) -> CanonicalApi:
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi",
        identity=ApiIdentity(name="Pets", **identity),
        types=list(types),
        services=list(services),
    )


def _record(key: str, *fields: CanonicalField, namespace: str = None) -> Type:
    return Type(key=key, name=key.split(".")[-1], kind=TypeKind.RECORD, fields=list(fields), namespace=namespace)


def _emit(api: CanonicalApi, **opts):
    return XsdEmitter().emit(api, opts=XsdEmitOptions(**opts))


def _schema(result, version: str = "1.0"):
    """Load the emitted documents with ``xmlschema`` (raises when a document is not valid XSD)."""
    cls = xmlschema.XMLSchema11 if version == "1.1" else xmlschema.XMLSchema10
    if len(result.files) == 1:
        return cls(result.files[0].content)
    return _load_with_imports(cls, {f.path: f.content for f in result.files}, result.files[0].path)


def _load_with_imports(cls, sources: Dict[str, str], main_path: str):
    """Load a multi-document export from a temporary directory, so ``schemaLocation`` resolves."""
    with tempfile.TemporaryDirectory() as tmp:
        for path, content in sources.items():
            Path(tmp, path).write_text(content)
        return cls(str(Path(tmp, main_path)))


def _pet_api(**identity) -> CanonicalApi:
    pet = _record(
        "Pet",
        _field("id", TypeRef(name="integer"), constraints=Constraints(format="int64"), field_number=1),
        _field(
            "name", TypeRef(name="string"),
            constraints=Constraints(min_length=1, max_length=40, pattern="^[A-Za-z ]+$"), field_number=2,
        ),
        _field("age", TypeRef(name="integer"), constraints=Constraints(minimum=0, maximum=40), field_number=3),
        _field("nickname", TypeRef(name="string", nullable=True), field_number=4),
        _field("tags", TypeRef(item=TypeRef(name="string")), field_number=5),
        _field("status", TypeRef(name="Status"), field_number=6),
        _field("owner", TypeRef(name="Contact"), field_number=7),
        _field("legs", TypeRef(name="integer"), default=4, field_number=8),
    )
    status = Type(
        key="Status", name="Status", kind=TypeKind.ENUM,
        enum_values=[EnumValue(key="Status.available", name="available"),
                     EnumValue(key="Status.sold", name="sold")],
    )
    contact = Type(
        key="Contact", name="Contact", kind=TypeKind.UNION,
        fields=[
            _field("email", TypeRef(name="string"), owner="Contact"),
            _field("phone", TypeRef(name="string"), owner="Contact"),
        ],
    )
    return _api([pet, status, contact], **identity)


def _by_name(root, tag: str, name: str):
    return next(el for el in root.iter(f"{_XSD}{tag}") if el.get("name") == name)


# ===========================================================================
# Types → XSD
# ===========================================================================


def test_emits_one_valid_document_with_the_source_namespace() -> None:
    result = _emit(_pet_api(namespace=_NS))
    assert [f.path for f in result.files] == ["Pets.xsd"]
    schema = _schema(result)
    assert schema.target_namespace == _NS
    assert {"Pet", "Status", "Contact"} <= {t.local_name for t in schema.types.values()}
    assert "Pet" in schema.elements


def test_constraints_land_as_facets_not_comments() -> None:
    result = _emit(_pet_api(namespace=_NS))
    content, root = result.files[0].content, _schema(result).root
    name = _by_name(root, "element", "name")
    restriction = name.find(f"{_XSD}simpleType/{_XSD}restriction")
    assert restriction.get("base") == "xsd:string"
    facets = {child.tag.split("}")[1]: child.get("value") for child in restriction}
    assert facets == {"minLength": "1", "maxLength": "40", "pattern": "[A-Za-z ]+"}
    age = _by_name(root, "element", "age").find(f"{_XSD}simpleType/{_XSD}restriction")
    assert {c.tag.split("}")[1]: c.get("value") for c in age} == {"minInclusive": "0", "maxInclusive": "40"}
    assert "<!-- Generated XSD 1.0" in content and content.count("<!--") == 1


def test_lists_nullability_unions_enums_and_defaults() -> None:
    root = _schema(_emit(_pet_api(namespace=_NS))).root
    assert _by_name(root, "element", "id").get("type") == "xsd:long"
    nickname = _by_name(root, "element", "nickname")
    assert (nickname.get("minOccurs"), nickname.get("nillable")) == ("0", "true")
    tags = _by_name(root, "element", "tags")
    assert (tags.get("minOccurs"), tags.get("maxOccurs")) == ("0", "unbounded")
    assert _by_name(root, "element", "legs").get("default") == "4"
    choice = _by_name(root, "complexType", "Contact").find(f"{_XSD}choice")
    assert [el.get("name") for el in choice] == ["email", "phone"]
    status = _by_name(root, "simpleType", "Status")
    assert [e.get("value") for e in status.iter(f"{_XSD}enumeration")] == ["available", "sold"]


def test_an_instance_document_validates_against_the_export() -> None:
    schema = _schema(_emit(_pet_api(namespace=_NS)))
    instance = (
        f'<Pet xmlns="{_NS}"><id>1</id><name>Rex</name><age>3</age><nickname xsi:nil="true" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/><tags>a</tags><status>sold</status>'
        "<owner><email>a@b.c</email></owner><legs>4</legs></Pet>"
    )
    assert schema.is_valid(instance)
    assert not schema.is_valid(instance.replace("<age>3</age>", "<age>99</age>"))
    assert not schema.is_valid(instance.replace("<name>Rex</name>", "<name>R2D2</name>"))


def test_a_source_without_a_namespace_writes_a_no_namespace_schema() -> None:
    result = _emit(_pet_api())
    schema = _schema(result)
    assert schema.target_namespace == ""
    root = schema.root
    assert root.get("targetNamespace") is None
    assert _by_name(root, "element", "status").get("type") == "Status"
    assert schema.is_valid("<Pet><id>1</id><name>Rex</name><age>3</age><status>sold</status>"
                           "<owner><phone>1</phone></owner><legs>4</legs></Pet>")


# ===========================================================================
# XSD 1.0 / 1.1
# ===========================================================================


def _multiple_of_api() -> CanonicalApi:
    return _api(
        [_record("Box", _field("size", TypeRef(name="integer"), owner="Box",
                                constraints=Constraints(multiple_of=5, minimum=0)))],
        namespace=_NS,
    )


def test_xsd_1_0_reports_multiple_of_as_unwritten() -> None:
    result = _emit(_multiple_of_api())
    assert "assertion" not in result.files[0].content and "minVersion" not in result.files[0].content
    assert any(loss.subject == "unsupported-facet" and "multipleOf" in loss.detail for loss in result.losses)
    _schema(result)


def test_xsd_1_1_writes_multiple_of_as_an_assertion() -> None:
    result = _emit(_multiple_of_api(), xsd_version="1.1")
    content = result.files[0].content
    assert 'vc:minVersion="1.1"' in content and "Generated XSD 1.1" in content
    assert '<xsd:assertion test="$value mod 5 = 0"' in content
    assert not any(loss.subject == "unsupported-facet" for loss in result.losses)
    schema = _schema(result, "1.1")
    assert schema.is_valid(f'<Box xmlns="{_NS}"><size>10</size></Box>')
    assert not schema.is_valid(f'<Box xmlns="{_NS}"><size>7</size></Box>')


def test_the_version_option_is_validated() -> None:
    with pytest.raises(ValueError):
        XsdEmitOptions(xsd_version="2.0")


# ===========================================================================
# Multi-namespace
# ===========================================================================


_COMMON = "http://example.com/common"


def _two_namespace_api() -> CanonicalApi:
    address = _record("Address", _field("city", TypeRef(name="string"), owner="Address"), namespace=_COMMON)
    order = _record(
        "Order",
        _field("id", TypeRef(name="string"), owner="Order"),
        _field("shipTo", TypeRef(name="Address"), owner="Order"),
        namespace=_NS,
    )
    return _api([order, address], namespace=_NS)


def test_namespaces_keep_uris_and_fold_package_names_into_the_main_one() -> None:
    api = _two_namespace_api()
    api.types.append(_record("Note", namespace="com.example.notes"))
    main, by_type = xsd_namespaces(api)
    assert main == _NS
    assert by_type == {"Order": _NS, "Address": _COMMON, "Note": _NS}


def test_a_multi_namespace_source_writes_one_document_per_namespace_with_imports() -> None:
    result = _emit(_two_namespace_api())
    assert [f.path for f in result.files] == ["Pets.xsd", "Pets-common.xsd"]
    main, common = (f.content for f in result.files)
    assert f'<xsd:import namespace="{_COMMON}" schemaLocation="Pets-common.xsd" />' in main
    assert f'xmlns:ns1="{_COMMON}"' in main and 'type="ns1:Address"' in main
    assert f'targetNamespace="{_COMMON}"' in common and "xsd:import" not in common
    schema = _schema(result)
    assert f"{{{_COMMON}}}Address" in schema.maps.types
    assert schema.is_valid(
        f'<Order xmlns="{_NS}" xmlns:c="{_COMMON}"><id>1</id><shipTo><c:city>Oslo</c:city></shipTo></Order>'
    )


def test_import_is_the_first_child_of_the_schema() -> None:
    main = _schema(_emit(_two_namespace_api())).root
    assert main[0].tag == f"{_XSD}import"


# ===========================================================================
# XSD source: written back as it was read
# ===========================================================================


def _purchase_order() -> CanonicalApi:
    text = (_EXAMPLES / "xsd" / "01-purchase-order.xsd").read_text()
    return import_source_text(get_import_source("xsd"), text, source_label="po")


def test_an_xsd_source_keeps_its_root_element_attributes_and_enum_values() -> None:
    result = _emit(_purchase_order())
    root = _schema(result).root
    assert root[0].get("name") == "purchaseOrder" and root[0].get("type") == "tns:PurchaseOrder"
    assert [el.get("name") for el in root.findall(f"{_XSD}element")] == ["purchaseOrder"]
    assert _by_name(root, "attribute", "orderDate").get("type") == "xsd:date"
    assert _by_name(root, "element", "items").get("type") == "tns:Item"
    assert _by_name(root, "element", "quantity").get("type") == "xsd:positiveInteger"
    status = _by_name(root, "simpleType", "Status")
    assert [e.get("value") for e in status.iter(f"{_XSD}enumeration")] == [
        "pending", "shipped", "delivered", "cancelled",
    ]


def test_an_xsd_source_round_trips_with_no_difference() -> None:
    source = _purchase_order()
    result = _emit(source)
    reimported = reimport_emitted(get_import_source("xsd"), result, multi_file=False)
    assert canonical_diff(source, reimported).is_empty


# ===========================================================================
# Shared mapping (MFX-14.1)
# ===========================================================================


def test_wsdl_and_xsd_write_the_same_types() -> None:
    api = _pet_api(namespace=_NS)
    xsd_root = _schema(_emit(api)).root
    wsdl = WsdlEmitter().emit(api)
    wsdl_types = next(f for f in wsdl.files if f.path.endswith(".xsd")).content
    wsdl_root = xmlschema.XMLSchema10(wsdl_types).root
    for name in ("Pet", "Contact"):
        assert _canonical_xml(_by_name(xsd_root, "complexType", name)) == _canonical_xml(
            _by_name(wsdl_root, "complexType", name)
        )
    assert _canonical_xml(_by_name(xsd_root, "simpleType", "Status")) == _canonical_xml(
        _by_name(wsdl_root, "simpleType", "Status")
    )


def _canonical_xml(element) -> str:
    """``element`` serialized without whitespace-only text, for comparing two documents."""
    copy = ET.fromstring(ET.tostring(element))
    for node in copy.iter():
        node.tail = node.text = (node.text or "").strip() or None
    return ET.tostring(copy, encoding="unicode")


# ===========================================================================
# Operations, losses and the fidelity report
# ===========================================================================


def _with_operation() -> CanonicalApi:
    api = _pet_api(namespace=_NS)
    api.services.append(
        Service(key="Pets", name="Pets", operations=[
            Operation(key="Pets.getPet", name="getPet", kind=OperationKind.REQUEST_RESPONSE, http_method="GET",
                      http_path="/pets/{id}"),
        ])
    )
    return api


def test_operations_are_dropped_and_reported() -> None:
    result = _emit(_with_operation())
    assert any(loss.kind is LossKind.NA and loss.subject == "services-dropped" for loss in result.losses)
    assert "getPet" not in result.files[0].content


def test_the_fidelity_report_drops_operations_and_carries_unions_and_facets() -> None:
    report = compute_lossiness_for_emitter(_with_operation(), XsdEmitter)
    by_key = {item.construct_key: item for item in report.items}
    assert by_key["Pets.getPet"].kind is LossinessKind.DROP
    # The union (an xs:choice) and the constrained field (facets) are carried: nothing is reported for them.
    for key in ("Contact", "Pet.name", "Pet.age"):
        assert key not in by_key or by_key[key].kind is LossinessKind.OK


def test_renamed_names_are_reported() -> None:
    api = _api([_record("my pet", _field("first name", TypeRef(name="string"), owner="my pet"))])
    result = _emit(api)
    assert {loss.subject for loss in result.losses} == {"renamed-identifier"}
    root = _schema(result).root
    assert _by_name(root, "complexType", "MyPet") is not None


def test_a_document_of_another_format_is_reported_at_the_root() -> None:
    report = compute_lossiness_for_emitter(_pet_api(namespace=_NS), XsdEmitter)
    root = [item for item in report.items if item.construct_key == ""]
    assert [item.kind for item in root] == [LossinessKind.APPROX]
    assert "XML Schema" in root[0].message
    xsd_report = compute_lossiness_for_emitter(_purchase_order(), XsdEmitter)
    assert not [item for item in xsd_report.items if item.construct_key == ""]


# ===========================================================================
# Enums and defaults
# ===========================================================================


def _enum(key: str, *members: EnumValue) -> Type:
    return Type(key=key, name=key, kind=TypeKind.ENUM, enum_values=list(members))


def test_enums_are_written_by_name_unless_they_are_numeric() -> None:
    tagged = _enum("Color", EnumValue(key="Color.RED", name="RED", value=1),
                   EnumValue(key="Color.BLUE", name="BLUE", value=2))
    numeric = _enum("Level", EnumValue(key="Level.1", name="1", value=1), EnumValue(key="Level.2", name="2", value=2))
    wire = _enum("Mode", EnumValue(key="Mode.IN_PROGRESS", name="IN_PROGRESS", value="in-progress"))
    root = _schema(_emit(_api([tagged, numeric, wire]))).root

    def restriction(name: str):
        r = _by_name(root, "simpleType", name).find(f"{_XSD}restriction")
        return r.get("base"), [e.get("value") for e in r]

    assert restriction("Color") == ("xsd:string", ["RED", "BLUE"])
    assert restriction("Level") == ("xsd:int", ["1", "2"])
    assert restriction("Mode") == ("xsd:string", ["in-progress"])


def test_an_enum_typed_field_keeps_its_default() -> None:
    status = _enum("Status", EnumValue(key="Status.ACTIVE", name="ACTIVE", value=0))
    pet = _record("Pet", _field("status", TypeRef(name="Status"), default="ACTIVE"))
    schema = _schema(_emit(_api([pet, status])))
    assert _by_name(schema.root, "element", "status").get("default") == "ACTIVE"
    assert schema.is_valid("<Pet><status/></Pet>")
