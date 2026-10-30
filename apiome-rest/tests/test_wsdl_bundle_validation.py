"""Emitted WSDL bundle packaging + validation — MFX-14.3 (#3891).

Covers, in order:

* the zip delivery: a ``bundle`` export packages ``<Name>.wsdl`` + ``<Name>.xsd`` (+ manifest), and
  the unpacked zip is a valid bundle;
* each check of :func:`app.wsdl_bundle_validation.validate_wsdl_bundle` passing on clean output and
  catching a deliberately broken bundle: root, XML, packaging, WS-I, structure (schema + references),
  re-import;
* inherited WS-I rules: a WSDL source's own issues are carried, not reported; new ones are;
* the export gate: ``validate_emitted_artifact("wsdl", …)`` passes every corpus export and rejects a
  broken one with structured findings;
* the two emitter fixes the validator surfaced: one-way operations bind only an ``input``, and an
  rpc-literal body names its namespace (WS-I R2717).
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Dict

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
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
from app.emitter import EmitResult, EmittedFile
from app.export_job_engine import build_export_zip
from app.export_validation import validate_emitted_artifact
from app.wsdl_bundle_validation import inherited_wsi_rules, validate_wsdl_bundle
from app.wsdl_emitter import WsdlEmitOptions, WsdlEmitter

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


# ===========================================================================
# Helpers
# ===========================================================================


def _api() -> CanonicalApi:
    """A REST model with one record and one operation (written document/literal wrapped)."""
    pet = Type(
        key="Pet",
        name="Pet",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="Pet.id", name="id", type=TypeRef(name="string"))],
    )
    operation = Operation(
        key="GET /pets/{petId}",
        name="getPetById",
        kind=OperationKind.QUERY,
        messages=[Message(key="getPetById.response", role=MessageRole.RESPONSE, payload=TypeRef(name="Pet"))],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi",
        identity=ApiIdentity(name="Pets"),
        types=[pet],
        services=[Service(key="default", name="default", operations=[operation])],
    )


def _members(result: EmitResult) -> Dict[str, str]:
    return {emitted.path: emitted.content for emitted in result.files}


def _bundle(**opts) -> Dict[str, str]:
    return _members(WsdlEmitter().emit(_api(), opts=WsdlEmitOptions(**opts)))


def _rules(problems) -> list:
    return [problem.rule for problem in problems]


def _corpus_api(path: Path) -> CanonicalApi:
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    fmt = {".wsdl": "wsdl", ".yaml": "openapi", ".proto": "protobuf", ".graphql": "graphql"}
    return build_conversion_source(
        {
            "id": "item-1",
            "name": path.stem,
            "source_format": fmt[path.suffix],
            "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")},
        }
    ).api


_CORPUS = [
    *sorted((_EXAMPLES / "wsdl").glob("*.wsdl")),
    _EXAMPLES / "openapi" / "07-nullable-types.yaml",
    _EXAMPLES / "openapi" / "22-advanced-oneof-polymorphism.yaml",
    _EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml",
    _EXAMPLES / "protobuf" / "01-simple-user.proto",
    _EXAMPLES / "graphql" / "06-union-types.graphql",
]


# ===========================================================================
# Zip packaging
# ===========================================================================


def test_bundle_export_zips_the_wsdl_and_its_schema_and_unpacks_valid() -> None:
    result = WsdlEmitter().emit(_api())
    with zipfile.ZipFile(io.BytesIO(build_export_zip(result, "wsdl"))) as archive:
        names = archive.namelist()
        unpacked = {name: archive.read(name).decode("utf-8") for name in names if name != "manifest.json"}
        manifest = json.loads(archive.read("manifest.json"))
    assert names == ["Pets.wsdl", "Pets.xsd", "manifest.json"]
    assert [entry["path"] for entry in manifest["files"]] == ["Pets.wsdl", "Pets.xsd"]
    assert validate_wsdl_bundle(unpacked) == []


# ===========================================================================
# Each check
# ===========================================================================


@pytest.mark.parametrize("layout", ["bundle", "single"])
def test_clean_export_has_no_problems(layout: str) -> None:
    assert validate_wsdl_bundle(_bundle(layout=layout)) == []


def test_bundle_must_carry_exactly_one_description() -> None:
    files = _bundle()
    assert _rules(validate_wsdl_bundle({**files, "Copy.wsdl": files["Pets.wsdl"]})) == ["wsdl.bundle-root"]
    assert _rules(validate_wsdl_bundle({"Pets.xsd": files["Pets.xsd"]})) == ["wsdl.bundle-root"]


def test_malformed_member_is_reported_with_its_file() -> None:
    problems = validate_wsdl_bundle({**_bundle(), "Pets.xsd": "<xsd:schema"})
    assert _rules(problems) == ["wsdl.xml"]
    assert problems[0].file == "Pets.xsd"


def test_unsafe_xml_is_rejected() -> None:
    doctype = '<!DOCTYPE x [<!ENTITY e "boom">]>'
    problems = validate_wsdl_bundle({**_bundle(), "Pets.xsd": doctype + _bundle()["Pets.xsd"]})
    assert _rules(problems) == ["wsdl.xml"]


@pytest.mark.parametrize(
    "location",
    ["Missing.xsd", "../Pets.xsd", "/etc/Pets.xsd", "http://example.com/Pets.xsd", "C:/Pets.xsd"],
)
def test_every_import_must_be_packaged(location: str) -> None:
    files = _bundle()
    wsdl = files["Pets.wsdl"].replace('schemaLocation="Pets.xsd"', f'schemaLocation="{location}"')
    problems = validate_wsdl_bundle({**files, "Pets.wsdl": wsdl})
    assert _rules(problems) == ["wsdl.bundle-reference"]
    assert problems[0].path == location and problems[0].file == "Pets.wsdl"


def test_a_missing_schema_file_is_a_packaging_problem() -> None:
    problems = validate_wsdl_bundle({"Pets.wsdl": _bundle()["Pets.wsdl"]})
    assert _rules(problems) == ["wsdl.bundle-reference"]


def test_imports_resolve_relative_to_the_importing_member() -> None:
    files = _bundle()
    nested = {
        "Pets.wsdl": files["Pets.wsdl"].replace('schemaLocation="Pets.xsd"', 'schemaLocation="types/Pets.xsd"'),
        "types/Pets.xsd": files["Pets.xsd"],
    }
    assert validate_wsdl_bundle(nested) == []


def test_ws_i_violation_is_reported_with_its_rule_and_path() -> None:
    files = _bundle()
    wsdl = files["Pets.wsdl"].replace('use="literal"', 'use="encoded"', 1)
    problems = validate_wsdl_bundle({**files, "Pets.wsdl": wsdl})
    assert _rules(problems) == ["wsi.literal-use"]
    assert problems[0].path.startswith("/binding/")


def test_an_unknown_schema_type_is_a_structure_problem() -> None:
    files = _bundle()
    xsd = files["Pets.xsd"].replace('type="xsd:string"', 'type="xsd:strang"')
    problems = validate_wsdl_bundle({**files, "Pets.xsd": xsd})
    assert _rules(problems) == ["wsdl.structure"]
    assert "xsd:strang" in problems[0].message
    assert "wsdl-bundle-" not in problems[0].message  # the temporary folder is not leaked


def test_a_dangling_message_reference_is_a_structure_problem() -> None:
    files = _bundle()
    wsdl = files["Pets.wsdl"].replace('message="tns:', 'message="tns:Nope', 1)
    problems = validate_wsdl_bundle({**files, "Pets.wsdl": wsdl})
    assert "wsdl.structure" in _rules(problems)
    assert any("unknown message" in problem.message for problem in problems)


def test_a_bundle_that_does_not_import_is_reported() -> None:
    # Well-formed, packaged and schema-valid, but a WSDL with no types and no port types.
    empty = '<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" targetNamespace="urn:x"/>'
    assert _rules(validate_wsdl_bundle({"Empty.wsdl": empty})) == ["wsdl.reimport"]


# ===========================================================================
# Inherited WS-I rules
# ===========================================================================


def test_inherited_rules_come_only_from_a_wsdl_source() -> None:
    api = _api().model_copy(update={"extras": {"wsdl_wsi_issues": [{"rule": "wsi.binding-style"}]}})
    assert inherited_wsi_rules(api) == frozenset()
    wsdl_api = api.model_copy(update={"format": "wsdl"})
    assert inherited_wsi_rules(wsdl_api) == frozenset({"wsi.binding-style"})


def test_inherited_rules_are_not_reported_but_new_ones_are() -> None:
    files = _bundle()
    wsdl = files["Pets.wsdl"].replace('use="literal"', 'use="encoded"', 1)
    broken = {**files, "Pets.wsdl": wsdl}
    assert validate_wsdl_bundle(broken, inherited_rules={"wsi.literal-use"}) == []
    assert _rules(validate_wsdl_bundle(broken, inherited_rules={"wsi.binding-style"})) == ["wsi.literal-use"]


def test_kitchen_sink_source_keeps_only_its_own_ws_i_issue() -> None:
    api = _corpus_api(_EXAMPLES / "wsdl" / "04-kitchen-sink.wsdl")
    members = _members(WsdlEmitter().emit(api))
    assert set(_rules(validate_wsdl_bundle(members))) == {"wsi.binding-style"}
    assert "wsi.binding-style" in inherited_wsi_rules(api)
    assert validate_wsdl_bundle(members, inherited_rules=inherited_wsi_rules(api)) == []


# ===========================================================================
# The export gate
# ===========================================================================


@pytest.mark.parametrize("path", _CORPUS, ids=lambda p: p.name)
async def test_every_corpus_export_passes_the_gate(path: Path) -> None:
    api = _corpus_api(path)
    verdict = await validate_emitted_artifact("wsdl", WsdlEmitter().emit(api), api=api)
    assert verdict.applicable and verdict.validated and verdict.valid, verdict.errors


async def test_gate_rejects_a_broken_bundle_with_structured_findings() -> None:
    api = _api()
    result = WsdlEmitter().emit(api)
    broken = EmitResult(
        files=[result.files[0], EmittedFile(path="Pets.xsd", content="<x", media_type="application/xml")],
        media_type=result.media_type,
    )
    verdict = await validate_emitted_artifact("wsdl", broken, api=api)
    assert verdict.failed
    assert verdict.findings[0].keyword == "wsdl.xml" and verdict.findings[0].file == "Pets.xsd"


async def test_gate_rejects_an_empty_export() -> None:
    api = _api()
    verdict = await validate_emitted_artifact("wsdl", EmitResult(files=[], media_type="application/wsdl+xml"), api=api)
    assert verdict.failed


# ===========================================================================
# Emitter fixes the validator surfaced
# ===========================================================================


def _kitchen_sink_wsdl() -> str:
    api = _corpus_api(_EXAMPLES / "wsdl" / "04-kitchen-sink.wsdl")
    return WsdlEmitter().emit(api).files[0].content


def test_one_way_operation_binds_only_an_input() -> None:
    wsdl = _kitchen_sink_wsdl()
    alarm = wsdl[wsdl.index('<wsdl:binding name="AlarmBinding"'):]
    alarm = alarm[: alarm.index("</wsdl:binding>")]
    assert "<wsdl:input>" in alarm and "<wsdl:output>" not in alarm


def test_rpc_literal_body_names_its_namespace() -> None:
    wsdl = _kitchen_sink_wsdl()
    assert '<soap:body use="literal" namespace="http://example.com/telemetry" />' in wsdl
