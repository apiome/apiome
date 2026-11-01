"""Smithy target card + fixtures — MFX-20.4 (#3917).

What the ``smithy`` export target shows and writes, pinned in ``fixtures/smithy_target/outcomes.json``
(regenerate with ``APIOME_REGEN_SMITHY_TARGET=1``):

* **the card** — the tier the Export dialog, browse and ``apiome export targets`` draw for a source of each
  kind (:func:`app.export_routes.build_target_fidelity_entries`). An imported Smithy model is written back as
  it was read (``lossless``); a REST, RPC, GraphQL, JSON Schema, WSDL or RAML source is ``lossy``;
* **high fidelity** — a source's constraints become constraint traits (the Petstore's ``minimum: 1`` is
  ``@range(min: 1)``) and its required fields ``@required``;
* **the options** — ``output`` (default ``idl``) writes the ``.smithy`` IDL, the JSON AST (``.json``) or both;
  ``protocol`` (default ``none``) applies ``aws.protocols#restJson1`` or ``smithy.protocols#rpcv2Cbor`` to each
  service; ``include_comments`` (default on) writes the IDL header comment; ``smithy_version`` is the
  ``$version``. Every pinned choice passes the export gate's check (``smithy validate`` where the CLI is
  installed, else the Smithy reader);
* **browse** — the public ``…/document`` route delivers the ``.smithy`` itself, and the two views of
  ``output: both`` as one zip;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-smithy.json`` and
  ``apiome-ui/tests/fixtures/export-targets-smithy-{rest,smithy}.json`` carry the live descriptor, options
  schema, defaults and card badge; ``apiome-cli/tests/fixtures/export-job-completed-smithy-lossy.json``
  carries the live fidelity summary and file name of the Petstore export.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from app.catalog_conversion import build_conversion_source
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_routes import build_target_fidelity_entries, render_emitted_document
from app.export_validation import validate_emitted_artifact
from app.smithy_roundtrip import validate_emitted_smithy

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "smithy_target" / "outcomes.json"
_CLI_FIXTURES = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures"
_CLI_TARGETS = _CLI_FIXTURES / "export-targets-smithy.json"
_CLI_JOB = _CLI_FIXTURES / "export-job-completed-smithy-lossy.json"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_SMITHY_TARGET"))
_TARGET = "smithy"

#: One corpus source per kind: the file and the format it is imported as. Every one imports without an
#: external toolchain, so the fixture is reproducible on any machine.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "rpc": ("thrift/01-user-service.thrift", "thrift"),
    "graphql": ("graphql/06-union-types.graphql", "graphql"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "wsdl": ("wsdl/02-order-service.wsdl", "wsdl"),
    "raml": ("raml/03-orders-service.raml", "raml"),
    "smithy": ("smithy/06-orders-service.smithy", "smithy"),
}

#: The option choices pinned, and the emit options that pick each.
OPTIONS: Dict[str, Dict[str, Any]] = {
    "default": {},
    "json-ast": {"output": "json-ast"},
    "both": {"output": "both"},
    "no-comments": {"include_comments": False},
    "rest-json": {"protocol": "restJson1"},
    "rpc-cbor": {"protocol": "rpcv2Cbor"},
}

#: The sources whose exports are pinned for every option choice.
OPTION_SOURCES = ("rest", "smithy")

#: The ``use`` line each ``protocol`` choice writes into the IDL (``None``: no protocol trait).
_PROTOCOL_USE = {"none": None, "restJson1": "use aws.protocols#restJson1",
                 "rpcv2Cbor": "use smithy.protocols#rpcv2Cbor"}


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


def _idl(result: Any) -> Optional[str]:
    """The ``.smithy`` IDL the export wrote, or ``None`` for a JSON-AST-only export."""
    return next((str(emitted.content) for emitted in result.files if emitted.path.endswith(".smithy")), None)


def _protocol_uses(text: Optional[str]) -> List[str]:
    """The protocol ``use`` lines of an IDL document."""
    uses = {line for line in _PROTOCOL_USE.values() if line}
    return [line for line in (text or "").splitlines() if line in uses]


def _outcome(api: Any, options: Dict[str, Any]) -> Dict[str, Any]:
    """The pinned facts of one export: its files, tier, preserved share, and what the documents carry."""
    result = _emit(api, options)
    idl = _idl(result)
    summary = build_export_fidelity(api, get_emitter(_TARGET), options=options or None).summary
    _, problems = validate_emitted_smithy(result)
    return {
        "files": [emitted.path for emitted in result.files],
        "tier": summary.tier.value,
        "preserved_percent": summary.preserved_percent,
        "problems": [problem["message"] for problem in problems],
        "header_comment": idl.startswith("//") if idl is not None else None,
        "protocol_uses": _protocol_uses(idl),
        "range_trait": "@range(" in (idl or ""),
        "required_trait": "@required" in (idl or ""),
    }


def _measure() -> Dict[str, Any]:
    return {
        "cards": {kind: {"available": _card(_source(kind)).descriptor.available,
                         "tier": _card(_source(kind)).fidelity.tier.value} for kind in SOURCES},
        "options": {kind: {choice: _outcome(_source(kind), options) for choice, options in OPTIONS.items()}
                    for kind in OPTION_SOURCES},
    }


def _targets_body(kind: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to the Smithy target."""
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


