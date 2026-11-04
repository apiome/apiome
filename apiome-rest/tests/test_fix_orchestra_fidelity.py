"""FIX Orchestra fidelity pack — MFX-37.2 (#4324).

Pins :class:`app.fix_orchestra_emitter.FixOrchestraFidelityRulePack` (and what the emitter writes for it) against
the issue's acceptance criteria:

* **losses enumerated** —
  * REST / RPC operations → a message **scenario** (``APPROX``) when a payload is written as a message, else
    ``DROP``, with a critical advisory counting the dropped ones;
  * FIX tag numbers → ``SYNTH``;
  * constraints → a **code set** (an inline enumeration) or ``APPROX`` (fieldRef bounds, group occurrences,
    documentation) — never silently dropped;
  * non-FIX types → flattened into a message / component / group (``APPROX``);
* **tag numbers stable across re-exports** — the tags a first export assigns come back from the MFX-12.2
  field-identity store (target ``fix-orchestra``) and are reused; a new field gets a tag no field has had.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import load_builtin_emitters
from app.export_service import ExportPersistenceContext, _field_identity_target, emit_canonical
from app.fidelity_engine import compute_lossiness_for_emitter
from app.field_identity_store import FIX_ORCHESTRA_TARGET
from app.fix_orchestra_emitter import (
    LOSS_BOUNDS,
    LOSS_CONSTRAINT_DOC,
    LOSS_ENUM_AS_CODESET,
    LOSS_OCCURS,
    LOSS_TAG_SYNTHESIZED,
    ORCHESTRA_NAMESPACE,
    FixOrchestraEmitOptions,
    FixOrchestraEmitter,
    orchestra_schema_problems,
)
from app.import_source import load_builtin_import_sources
from app.lossiness import LossinessKind, LossinessReport, LossinessSeverity, LossItem
from app.transcoding_guards import TranscodeVerdict, classify_transcode

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_NS = {"fixr": ORCHESTRA_NAMESPACE}


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


def _record(name: str, *fields: CanonicalField) -> Type:
    return Type(key=name, name=name, kind=TypeKind.RECORD, fields=list(fields))


def _api(*types: Type, services: List[Service] | None = None) -> CanonicalApi:
    return CanonicalApi(paradigm=ApiParadigm.REST if services else ApiParadigm.DATA_SCHEMA, format="openapi",
                        identity=ApiIdentity(name="Orders"), title="Orders", version="1.0", types=list(types),
                        services=services or [])


def _orders() -> CanonicalApi:
    create = _record("CreateOrder",
                     _f("CreateOrder", "symbol", "string", nullable=False, pattern="^[A-Z]{1,6}$", max_length=6),
                     _f("CreateOrder", "qty", "integer", minimum=1, maximum=1000000),
                     _f("CreateOrder", "side", "string", enum=["B", "S"]),
                     _f("CreateOrder", "legs", "Leg", item=True, min_items=1, max_items=4))
    leg = _record("Leg", _f("Leg", "ratio", "number", multiple_of=0.5))
    ack = _record("OrderAck", _f("OrderAck", "orderId", "string", nullable=False))
    operations = [
        Operation(key="POST /orders", name="createOrder", kind=OperationKind.REQUEST_RESPONSE, http_method="POST",
                  http_path="/orders", messages=[
                      Message(key="POST /orders#request", role=MessageRole.REQUEST,
                              payload=TypeRef(name="CreateOrder")),
                      Message(key="POST /orders#response.201", role=MessageRole.RESPONSE,
                              payload=TypeRef(name="OrderAck"))]),
        Operation(key="DELETE /orders/{id}", name="cancelOrder", kind=OperationKind.REQUEST_RESPONSE,
                  http_method="DELETE", http_path="/orders/{id}"),
    ]
    return _api(create, leg, ack, services=[Service(key="orders", name="orders", operations=operations)])


def _report(api: CanonicalApi, **options: Any) -> LossinessReport:
    return compute_lossiness_for_emitter(api, FixOrchestraEmitter, options=options or None)


def _items(report: LossinessReport, **match: Any) -> List[LossItem]:
    return [i for i in report.items if all(getattr(i, k) == v for k, v in match.items())]


def _xml(api: CanonicalApi, **options: Any) -> ET.Element:
    result = FixOrchestraEmitter().emit(api, opts=FixOrchestraEmitOptions(**options))
    assert orchestra_schema_problems(result.files[0].content) == []
    return ET.fromstring(result.files[0].content)


def _tags(root: ET.Element) -> Dict[str, int]:
    return {f.get("name"): int(f.get("id")) for f in root.findall("fixr:fields/fixr:field", _NS)}


# ===========================================================================
# Operations → scenario APPROX or DROP
# ===========================================================================


def test_an_operation_whose_payloads_are_messages_is_a_scenario() -> None:
    report = _report(_orders())
    kinds = {i.kind: i for i in _items(report, construct_key="POST /orders")}
    assert set(kinds) == {LossinessKind.APPROX, LossinessKind.DROP}
    assert kinds[LossinessKind.APPROX].target_mapping == "operation → message scenario"
    assert "CreateOrder" in kinds[LossinessKind.APPROX].message and "OrderAck" in kinds[LossinessKind.APPROX].message
    assert kinds[LossinessKind.DROP].severity is LossinessSeverity.INFO


def test_an_operation_with_no_message_payload_is_dropped() -> None:
    [item] = _items(_report(_orders()), construct_key="DELETE /orders/{id}")
    assert item.kind is LossinessKind.DROP and item.target_mapping == "operation → dropped (no message)"


def test_the_critical_advisory_counts_the_dropped_operations_and_the_scenarios() -> None:
    api = _orders()
    report = _report(api)
    [advisory] = _items(report, construct_key="", target_mapping="types-only")
    assert advisory.severity is LossinessSeverity.CRITICAL
    assert "1 of 2 operation(s)" in advisory.message and "1 operation(s) are kept as message scenarios" in \
        advisory.message
    assert classify_transcode(api, FixOrchestraEmitter, report=report).verdict in (TranscodeVerdict.NEAR_EMPTY,
                                                                                   TranscodeVerdict.SEVERE)


def test_no_advisory_when_every_operation_is_a_scenario() -> None:
    api = _orders()
    api.services[0].operations = api.services[0].operations[:1]
    assert not _items(_report(api), target_mapping="types-only")


def test_the_request_message_names_its_response() -> None:
    root = _xml(_orders())
    create = next(m for m in root.findall("fixr:messages/fixr:message", _NS) if m.get("name") == "CreateOrder")
    [response] = create.findall("fixr:responses/fixr:response", _NS)
    assert response.get("name") == "createOrder"
    assert response.find("fixr:messageRef", _NS).get("name") == "OrderAck"


def test_a_rest_source_s_operations_are_scenarios_or_drops() -> None:
    api = _imported("openapi", "openapi/30-openapi-3.0-petstore.yaml")
    report = _report(api)
    for operation in api.operations():
        kinds = {i.kind for i in _items(report, construct_key=operation.key)}
        assert LossinessKind.DROP in kinds and kinds <= {LossinessKind.DROP, LossinessKind.APPROX}, operation.key
    assert _items(report, target_mapping="operation → message scenario")


# ===========================================================================
# FIX tags → SYNTH, stable across re-exports
# ===========================================================================


def test_every_synthesized_tag_is_a_synth_item() -> None:
    synth = {i.construct_key for i in _items(_report(_orders()), kind=LossinessKind.SYNTH,
                                              target_mapping=LOSS_TAG_SYNTHESIZED)}
    assert {"CreateOrder.symbol", "CreateOrder.qty", "Leg.ratio", "OrderAck.orderId"} <= synth


def test_a_re_export_reuses_every_stored_tag() -> None:
    first = FixOrchestraEmitter().emit(_orders())
    assigned = first.field_identity_assignments
    assert assigned and all(key.startswith("field/") for key in assigned)
    again = FixOrchestraEmitter().emit(_orders(), opts=FixOrchestraEmitOptions(persisted_field_numbers=assigned))
    assert again.field_identity_assignments == {}
    assert again.files[0].content == first.files[0].content


def test_a_new_field_gets_a_tag_no_field_has_had() -> None:
    first = FixOrchestraEmitter().emit(_orders())
    stored = {**first.field_identity_assignments, "field/retired": 9000}
    api = _orders()
    api.types[2].fields.append(_f("OrderAck", "venue", "string"))
    root = _xml(api, persisted_field_numbers=stored)
    tags = _tags(root)
    assert {name: tags[name] for name in _tags(ET.fromstring(first.files[0].content))} == \
        _tags(ET.fromstring(first.files[0].content))
    assert tags["venue"] not in stored.values()


def test_stored_tags_survive_a_reordered_and_shrunk_model() -> None:
    first = FixOrchestraEmitter().emit(_orders())
    api = _orders()
    api.types[0].fields = list(reversed(api.types[0].fields[1:]))
    tags = _tags(_xml(api, persisted_field_numbers=first.field_identity_assignments))
    before = _tags(ET.fromstring(first.files[0].content))
    assert all(before[name] == tag for name, tag in tags.items())


def test_a_source_tag_wins_over_a_stored_one() -> None:
    api = _imported("fix-orchestra", "fix-orchestra/02-typical-order-repository.xml")
    tags = _tags(_xml(api, persisted_field_numbers={"field/Side": 7777}))
    assert tags["Side"] == 54


def test_the_export_service_uses_the_fix_orchestra_store_key() -> None:
    assert _field_identity_target(FixOrchestraEmitter) == FIX_ORCHESTRA_TARGET == "fix-orchestra"


@patch("app.export_service.load_persisted_field_numbers")
@patch("app.export_service.persist_field_number_assignments")
def test_emit_canonical_loads_and_persists_tags(mock_persist: MagicMock, mock_load: MagicMock) -> None:
    api = _api(_record("T", _f("T", "a", "string"), _f("T", "b", "string")))
    mock_load.return_value = {"field/b": 6001}
    result = emit_canonical(api, "fix-orchestra", persistence=ExportPersistenceContext(tenant_id="tenant-1",
                                                                                    artifact_id="project-1"))
    tags = _tags(ET.fromstring(result.files[0].content))
    assert tags == {"a": 5000, "b": 6001}
    mock_load.assert_called_once_with("tenant-1", "project-1", "fix-orchestra")
    mock_persist.assert_called_once_with("tenant-1", "project-1", "fix-orchestra", {"field/a": 5000})


def test_the_stored_tags_are_not_a_card_option() -> None:
    schema = FixOrchestraEmitOptions.model_json_schema()
    assert "persisted_field_numbers" not in schema["properties"] and "version" in schema["properties"]


# ===========================================================================
# Constraints → code set / APPROX
# ===========================================================================


def test_an_inline_enumeration_becomes_a_code_set() -> None:
    root = _xml(_orders())
    code_set = next(c for c in root.findall("fixr:codeSets/fixr:codeSet", _NS) if c.get("name") == "sideCodeSet")
    assert [(c.get("name"), c.get("value")) for c in code_set.findall("fixr:code", _NS)] == [("B", "B"), ("S", "S")]
    field = next(f for f in root.findall("fixr:fields/fixr:field", _NS) if f.get("name") == "side")
    assert field.get("type") == "sideCodeSet"
    [item] = _items(_report(_orders()), construct_key="CreateOrder.side", target_mapping=LOSS_ENUM_AS_CODESET)
    assert item.kind is LossinessKind.APPROX


def test_bounds_and_lengths_are_fieldref_attributes() -> None:
    root = _xml(_orders())
    tags = _tags(root)
    refs = {r.get("id"): r for r in root.findall(".//fixr:message/fixr:structure/fixr:fieldRef", _NS)}
    qty = refs[str(tags["qty"])]
    assert (qty.get("minInclusive"), qty.get("maxInclusive")) == ("1", "1000000")
    assert refs[str(tags["symbol"])].get("implMaxLength") == "6"
    assert _items(_report(_orders()), construct_key="CreateOrder.qty", target_mapping=LOSS_BOUNDS)


def test_list_counts_are_group_occurrences() -> None:
    group_ref = _xml(_orders()).find(".//fixr:message/fixr:structure/fixr:groupRef", _NS)
    assert (group_ref.get("implMinOccurs"), group_ref.get("implMaxOccurs")) == ("1", "4")
    assert _items(_report(_orders()), construct_key="CreateOrder.legs", target_mapping=LOSS_OCCURS)


def test_other_constraints_are_documented_not_silently_dropped() -> None:
    root = _xml(_orders())
    docs = [d.text for d in root.findall(".//fixr:fieldRef/fixr:annotation/fixr:documentation", _NS)]
    assert any("pattern ^[A-Z]{1,6}$" in (d or "") for d in docs)
    assert any("multiple_of 0.5" in (d or "") for d in docs)
    report = _report(_orders())
    assert _items(report, construct_key="Leg.ratio", target_mapping=LOSS_CONSTRAINT_DOC)
    assert not _items(report, target_mapping="constraints → dropped")
    for item in _items(report, construct_key="CreateOrder.symbol"):
        assert item.kind in (LossinessKind.APPROX, LossinessKind.SYNTH)


# ===========================================================================
# Non-FIX types → flattening APPROX
# ===========================================================================


def test_a_non_fix_record_is_flattened() -> None:
    report = _report(_orders())
    for key, kind in (("CreateOrder", "message"), ("Leg", "group"), ("OrderAck", "message")):
        flattened = _items(report, construct_key=key, kind=LossinessKind.APPROX)
        assert any(i.target_mapping == f"record → {kind}" for i in flattened), key
        assert not _items(report, construct_key=key, kind=LossinessKind.OK)


def test_an_orchestra_record_is_not_reported_as_flattened() -> None:
    api = _imported("fix-orchestra", "fix-orchestra/02-typical-order-repository.xml")
    report = _report(api)
    assert not [i for i in report.items if (i.target_mapping or "").startswith("record → ")]
    assert not _items(report, target_mapping=LOSS_TAG_SYNTHESIZED)


def test_every_item_has_a_message() -> None:
    for api in (_orders(), _imported("openapi", "openapi/30-openapi-3.0-petstore.yaml")):
        assert all(i.message.strip() for i in _report(api).items)
