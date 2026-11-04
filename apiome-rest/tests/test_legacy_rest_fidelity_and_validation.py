"""WADL & Google API Discovery fidelity packs + validation — MFX-29.3 (#4175).

Covers the acceptance criterion — **event/RPC sources warn REST-only; invalid output fails the job**:

* **REST only** — a GraphQL, RPC, event or data-schema source gets ``"WADL captures REST only"`` /
  ``"Google API Discovery captures REST only"`` at the root of its fidelity report, in the RAML wording family
  (:func:`app.fidelity_rulepack.rest_only_advisory`, which the RAML pack now uses too): a ``DROP`` naming the
  operations and channels that are not written, critical when only the types are, or an ``APPROX`` when every
  operation has an HTTP binding; a REST source gets none;
* **validation** — the export gate (:func:`app.export_validation.validate_emitted_artifact`) checks a WADL export
  against the W3C WADL schema, its grammars, its representation elements and a re-import
  (:mod:`app.wadl_validation`), and a Discovery export against the Discovery metaschema, the document rules and a
  re-import (:mod:`app.discovery_validation`); every corpus export passes, every broken one is rejected with its
  rule, and a broken artifact fails the export job (``EMITTED_ARTIFACT_INVALID``) before delivery.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List
from unittest.mock import patch

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.discovery_emitter import DiscoveryEmitter
from app.emitter import EmitResult, EmittedFile, load_builtin_emitters
from app.export_job_engine import ExportJobStartRequest, schedule_export_job
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.fidelity_rulepack import rest_only_advisory
from app.import_source import load_builtin_import_sources
from app.lossiness import LossinessKind, LossinessSeverity
from app.raml_emitter import RamlEmitter
from app.wadl_emitter import WadlEmitOptions, WadlEmitter
from app.wadl_validation import check_emitted_wadl

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_WARNINGS = {"wadl": "WADL captures REST only", "discovery": "Google API Discovery captures REST only"}
_EMITTERS = {"wadl": WadlEmitter, "discovery": DiscoveryEmitter}

#: Corpus sources the gate must pass, of every paradigm (each imports without an optional toolchain).
GATE_CORPUS = [
    ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    ("openapi/22-advanced-oneof-polymorphism.yaml", "openapi"),
    ("openapi/07-nullable-types.yaml", "openapi"),
    ("graphql/06-union-types.graphql", "graphql"),
    ("wsdl/02-order-service.wsdl", "wsdl"),
    ("json-schema/03-multiple-defs.json", "json-schema"),
    *[(f"wadl/{p.name}", "wadl") for p in sorted((_EXAMPLES / "wadl").glob("*.wadl"))],
    *[(f"discovery/{p.name}", "discovery") for p in sorted((_EXAMPLES / "discovery").glob("*.json"))],
]


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _load(path: str, fmt: str) -> CanonicalApi:
    file = _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source({"id": "i", "name": file.stem, "source_format": fmt,
                                    "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}).api


def _widget() -> Type:
    return Type(key="Widget", name="Widget", kind=TypeKind.RECORD,
                fields=[CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string", nullable=False))])


def _api(paradigm: ApiParadigm, *operations: Operation) -> CanonicalApi:
    return CanonicalApi(paradigm=paradigm, format="test", identity=ApiIdentity(name="Widgets"), title="Widgets",
                        services=[Service(key="Widgets", name="Widgets", operations=list(operations))],
                        types=[_widget()])


def _rpc(name: str) -> Operation:
    return Operation(key=name, name=name, kind=OperationKind.REQUEST_RESPONSE)


def _http(method: str, path: str) -> Operation:
    return Operation(key=f"{method} {path}", name=f"{method.lower()}Widget", kind=OperationKind.REQUEST_RESPONSE,
                     http_method=method, http_path=path)


def _advisories(api: CanonicalApi, key: str) -> List[Any]:
    report = compute_lossiness_for_emitter(api, _EMITTERS[key](), options={})
    return [item for item in report.items if _WARNINGS[key] in item.message]


# ===========================================================================
# REST only
# ===========================================================================


@pytest.mark.parametrize("key", ["wadl", "discovery"])
@pytest.mark.parametrize(("path", "fmt", "paradigm"), [
    ("asyncapi/02-order-events-3.0.yaml", "asyncapi", "event"),
    ("graphql/06-union-types.graphql", "graphql", "graph"),
])
def test_event_and_graph_sources_warn_rest_only(key: str, path: str, fmt: str, paradigm: str) -> None:
    [advisory] = _advisories(_load(path, fmt), key)
    assert advisory.construct_key == "" and advisory.kind is LossinessKind.DROP
    assert advisory.severity is LossinessSeverity.CRITICAL
    assert f"this {paradigm} API reads back as a REST API" in advisory.message
    assert advisory.message.endswith("are not written; only its types are exported")


@pytest.mark.parametrize("key", ["wadl", "discovery"])
def test_an_rpc_source_warns_rest_only_with_its_operations(key: str) -> None:
    [advisory] = _advisories(_api(ApiParadigm.RPC, _rpc("GetWidget"), _rpc("ListWidgets")), key)
    assert advisory.kind is LossinessKind.DROP and advisory.severity is LossinessSeverity.CRITICAL
    label = "WADL" if key == "wadl" else "Google API Discovery"
    place = "an HTTP resource" if key == "wadl" else "an HTTP method"
    assert advisory.message == (f"{label}: {label} captures REST only; this rpc API reads back as a REST API, and 2 "
                                f"operation(s) {label} cannot place on {place} are not written; only its types are "
                                "exported")
    assert advisory.target_mapping == "rpc → REST"


@pytest.mark.parametrize("key", ["wadl", "discovery"])
def test_some_operations_written_is_a_warning_not_critical(key: str) -> None:
    [advisory] = _advisories(_api(ApiParadigm.RPC, _rpc("GetWidget"), _http("POST", "/widgets")), key)
    assert advisory.kind is LossinessKind.DROP and advisory.severity is LossinessSeverity.WARN
    assert "1 operation(s)" in advisory.message and "only its types" not in advisory.message


@pytest.mark.parametrize("key", ["wadl", "discovery"])
def test_every_operation_bound_to_http_only_changes_the_paradigm(key: str) -> None:
    [advisory] = _advisories(_api(ApiParadigm.RPC, _http("GET", "/widgets/{id}")), key)
    assert advisory.kind is LossinessKind.APPROX
    written_as = "HTTP resources" if key == "wadl" else "HTTP methods"
    assert f"is written as {written_as} and reads back as a REST API" in advisory.message


@pytest.mark.parametrize("key", ["wadl", "discovery"])
@pytest.mark.parametrize(("path", "fmt"), [("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
                                           ("wadl/01-bookstore.wadl", "wadl"),
                                           ("discovery/05-webfonts-sample.json", "discovery")])
def test_a_rest_source_gets_no_advisory(key: str, path: str, fmt: str) -> None:
    assert _advisories(_load(path, fmt), key) == []


def test_raml_keeps_its_wording_on_the_shared_helper() -> None:
    api = _api(ApiParadigm.RPC, _rpc("GetWidget"))
    report = compute_lossiness_for_emitter(api, RamlEmitter(), options={})
    [advisory] = [i for i in report.items if "RAML captures REST only" in i.message]
    assert advisory.message == ("RAML: RAML captures REST only; this rpc API reads back as a REST API, and 1 "
                                "operation(s) RAML cannot place on an HTTP resource are not written; only its types "
                                "are exported")


def test_the_helper_says_nothing_for_rest() -> None:
    assert rest_only_advisory(_api(ApiParadigm.REST), target_label="WADL", dropped_operations=0,
                              written_operations=0) is None


# ===========================================================================
# The gate: valid exports pass
# ===========================================================================


@pytest.mark.parametrize("key", ["wadl", "discovery"])
@pytest.mark.parametrize(("path", "fmt"), GATE_CORPUS, ids=lambda v: str(v))
async def test_every_corpus_export_passes_the_gate(key: str, path: str, fmt: str) -> None:
    api = _load(path, fmt)
    verdict = await validate_emitted_artifact(key, _EMITTERS[key]().emit(api), api=api)
    assert verdict.valid, [(f.keyword, f.message) for f in verdict.findings]


async def test_a_single_layout_wadl_passes_the_gate() -> None:
    api = _load("openapi/30-openapi-3.0-petstore.yaml", "openapi")
    result = WadlEmitter().emit(api, opts=WadlEmitOptions(layout="single"))
    assert (await validate_emitted_artifact("wadl", result, api=api)).valid


# ===========================================================================
# The gate: broken WADL is rejected
# ===========================================================================


def _wadl_export(**changes: str) -> EmitResult:
    """The Petstore WADL bundle, with ``old=new`` text replacements in the ``.wadl`` (``xsd__old`` for the ``.xsd``)."""
    result = WadlEmitter().emit(_load("openapi/30-openapi-3.0-petstore.yaml", "openapi"))
    files = []
    for emitted in result.files:
        text = str(emitted.content)
        for old, new in changes.items():
            if old.startswith("xsd__") == emitted.path.endswith(".xsd"):
                text = text.replace(old.removeprefix("xsd__"), new)
        files.append(emitted.model_copy(update={"content": text}))
    return result.model_copy(update={"files": files})


def _wadl_rules(result: EmitResult) -> List[str]:
    return [problem.rule for problem in check_emitted_wadl(result)]


def test_the_wadl_schema_is_checked() -> None:
    result = _wadl_export(**{'name="GET"': 'name="GET" bogus="1"'})
    assert set(_wadl_rules(result)) == {"wadl.schema"}


def test_unsafe_or_malformed_xml_is_rejected() -> None:
    doctype = '<!DOCTYPE x [<!ENTITY e "boom">]>'
    result = _wadl_export()
    files = [result.files[0].model_copy(update={"content": doctype + str(result.files[0].content)}), result.files[1]]
    assert _wadl_rules(result.model_copy(update={"files": files})) == ["wadl.xml"]
    assert "wadl.xml" in _wadl_rules(_wadl_export(**{"</wadl:application>": ""}))


def test_an_included_grammar_must_be_in_the_export() -> None:
    result = _wadl_export()
    assert _wadl_rules(result.model_copy(update={"files": result.files[:1]})) == ["wadl.bundle-reference"]


def test_the_grammar_must_build() -> None:
    assert _wadl_rules(_wadl_export(**{'xsd__type="xsd:string"': 'type="xsd:strang"'})) == ["wadl.grammar"]


def test_representations_must_name_grammar_elements() -> None:
    result = _wadl_export(**{'element="tns:Pet"': 'element="tns:Animal"'})
    assert "wadl.representation" in _wadl_rules(result)
    # An undeclared prefix is not a QName at all: the WADL schema already rejects it.
    undeclared = _wadl_export(**{'element="tns:Pet"': 'element="zz:Pet"'})
    assert "wadl.schema" in _wadl_rules(undeclared)


def test_an_inline_grammar_is_built_too() -> None:
    api = _load("openapi/30-openapi-3.0-petstore.yaml", "openapi")
    result = WadlEmitter().emit(api, opts=WadlEmitOptions(layout="single"))
    broken = str(result.files[0].content).replace('type="xsd:string"', 'type="xsd:strang"', 1)
    files = [result.files[0].model_copy(update={"content": broken})]
    assert _wadl_rules(result.model_copy(update={"files": files})) == ["wadl.grammar"]


def test_one_wadl_file_is_required() -> None:
    assert _wadl_rules(EmitResult(files=[], media_type="application/xml")) == ["wadl.bundle-reference"]


async def test_a_wadl_the_importer_cannot_read_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.import_source import ImportSourceError

    def failing(*_args, **_kwargs):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.roundtrip_matrix.reimport_emitted", failing)
    api = _load("openapi/30-openapi-3.0-petstore.yaml", "openapi")
    verdict = await validate_emitted_artifact("wadl", WadlEmitter().emit(api), api=api)
    assert verdict.failed and [f.keyword for f in verdict.findings] == ["wadl.reimport"]


# ===========================================================================
# The gate: broken Discovery is rejected
# ===========================================================================


def _discovery_export(mutate) -> EmitResult:
    result = DiscoveryEmitter().emit(_load("openapi/30-openapi-3.0-petstore.yaml", "openapi"))
    document = json.loads(str(result.files[0].content))
    mutate(document)
    return result.model_copy(update={"files": [result.files[0].model_copy(update={"content": json.dumps(document)})]})


@pytest.mark.parametrize(("mutate", "rule"), [
    (lambda d: d.update(kind="discovery#other"), "discovery.schema"),
    (lambda d: d.update(servicePath="/v1/"), "discovery.urls"),
    (lambda d: next(iter(d["schemas"].values())).update(id="Wrong"), "discovery.schema-id"),
    (lambda d: d["resources"]["pets"]["methods"]["listPets"].update(response={"$ref": "Missing"}), "discovery.ref"),
    (lambda d: d["resources"]["pets"]["methods"]["listPets"].update(path="pets/{nope}"), "discovery.path-parameter"),
])
async def test_a_broken_discovery_document_is_rejected(mutate, rule: str) -> None:
    api = _load("openapi/30-openapi-3.0-petstore.yaml", "openapi")
    verdict = await validate_emitted_artifact("discovery", _discovery_export(mutate), api=api)
    assert verdict.failed and rule in {f.keyword for f in verdict.findings}


async def test_a_discovery_document_the_importer_cannot_read_is_rejected() -> None:
    api = _load("openapi/30-openapi-3.0-petstore.yaml", "openapi")
    with patch("app.discovery_import_source.DiscoveryImportSource.parse",
               side_effect=__import__("app.import_source", fromlist=["ImportSourceError"]).ImportSourceError("no")):
        verdict = await validate_emitted_artifact("discovery", DiscoveryEmitter().emit(api), api=api)
    assert verdict.failed and [f.keyword for f in verdict.findings] == ["discovery.reimport"]


# ===========================================================================
# Invalid output fails the job
# ===========================================================================


@pytest.mark.parametrize(("target", "rule"), [("wadl", "wadl.schema"), ("discovery", "discovery.schema")])
async def test_invalid_output_fails_the_job(target: str, rule: str) -> None:
    """MFX-29.3 acceptance: an invalid WADL or Discovery artifact fails the export job before delivery."""
    from test_export_job_engine import TENANT_ID, TENANT_SLUG, _source, _wait_terminal

    broken = {
        "wadl": EmitResult(files=[EmittedFile(path="w.wadl", media_type="application/vnd.sun.wadl+xml",
                                              content='<application xmlns="http://wadl.dev.java.net/2009/02">'
                                                      '<nonsense/></application>')],
                           media_type="application/vnd.sun.wadl+xml"),
        "discovery": EmitResult(files=[EmittedFile(path="w.discovery.json", media_type="application/json",
                                                   content='{"kind": "discovery#restDescription"}')],
                                media_type="application/json"),
    }[target]
    # `confirm`: the lossy-transcode confirmation, so the job gets as far as the gate.
    request = ExportJobStartRequest(artifact="artifact-1", target=target, confirm=True)
    with patch("app.export_job_engine.load_export_source", return_value=_source()), patch(
        "app.export_job_engine.emit_canonical", return_value=broken
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "failed"
    assert status["error"]["code"] == "EMITTED_ARTIFACT_INVALID"
    assert rule in {f["keyword"] for f in status["error"]["context"]["findings"]}