@pytest.mark.parametrize("kind", ["rest", "smithy"])
def test_the_ui_targets_fixtures_are_the_live_registry(kind: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-smithy-{kind}.json", _targets_body(kind))


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


def test_an_imported_smithy_model_badges_lossless() -> None:
    assert _card(_source("smithy")).fidelity.tier.value == "lossless"


def test_constraints_and_required_fields_become_traits() -> None:
    """The Petstore's ``minimum: 1`` is ``@range(min: 1)``, and its required fields are ``@required``."""
    idl = _idl(_emit(_source("rest"), {}))
    assert "@range(min: 1)" in idl and "@required" in idl


_EXTENSIONS = {"default": ["smithy"], "json-ast": ["json"], "both": ["smithy", "json"], "no-comments": ["smithy"],
               "rest-json": ["smithy"], "rpc-cbor": ["smithy"]}


@pytest.mark.parametrize("choice", OPTIONS)
@pytest.mark.parametrize("kind", OPTION_SOURCES)
def test_each_option_choice_writes_a_model_that_validates(kind: str, choice: str) -> None:
    outcome = _outcome(_source(kind), OPTIONS[choice])
    assert outcome["problems"] == []
    assert [path.rsplit(".", 1)[-1] for path in outcome["files"]] == _EXTENSIONS[choice]
    if outcome["header_comment"] is not None:
        assert outcome["header_comment"] is (choice != "no-comments")


@pytest.mark.parametrize("protocol", ["restJson1", "rpcv2Cbor"])
def test_the_protocol_option_applies_its_trait(protocol: str) -> None:
    outcome = _outcome(_source("rest"), {"protocol": protocol})
    assert outcome["protocol_uses"] == [_PROTOCOL_USE[protocol]]
    assert _outcome(_source("rest"), {})["protocol_uses"] == []


def test_the_options_are_in_the_descriptor() -> None:
    card = _card(_source("rest"))
    assert set(card.options_schema["properties"]) == {"include_comments", "output", "protocol", "smithy_version"}
    assert card.default_options == {"include_comments": True, "output": "idl", "protocol": "none",
                                    "smithy_version": "2.0"}


def test_browse_delivers_the_smithy_idl_itself() -> None:
    api = _source("rest")
    response = render_emitted_document(api, _TARGET, {}, None, bundle_multi_file=True)
    assert response.media_type != "application/zip"
    assert response.headers["content-disposition"].endswith('.smithy"')
    assert '$version: "2.0"' in response.body.decode("utf-8")


def test_browse_bundles_both_views_as_a_zip() -> None:
    api = _source("rest")
    response = render_emitted_document(api, _TARGET, {"output": "both"}, None, bundle_multi_file=True)
    assert response.media_type == "application/zip"
    assert response.headers["content-disposition"].endswith('.zip"')


@pytest.mark.parametrize("choice", ["default", "both"])
@pytest.mark.parametrize("kind", OPTION_SOURCES)
def test_the_validation_gate_passes_the_export(kind: str, choice: str) -> None:
    """The MFX-20.3 gate: ``smithy validate`` (or the Smithy reader without it), then the re-import."""
    api = _source(kind)
    verdict = asyncio.run(validate_emitted_artifact(_TARGET, _emit(api, OPTIONS[choice]), api=api))
    assert verdict.applicable and verdict.validated and verdict.valid, verdict.errors
