"""XSD target card + fixtures — MFX-22.6 (#4137).

What the standalone ``xsd`` export target shows and writes, pinned in ``fixtures/xsd_target/outcomes.json``
(regenerate with ``APIOME_REGEN_XSD_TARGET=1``):

* **the card** — the tier the Export dialog, browse and ``apiome export targets`` draw for a source of each
  kind (:func:`app.export_routes.build_target_fidelity_entries`). XSD is a types-only target, so a REST, RPC,
  GraphQL, JSON Schema, WSDL or RAML source badges ``types-only``; an imported XSD badges ``lossless``;
* **the fixture cases** — a plain schema (``02-minimal-note``), a facet-heavy one (``01-purchase-order``:
  patterns, bounds, enumerations), a UBL-style document profile (``05-ubl-invoice-shape``) and a
  multi-namespace model (two URI namespaces, built here): it exports one ``.xsd`` per namespace, the first
  ``xs:import`` ing the second, and browse delivers the set as a zip;
* **the options** — ``xsd_version`` (``1.0`` default; ``1.1`` marks ``vc:minVersion="1.1"``),
  ``include_xml_declaration`` and ``include_comments`` (both default on). Every pinned choice passes the export
  gate's check (:func:`app.xsd_roundtrip.check_emitted_xsd`). RELAX NG / DTD modes (MFX-22.3) and the
  ISO 20022 profile (MFX-22.4) are not in the registry yet; the card shows them when they are;
* **browse** — the public ``…/document`` route delivers a one-namespace ``.xsd`` itself;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-xsd.json`` and
  ``apiome-ui/tests/fixtures/export-targets-xsd-{rest,xsd}.json`` carry the live descriptor, options schema,
  defaults and card badge; ``apiome-cli/tests/fixtures/export-job-completed-xsd-types-only.json`` carries the
  live fidelity summary and file name of the Petstore export.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest

from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi, CanonicalField, Type, TypeKind, TypeRef
from app.catalog_conversion import build_conversion_source
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_routes import build_target_fidelity_entries, render_emitted_document
from app.export_validation import validate_emitted_artifact
from app.xsd_roundtrip import check_emitted_xsd

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "xsd_target" / "outcomes.json"
_CLI_FIXTURES = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures"
_CLI_TARGETS = _CLI_FIXTURES / "export-targets-xsd.json"
_CLI_JOB = _CLI_FIXTURES / "export-job-completed-xsd-types-only.json"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_XSD_TARGET"))
_TARGET = "xsd"

#: One corpus source per kind, and the XSD cases: the file and the format it is imported as. Every one
#: imports without an external toolchain, so the fixture is reproducible on any machine.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "rpc": ("thrift/01-user-service.thrift", "thrift"),
    "graphql": ("graphql/06-union-types.graphql", "graphql"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "wsdl": ("wsdl/02-order-service.wsdl", "wsdl"),
    "raml": ("raml/03-orders-service.raml", "raml"),
    "xsd-plain": ("xsd/02-minimal-note.xsd", "xsd"),
    "xsd-facets": ("xsd/01-purchase-order.xsd", "xsd"),
    "xsd-profile": ("xsd/05-ubl-invoice-shape.xsd", "xsd"),
}

#: The kinds that are not XSD sources: XSD keeps only their types.
NON_XSD_KINDS = ("rest", "rpc", "graphql", "json-schema", "wsdl", "raml")

#: The option choices pinned, and the emit options that pick each.
OPTIONS: Dict[str, Dict[str, Any]] = {
    "default": {},
    "xsd-1.1": {"xsd_version": "1.1"},
    "no-declaration": {"include_xml_declaration": False},
    "no-comments": {"include_comments": False},
}

#: The sources whose exports are pinned for every option choice.
OPTION_SOURCES = ("rest", "xsd-facets", "multi-namespace")


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()


def _multi_namespace() -> CanonicalApi:
    """An ``Order`` in ``urn:example:orders`` whose ``shipTo`` is an ``Address`` in ``urn:example:common``."""
    city = CanonicalField(key="Address.city", name="city", type=TypeRef(name="string", nullable=False))
    address = Type(key="Address", name="Address", kind=TypeKind.RECORD, namespace="urn:example:common", fields=[city])
    order = Type(key="Order", name="Order", kind=TypeKind.RECORD, namespace="urn:example:orders", fields=[
        CanonicalField(key="Order.id", name="id", type=TypeRef(name="string", nullable=False)),
        CanonicalField(key="Order.shipTo", name="shipTo", type=TypeRef(name="Address", nullable=False)),
    ])
    return CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="xsd", title="Orders", types=[order, address],
                        identity=ApiIdentity(name="Orders", namespace="urn:example:orders"))


def _source(kind: str) -> Any:
    if kind == "multi-namespace":
        return _multi_namespace()
    path, fmt = SOURCES[kind]
    file = _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": file.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}
    ).api


def _card(api: Any) -> Any:
    return next(entry for entry in build_target_fidelity_entries(api) if entry.descriptor.key == _TARGET)


def _emit(api: Any, options: Dict[str, Any]) -> Any:
    emitter = get_emitter(_TARGET)
    return emitter().emit(api, opts=coerce_emit_options(emitter, options))


def _outcome(api: Any, options: Dict[str, Any]) -> Dict[str, Any]:
    """The pinned facts of one export: its files, tier, preserved share, and what the documents carry."""
    result = _emit(api, options)
    main = str(result.files[0].content)
    summary = build_export_fidelity(api, get_emitter(_TARGET), options=options or None).summary
    return {
        "files": [emitted.path for emitted in result.files],
        "tier": summary.tier.value,
        "preserved_percent": summary.preserved_percent,
        "problems": [problem["message"] for problem in check_emitted_xsd(result)],
        "xml_declaration": main.startswith("<?xml"),
        "header_comment": "<!-- Generated XSD" in main,
        "min_version_1_1": 'vc:minVersion="1.1"' in main,
        "imports": main.count("<xsd:import "),
    }


def _measure() -> Dict[str, Any]:
    kinds = (*SOURCES, "multi-namespace")
    return {
        "cards": {kind: {"available": _card(_source(kind)).descriptor.available,
                         "tier": _card(_source(kind)).fidelity.tier.value} for kind in kinds},
        "options": {kind: {choice: _outcome(_source(kind), options) for choice, options in OPTIONS.items()}
                    for kind in OPTION_SOURCES},
        "cases": {kind: _outcome(_source(kind), {}) for kind in ("xsd-plain", "xsd-profile")},
    }


def _targets_body(kind: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to the XSD target."""
    return {"artifact": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "version": "1.0.0",
            "targets": [_card(_source(kind)).model_dump(mode="json")]}


