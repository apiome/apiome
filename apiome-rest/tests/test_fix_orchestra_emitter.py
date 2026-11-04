"""FIX Orchestra emitter — MFX-37.1 (#4323).

Pins :class:`app.fix_orchestra_emitter.FixOrchestraEmitter` against the issue's acceptance criterion:

* **emits Orchestra XML valid against the official XSD for a typed source** — every export, from an
  imported Orchestra repository and from REST, JSON Schema and GraphQL items, validates against the vendored
  FIX Orchestra 1.0 repository schema (:func:`orchestra_schema_problems`, loaded offline).

Plus the mapping (messages, components, groups, fields with tags, code sets; presence, rules, scenarios,
responses, actors and flows where the model carries them), the decisions the emitter makes up (tags, groups for
lists and maps, components for unions, a placeholder code set, the version), the re-import, and the fidelity
report.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    EnumValue,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitOptionsError, EmitPreconditionError, EmitResult, get_emitter, load_builtin_emitters
from app.fidelity_engine import compute_lossiness_for_emitter
from app.fix_orchestra_emitter import (
    FIRST_SYNTHESIZED_TAG,
    LOSS_LIST_AS_GROUP,
    LOSS_MAP_AS_GROUP,
    LOSS_PLACEHOLDER_CODESET,
    LOSS_RENAMED,
    LOSS_TAG_SYNTHESIZED,
    LOSS_UNION_AS_COMPONENT,
    LOSS_VERSION,
    ORCHESTRA_NAMESPACE,
    ORCHESTRA_XSD,
    FixOrchestraEmitOptions,
    FixOrchestraEmitter,
    orchestra_schema_problems,
)
from app.import_source import get_import_source, load_builtin_import_sources
from app.lossiness import LossinessKind, LossinessSeverity

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_ORCHESTRA = sorted(p.name for p in (_EXAMPLES / "fix-orchestra").glob("*.xml"))
_NS = {"fixr": ORCHESTRA_NAMESPACE, "dc": "http://purl.org/dc/elements/1.1/"}


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _imported(fmt: str, relative: str) -> CanonicalApi:
    text = (_EXAMPLES / relative).read_text(encoding="utf-8")
    return build_conversion_source({"id": "i", "name": Path(relative).stem, "source_format": fmt,
                                    "format_metadata": {"sourceContent": text}}).api


def _f(owner: str, name: str, type_: str, *, nullable: bool = True, item: bool = False,
       **constraints: Any) -> CanonicalField:
    ref = TypeRef(item=TypeRef(name=type_), nullable=nullable) if item else TypeRef(name=type_, nullable=nullable)
    return CanonicalField(key=f"{owner}.{name}", name=name, type=ref,
                          constraints=Constraints(**constraints) if constraints else None)


def _model(*types: Type, version: str = "1.0.0") -> CanonicalApi:
    return CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema", identity=ApiIdentity(name="Shop"),
                        title="Shop", version=version, types=list(types))


def _shop() -> CanonicalApi:
    side = Type(key="Side", name="Side", kind=TypeKind.ENUM, enum_values=[
        EnumValue(key="Side.buy", name="buy", value="1"), EnumValue(key="Side.sell", name="sell", value="2")])
    line = Type(key="Line", name="Line", kind=TypeKind.RECORD, fields=[
        _f("Line", "sku", "string", nullable=False), _f("Line", "qty", "integer")])
    party = Type(key="Party", name="Party", kind=TypeKind.RECORD, fields=[_f("Party", "partyId", "string")])
    tags = Type(key="Tags", name="Tags", kind=TypeKind.MAP, key_type=TypeRef(name="string"),
                value_type=TypeRef(name="integer"))
    shape = Type(key="Shape", name="Shape", kind=TypeKind.UNION, union_members=["Party", "Line"])
    order = Type(key="Order", name="Order", kind=TypeKind.RECORD, description="An order", fields=[
        _f("Order", "orderId", "string", nullable=False),
        _f("Order", "side", "Side", nullable=False),
        _f("Order", "placed-at", "string", format="date-time"),
        _f("Order", "price", "number"),
        _f("Order", "lines", "Line", item=True),
        _f("Order", "notes", "string", item=True),
        _f("Order", "party", "Party"),
        _f("Order", "tags", "Tags"),
        _f("Order", "shape", "Shape"),
    ])
    return _model(side, line, party, tags, shape, order)


def _xml(result: EmitResult) -> ET.Element:
    return ET.fromstring(result.files[0].content)


def _assert_valid(result: EmitResult) -> None:
    assert orchestra_schema_problems(result.files[0].content) == []


def _subjects(result: EmitResult) -> set:
    return {loss.subject for loss in result.losses}


# ===========================================================================
# Valid against the official XSD
# ===========================================================================


def test_the_emitter_is_registered_as_fix_orchestra() -> None:
    emitter = get_emitter("fix-orchestra")
    assert emitter is FixOrchestraEmitter and emitter.requires_source == ("record-type",)


def test_the_vendored_schema_is_the_official_orchestra_1_0_repository_xsd() -> None:
    text = ORCHESTRA_XSD.read_text(encoding="utf-8")
    assert f'targetNamespace="{ORCHESTRA_NAMESPACE}"' in text
    assert (ORCHESTRA_XSD.parent / "repositorytypes.xsd").is_file()


@pytest.mark.parametrize("name", _ORCHESTRA)
def test_every_imported_orchestra_repository_exports_valid_against_the_xsd(name: str) -> None:
    _assert_valid(FixOrchestraEmitter().emit(_imported("fix-orchestra", f"fix-orchestra/{name}")))


@pytest.mark.parametrize(("fmt", "path"), [
    ("openapi", "openapi/30-openapi-3.0-petstore.yaml"),
    ("json-schema", "json-schema/03-multiple-defs.json"),
    ("graphql", "graphql/06-union-types.graphql"),
])
def test_a_typed_source_exports_valid_against_the_xsd(fmt: str, path: str) -> None:
    _assert_valid(FixOrchestraEmitter().emit(_imported(fmt, path)))


def test_the_constructed_model_exports_valid_against_the_xsd() -> None:
    _assert_valid(FixOrchestraEmitter().emit(_shop()))


def test_the_checker_reports_what_the_xsd_refuses() -> None:
    valid = FixOrchestraEmitter().emit(_shop()).files[0].content
    for broken in (valid.replace('version="1.0"', 'version="v1"'),
                   valid.replace("fixr:metadata>", "fixr:metadataX>"),
                   "<not-xml"):
        assert orchestra_schema_problems(broken)


# ===========================================================================
# The mapping
# ===========================================================================


def test_root_records_are_messages_and_held_records_components_and_groups() -> None:
    root = _xml(FixOrchestraEmitter().emit(_shop()))
    messages = [m.get("name") for m in root.findall("fixr:messages/fixr:message", _NS)]
    components = [c.get("name") for c in root.findall("fixr:components/fixr:component", _NS)]
    groups = [g.get("name") for g in root.findall("fixr:groups/fixr:group", _NS)]
    assert messages == ["Order"]
    assert {"Party", "Shape"} <= set(components)
    assert {"Line", "notesGrp", "TagsGrp"} <= set(groups)
    order = root.find("fixr:messages/fixr:message", _NS)
    assert order.find("fixr:annotation/fixr:documentation", _NS).text == "An order"


def test_fields_are_declared_once_with_tags_and_referenced_by_tag() -> None:
    root = _xml(FixOrchestraEmitter().emit(_shop()))
    fields = {f.get("name"): f for f in root.findall("fixr:fields/fixr:field", _NS)}
    assert int(fields["orderId"].get("id")) >= FIRST_SYNTHESIZED_TAG
    assert fields["side"].get("type") == "Side"
    assert fields["placed_at"].get("type") == "UTCTimestamp" and fields["price"].get("type") == "float"
    tags = [int(f.get("id")) for f in fields.values()]
    assert len(tags) == len(set(tags))
    structure = root.find("fixr:messages/fixr:message/fixr:structure", _NS)
    first = structure[0]
    assert first.tag.endswith("fieldRef") and first.get("id") == fields["orderId"].get("id")
    assert first.get("presence") == "required"


def test_enumerations_are_code_sets() -> None:
    root = _xml(FixOrchestraEmitter().emit(_shop()))
    [code_set] = root.findall("fixr:codeSets/fixr:codeSet", _NS)
    assert (code_set.get("name"), code_set.get("type")) == ("Side", "char")
    assert [(c.get("name"), c.get("value")) for c in code_set.findall("fixr:code", _NS)] == [("buy", "1"),
                                                                                            ("sell", "2")]


def test_groups_carry_their_num_in_group_counter() -> None:
    root = _xml(FixOrchestraEmitter().emit(_shop()))
    fields = {f.get("id"): f.get("name") for f in root.findall("fixr:fields/fixr:field", _NS)}
    for group in root.findall("fixr:groups/fixr:group", _NS):
        counter = group.find("fixr:numInGroup", _NS)
        assert counter is not None and fields[counter.get("id")].startswith("No")


def test_every_made_up_decision_is_reported() -> None:
    result = FixOrchestraEmitter().emit(_shop())
    assert {LOSS_TAG_SYNTHESIZED, LOSS_LIST_AS_GROUP, LOSS_MAP_AS_GROUP, LOSS_UNION_AS_COMPONENT,
            LOSS_RENAMED} <= _subjects(result)
    assert LOSS_PLACEHOLDER_CODESET not in _subjects(result)


def test_a_model_with_no_enumeration_gets_a_reported_placeholder_code_set() -> None:
    api = _model(Type(key="T", name="T", kind=TypeKind.RECORD, fields=[_f("T", "a", "string")]))
    result = FixOrchestraEmitter().emit(api)
    _assert_valid(result)
    assert [c.get("name") for c in _xml(result).findall("fixr:codeSets/fixr:codeSet", _NS)] == ["NoCodeSet"]
    assert LOSS_PLACEHOLDER_CODESET in _subjects(result)


def test_the_version_follows_the_pattern_the_xsd_accepts() -> None:
    api = _model(Type(key="T", name="T", kind=TypeKind.RECORD, fields=[_f("T", "a", "string")]), version="2.3.1")
    result = FixOrchestraEmitter().emit(api)
    assert _xml(result).get("version") == "2.3" and LOSS_VERSION in _subjects(result)
    assert _xml(FixOrchestraEmitter().emit(api, opts=FixOrchestraEmitOptions(version="FIX.5.0SP2"))).get(
        "version") == "FIX.5.0SP2"
    with pytest.raises(EmitOptionsError):
        FixOrchestraEmitter().emit(api, opts=FixOrchestraEmitOptions(version="latest"))
    orders = _imported("fix-orchestra", "fix-orchestra/02-typical-order-repository.xml")
    assert _xml(FixOrchestraEmitter().emit(orders)).get("version") == "FIX.4.4"  # EP001 is outside the pattern


def test_a_model_with_no_record_is_refused() -> None:
    enum = Type(key="E", name="E", kind=TypeKind.ENUM, enum_values=[EnumValue(key="E.a", name="a")])
    with pytest.raises(EmitPreconditionError):
        FixOrchestraEmitter().emit(_model(enum))
    with pytest.raises(EmitPreconditionError):
        FixOrchestraEmitter().emit(_model(Type(key="T", name="T", kind=TypeKind.RECORD, fields=[])))


# ===========================================================================
# An imported Orchestra repository exports back
# ===========================================================================


def _reimport(result: EmitResult) -> CanonicalApi:
    source = get_import_source("fix-orchestra")
    return source.normalize(source.parse(result.files[0].content), include_raw=False)


def test_an_orchestra_source_keeps_its_tags_ids_msg_types_and_names() -> None:
    api = _imported("fix-orchestra", "fix-orchestra/02-typical-order-repository.xml")
    result = FixOrchestraEmitter().emit(api)
    assert LOSS_TAG_SYNTHESIZED not in _subjects(result)
    root = _xml(result)
    fields = {f.get("name"): f.get("id") for f in root.findall("fixr:fields/fixr:field", _NS)}
    assert fields["Side"] == "54" and fields["ClOrdID"] == "11"
    order = next(m for m in root.findall("fixr:messages/fixr:message", _NS) if m.get("name") == "NewOrderSingle")
    assert order.get("msgType") == "D"
    side = next(c for c in root.findall("fixr:codeSets/fixr:codeSet", _NS) if c.get("name") == "SideCodeSet")
    assert side.get("id") == "54" and side.find("fixr:code", _NS).get("id") == "54001"
    back = _reimport(result)
    assert {t.key for t in back.types} == {t.key for t in api.types}


def test_presence_rules_and_scenarios_are_written() -> None:
    api = _imported("fix-orchestra", "fix-orchestra/04-stress-presence-and-rules.xml")
    root = _xml(FixOrchestraEmitter().emit(api))
    refs = root.findall(".//fixr:fieldRef", _NS)
    presences = {r.get("presence") for r in refs}
    assert {"required", "constant"} <= presences and "conditional" not in presences
    assert root.findall(".//fixr:fieldRef/fixr:rule/fixr:when", _NS)


def test_actors_flows_and_responses_are_written_when_the_source_carries_them() -> None:
    api = _imported("fix-orchestra", "fix-orchestra/06-typical-actors-and-state-machine.xml")
    root = _xml(FixOrchestraEmitter().emit(api))
    assert root.findall("fixr:actors/fixr:actor", _NS)
    assert root.findall("fixr:actors/fixr:actor/fixr:states/fixr:initial", _NS)
    flows = root.findall("fixr:actors/fixr:flow", _NS)
    assert len(flows) == len(api.extras["fix_flows"])
    execution = _imported("fix-orchestra", "fix-orchestra/05-real-world-execution-flow.xml")
    if any(t.extras.get("fix_responses") for t in execution.types):
        assert _xml(FixOrchestraEmitter().emit(execution)).findall(".//fixr:responses/fixr:response/fixr:messageRef",
                                                                    _NS)


def test_the_output_is_deterministic() -> None:
    assert FixOrchestraEmitter().emit(_shop()).files[0].content == FixOrchestraEmitter().emit(_shop()).files[0].content


# ===========================================================================
# Fidelity
# ===========================================================================


def _items(api: CanonicalApi, **match: Any) -> List[Any]:
    report = compute_lossiness_for_emitter(api, FixOrchestraEmitter)
    return [i for i in report.items if all(getattr(i, k) == v for k, v in match.items())]


def test_an_operation_bearing_source_gets_the_critical_types_only_advisory() -> None:
    api = _imported("openapi", "openapi/30-openapi-3.0-petstore.yaml")
    [advisory] = _items(api, construct_key="", target_mapping="types-only")
    assert advisory.kind is LossinessKind.DROP and advisory.severity is LossinessSeverity.CRITICAL


def test_synthesized_tags_are_synth_items() -> None:
    synth = {i.construct_key for i in _items(_shop(), kind=LossinessKind.SYNTH,
                                              target_mapping=LOSS_TAG_SYNTHESIZED)}
    assert {"Order.orderId", "Line.sku"} <= synth


def test_an_orchestra_source_reports_no_synthesized_tag() -> None:
    api = _imported("fix-orchestra", "fix-orchestra/02-typical-order-repository.xml")
    assert not _items(api, target_mapping=LOSS_TAG_SYNTHESIZED)


def test_every_item_has_a_message() -> None:
    for api in (_shop(), _imported("openapi", "openapi/30-openapi-3.0-petstore.yaml")):
        assert all(i.message.strip() for i in compute_lossiness_for_emitter(api, FixOrchestraEmitter).items)


def test_list_and_map_decisions_are_filed_under_their_field() -> None:
    by_key: Dict[str, set] = {}
    for item in _items(_shop()):
        by_key.setdefault(item.construct_key, set()).add(item.target_mapping)
    assert LOSS_LIST_AS_GROUP in by_key["Order.notes"] and LOSS_MAP_AS_GROUP in by_key["Order.tags"]
