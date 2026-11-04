"""Data-lake fidelity packs + validation — MFX-36.4 (#4320).

Pins the rules of the Arrow / Parquet, BigQuery, Spark (the Arrow target's ``output`` modes) and Iceberg
fidelity reports against the issue's acceptance criteria:

* **losses enumerated per mode** —
  * operations → ``DROP`` with the critical types-only advisory (the guard classifies the export
    ``near-empty``),
  * constraints → ``DROP``,
  * unions → ``APPROX`` (Arrow keeps a dense union; BigQuery, Spark and Iceberg flatten it),
  * field IDs → ``SYNTH`` (Iceberg only: the other modes have no field IDs),
  * enumerations → ``APPROX`` (no mode keeps the allowed values);
* **invalid output fails the job** — the gate (pyarrow construction, BigQuery schema rules, Spark's DDL
  grammar, pyiceberg) rejects a broken artifact, and the delivery gate then blocks the job.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from app import import_export_quality_policy as qp
from app.arrow_emitter import ArrowEmitter
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
from app.emitter import EmitResult, EmittedFile, load_builtin_emitters
from app.export_delivery_gate import DeliveryDecision, evaluate_delivery
from app.export_validation import validate_emitted_artifact
from app.export_validation_gate import build_validation_report
from app.fidelity_engine import compute_lossiness_for_emitter
from app.iceberg_emitter import IcebergEmitter
from app.import_source import load_builtin_import_sources
from app.lossiness import LossinessKind, LossinessReport, LossinessSeverity, LossItem
from app.transcoding_guards import TranscodeVerdict, classify_transcode

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"

#: (label, emitter, options) for every mode.
MODES: List[Tuple[str, Any, Dict[str, Any]]] = [
    ("arrow", ArrowEmitter, {}),
    ("bigquery", ArrowEmitter, {"output": "bigquery"}),
    ("spark", ArrowEmitter, {"output": "spark"}),
    ("iceberg", IcebergEmitter, {}),
]
_IDS = [m[0] for m in MODES]


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _report(api: CanonicalApi, emitter: Any, options: Dict[str, Any]) -> LossinessReport:
    return compute_lossiness_for_emitter(api, emitter, options=options or None)


def _items(report: LossinessReport, **match: Any) -> List[LossItem]:
    return [i for i in report.items if all(getattr(i, k) == v for k, v in match.items())]


def _petstore() -> CanonicalApi:
    text = (_EXAMPLES / "openapi/30-openapi-3.0-petstore.yaml").read_text(encoding="utf-8")
    return build_conversion_source({"id": "i", "name": "pets", "source_format": "openapi",
                                    "format_metadata": {"sourceContent": text}}).api


def _f(owner: str, name: str, type_: str, **constraints: Any) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=TypeRef(name=type_),
                          constraints=Constraints(**constraints) if constraints else None)


def _shapes() -> CanonicalApi:
    circle = Type(key="Circle", name="Circle", kind=TypeKind.RECORD, fields=[_f("Circle", "r", "double")])
    square = Type(key="Square", name="Square", kind=TypeKind.RECORD, fields=[_f("Square", "side", "double")])
    shape = Type(key="Shape", name="Shape", kind=TypeKind.UNION, union_members=["Circle", "Square"])
    size = Type(key="Size", name="Size", kind=TypeKind.ENUM, enum_values=[
        EnumValue(key="Size.s", name="s"), EnumValue(key="Size.l", name="l")])
    picture = Type(key="Picture", name="Picture", kind=TypeKind.RECORD, fields=[
        _f("Picture", "shape", "Shape"), _f("Picture", "size", "Size"),
        _f("Picture", "title", "string", min_length=1, max_length=80, pattern="^[A-Z]"),
        _f("Picture", "width", "int32", minimum=1)])
    return CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema", identity=ApiIdentity(name="m"),
                        types=[circle, square, shape, size, picture])


# ===========================================================================
# Losses enumerated per mode
# ===========================================================================


@pytest.mark.parametrize(("mode", "emitter", "options"), MODES, ids=_IDS)
def test_operations_are_dropped_under_the_critical_types_only_advisory(mode: str, emitter: Any,
                                                                      options: Dict[str, Any]) -> None:
    api = _petstore()
    report = _report(api, emitter, options)
    [advisory] = _items(report, construct_key="", target_mapping="types-only")
    assert advisory.kind is LossinessKind.DROP and advisory.severity is LossinessSeverity.CRITICAL
    for operation in api.operations():
        assert [i.kind for i in _items(report, construct_key=operation.key)] == [LossinessKind.DROP], mode
    guard = classify_transcode(api, emitter, report=report)
    assert guard.verdict is TranscodeVerdict.NEAR_EMPTY


@pytest.mark.parametrize(("mode", "emitter", "options"), MODES, ids=_IDS)
def test_constraints_are_dropped(mode: str, emitter: Any, options: Dict[str, Any]) -> None:
    report = _report(_shapes(), emitter, options)
    for key, facets in (("Picture.title", "max_length, min_length, pattern"), ("Picture.width", "minimum")):
        [item] = _items(report, construct_key=key, target_mapping="constraints → dropped")
        assert item.kind is LossinessKind.DROP and facets in item.message, (mode, key)


@pytest.mark.parametrize(("mode", "emitter", "options", "mapping", "needle"), [
    ("arrow", ArrowEmitter, {}, "union → dense union", "dense Arrow union"),
    ("bigquery", ArrowEmitter, {"output": "bigquery"}, "union → RECORD of optional members", "flattened"),
    ("spark", ArrowEmitter, {"output": "spark"}, "union → STRUCT of optional members", "flattened"),
    ("iceberg", IcebergEmitter, {}, "union → struct of optional members", "flattened"),
], ids=_IDS)
def test_unions_are_approximated_per_mode(mode: str, emitter: Any, options: Dict[str, Any], mapping: str,
                                          needle: str) -> None:
    items = _items(_report(_shapes(), emitter, options), construct_key="Shape")
    [item] = [i for i in items if i.kind is LossinessKind.APPROX]
    assert item.target_mapping == mapping and needle in item.message
    # Arrow also measures the round trip: the union reads back under its column's path (DROP, re-keyed).
    assert {i.kind for i in items} <= {LossinessKind.APPROX, LossinessKind.DROP}


@pytest.mark.parametrize(("mode", "emitter", "options"), MODES, ids=_IDS)
def test_enumerations_are_approximated_never_ok(mode: str, emitter: Any, options: Dict[str, Any]) -> None:
    items = _items(_report(_shapes(), emitter, options), construct_key="Size")
    assert items and LossinessKind.OK not in {i.kind for i in items}
    assert any("allowed values" in i.message or "string" in i.message for i in items)


@pytest.mark.parametrize(("mode", "emitter", "options"), MODES, ids=_IDS)
def test_field_ids_are_synthesized_only_where_the_target_has_them(mode: str, emitter: Any,
                                                                  options: Dict[str, Any]) -> None:
    synth = _items(_report(_shapes(), emitter, options), target_mapping="synthesized field ID (persisted)")
    if mode == "iceberg":
        assert {i.construct_key for i in synth} >= {"Picture.shape", "Picture.title", "Circle.r"}
        assert all(i.kind is LossinessKind.SYNTH for i in synth)
    else:
        assert synth == []


def test_each_mode_reports_its_own_type_approximations() -> None:
    def table(report: LossinessReport) -> str:
        return " ".join(i.message for i in _items(report, construct_key="Picture"))

    assert "map" not in table(_report(_shapes(), ArrowEmitter, {"output": "bigquery"}))
    assert "union" in table(_report(_shapes(), ArrowEmitter, {"output": "spark"}))
    assert "union" in table(_report(_shapes(), IcebergEmitter, {}))


@pytest.mark.parametrize(("mode", "emitter", "options"), MODES, ids=_IDS)
def test_every_item_has_a_message(mode: str, emitter: Any, options: Dict[str, Any]) -> None:
    for api in (_shapes(), _petstore()):
        assert all(i.message.strip() for i in _report(api, emitter, options).items)


# ===========================================================================
# Invalid output fails the job
# ===========================================================================


@pytest.fixture
def _no_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qp.db, "get_latest_import_export_quality_policy", lambda _tenant: None)
    monkeypatch.setattr(qp.db, "list_active_import_export_quality_waivers", lambda _tenant, **_kw: [])


def _decision(target: str, result: EmitResult, api: CanonicalApi) -> DeliveryDecision:
    validation = asyncio.run(validate_emitted_artifact(target, result, api=api))
    report = evaluate_delivery(tenant_id="t1", tenant_slug="acme", target_format=target, target_key=target,
                               version_record_id="rev-1", validation=build_validation_report(validation),
                               preserved_percent=100)
    return report.decision


@pytest.mark.parametrize(("target", "path", "content"), [
    ("arrow", "t.arrow.json", '{"schema": {"fields": [{"name": "a", "nullable": true, "type": {"name": "nope"}, '
                              '"children": []}]}}'),
    ("arrow", "t.bigquery.json", '[{"name": "a", "type": "VARCHAR", "mode": "NULLABLE"}]'),
    ("arrow", "t.spark.ddl", "`a` INTT\n"),
    ("iceberg", "t.iceberg.json", '{"type": "struct", "fields": [{"id": 1, "name": "a", "required": true, '
                                  '"type": "int"}, {"id": 1, "name": "b", "required": true, "type": "int"}]}'),
], ids=["arrow-schema", "bigquery", "spark", "iceberg-duplicate-id"])
def test_invalid_output_fails_the_job(_no_policy: None, target: str, path: str, content: str) -> None:
    broken = EmitResult(files=[EmittedFile(path=path, content=content)])
    assert _decision(target, broken, _shapes()) is DeliveryDecision.BLOCK


@pytest.mark.parametrize(("mode", "emitter", "options"), MODES, ids=_IDS)
def test_valid_output_is_not_blocked(_no_policy: None, mode: str, emitter: Any, options: Dict[str, Any]) -> None:
    api = _shapes()
    result = emitter().emit(api, opts=emitter.options_model(**options))
    # No lint report is passed, so the gate may warn; it must not block.
    assert _decision(emitter.key, result, api) is not DeliveryDecision.BLOCK
