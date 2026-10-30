"""FlatBuffers and Cap'n Proto fidelity packs and compile validation — MFX-30.3 (#4180).

Covers:

* **constraint text** (:mod:`app.constraint_text`) — every facet as a phrase, width formats left out;
* **FlatBuffers** — constraints written as a ``//`` comment (``APPROX``; a ``DROP`` with comments off),
  maps as key/value entry vectors (``APPROX``), field ids the source does not give (``SYNTH``; a ``.fbs``
  source keeps its own), operations and channels a critical ``DROP`` with the root types-only advisory;
* **Cap'n Proto** — an operation as an interface method (``APPROX``) with its synthesized ordinal
  (``SYNTH``) and dropped errors, constraints as a ``#`` comment, maps as entry lists, the synthesized file
  id at the root; a ``.capnp`` source reports none of the synthesis;
* **the report matches the export** — every writer loss the packs map is in the report on its construct;
* **compile validation** — a ``flatc`` / ``capnp`` error is a finding with the file, line, column and rule,
  and non-compiling output fails the export job. Both compilers are stood in (the image bundles them; the
  real-compiler tests live in the emitters' own test files).
"""

from __future__ import annotations

from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
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
from app.capnproto_compile import CapnpCompileError
from app.capnproto_emitter import CapnpEmitOptions, CapnpEmitter, CapnpFidelityRulePack
from app.capnproto_normalizer import CapnpNormalizer
from app.capnproto_parser import parse_capnproto
from app.constraint_text import constraint_comment, constraint_phrases
from app.export_job_engine import ExportJobStartRequest, schedule_export_job
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.flatbuffers_compile import FlatcCompileError
from app.flatbuffers_emitter import FlatBuffersEmitOptions, FlatBuffersEmitter, FlatBuffersFidelityRulePack
from app.import_source import get_import_source
from app.lossiness import LossinessKind, LossinessSeverity

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


# ===========================================================================
# Helpers
# ===========================================================================


def _field(owner: str, name: str, ref: TypeRef, **kw) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=ref, **kw)


def _shop(*, services: List[Service] = (), channels: List[Channel] = ()) -> CanonicalApi:
    """A converted model: constrained fields, a map, no ids or ordinals."""
    o = "Order"
    return CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA, format="openapi", identity=ApiIdentity(name="Shop"),
        types=[
            Type(key=o, name="Order", kind=TypeKind.RECORD, fields=[
                _field(o, "id", TypeRef(name="i64"), constraints=Constraints(format="int64")),
                _field(o, "qty", TypeRef(name="i32"), constraints=Constraints(minimum=1, maximum=100)),
                _field(o, "sku", TypeRef(name="string"),
                       constraints=Constraints(max_length=12, pattern="^[A-Z]{3}-[0-9]+$")),
                _field(o, "email", TypeRef(name="string"), constraints=Constraints(format="email")),
                _field(o, "tags", TypeRef(name="Tags")),
            ]),
            Type(key="Tags", name="Tags", kind=TypeKind.MAP, key_type=TypeRef(name="string"),
                 value_type=TypeRef(name="string")),
        ],
        services=list(services), channels=list(channels),
    )


def _service() -> Service:
    return Service(key="Orders", name="Orders", operations=[
        Operation(key="GET /orders/{id}", name="getOrder", kind=OperationKind.REQUEST_RESPONSE,
                  messages=[Message(key="GET#response.200", role=MessageRole.RESPONSE, payload=TypeRef(name="Order")),
                            Message(key="GET#response.404", role=MessageRole.ERROR)]),
    ])


def _report(api: CanonicalApi, emitter):
    return compute_lossiness_for_emitter(api, emitter)


def _items(report, key: str, mapping: str):
    return [i for i in report.items if i.construct_key == key and i.target_mapping == mapping]


def _one(report, key: str, mapping: str):
    items = _items(report, key, mapping)
    assert len(items) == 1, (key, mapping, [(i.construct_key, i.target_mapping) for i in report.items])
    return items[0]


def _fbs_item(name: str) -> CanonicalApi:
    adapter = get_import_source("flatbuffers")
    path = _EXAMPLES / "flatbuffers" / name
    return adapter.normalize(adapter.parse(path.read_text(), source_label=path.name), include_raw=True)


def _capnp_item(name: str) -> CanonicalApi:
    return CapnpNormalizer().normalize(parse_capnproto((_EXAMPLES / "capnproto" / name).read_text(encoding="utf-8")))


# ===========================================================================
# Constraint text
# ===========================================================================


