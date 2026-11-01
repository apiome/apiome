"""OData target card + fixtures — MFX-16.4 (#3900).

What the ``odata`` export target shows and writes, pinned in ``fixtures/odata_target/outcomes.json``
(regenerate with ``APIOME_REGEN_ODATA_TARGET=1``):

* **the card** — the tier the Export dialog, browse and ``apiome export targets`` draw for a source of each
  kind (:func:`app.export_routes.build_target_fidelity_entries`). An imported OData service is written back
  as it was read (``lossless``); a REST, RPC, GraphQL, JSON Schema or WSDL source is ``lossy``;
* **the options** — ``output`` (default ``json``) writes CSDL JSON 4.01 (``.csdl.json``, the canonical form),
  CSDL XML (``.edmx``) or both; ``include_comments`` (default on) writes the XML comment header. Every pinned
  choice passes the checks an OData import runs (:func:`app.odata_roundtrip.check_emitted_odata`: OASIS CSDL
  JSON schema, EDMX/EDM XSDs, reference and key resolution), and every entity type carries a ``$Key``
  (synthesized where the source had none);
* **browse** — the public ``…/document`` route delivers the ``.csdl.json`` itself, and the two documents of
  ``output: both`` as one zip;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-odata.json`` and
  ``apiome-ui/tests/fixtures/export-targets-odata-{rest,odata}.json`` carry the live descriptor, options
  schema, defaults and card badge; ``apiome-cli/tests/fixtures/export-job-completed-odata-lossy.json``
  carries the live fidelity summary and file name of the Petstore export.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.catalog_conversion import build_conversion_source
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_routes import build_target_fidelity_entries, render_emitted_document
from app.export_validation import validate_emitted_artifact
from app.odata_roundtrip import check_emitted_odata

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "odata_target" / "outcomes.json"
_CLI_FIXTURES = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures"
_CLI_TARGETS = _CLI_FIXTURES / "export-targets-odata.json"
_CLI_JOB = _CLI_FIXTURES / "export-job-completed-odata-lossy.json"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_ODATA_TARGET"))
_TARGET = "odata"

#: One corpus source per kind: the file and the format it is imported as. Every one imports without an
#: external toolchain, so the fixture is reproducible on any machine.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "rpc": ("thrift/01-user-service.thrift", "thrift"),
    "graphql": ("graphql/06-union-types.graphql", "graphql"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "wsdl": ("wsdl/02-order-service.wsdl", "wsdl"),
    "odata": ("odata/01-northwind.edmx", "odata"),
}

#: The option choices pinned, and the emit options that pick each.
OPTIONS: Dict[str, Dict[str, Any]] = {
    "default": {},
    "xml": {"output": "xml"},
    "both": {"output": "both"},
    "xml-no-comments": {"output": "xml", "include_comments": False},
}

#: The sources whose exports are pinned for every option choice.
OPTION_SOURCES = ("rest", "odata")


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


def _entity_types_keyed(result: Any) -> bool:
    """Every ``EntityType`` of the CSDL JSON document declares a ``$Key`` (``True`` when none is written)."""
    for emitted in result.files:
        if not emitted.path.endswith(".csdl.json"):
            continue
        document = json.loads(str(emitted.content))
        for schema in document.values():
            if not isinstance(schema, dict):
                continue
            for member in schema.values():
                if isinstance(member, dict) and member.get("$Kind") == "EntityType" \
                        and not member.get("$BaseType") and not member.get("$Abstract") and "$Key" not in member:
                    return False
    return True


def _header_comment(result: Any) -> List[bool]:
    """Per CSDL XML document, whether it opens with the generated comment header."""
    return ["<!-- Generated by Apiome" in str(emitted.content).split("<edmx:", 1)[0]
            for emitted in result.files if emitted.path.endswith(".edmx")]


def _outcome(api: Any, options: Dict[str, Any]) -> Dict[str, Any]:
    """The pinned facts of one export: its files, tier, preserved share, and what the documents carry."""
    result = _emit(api, options)
    summary = build_export_fidelity(api, get_emitter(_TARGET), options=options or None).summary
    return {
        "files": [emitted.path for emitted in result.files],
        "tier": summary.tier.value,
        "preserved_percent": summary.preserved_percent,
        "problems": [problem["rule"] for problem in check_emitted_odata(result)],
        "entity_types_keyed": _entity_types_keyed(result),
        "xml_header_comment": _header_comment(result),
    }


def _measure() -> Dict[str, Any]:
    return {
        "cards": {kind: {"available": _card(_source(kind)).descriptor.available,
                         "tier": _card(_source(kind)).fidelity.tier.value} for kind in SOURCES},
        "options": {kind: {choice: _outcome(_source(kind), options) for choice, options in OPTIONS.items()}
                    for kind in OPTION_SOURCES},
    }


def _targets_body(kind: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to the OData target."""
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


