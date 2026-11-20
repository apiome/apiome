"""Arazzo fidelity pack — MFX-10.2 (#3871).

Arazzo is workflow-only. :class:`app.arazzo_emitter.ArazzoFidelityRulePack` keeps an Arazzo source's
report as the capability rules make it, and for any other (non-workflow) source:

* leads the report with the warning that *this target captures workflows, not the full API
  surface* — and the MFX-2.4 advisory fires;
* marks the workflows synthesized from services (``SYNTH``), or a source with nothing to sequence as
  a near-empty document (``DROP``);
* writes each operation as a step (``APPROX``), with a ``SYNTH`` when its ``operationId`` is made up;
* drops type declarations and channels;
* predicts the re-import's own keys (COA-1.4, #7040): a step is keyed ``{workflowId}#{stepId}``, so an
  operation whose key changes is ``DROP`` under the old key and ``SYNTH`` under the new one, a service
  becomes a workflow (``APPROX``) or is not written (``DROP``), and agents and skills are dropped.

The writer records the same losses, and every corpus export still re-imports as Arazzo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pytest
import yaml

from app.arazzo_emitter import WORKFLOWS_ONLY_WARNING, ArazzoEmitter, validate_arazzo_document
from app.arazzo_roundtrip import round_trip_arazzo
from app.canonical_model import (
    AgentDescriptor,
    AgentSkill,
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitPreconditionError
from app.fidelity_advisory import build_export_advisory
from app.fidelity_engine import compute_lossiness_for_emitter
from app.lossiness import LossinessKind

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


def _items(api: CanonicalApi) -> Dict[str, List]:
    out: Dict[str, List] = {}
    for item in compute_lossiness_for_emitter(api, ArazzoEmitter()).items:
        out.setdefault(item.construct_key, []).append(item)
    return out


def _kinds(api: CanonicalApi, key: str) -> set:
    return {item.kind for item in _items(api).get(key, [])}


def _op(key: str, **kw) -> Operation:
    return Operation(key=key, name=key, kind=kw.pop("kind", OperationKind.REQUEST_RESPONSE), **kw)


def _api(*operations: Operation, fmt: str = "openapi-3.1", **kw) -> CanonicalApi:
    defaults = dict(
        paradigm=ApiParadigm.REST, format=fmt, identity=ApiIdentity(name="Shop"), title="Shop",
        services=[Service(key="orders", name="Orders", operations=list(operations))] if operations else [],
        types=[Type(key="Order", name="Order", kind=TypeKind.RECORD, fields=[
            CanonicalField(key="Order.id", name="id", type=TypeRef(name="string", nullable=False), field_number=1),
        ])],
    )
    defaults.update(kw)
    return CanonicalApi(**defaults)


def _rest_api() -> CanonicalApi:
    return _api(
        _op("GET /orders", http_method="GET", http_path="/orders", extras={"operationId": "listOrders"}),
        _op("POST /orders", http_method="POST", http_path="/orders"),
    )


def _corpus_api(path: Path, fmt: str) -> CanonicalApi:
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


# ===========================================================================
# The warning and the advisory
# ===========================================================================


def test_a_non_workflow_source_is_warned_that_arazzo_captures_workflows_only() -> None:
    root = _items(_rest_api())[""]
    warning = next(item for item in root if item.target_mapping == "API surface → workflows")
    assert warning.kind is LossinessKind.APPROX and warning.severity.value == "warn"
    assert WORKFLOWS_ONLY_WARNING in warning.message


def test_the_advisory_fires_for_a_non_workflow_source() -> None:
    report = compute_lossiness_for_emitter(_rest_api(), ArazzoEmitter())
    advisory = build_export_advisory(report, "Arazzo")
    assert advisory.show and advisory.severity.value == "warn"
    assert advisory.synthesized >= 1 and advisory.dropped >= 1


def test_an_arazzo_source_carries_no_warning() -> None:
    api = _rest_api().model_copy(update={"format": "arazzo"})
    items = _items(api)
    assert "" not in items
    assert _kinds(api, "GET /orders") == {LossinessKind.OK}


# ===========================================================================
# Workflows, steps, near-empty documents
# ===========================================================================


def test_synthesized_workflows_are_named() -> None:
    synth = next(item for item in _items(_rest_api())[""] if item.target_mapping == "service → synthesized workflow")
    assert synth.kind is LossinessKind.SYNTH and "'Orders' becomes a workflow" in synth.message


@pytest.mark.parametrize(
    "operations",
    [
        (),  # a set of types
        (_op("orderPlaced", kind=OperationKind.PUBLISH, channel_ref="orders"),),  # an event API
    ],
    ids=["types-only", "events-only"],
)
def test_a_source_with_nothing_to_sequence_is_reported_near_empty_and_refused(operations) -> None:
    """The preview still says why (near-empty DROP); the export itself is refused (MFX-10.3)."""
    api = _api(*operations, channels=[Channel(key="orders", name="orders", address="orders")])
    near_empty = next(item for item in _items(api)[""] if item.target_mapping == "no operations → near-empty document")
    assert near_empty.kind is LossinessKind.DROP
    reason = ArazzoEmitter.source_unsupported_reason(api)
    assert reason is not None and "at least one operation to sequence" in reason
    with pytest.raises(EmitPreconditionError, match="at least one operation to sequence"):
        ArazzoEmitter().emit(api)


def test_each_operation_becomes_a_step_and_a_made_up_target_is_synthesized() -> None:
    api = _rest_api()
    # Both become steps; the re-import keys them `orders#…`, so each also loses its source key (#7040).
    assert _kinds(api, "GET /orders") == {LossinessKind.APPROX, LossinessKind.DROP}  # names its operationId
    assert _kinds(api, "POST /orders") == {LossinessKind.APPROX, LossinessKind.DROP, LossinessKind.SYNTH}
    step = next(i for i in _items(api)["POST /orders"] if i.kind is LossinessKind.SYNTH)
    assert "operationId is the canonical operation key" in step.message


def test_event_operations_and_channels_are_dropped() -> None:
    api = _api(_op("GET /orders", http_method="GET", http_path="/orders"),
               _op("orderPlaced", kind=OperationKind.PUBLISH, channel_ref="orders"),
               channels=[Channel(key="orders", name="orders", address="orders")])
    assert _kinds(api, "orderPlaced") == {LossinessKind.DROP}
    # The channel shares its key with the service, which becomes a workflow (APPROX, #7040).
    channel = [i for i in _items(api)["orders"] if i.target_mapping == "channel → dropped"]
    assert [i.kind for i in channel] == [LossinessKind.DROP]


# ===========================================================================
# The re-import's own keys are predicted — COA-1.4 (#7040)
# ===========================================================================


def test_a_rekeyed_operation_is_dropped_under_its_old_key_and_synthesized_under_the_new() -> None:
    """The Arazzo importer keys a step `{workflowId}#{stepId}`; the report names both keys."""
    items = _items(_rest_api())
    drop = next(i for i in items["GET /orders"] if i.kind is LossinessKind.DROP)
    assert drop.target_mapping == "GET /orders → orders#GET /orders"
    [synth] = items["orders#GET /orders"]
    assert synth.kind is LossinessKind.SYNTH and "re-imports as 'orders#GET /orders'" in synth.message


def test_an_operation_whose_key_survives_is_not_dropped() -> None:
    """An Arazzo-shaped key (`service#step`) re-imports unchanged, so only the step APPROX is reported."""
    api = _api(_op("orders#list", extras={"stepId": "list", "operationId": "listOrders"}))
    assert _kinds(api, "orders#list") == {LossinessKind.APPROX}


def test_an_operation_that_shares_a_step_id_is_reported_as_not_written() -> None:
    """Step ids are unique in a workflow; the writer keeps the later operation, and the report agrees."""
    first = _op("GET /a", extras={"stepId": "same"})
    second = _op("GET /b", extras={"stepId": "same"})
    api = _api(first, second)
    assert _kinds(api, "GET /a") == {LossinessKind.DROP}
    assert "duplicate step id" in _items(api)["GET /a"][0].target_mapping
    assert LossinessKind.APPROX in _kinds(api, "GET /b")
    document = yaml.safe_load(ArazzoEmitter().emit(api).files[0].content)
    assert [step["operationId"] for step in document["workflows"][0]["steps"]] == ["GET /b"]


def test_a_service_becomes_a_workflow_and_a_service_with_no_step_is_not_written() -> None:
    events = Service(key="events", name="Events", operations=[
        _op("orderPlaced", kind=OperationKind.PUBLISH, channel_ref="orders")])
    api = _rest_api()
    api = api.model_copy(update={"services": [*api.services, events]})
    assert _kinds(api, "orders") == {LossinessKind.APPROX}
    assert _kinds(api, "events") == {LossinessKind.DROP}


def test_agents_and_skills_are_dropped() -> None:
    agent = AgentDescriptor(key="Concierge", name="Concierge", protocol="a2a", skills=[
        AgentSkill(key="Concierge.search", name="search", id="search")])
    api = _rest_api().model_copy(update={"agents": [agent]})
    assert _kinds(api, "Concierge") == {LossinessKind.DROP}
    assert _kinds(api, "Concierge.search") == {LossinessKind.DROP}


def test_an_arazzo_source_gets_no_rekey_or_agent_findings() -> None:
    api = _rest_api().model_copy(update={"format": "arazzo"})
    items = _items(api)
    assert "orders#GET /orders" not in items
    assert "orders" not in items


@pytest.mark.parametrize(
    ("path", "fmt"),
    [
        ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
        ("graphql/06-union-types.graphql", "graphql"),
        ("raml/01-simple-api.raml", "raml"),
    ],
)
def test_corpus_exports_round_trip_with_every_difference_explained(path: str, fmt: str) -> None:
    """Export → re-import → diff: every difference matches a finding, and none over-claims (#7040)."""
    api = _corpus_api(_EXAMPLES / path, fmt)
    report = round_trip_arazzo(api)
    assert report.reimported
    assert report.unexplained == [] and report.overclaims == []


def test_types_are_dropped_with_their_fields() -> None:
    api = _rest_api()
    assert _kinds(api, "Order") == {LossinessKind.DROP}
    assert "Order.id" not in _items(api)


# ===========================================================================
# The writer agrees, and the output stays Arazzo
# ===========================================================================


def test_the_writer_records_the_same_losses() -> None:
    subjects = {loss.subject for loss in ArazzoEmitter().emit(_rest_api()).losses}
    assert {"workflows-only", "workflows-synthesized", "types-not-written"} <= subjects
    assert any(subject.startswith("step-target:") for subject in subjects)


def test_an_arazzo_source_records_no_non_workflow_loss() -> None:
    api = _rest_api().model_copy(update={"format": "arazzo"})
    subjects = {loss.subject for loss in ArazzoEmitter().emit(api).losses}
    assert not subjects & {"workflows-only", "workflows-synthesized", "no-workflow", "types-not-written"}


@pytest.mark.parametrize(
    ("path", "fmt"),
    [
        ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
        ("graphql/06-union-types.graphql", "graphql"),
        ("raml/01-simple-api.raml", "raml"),
    ],
)
def test_corpus_exports_warn_and_still_reimport(path: str, fmt: str) -> None:
    api = _corpus_api(_EXAMPLES / path, fmt)
    root = _items(api)[""]
    assert any(WORKFLOWS_ONLY_WARNING in item.message for item in root)
    validate_arazzo_document(ArazzoEmitter().emit(api).files[0].content)
