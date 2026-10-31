"""RAML fidelity pack: non-REST losses and type coverage — MFX-17.2 (#3902).

:class:`app.raml_emitter.RamlFidelityRulePack` on top of the MFX-17.1 rules:

* a source that is not a REST API gets the root advisory :data:`~app.raml_emitter.REST_ONLY_WARNING`
  — a ``DROP`` naming what is not written (``critical`` when only types are exported), or an
  ``APPROX`` when every operation has an HTTP binding; a REST source gets none;
* what a re-import of the RAML gives back, so the round trip can explain it: a service whose key is
  not the title is dropped and the title's service is synthesized; a type declared under a name other
  than its key is dropped under its key and synthesized under the declared name; a record with
  unnumbered fields reads back numbered by position; a non-RAML type's or parameter's source-specific
  details are not written — and the writer records the same losses;
* the drive-loop hooks the pack uses (:meth:`~app.fidelity_rulepack.FidelityRulePack.service_verdicts`,
  :meth:`~app.fidelity_rulepack.FidelityRulePack.synthesized_verdicts`) record nothing by default;
* the acceptance check: the round trip of every cross-format corpus source is fully explained by the
  fidelity report, except a WADL source whose operation names the RAML reader does not read back.
"""

from __future__ import annotations

from typing import Dict, List

import pytest
from test_raml_emitter import _CORPUS, _corpus_api, _emit, _field, _op, _param, _subjects

from app import raml_amf
from app import raml_import_source as raml_import_source_module
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Channel,
    Operation,
    OperationKind,
    ParameterLocation,
    Service,
    Type,
    TypeKind,
)
from app.emitter import CapabilityProfile
from app.fidelity_engine import compute_lossiness_for_emitter
from app.fidelity_rulepack import CapabilityRulePack
from app.lossiness import LossinessKind, LossinessSeverity, LossItem
from app.raml_emitter import REST_ONLY_WARNING, RamlEmitter
from app.raml_roundtrip import round_trip_raml


