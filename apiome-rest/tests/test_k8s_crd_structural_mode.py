"""Kubernetes CRD structural-schema output — MFX-21.6 (#4345).

The CRD output the ticket asks for is the ``k8s-crd`` export target (FMT-2.1, #5419): it inlines every named
type (a structural schema has no ``$ref``), enforces the structural-schema rules, and wraps the root type in
a CustomResourceDefinition with ``group`` / ``kind`` / ``version`` options. These tests pin the ticket's two
acceptance criteria against it, from a JSON Schema source:

* **the CRD passes kubeconform** — the export gate checks the manifest with kubeconform when the toolchain has
  it (:mod:`app.k8s_kubeconform`), after Apiome's structural-schema rules. kubeconform is replayed from
  report samples in ``fixtures/k8s_crd_mode/`` written in the shape of kubeconform 0.7.0's ``-output json``
  (it is not run live here);
* **non-structural constructs are reported APPROX / DROP** — the fidelity report names what the structural
  rules cost (:class:`app.k8s_crd_emitter.K8sCrdFidelityRulePack`): a reference cycle, an unresolved
  reference and the ``spec`` wrapping are ``APPROX``; a ``deprecated`` flag and a ``required`` name with no
  property are ``DROP``. Before MFX-21.6 the report called the same export lossless.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
import yaml

from app import k8s_kubeconform
from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi, CanonicalField, Type, TypeKind, TypeRef
from app.catalog_conversion import build_conversion_source
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_validation import validate_emitted_artifact
from app.k8s_kubeconform import KUBECONFORM_ARGS, read_kubeconform_report, run_kubeconform
from app.k8s_structural_schema import validate_k8s_crd_document
from app.lossiness import LossinessKind
from app.toolchain_runner import ToolExecutionError, ToolNotAvailableError

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "k8s_crd_mode"
_TARGET = "k8s-crd"


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()


def _report(name: str) -> str:
    return (_FIXTURES / f"kubeconform-{name}.json").read_text(encoding="utf-8")


def _widget_api() -> CanonicalApi:
    """The JSON Schema source: a shared ``$ref``, a reference cycle and a ``oneOf``."""
    text = (_FIXTURES / "widget.schema.json").read_text(encoding="utf-8")
    return build_conversion_source(
        {"id": "item-1", "name": "Widget", "source_format": "json-schema", "format_metadata": {"sourceContent": text}}
    ).api


def _emit(api: CanonicalApi, **options: Any) -> Any:
    emitter = get_emitter(_TARGET)
    return emitter().emit(api, opts=coerce_emit_options(emitter, options))


def _crd(result: Any) -> Dict[str, Any]:
    return yaml.safe_load(str(result.files[0].content))


def _validate(result: Any, api: CanonicalApi) -> Any:
    return asyncio.run(validate_emitted_artifact(_TARGET, result, api=api))


def _kubeconform(monkeypatch: pytest.MonkeyPatch, *, available: bool = True, stdout: str = "",
                 exit_code: int = 0, error: Exception | None = None) -> List[Dict[str, Any]]:
    """Stand kubeconform in: ``available`` for the probe, and each run answers ``stdout`` (or raises)."""
    calls: List[Dict[str, Any]] = []

    def _run(key: str, args: Any = (), **kwargs: Any) -> Any:
        calls.append({"key": key, "args": list(args), **kwargs})
        if error is not None:
            raise error
        if exit_code:
            raise ToolExecutionError(key, exit_code, stdout, "")
        return SimpleNamespace(stdout=stdout)

    monkeypatch.setattr(k8s_kubeconform, "kubeconform_available", lambda: available)
    monkeypatch.setattr(k8s_kubeconform, "run_tool_blocking", _run)
    return calls


# ---------------------------------------------------------------------------
# The CRD itself: inline-expanded, structural, wrapped
# ---------------------------------------------------------------------------


def test_a_json_schema_source_exports_a_structural_crd_with_no_ref() -> None:
    result = _emit(_widget_api())
    text = str(result.files[0].content)
    assert "$ref" not in text
    validate_k8s_crd_document(text)
    crd = _crd(result)
    assert (crd["apiVersion"], crd["kind"]) == ("apiextensions.k8s.io/v1", "CustomResourceDefinition")
    schema = crd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]
    # The shared `Owner` definition is expanded in place.
    assert schema["properties"]["spec"]["properties"]["owner"] == {
        "type": "object", "properties": {"team": {"type": "string"}}}


def test_the_group_kind_and_version_options_name_the_crd() -> None:
    crd = _crd(_emit(_widget_api(), group="widgets.acme.io", kind="Widget", version="v1alpha1"))
    assert crd["metadata"]["name"] == "widgets.widgets.acme.io"
    assert crd["spec"]["group"] == "widgets.acme.io"
    assert crd["spec"]["names"]["kind"] == "Widget"
    assert [version["name"] for version in crd["spec"]["versions"]] == ["v1alpha1"]


# ---------------------------------------------------------------------------
# Acceptance 2 — non-structural constructs are reported APPROX / DROP
# ---------------------------------------------------------------------------


def _items(api: CanonicalApi) -> List[Any]:
    return build_export_fidelity(api, get_emitter(_TARGET)).report.items


def _by_mapping(api: CanonicalApi) -> Dict[str, LossinessKind]:
    return {item.target_mapping: item.kind for item in _items(api) if item.target_mapping}


def test_the_expansion_s_semantic_changes_are_approximated() -> None:
    mappings = _by_mapping(_widget_api())
    assert mappings["reference-cycle"] is LossinessKind.APPROX
    assert mappings["unresolved-type-reference"] is LossinessKind.APPROX
    assert mappings["synthesized-spec-wrapper"] is LossinessKind.APPROX


def test_the_report_no_longer_calls_the_export_lossless() -> None:
    summary = build_export_fidelity(_widget_api(), get_emitter(_TARGET)).summary
    assert summary.tier.value != "lossless"
    assert summary.approximated == 3


def _record(name: str, fields: List[CanonicalField], **kwargs: Any) -> Type:
    return Type(key=name, name=name, kind=TypeKind.RECORD, fields=fields, **kwargs)


def _field(name: str, type_name: str | None, **kwargs: Any) -> CanonicalField:
    return CanonicalField(key=f"field.{name}", name=name, type=TypeRef(name=type_name, nullable=True), **kwargs)


def _model(types: List[Type]) -> CanonicalApi:
    return CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema",
                        identity=ApiIdentity(name="Widget"), title="Widget", types=types)


def test_keywords_a_structural_schema_cannot_carry_are_dropped() -> None:
    widget = _record("Widget", [_field("spec", None), _field("legacy", "string", deprecated=True)],
                     extras={"required_names": ["spec", "ghost"]})
    items = _items(_model([widget]))
    kinds = {(item.target_mapping, item.kind) for item in items}
    assert ("deprecated-keyword", LossinessKind.DROP) in kinds
    assert ("required-without-property", LossinessKind.DROP) in kinds
    # The deprecated flag is reported on the field that carried it.
    assert any(item.model_dump()["construct"] == "field.legacy" and item.target_mapping == "deprecated-keyword"
               for item in items)


def test_a_resource_shaped_structural_model_reports_no_structural_loss() -> None:
    """Nothing the structural rules cost, nothing reported: a resource root with plain members."""
    widget = _record("Widget", [_field("spec", None), _field("status", None)])
    mappings = _by_mapping(_model([widget]))
    assert not set(mappings) & set(get_emitter(_TARGET).fidelity_rule_pack()._STRUCTURAL_LOSSES)


def test_the_badge_is_still_computed_without_emitting(monkeypatch: pytest.MonkeyPatch) -> None:
    emitter = get_emitter(_TARGET)
    monkeypatch.setattr(emitter, "emit", lambda *args, **kwargs: pytest.fail("emit must not run"))
    assert build_export_fidelity(_widget_api(), emitter).summary.approximated == 3


# ---------------------------------------------------------------------------
# Acceptance 1 — kubeconform
# ---------------------------------------------------------------------------


def test_a_valid_report_has_no_problems() -> None:
    assert read_kubeconform_report(_report("valid")) == []


def test_an_invalid_resource_lists_each_validation_error_with_its_path() -> None:
    assert read_kubeconform_report(_report("invalid")) == [{
        "status": "statusInvalid", "kind": "CustomResourceDefinition", "name": "widgets.example.com",
        "path": "/spec/names", "message": "/spec/names: missing property 'plural'",
    }]


def test_a_resource_kubeconform_could_not_validate_is_a_problem() -> None:
    problems = read_kubeconform_report(_report("error"))
    assert [(problem["status"], problem["message"]) for problem in problems] == [
        ("statusError", "could not find schema for CustomResourceDefinition")]


@pytest.mark.parametrize("stdout", ["", "   ", "not json", "[]", '{"resources": "x"}'])
def test_output_that_is_not_a_report_is_none(stdout: str) -> None:
    assert read_kubeconform_report(stdout) is None


def test_a_skipped_resource_is_not_a_problem() -> None:
    report = {"resources": [{"kind": "Widget", "status": "statusSkipped"}], "summary": {}}
    assert read_kubeconform_report(json.dumps(report)) == []


def test_run_passes_the_manifest_on_stdin_with_the_strict_json_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _kubeconform(monkeypatch, stdout=_report("valid"))
    assert run_kubeconform("kind: CustomResourceDefinition\n") == []
    assert calls[0]["key"] == "kubeconform"
    assert calls[0]["args"] == list(KUBECONFORM_ARGS) == ["-strict", "-summary", "-output", "json", "-"]
    assert calls[0]["stdin"] == "kind: CustomResourceDefinition\n"


def test_run_reads_the_report_of_a_failing_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """kubeconform exits 1 for an invalid resource; the report is still on stdout."""
    _kubeconform(monkeypatch, stdout=_report("invalid"), exit_code=1)
    assert [problem["path"] for problem in run_kubeconform("x")] == ["/spec/names"]


def test_run_without_a_report_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _kubeconform(monkeypatch, stdout="", exit_code=1)
    with pytest.raises(ValueError):
        run_kubeconform("x")


def test_the_gate_passes_the_crd_kubeconform_accepts(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _widget_api()
    result = _emit(api)
    calls = _kubeconform(monkeypatch, stdout=_report("valid"))
    verdict = _validate(result, api)
    assert verdict.applicable and verdict.validated and verdict.valid, verdict.errors
    assert calls[0]["stdin"] == str(result.files[0].content)


def test_the_gate_rejects_what_kubeconform_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _widget_api()
    _kubeconform(monkeypatch, stdout=_report("invalid"), exit_code=1)
    verdict = _validate(_emit(api), api)
    assert verdict.valid is False
    assert any("missing property 'plural'" in error for error in verdict.errors)


def test_the_gate_rejects_a_kubeconform_that_gives_no_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _widget_api()
    _kubeconform(monkeypatch, error=ToolNotAvailableError("kubeconform", "kubeconform"))
    verdict = _validate(_emit(api), api)
    assert verdict.valid is False
    assert any("kubeconform could not validate the CRD" in error for error in verdict.errors)


def test_without_kubeconform_the_structural_rules_decide(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _widget_api()
    calls = _kubeconform(monkeypatch, available=False)
    verdict = _validate(_emit(api), api)
    assert verdict.valid is True
    assert calls == []


def test_kubeconform_does_not_run_on_a_crd_the_structural_rules_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _widget_api()
    result = _emit(api)
    broken = result.model_copy(update={"files": [result.files[0].model_copy(update={"content": "kind: [\n"})]})
    calls = _kubeconform(monkeypatch, stdout=_report("valid"))
    assert _validate(broken, api).valid is False
    assert calls == []


def test_kubeconform_is_a_bundled_optional_tool() -> None:
    from app.toolchain_packaging import BUNDLED_TOOLS

    tool = next(tool for tool in BUNDLED_TOOLS if tool.key == "kubeconform")
    assert (tool.version, tool.parses_json, tool.env_override_key) == ("0.7.0", False, "APIOME_KUBECONFORM_BIN")
