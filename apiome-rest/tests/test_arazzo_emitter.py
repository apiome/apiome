"""Arazzo emitter contract — MFX-10.1 (#3870).

Pins the standard emitter contract for the ``arazzo`` target end to end, through the same
seams every export takes:

* **registry** — the emitter self-registers under ``arazzo`` and is listed as an available,
  single-file export target;
* **emit** — a workflow model becomes one deterministic ``*.arazzo.yaml`` document with
  provenance;
* **fidelity report** — the dispatch attaches the MFX-2.2 report: an Arazzo source exports
  without a ``DROP``, a plain REST source is warned that *this target captures workflows, not
  the full API surface*;
* **emitted-output validation** — the MFX-5.1 gate re-parses the artifact and passes it;
* **round trip** — every corpus workflow re-imports to the same canonical model (the IXH-1.7
  matrix cell passes).

The deeper behaviour is pinned elsewhere: the fidelity pack in ``test_arazzo_fidelity_pack.py``
(MFX-10.2) and version selection in ``test_arazzo_1_1.py`` (FMT-3.1).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from app.arazzo_emitter import WORKFLOWS_ONLY_WARNING, ArazzoEmitter
from app.arazzo_import_source import ArazzoImportSource
from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi, Operation, OperationKind, Service
from app.emitter import describe_emit_targets, get_emitter, load_builtin_emitters
from app.export_dispatch import dispatch_from_source
from app.export_source import ExportSource
from app.export_validation import validate_emitted_artifact
from app.import_source import canonical_diff, load_builtin_import_sources
from app.lossiness import LossinessKind
from app.roundtrip_matrix import MatrixCellStatus, production_emit_targets, run_roundtrip

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "arazzo"

#: The corpus workflows the round-trip fixtures cover (``negative/`` holds invalid documents).
_CORPUS = sorted(p.name for p in _EXAMPLES.glob("*.yaml")) if _EXAMPLES.is_dir() else []


@pytest.fixture(autouse=True)
def _registries() -> None:
    """Emitters + import adapters registered for every test."""
    load_builtin_emitters()
    load_builtin_import_sources()


def _import(name: str) -> CanonicalApi:
    """Import one corpus workflow through the real Arazzo adapter."""
    path = _EXAMPLES / name
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    adapter = ArazzoImportSource()
    native = adapter.parse(path.read_text(encoding="utf-8"), source_label=name)
    return adapter.normalize(native, include_raw=False)


def _rest_api() -> CanonicalApi:
    """A plain REST model with no workflow of its own."""
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="Shop"),
        title="Shop",
        services=[
            Service(
                key="orders",
                name="Orders",
                operations=[
                    Operation(
                        key="GET /orders",
                        name="listOrders",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="GET",
                        http_path="/orders",
                        extras={"operationId": "listOrders"},
                    )
                ],
            )
        ],
    )


def _source(api: CanonicalApi) -> ExportSource:
    return ExportSource(api=api, artifact_id="artifact-1", version_record_id="rev-1", version_label="1.0.0")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_emitter_is_registered_as_a_single_file_target() -> None:
    assert get_emitter("arazzo") is ArazzoEmitter
    [target] = [t for t in describe_emit_targets() if t.descriptor.key == "arazzo"]
    assert target.descriptor.format == "arazzo"
    assert target.descriptor.available is True
    assert target.descriptor.multi_file is False


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _CORPUS)
def test_emit_writes_one_deterministic_arazzo_document(name: str) -> None:
    api = _import(name)
    first = ArazzoEmitter().emit(api)
    second = ArazzoEmitter().emit(api)

    [emitted] = first.files
    assert emitted.path.endswith(".arazzo.yaml")
    assert emitted.media_type == "application/yaml"
    assert emitted.content == second.files[0].content
    document = yaml.safe_load(emitted.content)
    assert str(document["arazzo"]).startswith("1.")
    assert document["workflows"]
    assert first.provenance


def test_a_rest_source_emits_a_synthesized_workflow() -> None:
    document = yaml.safe_load(ArazzoEmitter().emit(_rest_api()).files[0].content)
    [workflow] = document["workflows"]
    assert [step.get("operationId") for step in workflow["steps"]] == ["listOrders"]


# ---------------------------------------------------------------------------
# Fidelity report (attached by the dispatch)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _CORPUS)
def test_an_arazzo_source_exports_without_a_drop(name: str) -> None:
    dispatch = dispatch_from_source(_source(_import(name)), "arazzo")
    assert dispatch.emit is not None
    assert dispatch.fidelity.report.kind_counts.get(LossinessKind.DROP.value, 0) == 0


def test_a_rest_source_is_warned_that_arazzo_captures_workflows_only() -> None:
    dispatch = dispatch_from_source(_source(_rest_api()), "arazzo", confirm=True)
    messages = [item.message for item in dispatch.fidelity.report.items]
    assert any(WORKFLOWS_ONLY_WARNING in message for message in messages)
    assert dispatch.fidelity.advisory.show is True


# ---------------------------------------------------------------------------
# Emitted-output validation (MFX-5.1 gate)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _CORPUS)
def test_emitted_document_passes_the_validation_gate(name: str) -> None:
    api = _import(name)
    verdict = asyncio.run(validate_emitted_artifact("arazzo", ArazzoEmitter().emit(api), api=api))
    assert verdict.applicable and verdict.validated and verdict.valid, verdict.errors


def test_a_rest_export_also_passes_the_validation_gate() -> None:
    api = _rest_api()
    verdict = asyncio.run(validate_emitted_artifact("arazzo", ArazzoEmitter().emit(api), api=api))
    assert verdict.valid, verdict.errors


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _CORPUS)
def test_corpus_workflow_round_trips_to_the_same_model(name: str) -> None:
    api = _import(name)
    adapter = ArazzoImportSource()
    content = ArazzoEmitter().emit(api).files[0].content
    reimported = adapter.normalize(adapter.parse(content, source_label="reimport"), include_raw=False)
    assert canonical_diff(api, reimported).is_empty


@pytest.mark.parametrize("name", _CORPUS)
def test_roundtrip_matrix_cell_passes(name: str) -> None:
    [target] = [t for t in production_emit_targets() if t.descriptor.key == "arazzo"]
    cell = run_roundtrip(_import(name), target, source_format="arazzo")
    assert cell.status is MatrixCellStatus.PASS, cell.reason
