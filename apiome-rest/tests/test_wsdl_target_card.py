"""WSDL target card + fixtures — MFX-14.4 (#3892).

What the ``wsdl`` export target shows and writes, pinned in ``fixtures/wsdl_target/outcomes.json``
(regenerate with ``APIOME_REGEN_WSDL_TARGET=1``):

* **the card** — the tier the Export dialog, browse and ``apiome export targets`` draw for a source of each
  kind (:func:`app.export_routes.build_target_fidelity_entries`). A REST, RPC, GraphQL or JSON Schema
  source is ``lossy`` (HTTP method and path, field numbers, JSON-only constructs); an imported WSDL or
  XSD numbers its fields by position, which the export keeps, so a WSDL source is ``lossless``;
* **the layout picker** — ``layout`` writes the WSDL and its XSD as two files (``bundle``, the default) or
  inlines the schema (``single``); every pinned choice passes the MFX-14.3 bundle check
  (:func:`app.wsdl_bundle_validation.validate_wsdl_bundle`: WS-I, references, ``xmlschema``, re-import);
* **browse** — the public ``…/document`` route delivers a bundle as one zip;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-wsdl.json`` and
  ``apiome-ui/tests/fixtures/export-targets-wsdl-{rest,wsdl}.json`` carry the live descriptor, options
  schema, defaults and card badge; ``apiome-cli/tests/fixtures/export-job-completed-wsdl-lossy.json``
  carries the live fidelity summary and file names of the Petstore export.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path
from typing import Any, Dict

import pytest

from app.catalog_conversion import build_conversion_source
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_routes import build_target_fidelity_entries, render_emitted_document
from app.wsdl_bundle_validation import inherited_wsi_rules, validate_wsdl_bundle

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "wsdl_target" / "outcomes.json"
_CLI_FIXTURES = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures"
_CLI_TARGETS = _CLI_FIXTURES / "export-targets-wsdl.json"
_CLI_JOB = _CLI_FIXTURES / "export-job-completed-wsdl-lossy.json"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_WSDL_TARGET"))
_TARGET = "wsdl"

#: One corpus source per kind: the file and the format it is imported as. Every one imports without an
#: external toolchain, so the fixture is reproducible on any machine.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "rpc": ("thrift/01-user-service.thrift", "thrift"),
    "graphql": ("graphql/06-union-types.graphql", "graphql"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "wsdl": ("wsdl/02-order-service.wsdl", "wsdl"),
    "xsd": ("xsd/01-purchase-order.xsd", "xsd"),
}

#: The layout choices pinned, and the emit options that pick each.
LAYOUTS: Dict[str, Dict[str, Any]] = {
    "bundle": {},
    "single": {"layout": "single"},
}

#: The sources whose exports are pinned for every layout.
LAYOUT_SOURCES = ("rest", "wsdl")


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()


def _source(kind: str) -> Any:
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
    """The pinned facts of one export: its files, tier, preserved share and bundle-check result."""
    result = _emit(api, options)
    files = {emitted.path: str(emitted.content) for emitted in result.files}
    summary = build_export_fidelity(api, get_emitter(_TARGET), options=options or None).summary
    return {
        "files": list(files),
        "tier": summary.tier.value,
        "preserved_percent": summary.preserved_percent,
        "problems": [problem.rule for problem in validate_wsdl_bundle(files, inherited_rules=inherited_wsi_rules(api))],
    }


def _measure() -> Dict[str, Any]:
    return {
        "cards": {kind: {"available": _card(_source(kind)).descriptor.available,
                         "tier": _card(_source(kind)).fidelity.tier.value} for kind in SOURCES},
        "layouts": {kind: {layout: _outcome(_source(kind), options) for layout, options in LAYOUTS.items()}
                    for kind in LAYOUT_SOURCES},
    }


def _targets_body(kind: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to the WSDL target."""
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


@pytest.mark.parametrize("kind", ["rest", "wsdl"])
def test_the_ui_targets_fixtures_are_the_live_registry(kind: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-wsdl-{kind}.json", _targets_body(kind))


def test_the_cli_job_fixture_carries_the_live_fidelity_and_files() -> None:
    """The completed-job envelope the CLI tests replay reports what the Petstore export really is."""
    if not _CLI_JOB.is_file():
        pytest.skip(f"{_CLI_JOB.parent} is not checked out")
    api = _source("rest")
    job = json.loads(_CLI_JOB.read_text(encoding="utf-8"))["result"]
    live = build_export_fidelity(api, get_emitter(_TARGET)).summary.model_dump(mode="json")
    assert job["fidelity"]["summary"] == live
    assert [row["path"] for row in job["files"]] == [emitted.path for emitted in _emit(api, {}).files]


@pytest.mark.parametrize("kind", SOURCES)
def test_every_source_is_offered_as_a_multi_file_target(kind: str) -> None:
    card = _card(_source(kind))
    assert card.descriptor.available is True and card.descriptor.multi_file is True


@pytest.mark.parametrize("kind", ["wsdl", "xsd"])
def test_a_wsdl_or_xsd_source_keeps_its_field_numbers(kind: str) -> None:
    report = build_export_fidelity(_source(kind), get_emitter(_TARGET)).report
    assert not any("field number" in item.message for item in report.items)


def test_an_imported_wsdl_badges_lossless() -> None:
    assert _card(_source("wsdl")).fidelity.tier.value == "lossless"


@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("kind", LAYOUT_SOURCES)
def test_each_layout_writes_a_bundle_that_passes_the_checks(kind: str, layout: str) -> None:
    outcome = _outcome(_source(kind), LAYOUTS[layout])
    assert outcome["problems"] == []
    suffixes = [path.rsplit(".", 1)[-1] for path in outcome["files"]]
    assert suffixes == (["wsdl", "xsd"] if layout == "bundle" else ["wsdl"])


def test_the_layout_picker_is_in_the_descriptor() -> None:
    card = _card(_source("rest"))
    layout = card.options_schema["properties"]["layout"]
    assert layout["enum"] == ["bundle", "single"]
    assert card.default_options == {"include_comments": True, "layout": "bundle"}


def test_browse_delivers_the_bundle_as_one_zip() -> None:
    api = _source("rest")
    response = render_emitted_document(api, _TARGET, {}, None, bundle_multi_file=True)
    assert response.media_type == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        names = set(archive.namelist())
    assert {name.rsplit(".", 1)[-1] for name in names if name != "manifest.json"} == {"wsdl", "xsd"}
