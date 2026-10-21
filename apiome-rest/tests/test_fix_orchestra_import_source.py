"""Tests for the FIX Orchestra import adapter — FMT-6.9 (#5453).

Covers detection (and routing beside the ``fix`` tag=value adapter), the repository reader
(datatypes, code sets, fields, components, groups, messages, scenarios, actors, flows, state
machines, ``xi:include`` inside a fileset, every refusal code), the canonical normalizer (messages
as records, code sets as enums, groups as lists, ``presence`` as optionality and constraints with
``forbidden`` kept as a declared constraint), the ``fixMsgTypes`` link to message-derived ``fix``
items, and the version-coverage entry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest

from app.api_identity_service import rank_identity_suggestions
from app.canonical_model import ApiParadigm, CanonicalApi, TypeKind
from app.data_contract_facts import SCHEMA_ONLY_FORMATS
from app.fileset import IntakeFileset
from app.fix_orchestra_import_source import FixOrchestraImportSource
from app.fix_orchestra_normalizer import fix_primitive
from app.fix_orchestra_parser import (
    BASE_SCENARIO,
    OrchestraParseError,
    OrchestraRepository,
    is_orchestra,
    parse_orchestra,
    parse_orchestra_fileset,
)
from app.format_version_coverage import VersionSupport, version_coverage_for
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    detect_import_source,
    get_import_source,
    load_builtin_import_sources,
)
from app.import_source_pipeline import fix_msg_types_metadata
from app.secure_xml import SecureXmlError, parse_xml

load_builtin_import_sources()

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_NS = "http://fixprotocol.io/2020/orchestra/repository"


def _fixture(name: str) -> str:
    return (_EXAMPLES / "fix-orchestra" / name).read_text(encoding="utf-8")


_MINIMAL = _fixture("01-minimal-repository.xml")
_TYPICAL = _fixture("02-typical-order-repository.xml")
_COMPOSITION = _fixture("03-composition-components-and-groups.xml")
_STRESS = _fixture("04-stress-presence-and-rules.xml")
_REAL_WORLD = _fixture("05-real-world-execution-flow.xml")
_ACTORS = _fixture("06-typical-actors-and-state-machine.xml")


def _repository(body: str, *, attrs: str = 'name="Test" version="FIX.4.4"') -> str:
    """A repository document with ``body`` inside the root."""
    return f'<fixr:repository xmlns:fixr="{_NS}" {attrs}>{body}</fixr:repository>'


_ONE_FIELD = '<fixr:fields><fixr:field id="11" name="ClOrdID" type="String"/></fixr:fields>'


def _message(structure: str, *, attrs: str = 'name="NewOrderSingle" id="14" msgType="D"') -> str:
    return (
        f"<fixr:messages><fixr:message {attrs}><fixr:structure>{structure}</fixr:structure>"
        "</fixr:message></fixr:messages>"
    )


@pytest.fixture
def adapter() -> FixOrchestraImportSource:
    return FixOrchestraImportSource()


def _model(adapter: FixOrchestraImportSource, text: str) -> CanonicalApi:
    return adapter.normalize(adapter.parse(text, source_label="repo.xml"))


def _type(model: CanonicalApi, name: str):
    return next(t for t in model.types if t.name == name)


def _field(model: CanonicalApi, type_name: str, field_name: str):
    return next(f for f in _type(model, type_name).fields if f.name == field_name)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_detection_claims_a_repository_root(adapter: FixOrchestraImportSource):
    result = adapter.detect(DetectionInput(text=_MINIMAL, filename="repo.xml"))
    assert result.matched
    assert result.format == "fix-orchestra"
    assert result.confidence >= 0.9


def test_detection_claims_the_2016_draft_namespace():
    assert is_orchestra('<fixr:repository xmlns:fixr="http://fixprotocol.io/2016/fixrepository" name="x"/>')


@pytest.mark.parametrize(
    "text",
    [
        "8=FIX.4.4|9=10|35=D|11=A|10=000|",
        '<repository xmlns="urn:other"/>',
        f'<codeSets xmlns="{_NS}"/>',
        '<!-- <fixr:repository xmlns:fixr="http://fixprotocol.io/2020/orchestra/repository"> -->\n<a/>',
        "",
    ],
)
def test_detection_refuses_what_is_not_a_repository(text: str, adapter: FixOrchestraImportSource):
    assert not adapter.detect(DetectionInput(text=text, filename="x")).matched


def test_truncated_repository_is_still_claimed(adapter: FixOrchestraImportSource):
    text = (_EXAMPLES / "fix-orchestra" / "negative" / "03-truncated-mid-codeset.xml").read_text()
    assert adapter.detect(DetectionInput(text=text, filename="x.xml")).matched


def test_registry_routes_orchestra_and_tag_value_apart():
    orchestra = detect_import_source(DetectionInput(text=_TYPICAL, filename="repo.xml"))
    assert orchestra is not None and orchestra[0].key == "fix-orchestra"
    tag_value = (_EXAMPLES / "fix" / "01-newordersingle.fix").read_text()
    fix = detect_import_source(DetectionInput(text=tag_value, filename="order.fix"))
    assert fix is not None and fix[0].key == "fix"


def test_adapter_is_registered():
    adapter = get_import_source("fix-orchestra")
    assert adapter.paradigm is ApiParadigm.DATA_SCHEMA
    assert "orchestra" in adapter.formats


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_minimal_repository_parses():
    repository = parse_orchestra(_MINIMAL)
    assert repository.name == "ExampleMinimal"
    assert repository.version == "FIX.4.4"
    assert [code.value for code in repository.code_sets[0].codes] == ["1", "2"]
    assert [(f.id, f.name, f.type) for f in repository.fields] == [
        ("11", "ClOrdID", "String"),
        ("54", "Side", "SideCodeSet"),
    ]
    message = repository.messages[0]
    assert (message.name, message.msg_type, message.scenario) == ("NewOrderSingle", "D", BASE_SCENARIO)
    assert [(m.kind, m.id, m.presence) for m in message.members] == [
        ("field", "11", "required"),
        ("field", "54", "required"),
    ]


def test_typical_repository_reads_metadata_datatypes_and_components():
    repository = parse_orchestra(_TYPICAL)
    assert repository.metadata["title"] == "Example equities order flow"
    assert repository.datatype_named("Price").base_type == "float"
    assert repository.components[0].name == "Instrument"
    assert repository.fields[0].documentation.startswith("Unique identifier")


def test_group_reads_its_counter_and_nested_group():
    repository = parse_orchestra(_COMPOSITION)
    parties = next(g for g in repository.groups if g.name == "PartiesGrp")
    assert parties.num_in_group == "453"
    assert [(m.kind, m.id) for m in parties.members][-1] == ("group", "2005")


def test_rules_and_responses_are_read():
    repository = parse_orchestra(_STRESS)
    base = next(m for m in repository.messages if m.scenario == "base" and m.name == "NewOrderSingle")
    price = next(m for m in base.members if m.id == "44")
    assert price.presence == "conditional"
    assert price.rules[0].when == 'OrdType in {"^Limit", "^StopLimit"}'
    assert price.rules[0].presence == "required"
    assert base.responses[0].message_refs == (("ExecutionReport", "8"),)
    assert {m.scenario for m in repository.messages if m.name == "NewOrderSingle"} == {"base", "dark"}


def test_actors_flows_and_state_machines_are_read():
    repository = parse_orchestra(_ACTORS)
    assert [flow.reliability for flow in repository.flows] == ["idempotent", "recoverable"]
    book = next(actor for actor in repository.actors if actor.name == "OrderBook")
    machine = book.state_machines[0]
    assert machine.name == "OrderState"
    new = machine.states[0]
    assert [(t.name, t.target) for t in new.transitions] == [
        ("PartialFill", "PartiallyFilled"),
        ("Fill", "Filled"),
        ("Cancel", "Canceled"),
    ]
    assert new.transitions[0].when == 'ExecType == "^Trade" and LeavesQty > 0'


def test_presence_defaults_to_optional():
    repository = parse_orchestra(_repository(_ONE_FIELD + _message('<fixr:fieldRef id="11"/>')))
    assert repository.messages[0].members[0].presence == "optional"


def test_ref_falls_back_to_the_base_scenario():
    text = _repository(_ONE_FIELD + _message('<fixr:fieldRef id="11" scenario="dark"/>'))
    repository = parse_orchestra(text)
    assert repository.field_by_ref(repository.messages[0].members[0]).name == "ClOrdID"


def test_scenario_specific_entity_wins_over_base():
    fields = (
        '<fixr:fields><fixr:field id="11" name="ClOrdID" type="String"/>'
        '<fixr:field id="11" name="ClOrdIDDark" type="String" scenario="dark"/></fixr:fields>'
    )
    repository = parse_orchestra(_repository(fields + _message('<fixr:fieldRef id="11" scenario="dark"/>')))
    assert repository.field_by_ref(repository.messages[0].members[0]).name == "ClOrdIDDark"


@pytest.mark.parametrize(
    "name, code",
    [
        ("negative/01-syntactic-unclosed-message.xml", "INPUT_MALFORMED"),
        ("negative/02-semantic-no-messages.xml", "INPUT_SEMANTIC_INVALID"),
        ("negative/03-truncated-mid-codeset.xml", "INPUT_TRUNCATED"),
        ("negative/04-wrong-format-fix-tagvalue.fix", "FORMAT_MISMATCH"),
        ("negative/06-unresolvable-field-ref.xml", "INPUT_REFERENCE_UNRESOLVED"),
    ],
)
def test_corpus_negatives(name: str, code: str):
    with pytest.raises(OrchestraParseError) as info:
        parse_orchestra(_fixture(name), source_label=name)
    assert info.value.code == code


def test_unresolved_refs_are_all_named():
    with pytest.raises(OrchestraParseError) as info:
        parse_orchestra(_fixture("negative/06-unresolvable-field-ref.xml"))
    assert "field 9999" in str(info.value)
    assert "component 2222" in str(info.value)


def test_encoding_fault_is_code_less():
    raw = (_EXAMPLES / "fix-orchestra" / "negative" / "05-encoding-utf16.xml").read_bytes()
    with pytest.raises(OrchestraParseError) as info:
        parse_orchestra(raw.decode("utf-8", errors="replace"))
    assert info.value.code is None


@pytest.mark.parametrize(
    "text, code, fragment",
    [
        ("", "INPUT_EMPTY", "empty"),
        ('<repository xmlns="urn:other"><messages/></repository>', "FORMAT_MISMATCH", "root"),
        (
            _repository(_ONE_FIELD + _message('<fixr:fieldRef id="11" presence="sometimes"/>')),
            "INPUT_SEMANTIC_INVALID",
            "sometimes",
        ),
        (_repository(_ONE_FIELD + _message('<fixr:fieldRef presence="required"/>')), "INPUT_SEMANTIC_INVALID", "`id`"),
        (
            _repository(
                '<fixr:fields><fixr:field id="11" name="A"/><fixr:field id="11" name="B"/></fixr:fields>'
                + _message('<fixr:fieldRef id="11"/>')
            ),
            "INPUT_SEMANTIC_INVALID",
            "twice",
        ),
        (
            _repository(
                '<fixr:fields><fixr:field id="11" name="A"/></fixr:fields>'
                '<fixr:groups><fixr:group id="1" name="G"><fixr:numInGroup id="999"/>'
                '<fixr:fieldRef id="11"/></fixr:group></fixr:groups>' + _message('<fixr:groupRef id="1"/>')
            ),
            "INPUT_REFERENCE_UNRESOLVED",
            "numInGroup field 999",
        ),
        ('<!DOCTYPE r [<!ENTITY x "y">]><r/>', "INPUT_UNSAFE_CONSTRUCT", "DTD"),
    ],
)
def test_refusals_carry_a_code(text: str, code: str, fragment: str):
    with pytest.raises(OrchestraParseError) as info:
        parse_orchestra(text)
    assert info.value.code == code
    assert fragment in str(info.value)


def test_adapter_parse_carries_the_code(adapter: FixOrchestraImportSource):
    with pytest.raises(ImportSourceError) as info:
        adapter.parse(_fixture("negative/02-semantic-no-messages.xml"))
    assert info.value.code == "INPUT_SEMANTIC_INVALID"


# ---------------------------------------------------------------------------
# XInclude — resolved only inside a fileset
# ---------------------------------------------------------------------------


def _modular_members() -> Dict[str, str]:
    folder = _EXAMPLES / "fix-orchestra" / "07-modular-set"
    return {path.name: path.read_text(encoding="utf-8") for path in folder.iterdir()}


def test_fileset_resolves_xinclude_against_its_members(adapter: FixOrchestraImportSource):
    fileset = IntakeFileset(members=_modular_members(), root="repository.xml")
    repository = adapter.parse_fileset(fileset)
    assert repository.includes == ["codesets.xml"]
    assert {code_set.name for code_set in repository.code_sets} == {
        "SideCodeSet",
        "OrdTypeCodeSet",
        "TimeInForceCodeSet",
    }
    model = adapter.normalize(repository)
    assert _field(model, "NewOrderSingle", "Side").type.name == "SideCodeSet"


def test_single_file_with_xinclude_is_unresolved():
    with pytest.raises(OrchestraParseError) as info:
        parse_orchestra(_modular_members()["repository.xml"], source_label="repository.xml")
    assert info.value.code == "INPUT_REFERENCE_UNRESOLVED"
    assert "codesets.xml" in str(info.value)


def test_fileset_include_of_a_missing_member_is_unresolved():
    members = {"repository.xml": _modular_members()["repository.xml"]}
    with pytest.raises(OrchestraParseError) as info:
        parse_orchestra_fileset(members, "repository.xml")
    assert info.value.code == "INPUT_REFERENCE_UNRESOLVED"


def test_include_cycle_is_refused():
    include = '<xi:include xmlns:xi="http://www.w3.org/2001/XInclude" href="{}"/>'
    members = {
        "repo.xml": _repository(include.format("a.xml") + _ONE_FIELD + _message('<fixr:fieldRef id="11"/>')),
        "a.xml": f'<fixr:codeSets xmlns:fixr="{_NS}">{include.format("b.xml")}</fixr:codeSets>',
        "b.xml": f'<fixr:codeSets xmlns:fixr="{_NS}">{include.format("a.xml")}</fixr:codeSets>',
    }
    with pytest.raises(OrchestraParseError) as info:
        parse_orchestra_fileset(members, "repo.xml")
    assert info.value.code == "INPUT_SEMANTIC_INVALID"
    assert "cycle" in str(info.value)


def test_text_include_is_refused():
    include = '<xi:include xmlns:xi="http://www.w3.org/2001/XInclude" href="a.txt" parse="text"/>'
    members = {"repo.xml": _repository(include + _ONE_FIELD + _message('<fixr:fieldRef id="11"/>')), "a.txt": "x"}
    with pytest.raises(OrchestraParseError) as info:
        parse_orchestra_fileset(members, "repo.xml")
    assert info.value.code == "INPUT_SEMANTIC_INVALID"


def test_secure_xml_still_refuses_xinclude_by_default():
    text = '<r><xi:include xmlns:xi="http://www.w3.org/2001/XInclude" href="x.xml"/></r>'
    with pytest.raises(SecureXmlError) as info:
        parse_xml(text)
    assert info.value.code == "INPUT_UNSAFE_CONSTRUCT"
    root = parse_xml(text, allow_xinclude=True)
    assert len(list(root)) == 1


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def test_messages_become_records_and_code_sets_enums(adapter: FixOrchestraImportSource):
    model = _model(adapter, _MINIMAL)
    assert model.format == "fix-orchestra"
    assert model.paradigm is ApiParadigm.DATA_SCHEMA
    message = _type(model, "NewOrderSingle")
    assert message.kind is TypeKind.RECORD
    assert message.extras["fix_msg_type"] == "D"
    side = _type(model, "SideCodeSet")
    assert side.kind is TypeKind.ENUM
    assert [(v.name, v.value) for v in side.enum_values] == [("Buy", "1"), ("Sell", "2")]
    field = _field(model, "NewOrderSingle", "Side")
    assert field.type.name == "SideCodeSet"
    assert field.field_number == 54
    assert field.extras["fix_tag"] == "54"


def test_datatypes_resolve_to_primitives(adapter: FixOrchestraImportSource):
    model = _model(adapter, _TYPICAL)
    assert _field(model, "NewOrderSingle", "OrderQty").type.name == "number"
    transact = _field(model, "NewOrderSingle", "TransactTime")
    assert transact.type.name == "string"
    assert transact.constraints.format == "date-time"
    assert _field(model, "NewOrderSingle", "ClOrdID").description.startswith("Unique identifier")


def test_fix_primitive_follows_the_base_type_chain():
    repository = parse_orchestra(_TYPICAL)
    assert fix_primitive(repository, "Price") == ("number", None)
    assert fix_primitive(repository, "int") == ("integer", None)
    assert fix_primitive(repository, "Unknown") == ("string", None)
    assert fix_primitive(repository, None) == ("string", None)


def test_components_and_nested_groups(adapter: FixOrchestraImportSource):
    model = _model(adapter, _COMPOSITION)
    instrument = _field(model, "NewOrderSingle", "Instrument")
    assert instrument.type.name == "Instrument" and instrument.type.nullable is False
    parties = _field(model, "NewOrderSingle", "PartiesGrp")
    assert parties.type.is_list() and parties.type.item.name == "PartiesGrp"
    assert parties.type.nullable is True
    assert parties.constraints.min_items == 1
    assert parties.extras["fix_num_in_group"] == {"tag": "453", "name": "NoPartyIDs"}
    nested = _field(model, "PartiesGrp", "PartySubIDsGrp")
    assert nested.type.item.name == "PartySubIDsGrp"
    assert _type(model, "PartiesGrp").extras["fix_kind"] == "group"


@pytest.mark.parametrize(
    "field_name, nullable, presence",
    [
        ("ClOrdID", False, "required"),
        ("Account", True, "optional"),
        ("Price", True, "conditional"),
        ("MinQty", True, "forbidden"),
        ("ExecInst", True, "ignored"),
        ("HandlInst", False, "constant"),
    ],
)
def test_presence_maps_to_optionality(
    adapter: FixOrchestraImportSource, field_name: str, nullable: bool, presence: str
):
    field = _field(_model(adapter, _STRESS), "NewOrderSingle", field_name)
    assert field.type.nullable is nullable
    assert field.extras["fix_presence"] == presence


def test_forbidden_is_a_declared_constraint_not_a_dropped_field(adapter: FixOrchestraImportSource):
    model = _model(adapter, _STRESS)
    min_qty = _field(model, "NewOrderSingle", "MinQty")
    assert min_qty.constraints.extras["fix_presence"] == "forbidden"
    price = _field(model, "NewOrderSingle_dark", "Price")
    assert price.constraints.extras["fix_presence"] == "forbidden"


def test_constant_is_a_pinned_value(adapter: FixOrchestraImportSource):
    field = _field(_model(adapter, _STRESS), "NewOrderSingle", "HandlInst")
    assert field.default == "1"
    assert field.constraints.enum == ["1"]


def test_conditional_carries_its_rule(adapter: FixOrchestraImportSource):
    field = _field(_model(adapter, _STRESS), "NewOrderSingle", "StopPx")
    assert field.constraints.extras["fix_rules"] == [
        {"name": "RequiredForStop", "presence": "required", "when": 'OrdType in {"^Stop", "^StopLimit"}'}
    ]
    quantity = _field(_model(adapter, _STRESS), "NewOrderSingle", "OrderQty")
    assert quantity.constraints.extras["fix_rules"] == [{"name": "PositiveQuantity", "assign": "OrderQty > 0"}]


def test_scenarios_are_separate_types(adapter: FixOrchestraImportSource):
    model = _model(adapter, _STRESS)
    dark = _type(model, "NewOrderSingle_dark")
    assert dark.extras["fix_scenario"] == "dark"
    assert dark.extras["fix_msg_type"] == "D"
    assert _field(model, "NewOrderSingle_dark", "MinQty").type.nullable is False
    assert _type(model, "NewOrderSingle").extras["fix_responses"] == [
        {"name": "accept", "messages": [{"name": "ExecutionReport", "msgType": "8"}]}
    ]


def test_name_clash_across_kinds_is_qualified(adapter: FixOrchestraImportSource):
    body = (
        _ONE_FIELD
        + '<fixr:components><fixr:component id="1" name="NewOrderSingle">'
        + '<fixr:fieldRef id="11"/></fixr:component></fixr:components>'
        + _message('<fixr:componentRef id="1"/>')
    )
    model = _model(adapter, _repository(body))
    assert {t.name for t in model.types} == {"NewOrderSingle", "NewOrderSingle_component"}
    assert _field(model, "NewOrderSingle", "NewOrderSingle").type.name == "NewOrderSingle_component"


def test_model_extras_record_actors_flows_and_msg_types(adapter: FixOrchestraImportSource):
    model = _model(adapter, _ACTORS)
    assert model.extras["fix_msg_types"] == ["8", "D"]
    assert model.extras["fix_flows"][0] == {
        "name": "OrderEntry",
        "source": "BuySide",
        "destination": "SellSide",
        "reliability": "idempotent",
    }
    buy_side = next(actor for actor in model.extras["fix_actors"] if actor["name"] == "BuySide")
    assert buy_side["fields"] == ["ClOrdID"]
    book = next(actor for actor in model.extras["fix_actors"] if actor["name"] == "OrderBook")
    assert [state["name"] for state in book["state_machines"][0]["states"]] == [
        "New",
        "PartiallyFilled",
        "Filled",
        "Canceled",
    ]


def test_identity_and_title(adapter: FixOrchestraImportSource):
    model = _model(adapter, _REAL_WORLD)
    assert model.title == "Example Venue — order entry rules of engagement"
    assert model.identity.name == "ExampleVenueRules"
    assert model.identity.namespace == "FIX.4.4_EP0044"
    assert model.raw["metadata"]["publisher"] == "Example Venue Ltd"


def test_metadata_date_is_not_part_of_the_contract(adapter: FixOrchestraImportSource):
    from app.fingerprint import fingerprint

    redated = _TYPICAL.replace("2026-08-19", "2027-01-01")
    assert fingerprint(_model(adapter, _TYPICAL)) == fingerprint(_model(adapter, redated))


def test_normalizer_rejects_foreign_ast(adapter: FixOrchestraImportSource):
    with pytest.raises(ImportSourceError):
        adapter.normalize({"not": "a repository"})


def test_schema_only_and_classified():
    assert "fix-orchestra" in SCHEMA_ONLY_FORMATS


# ---------------------------------------------------------------------------
# Linking to message-derived fix items
# ---------------------------------------------------------------------------


def test_fix_msg_types_metadata_for_both_formats(adapter: FixOrchestraImportSource):
    assert fix_msg_types_metadata(_model(adapter, _REAL_WORLD)) == ["8", "9", "D"]
    fix_adapter = get_import_source("fix")
    message = (_EXAMPLES / "fix" / "01-newordersingle.fix").read_text()
    assert fix_msg_types_metadata(fix_adapter.normalize(fix_adapter.parse(message))) == ["D"]


def test_fix_msg_types_metadata_ignores_other_formats():
    model = CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="json-schema",
        identity={"name": "x"},
        extras={"fix_msg_types": ["D"]},
    )
    assert fix_msg_types_metadata(model) == []


def test_shared_msg_type_suggests_the_link():
    anchor = {"name": "Venue rules", "format_metadata": {"fixMsgTypes": ["8", "D"]}}
    candidates = [
        {
            "project_id": "order",
            "name": "NewOrderSingle (FIX.4.4)",
            "slug": "o",
            "format_metadata": {"fixMsgTypes": ["D"]},
        },
        {"project_id": "quote", "name": "Quote (FIX.4.4)", "slug": "q", "format_metadata": {"fixMsgTypes": ["S"]}},
    ]
    suggestions = rank_identity_suggestions(anchor=anchor, anchor_ops=set(), candidates=candidates, candidate_ops={})
    assert [s.project_id for s in suggestions] == ["order"]
    assert "shared FIX message type(s) D" in suggestions[0].reason


# ---------------------------------------------------------------------------
# Version coverage
# ---------------------------------------------------------------------------


def test_version_coverage_names_orchestra():
    coverage = version_coverage_for("fix-orchestra")
    assert coverage is not None
    assert coverage.reads[0].support is VersionSupport.FULL
    assert "Orchestra" in coverage.reads[0].version
    assert not coverage.writes


def test_repository_type_is_exported():
    assert isinstance(parse_orchestra(_MINIMAL), OrchestraRepository)