def test_every_constraint_is_a_phrase_and_width_formats_are_left_out() -> None:
    c = Constraints(minimum=1.0, exclusive_maximum=10, multiple_of=0.5, min_length=2, max_length=40, min_items=1,
                    max_items=5, unique_items=True, pattern="^a  b$", enum=["x", "y"], format="email")
    assert constraint_phrases(c) == [">= 1", "< 10", "multiple of 0.5", "min length 2", "max length 40",
                                     "min items 1", "max items 5", "unique items", "pattern ^a b$", "one of: x, y",
                                     "format email"]
    assert constraint_comment(Constraints(minimum=1, maximum=3)) == "constraints: >= 1; <= 3"
    assert constraint_comment(Constraints(format="int32")) is None
    assert constraint_comment(None) is None and constraint_phrases(Constraints()) == []


# ===========================================================================
# FlatBuffers
# ===========================================================================


def test_flatbuffers_writes_constraints_as_comments_and_reports_them() -> None:
    result = FlatBuffersEmitter().emit(_shop())
    text = result.files[0].content
    assert "  // constraints: >= 1; <= 100\n  qty: int" in text
    assert "  // constraints: max length 12; pattern ^[A-Z]{3}-[0-9]+$\n  sku: string" in text
    assert "// constraints: format email" in text
    assert "format int64" not in text  # the width is the type
    report = _report(_shop(), FlatBuffersEmitter)
    qty = _one(report, "Order.qty", "constraints-as-comment")
    assert (qty.kind, qty.severity) == (LossinessKind.APPROX, LossinessSeverity.WARN)
    assert "nothing checks" in qty.message and ">= 1; <= 100" in qty.message
    assert not _items(report, "Order.id", "constraints-as-comment")
    # The capability pack's generic "constraints → doc comment" is gone: the writer says what it wrote.
    assert not [i for i in report.items if i.target_mapping == "constraints → doc comment"]


def test_flatbuffers_without_comments_drops_constraints() -> None:
    result = FlatBuffersEmitter().emit(_shop(), opts=FlatBuffersEmitOptions(include_comments=False))
    assert "constraints:" not in result.files[0].content
    assert {(loss.subject, loss.pointer) for loss in result.losses} >= {("constraints-dropped", "Order.qty")}


def test_flatbuffers_maps_and_field_ids() -> None:
    report = _report(_shop(), FlatBuffersEmitter)
    entries = _one(report, "Tags", "map-as-vector")
    assert entries.kind is LossinessKind.APPROX
    for name in ("id", "qty", "sku", "email", "tags"):
        item = _one(report, f"Order.{name}", "synthesized-field-id")
        assert (item.kind, item.severity) == (LossinessKind.SYNTH, LossinessSeverity.INFO)
    assert "id: 1" in _one(report, "Order.qty", "synthesized-field-id").message


@pytest.mark.parametrize("name", ["01-monster.fbs", "06-telemetry.fbs"])
def test_a_flatbuffers_source_keeps_its_ids(name: str) -> None:
    api = _fbs_item(name)
    report = _report(api, FlatBuffersEmitter)
    assert not [i for i in report.items if i.target_mapping == "synthesized-field-id"]
    assert not any(loss.subject == "synthesized-field-id" for loss in FlatBuffersEmitter().emit(api).losses)


def test_flatbuffers_drops_operations_and_channels_with_the_types_only_advisory() -> None:
    api = _shop(services=[_service()], channels=[Channel(key="orders", name="orders", address="orders")])
    report = _report(api, FlatBuffersEmitter)
    advisory = _one(report, "", "types-only")
    assert (advisory.kind, advisory.severity) == (LossinessKind.DROP, LossinessSeverity.CRITICAL)
    for key in ("GET /orders/{id}", "orders"):
        (item,) = [i for i in report.items if i.construct_key == key]
        assert (item.kind, item.severity) == (LossinessKind.DROP, LossinessSeverity.CRITICAL)


# ===========================================================================
# Cap'n Proto
# ===========================================================================


def test_capnp_operations_are_approximated_as_interface_methods() -> None:
    api = _shop(services=[_service()])
    text = CapnpEmitter().emit(api).files[0].content
    assert "getOrder @0" in text
    report = _report(api, CapnpEmitter)
    method = _one(report, "GET /orders/{id}", "operation-as-method")
    assert (method.kind, method.severity) == (LossinessKind.APPROX, LossinessSeverity.WARN)
    assert "'getOrder' @0" in method.message and "HTTP method and path" in method.message
    assert _one(report, "GET /orders/{id}", "synthesized-ordinal").kind is LossinessKind.SYNTH
    assert _one(report, "GET /orders/{id}", "errors-dropped").kind is LossinessKind.DROP


def test_capnp_constraints_maps_ordinals_and_file_id() -> None:
    text = CapnpEmitter().emit(_shop()).files[0].content
    assert "  # constraints: >= 1; <= 100\n  qty @1 :Int32;" in text
    report = _report(_shop(), CapnpEmitter)
    assert _one(report, "Order.qty", "constraints-as-comment").kind is LossinessKind.APPROX
    assert _one(report, "Tags", "map-as-entry-list").kind is LossinessKind.APPROX
    assert _one(report, "Order.sku", "synthesized-ordinal").kind is LossinessKind.SYNTH
    file_id = _one(report, "", "synthesized-file-id")
    assert (file_id.kind, file_id.severity) == (LossinessKind.SYNTH, LossinessSeverity.INFO)
    assert not [i for i in report.items if i.target_mapping in ("constraints → doc comment",
                                                                 "synthesized field number")]


