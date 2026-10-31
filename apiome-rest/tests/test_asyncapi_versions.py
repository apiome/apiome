"""AsyncAPI multi-version output (2.6 / 3.0 / 3.1) — MFX-11.3 (#3876).

``asyncapi_version`` picks the version written: ``3.1`` (native), ``3.0`` and ``2.6``. Pinned against
``fixtures/asyncapi_versions/robot-telemetry-3.1.yaml``, an AsyncAPI 3.1 document using what 3.1 added
over 3.0 (``ros2`` server and operation bindings; a payload ``schemaFormat`` naming 3.1.0):

* **3.0** — :func:`app.asyncapi_downgrade.downgrade_to_asyncapi_30` drops the ``ros2`` bindings and
  non-map example headers and renames 3.1.0 schema formats, each recorded as a loss. Without it the
  document fails the AsyncAPI 3.0 parser (``ros2`` is "not expected"); with it, it parses and
  re-imports;
* **2.6** — runs the 3.0 projection first, so a 2.6 export reports what 3.1 added *and* what 2.x
  cannot carry;
* **the fidelity report** — computed for the chosen version: 3.1 reports no downgrade, 3.0 and 2.6
  report each downgrade loss (``DROP`` / ``APPROX``), so the preview and the export job agree with
  what is written.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict

import pytest

from app.asyncapi_downgrade import ASYNCAPI_30_VERSION, downgrade_to_asyncapi_30
from app.asyncapi_emitter import AsyncApiEmitOptions, AsyncApiEmitter
from app.asyncapi_parser import ASYNCAPI_PARSER_TOOL_KEY, parse_asyncapi
from app.catalog_conversion import build_conversion_source
from app.emitter import LossTracker, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.lossiness import LossinessKind
from app.toolchain_packaging import probe_tool

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "asyncapi_versions" / "robot-telemetry-3.1.yaml"
_PARSER = pytest.mark.skipif(
    not getattr(probe_tool(ASYNCAPI_PARSER_TOOL_KEY), "available", False),
    reason="the bundled @asyncapi/parser toolchain is not installed in this runtime",
)


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()


def _robot() -> Any:
    """The fixture imported as the catalog imports it ($refs resolved, types collected)."""
    return build_conversion_source(
        {"id": "item-1", "name": "robot", "source_format": "asyncapi",
         "format_metadata": {"sourceContent": _FIXTURE.read_text(encoding="utf-8")}}
    ).api


def _emit(api: Any, version: str) -> Any:
    return AsyncApiEmitter().emit(api, opts=AsyncApiEmitOptions(asyncapi_version=version))


def _subjects(result: Any) -> set:
    return {loss.subject for loss in result.losses}


async def _parse(document: Dict[str, Any]) -> Any:
    return await parse_asyncapi(json.dumps(document))


# ===========================================================================
# The version option
# ===========================================================================


def test_the_option_offers_31_30_and_26_with_31_the_default() -> None:
    schema = AsyncApiEmitter.options_schema()["properties"]["asyncapi_version"]
    assert schema["enum"] == ["3.1", "3.0", "2.6"] and schema["default"] == "3.1"
    with pytest.raises(ValueError):
        AsyncApiEmitOptions(asyncapi_version="2.0")


@pytest.mark.parametrize(("version", "declared"), [("3.1", "3.1.0"), ("3.0", "3.0.0"), ("2.6", "2.6.0")])
def test_each_version_is_declared_on_the_document(version: str, declared: str) -> None:
    assert _emit(_robot(), version).document["asyncapi"] == declared


# ===========================================================================
# 3.1 → 3.0
# ===========================================================================


def test_31_keeps_what_31_added() -> None:
    document = _emit(_robot(), "3.1").document
    assert "ros2" in document["servers"]["robot"]["bindings"]
    assert "ros2" in document["operations"]["publishReading"]["bindings"]


def test_30_drops_the_ros2_bindings_and_renames_the_schema_format() -> None:
    result = _emit(_robot(), "3.0")
    document = result.document
    assert document["asyncapi"] == ASYNCAPI_30_VERSION
    # The bindings were only ros2: the emptied Bindings Objects are left out.
    assert "bindings" not in document["servers"]["robot"]
    assert "bindings" not in document["operations"]["publishReading"]
    payload = document["channels"]["telemetry"]["messages"]["Reading"]["payload"]
    assert payload["schemaFormat"] == "application/vnd.aai.asyncapi+json;version=3.0.0"
    pointers = sorted(loss.pointer for loss in result.losses if loss.subject == "asyncapi30-binding")
    assert pointers == ["/operations/publishReading/bindings/ros2", "/servers/robot/bindings/ros2"]
    assert "asyncapi30-schema-format" in _subjects(result)


def test_the_30_projection_drops_non_map_example_headers_and_keeps_other_bindings() -> None:
    document = {
        "asyncapi": "3.1.0",
        "servers": {"s": {"host": "h", "protocol": "kafka", "bindings": {"kafka": {"x": 1}, "ros2": {}}}},
        "channels": {"c": {"messages": {"m": {"examples": [{"headers": "trace", "payload": 1},
                                                            {"headers": {"a": 1}}]}}}},
        "components": {
            "operationBindings": {"ob": {"ros2": {"role": "publisher"}}},
            "serverBindings": {"sb": {"ros2": {}, "mqtt": {}}},
            "messageTraits": {"t": {"examples": [{"headers": ["x"]}]}},
        },
    }
    original = copy.deepcopy(document)
    losses = LossTracker()
    result = downgrade_to_asyncapi_30(document, losses)
    assert document == original  # the input is not modified
    assert result["servers"]["s"]["bindings"] == {"kafka": {"x": 1}}
    assert result["components"]["operationBindings"]["ob"] == {}
    assert result["components"]["serverBindings"]["sb"] == {"mqtt": {}}
    examples = result["channels"]["c"]["messages"]["m"]["examples"]
    assert examples == [{"payload": 1}, {"headers": {"a": 1}}]
    assert result["components"]["messageTraits"]["t"]["examples"] == [{}]
    records = losses.records()
    assert sorted(loss.pointer for loss in records if loss.subject == "asyncapi30-example-headers") == [
        "/channels/c/messages/m/examples/0/headers", "/components/messageTraits/t/examples/0/headers"]
    assert len([loss for loss in records if loss.subject == "asyncapi30-binding"]) == 3


def test_a_document_with_nothing_31_only_loses_nothing_in_30() -> None:
    losses = LossTracker()
    result = downgrade_to_asyncapi_30({"asyncapi": "3.1.0", "channels": {"c": {"address": "c"}}}, losses)
    assert result == {"asyncapi": "3.0.0", "channels": {"c": {"address": "c"}}}
    assert losses.records() == []


@_PARSER
async def test_without_the_projection_a_30_document_fails_the_parser() -> None:
    document = _emit(_robot(), "3.1").document
    document["asyncapi"] = "3.0.0"
    result = await _parse(document)
    assert not result.ok
    assert any("ros2" in d.message for d in result.diagnostics if d.severity == "error")


@_PARSER
@pytest.mark.parametrize("version", ["3.1", "3.0", "2.6"])
async def test_every_version_parses(version: str) -> None:
    result = await _parse(_emit(_robot(), version).document)
    assert result.ok, [d for d in result.diagnostics if d.severity == "error"]


@_PARSER
async def test_a_30_export_passes_the_export_gate_and_re_imports() -> None:
    api = _robot()
    result = _emit(api, "3.0")
    verdict = await validate_emitted_artifact("asyncapi-3", result, api=api, options={"asyncapi_version": "3.0"})
    assert verdict.validated and verdict.valid, verdict.errors
    back = build_conversion_source(
        {"id": "item-2", "name": "robot", "source_format": "asyncapi",
         "format_metadata": {"sourceContent": json.dumps(result.document)}}
    ).api
    assert sorted(op.key for op in back.operations()) == sorted(op.key for op in api.operations())
    assert [c.address for c in back.channels] == [c.address for c in api.channels]


# ===========================================================================
# 2.6: the 3.0 projection first
# ===========================================================================


def test_26_reports_what_31_added_and_what_2x_cannot_carry() -> None:
    result = _emit(_robot(), "2.6")
    subjects = _subjects(result)
    assert {"asyncapi30-binding", "asyncapi30-schema-format"} <= subjects
    assert any(subject.startswith("asyncapi2-") for subject in subjects)
    assert "bindings" not in result.document["servers"]["robot"]


# ===========================================================================
# The fidelity report follows the chosen version
# ===========================================================================


def _downgrade_items(version: str):
    report = compute_lossiness_for_emitter(_robot(), AsyncApiEmitter, options={"asyncapi_version": version})
    return [item for item in report.items
            if (item.target_mapping or "").startswith(("asyncapi30-", "asyncapi2-"))]


def test_the_31_report_has_no_downgrade() -> None:
    assert _downgrade_items("3.1") == []


def test_the_30_report_lists_each_downgrade_loss() -> None:
    items = _downgrade_items("3.0")
    drops = [i for i in items if i.target_mapping == "asyncapi30-binding"]
    renames = [i for i in items if i.target_mapping == "asyncapi30-schema-format"]
    assert len(drops) == 2 and all(i.kind is LossinessKind.DROP for i in drops)
    assert len(renames) == 1 and renames[0].kind is LossinessKind.APPROX
    assert any("/servers/robot/bindings" in i.message for i in drops)


def test_the_26_report_also_lists_the_2x_losses() -> None:
    mappings = {item.target_mapping for item in _downgrade_items("2.6")}
    assert "asyncapi30-binding" in mappings and any(m.startswith("asyncapi2-") for m in mappings)


def test_the_preview_tier_follows_the_chosen_version() -> None:
    api = _robot()
    tiers = {version: build_export_fidelity(api, AsyncApiEmitter, options={"asyncapi_version": version})
             for version in ("3.1", "3.0")}
    assert tiers["3.1"].summary.tier.value == "lossless"
    assert tiers["3.0"].summary.tier.value == "lossy"
    assert tiers["3.0"].summary.dropped == tiers["3.1"].summary.dropped + 2


def test_invalid_options_fall_back_to_the_31_report() -> None:
    report = compute_lossiness_for_emitter(_robot(), AsyncApiEmitter, options={"asyncapi_version": "1.0"})
    assert not [i for i in report.items if (i.target_mapping or "").startswith("asyncapi30-")]