@pytest.fixture
def no_amf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate and re-import through the pure-Python RAML reader."""
    monkeypatch.setattr(raml_amf, "amf_available", lambda: False)
    monkeypatch.setattr(raml_import_source_module, "amf_available", lambda: False)


def _api(*, paradigm=ApiParadigm.REST, fmt="openapi-3.1", operations=(), types=(), service="default", **kw):
    """A small model of ``paradigm`` / ``fmt`` with one service holding ``operations``."""
    return CanonicalApi(
        paradigm=paradigm, format=fmt, identity=ApiIdentity(name="Shop"), title="Shop",
        services=[Service(key=service, name=service, operations=list(operations))], types=list(types), **kw,
    )


def _items(api: CanonicalApi) -> Dict[str, List[LossItem]]:
    out: Dict[str, List[LossItem]] = {}
    for item in compute_lossiness_for_emitter(api, RamlEmitter()).items:
        out.setdefault(item.construct_key, []).append(item)
    return out


def _advisory(api: CanonicalApi) -> List[LossItem]:
    return [item for item in _items(api).get("", []) if REST_ONLY_WARNING in item.message]


def _rpc(key: str) -> Operation:
    """An operation with no HTTP binding."""
    return Operation(key=key, name=key, kind=OperationKind.REQUEST_RESPONSE)


# ===========================================================================
# Non-REST sources: "RAML captures REST only"
# ===========================================================================


def test_a_rest_source_gets_no_rest_only_advisory() -> None:
    assert _advisory(_api(operations=[_op("GET", "/pets")])) == []


def test_a_source_with_nothing_raml_can_place_is_a_critical_drop() -> None:
    api = _api(paradigm=ApiParadigm.GRAPH, fmt="graphql", operations=[_rpc("Query.pets"), _rpc("Mutation.add")])
    [item] = _advisory(api)
    assert (item.kind, item.severity, item.target_mapping) == (
        LossinessKind.DROP, LossinessSeverity.CRITICAL, "graph → REST"
    )
    assert "2 operation(s) RAML cannot place" in item.message and "only its types are exported" in item.message
    # Each operation stays dropped on its own.
    assert {i.kind for i in _items(api)["Query.pets"]} == {LossinessKind.DROP}


def test_a_partly_placed_source_is_a_warning_drop_with_its_channels() -> None:
    api = _api(paradigm=ApiParadigm.RPC, fmt="protobuf", operations=[_op("GET", "/a"), _rpc("svc.Call")],
               channels=[Channel(key="orders", address="orders")])
    [item] = _advisory(api)
    assert (item.kind, item.severity, item.target_mapping) == (LossinessKind.DROP, LossinessSeverity.WARN, "rpc → REST")
    assert "1 operation(s)" in item.message and "1 channel(s)" in item.message
    assert "only its types" not in item.message


def test_a_non_rest_source_whose_operations_all_have_routes_is_an_approximation() -> None:
    [item] = _advisory(_api(paradigm=ApiParadigm.DATA_SCHEMA, fmt="jsonschema", operations=[_op("GET", "/a")]))
    assert (item.kind, item.severity) == (LossinessKind.APPROX, LossinessSeverity.WARN)
    assert "reads back as a REST API" in item.message


def test_a_types_only_source_says_its_types_are_all_that_is_exported() -> None:
    api = _api(paradigm=ApiParadigm.DATA_SCHEMA, fmt="avro", operations=[_rpc("x")],
               types=[Type(key="Pet", name="Pet", kind=TypeKind.RECORD)])
    assert _advisory(api)[0].severity is LossinessSeverity.CRITICAL


# ===========================================================================
# Services and type keys: what a re-import gives back
# ===========================================================================


def test_a_service_not_keyed_by_the_title_is_dropped_and_the_title_service_synthesized() -> None:
    items = _items(_api(operations=[_op("GET", "/a")]))
    [dropped] = items["default"]
    assert (dropped.kind, dropped.severity) == (LossinessKind.DROP, LossinessSeverity.INFO)
    assert "read back as the service 'Shop'" in dropped.message
    [synth] = items["Shop"]
    assert (synth.kind, synth.target_mapping) == (LossinessKind.SYNTH, "title → service")


def test_a_service_keyed_by_the_title_is_kept() -> None:
    items = _items(_api(fmt="raml", service="Shop", operations=[_op("GET", "/a")]))
    assert "Shop" not in items and "default" not in items


def test_a_model_without_services_still_reads_back_one() -> None:
    api = CanonicalApi(paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="Shop"),
                       title="Shop")
    assert [i.kind for i in _items(api)["Shop"]] == [LossinessKind.SYNTH]


def test_a_namespaced_type_is_dropped_under_its_key_and_synthesized_under_its_name() -> None:
    order = Type(key="http://acme.example/orders.Order", name="Order", namespace="http://acme.example/orders",
                 kind=TypeKind.RECORD, fields=[_field("http://acme.example/orders.Order", "id", number=1)])
    items = _items(_api(fmt="wsdl", types=[order]))
    assert [i.kind for i in items[order.key]] == [LossinessKind.DROP]
    assert "is declared as 'Order'" in items[order.key][0].message
    [synth] = items["Order"]
    assert (synth.kind, synth.target_mapping) == (LossinessKind.SYNTH, "type Order")


def test_a_declared_name_taken_by_another_source_type_is_not_synthesized() -> None:
    types = [Type(key="a.Pet", name="Pet", namespace="a", kind=TypeKind.RECORD),
             Type(key="Pet2", name="Pet2", kind=TypeKind.RECORD),
             Type(key="Pet", name="Pet", kind=TypeKind.RECORD)]
    items = _items(_api(types=types))
    # `a.Pet` is declared as `Pet`, which is already a source type: no new construct appears.
    assert [i.kind for i in items["a.Pet"]] == [LossinessKind.DROP]
    assert all(i.kind is not LossinessKind.SYNTH for i in items.get("Pet", []))


# ===========================================================================
# Type coverage
# ===========================================================================


def test_unnumbered_record_fields_read_back_numbered_by_position() -> None:
    pet = Type(key="Pet", name="Pet", kind=TypeKind.RECORD, fields=[_field("Pet", "id"), _field("Pet", "name")])
    api = _api(types=[pet])
    [item] = _items(api)["Pet"]
    assert item.kind is LossinessKind.APPROX and "numbered by position" in item.message
    assert _subjects(_emit(api))["field-numbers-positional"] == ["Pet"]


def test_numbered_record_fields_are_not_reported() -> None:
    pet = Type(key="Pet", name="Pet", kind=TypeKind.RECORD,
               fields=[_field("Pet", "id", number=1), _field("Pet", "name", number=2)])
    assert [i.kind for i in _items(_api(types=[pet]))["Pet"]] == [LossinessKind.OK]


def test_source_specific_type_details_are_reported_for_other_formats_only() -> None:
    def pet(fmt: str) -> CanonicalApi:
        kind = "raml_kind" if fmt == "raml" else "graphql_type"
        return _api(fmt=fmt, service="Shop",
                    types=[Type(key="Pet", name="Pet", kind=TypeKind.RECORD, extras={kind: "object"})])

    [item] = _items(pet("graphql"))["Pet"]
    assert item.kind is LossinessKind.APPROX and "(graphql_type) are not written" in item.message
    assert _subjects(_emit(pet("graphql")))["type-details-dropped"] == ["Pet"]
    assert [i.kind for i in _items(pet("raml"))["Pet"]] == [LossinessKind.OK]


def test_source_specific_parameter_details_are_reported() -> None:
    op = _op("GET", "/q", parameters=[_param("GET /q", "q", ParameterLocation.QUERY, extras={"wadl_type": "string"})])
    api = _api(fmt="wadl", operations=[op])
    [item] = _items(api)["GET /q"]
    assert item.kind is LossinessKind.APPROX and "parameter 'q' (wadl_type) are not written" in item.message
    assert "parameter-details-dropped" in _subjects(_emit(api))


# ===========================================================================
# The drive-loop hooks
# ===========================================================================


def test_the_service_and_synthesized_hooks_record_nothing_by_default() -> None:
    api = _api(operations=[_op("GET", "/a")], types=[Type(key="a.Pet", name="Pet", kind=TypeKind.RECORD)])
    report = CapabilityRulePack(CapabilityProfile(), "the target").evaluate(api)
    keys = {item.construct_key for item in report.items}
    assert "default" not in keys and "Shop" not in keys and "Pet" not in keys


# ===========================================================================
# Acceptance: cross-format round trips are explained by the report
# ===========================================================================


@pytest.mark.parametrize("path", _CORPUS, ids=lambda p: p.name)
def test_cross_format_round_trips_are_explained(path, no_amf) -> None:
    report = round_trip_raml(_corpus_api(path))
    assert report.valid and report.reimported
    if path.suffix == ".wadl":
        # The RAML reader does not read `displayName`: the source's operation name comes back as
        # "<VERB> <path>" — a reader limit, not a RAML loss, so the pack does not claim it.
        assert [(e.entity, e.key) for e in report.unexplained] == [("operation", "DELETE /reindex")]
        assert report.overclaims == ["DELETE /reindex"]
    else:
        assert report.explained, (report.unexplained, report.overclaims)