def test_capnp_without_comments_drops_constraints() -> None:
    result = CapnpEmitter().emit(_shop(), opts=CapnpEmitOptions(include_comments=False))
    assert "constraints:" not in result.files[0].content
    assert ("constraints-dropped", "Order.qty") in {(loss.subject, loss.pointer) for loss in result.losses}


def test_a_capnp_source_reports_no_synthesis() -> None:
    api = _capnp_item("06-task-queue.capnp")
    assert api.services, "the fixture declares an interface"
    report = _report(api, CapnpEmitter)
    synthesized = {"operation-as-method", "synthesized-ordinal", "synthesized-file-id"}
    assert not [i for i in report.items if i.target_mapping in synthesized]


# ===========================================================================
# The report matches the export
# ===========================================================================


@pytest.mark.parametrize(("emitter", "pack"), [(FlatBuffersEmitter, FlatBuffersFidelityRulePack),
                                               (CapnpEmitter, CapnpFidelityRulePack)])
def test_every_mapped_writer_loss_is_in_the_report(emitter, pack) -> None:
    api = _shop(services=[_service()])
    report = _report(api, emitter)
    reported = {(i.target_mapping, i.message) for i in report.items}
    for loss in emitter().emit(api).losses:
        if loss.subject in pack._WRITER_LOSSES:
            assert (loss.subject, loss.detail) in reported, loss


# ===========================================================================
# Compile validation
# ===========================================================================


async def test_a_flatc_error_is_a_finding_with_its_file_and_position() -> None:
    error = FlatcCompileError("x", diagnostics=["error: /tmp/w/Shop.fbs:7: 12: error: unknown type: Foo"])
    with patch("app.flatbuffers_compile.flatc_available", return_value=True), \
            patch("app.flatbuffers_compile.compile_fbs_schema", side_effect=error):
        verdict = await validate_emitted_artifact("flatbuffers", FlatBuffersEmitter().emit(_shop()), api=_shop())
    assert verdict.failed
    (finding,) = verdict.findings
    assert (finding.file, finding.line, finding.column, finding.keyword) == ("Shop.fbs", 7, 12, "flatc.compile")
    assert finding.message.endswith("unknown type: Foo")


async def test_a_capnp_error_is_a_finding_with_its_file_and_position() -> None:
    error = CapnpCompileError("x", diagnostics=["Shop.capnp:4:3: error: Parse error.", "Shop.capnp:9:1: error: x"])
    with patch("app.capnproto_compile.compile_capnp_schema", side_effect=error):
        verdict = await validate_emitted_artifact("capnproto", CapnpEmitter().emit(_shop()), api=_shop())
    assert verdict.failed
    assert [(f.file, f.line, f.column, f.keyword) for f in verdict.findings] == [
        ("Shop.capnp", 4, 3, "capnp.compile"), ("Shop.capnp", 9, 1, "capnp.compile")]


@pytest.mark.parametrize(("target", "emit"), [
    ("flatbuffers", lambda: FlatBuffersEmitter().emit(_shop())),
    ("capnproto", lambda: CapnpEmitter().emit(_shop())),
])
async def test_non_compiling_output_fails_the_export_job(target: str, emit) -> None:
    """MFX-30.3 acceptance: output the compiler rejects fails the job, carrying the compiler's error."""
    from test_export_job_engine import TENANT_ID, TENANT_SLUG, _source, _wait_terminal

    flatc_error = FlatcCompileError("x", diagnostics=["error: Shop.fbs:3: 1: error: expecting: ;"])
    capnp_error = CapnpCompileError("x", diagnostics=["Shop.capnp:3:1: error: Parse error."])
    request = ExportJobStartRequest(artifact="artifact-1", target=target, confirm=True)
    with patch("app.export_job_engine.load_export_source", return_value=_source()), \
            patch("app.export_job_engine.emit_canonical", side_effect=lambda *a, **k: emit()), \
            patch("app.flatbuffers_compile.flatc_available", return_value=True), \
            patch("app.flatbuffers_compile.compile_fbs_schema", side_effect=flatc_error), \
            patch("app.capnproto_compile.compile_capnp_schema", side_effect=capnp_error):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "failed"
    assert status["error"]["code"] == "EMITTED_ARTIFACT_INVALID"
    finding = status["error"]["context"]["findings"][0]
    assert finding["keyword"] == ("flatc.compile" if target == "flatbuffers" else "capnp.compile")
    assert finding["line"] == 3