def _check_recorded(path: Path, live: Dict[str, Any]) -> None:
    """``path`` holds ``live`` (written first under regen); skipped when that package is not checked out."""
    if _REGEN and path.parent.is_dir():
        path.write_text(json.dumps(live, indent=2) + "\n", encoding="utf-8")
    if not path.is_file():
        pytest.skip(f"{path.parent} is not checked out")
    assert json.loads(path.read_text(encoding="utf-8")) == live


def test_the_outcomes_match_the_fixture() -> None:
    measured = _measure()
    if _REGEN:
        _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert measured == json.loads(_GOLDEN.read_text(encoding="utf-8"))


def test_the_cli_targets_fixture_is_the_live_registry() -> None:
    _check_recorded(_CLI_TARGETS, _targets_body("rest"))


@pytest.mark.parametrize("kind", ["rest", "xsd"])
def test_the_ui_targets_fixtures_are_the_live_registry(kind: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-xsd-{kind}.json",
                    _targets_body("rest" if kind == "rest" else "xsd-facets"))


def test_the_cli_job_fixture_carries_the_live_fidelity_and_file() -> None:
    """The completed-job envelope the CLI tests replay reports what the Petstore export really is."""
    if not _CLI_JOB.is_file():
        pytest.skip(f"{_CLI_JOB.parent} is not checked out")
    api = _source("rest")
    job = json.loads(_CLI_JOB.read_text(encoding="utf-8"))["result"]
    live = build_export_fidelity(api, get_emitter(_TARGET)).summary.model_dump(mode="json")
    assert job["fidelity"]["summary"] == live
    assert [row["path"] for row in job["files"]] == [emitted.path for emitted in _emit(api, {}).files]


@pytest.mark.parametrize("kind", (*SOURCES, "multi-namespace"))
def test_every_source_is_offered_as_a_single_file_target(kind: str) -> None:
    card = _card(_source(kind))
    assert card.descriptor.available is True and card.descriptor.multi_file is False


@pytest.mark.parametrize("kind", NON_XSD_KINDS)
def test_a_non_xsd_source_badges_types_only(kind: str) -> None:
    assert _card(_source(kind)).fidelity.tier.value == "types-only"


@pytest.mark.parametrize("kind", ["xsd-plain", "xsd-facets", "xsd-profile", "multi-namespace"])
def test_an_xsd_source_badges_lossless(kind: str) -> None:
    assert _card(_source(kind)).fidelity.tier.value == "lossless"


@pytest.mark.parametrize("choice", OPTIONS)
@pytest.mark.parametrize("kind", OPTION_SOURCES)
def test_each_option_choice_writes_a_schema_the_gate_accepts(kind: str, choice: str) -> None:
    outcome = _outcome(_source(kind), OPTIONS[choice])
    assert outcome["problems"] == []
    assert outcome["xml_declaration"] is (choice != "no-declaration")
    assert outcome["header_comment"] is (choice != "no-comments")
    assert outcome["min_version_1_1"] is (choice == "xsd-1.1")


def test_a_multi_namespace_model_writes_one_schema_per_namespace() -> None:
    outcome = _outcome(_source("multi-namespace"), {})
    assert outcome["files"] == ["Orders.xsd", "Orders-common.xsd"]
    assert outcome["imports"] == 1


def test_the_options_are_in_the_descriptor() -> None:
    card = _card(_source("rest"))
    assert set(card.options_schema["properties"]) == {"include_comments", "include_xml_declaration", "xsd_version"}
    assert card.options_schema["properties"]["xsd_version"]["enum"] == ["1.0", "1.1"]
    assert card.default_options == {"include_comments": True, "include_xml_declaration": True, "xsd_version": "1.0"}


def test_browse_delivers_a_one_namespace_xsd_itself() -> None:
    response = render_emitted_document(_source("xsd-facets"), _TARGET, {}, None, bundle_multi_file=True)
    assert response.media_type != "application/zip"
    assert response.headers["content-disposition"].endswith('.xsd"')
    assert "<xsd:schema" in response.body.decode("utf-8")


def test_browse_bundles_a_multi_namespace_set_as_a_zip() -> None:
    response = render_emitted_document(_source("multi-namespace"), _TARGET, {}, None, bundle_multi_file=True)
    assert response.media_type == "application/zip"
    assert response.headers["content-disposition"].endswith('.zip"')


@pytest.mark.parametrize("kind", ["rest", "xsd-facets", "multi-namespace"])
def test_the_validation_gate_passes_the_default_export(kind: str) -> None:
    """The MFX-22.5 gate: xmlschema (1.0 and 1.1), then the re-import."""
    api = _source(kind)
    verdict = asyncio.run(validate_emitted_artifact(_TARGET, _emit(api, {}), api=api))
    assert verdict.applicable and verdict.validated and verdict.valid, verdict.errors