@pytest.mark.parametrize("kind", ["rest", "odata"])
def test_the_ui_targets_fixtures_are_the_live_registry(kind: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-odata-{kind}.json", _targets_body(kind))


def test_the_cli_job_fixture_carries_the_live_fidelity_and_file() -> None:
    """The completed-job envelope the CLI tests replay reports what the Petstore export really is."""
    if not _CLI_JOB.is_file():
        pytest.skip(f"{_CLI_JOB.parent} is not checked out")
    api = _source("rest")
    job = json.loads(_CLI_JOB.read_text(encoding="utf-8"))["result"]
    live = build_export_fidelity(api, get_emitter(_TARGET)).summary.model_dump(mode="json")
    assert job["fidelity"]["summary"] == live
    assert [row["path"] for row in job["files"]] == [emitted.path for emitted in _emit(api, {}).files]


@pytest.mark.parametrize("kind", SOURCES)
def test_every_source_is_offered_as_a_single_file_target(kind: str) -> None:
    card = _card(_source(kind))
    assert card.descriptor.available is True and card.descriptor.multi_file is False


def test_an_imported_odata_service_badges_lossless() -> None:
    assert _card(_source("odata")).fidelity.tier.value == "lossless"


_EXTENSIONS = {"default": ["csdl.json"], "xml": ["edmx"], "both": ["csdl.json", "edmx"],
               "xml-no-comments": ["edmx"]}


@pytest.mark.parametrize("choice", OPTIONS)
@pytest.mark.parametrize("kind", OPTION_SOURCES)
def test_each_option_choice_writes_csdl_an_odata_import_accepts(kind: str, choice: str) -> None:
    outcome = _outcome(_source(kind), OPTIONS[choice])
    assert outcome["problems"] == []
    assert outcome["entity_types_keyed"] is True
    assert ["csdl.json" if path.endswith(".csdl.json") else path.rsplit(".", 1)[-1]
            for path in outcome["files"]] == _EXTENSIONS[choice]
    assert outcome["xml_header_comment"] == [choice != "xml-no-comments"] * _EXTENSIONS[choice].count("edmx")


def test_the_options_are_in_the_descriptor() -> None:
    card = _card(_source("rest"))
    assert set(card.options_schema["properties"]) == {"include_comments", "output"}
    assert card.options_schema["properties"]["output"]["enum"] == ["json", "xml", "both"]
    assert card.default_options == {"include_comments": True, "output": "json"}


def test_browse_delivers_the_csdl_json_itself() -> None:
    api = _source("rest")
    response = render_emitted_document(api, _TARGET, {}, None, bundle_multi_file=True)
    assert response.media_type != "application/zip"
    assert response.headers["content-disposition"].endswith('.csdl.json"')
    assert "$Version" in json.loads(response.body.decode("utf-8"))


def test_browse_bundles_both_documents_as_a_zip() -> None:
    api = _source("rest")
    response = render_emitted_document(api, _TARGET, {"output": "both"}, None, bundle_multi_file=True)
    assert response.media_type == "application/zip"
    assert response.headers["content-disposition"].endswith('.zip"')


@pytest.mark.parametrize("choice", ["default", "both"])
@pytest.mark.parametrize("kind", OPTION_SOURCES)
def test_the_validation_gate_passes_the_export(kind: str, choice: str) -> None:
    """The MFX-16.3 gate: OASIS CSDL schema, EDMX XSDs, resolution and keys; ``both`` agrees on one model."""
    api = _source(kind)
    verdict = asyncio.run(validate_emitted_artifact(_TARGET, _emit(api, OPTIONS[choice]), api=api))
    assert verdict.applicable and verdict.validated and verdict.valid, verdict.errors
