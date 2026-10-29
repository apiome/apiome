"""Arazzo fidelity pack — MFX-10.2 (#3871).

Arazzo is workflow-only. :class:`app.arazzo_emitter.ArazzoFidelityRulePack` keeps an Arazzo source's
report as the capability rules make it, and for any other (non-workflow) source:

* leads the report with the warning that *this target captures workflows, not the full API
  surface* — and the MFX-2.4 advisory fires;
* marks the workflows synthesized from services (``SYNTH``), or a source with nothing to sequence as
  a near-empty document (``DROP``);
* writes each operation as a step (``APPROX``), with a ``SYNTH`` when its ``operationId`` is made up;
* drops type declarations and channels.

The writer records the same losses, and every corpus export still re-imports as Arazzo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pytest
import yaml

from app.arazzo_emitter import WORKFLOWS_ONLY_WARNING, ArazzoEmitter, validate_arazzo_document
from app.canonical_model import (
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
def test_a_source_with_nothing_to_sequence_is_a_near_empty_document(operations) -> None:
    api = _api(*operations, channels=[Channel(key="orders", name="orders", address="orders")])
    near_empty = next(item for item in _items(api)[""] if item.target_mapping == "no operations → near-empty document")
    assert near_empty.kind is LossinessKind.DROP
    result = ArazzoEmitter().emit(api)
    assert yaml.safe_load(result.files[0].content)["workflows"] == []
    assert "no-workflow" in {loss.subject for loss in result.losses}


def test_each_operation_becomes_a_step_and_a_made_up_target_is_synthesized() -> None:
    api = _rest_api()
    assert _kinds(api, "GET /orders") == {LossinessKind.APPROX}  # it names its own operationId
    assert _kinds(api, "POST /orders") == {LossinessKind.APPROX, LossinessKind.SYNTH}
    step = next(i for i in _items(api)["POST /orders"] if i.kind is LossinessKind.SYNTH)
    assert "operationId is the canonical operation key" in step.message


def test_event_operations_and_channels_are_dropped() -> None:
    api = _api(_op("GET /orders", http_method="GET", http_path="/orders"),
               _op("orderPlaced", kind=OperationKind.PUBLISH, channel_ref="orders"),
               channels=[Channel(key="orders", name="orders", address="orders")])
    assert _kinds(api, "orderPlaced") == {LossinessKind.DROP}
    assert _kinds(api, "orders") == {LossinessKind.DROP}


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
