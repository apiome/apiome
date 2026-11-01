"""OMG IDL target card + fixtures — MFX-28.4 (#4171).

What the ``corbaidl`` export target shows and writes, pinned in ``fixtures/corbaidl_target/outcomes.json``
(regenerate with ``APIOME_REGEN_CORBAIDL_TARGET=1``):

* **the card** — the tier the Export dialog, browse and ``apiome export idl`` draw for a source of each kind
  (:func:`app.export_routes.build_target_fidelity_entries`). An imported CORBA IDL is written back as it was
  read (``lossless`` — its member positions are its field numbers, kept in order); a REST, RPC, GraphQL,
  JSON Schema, WSDL, RAML or Smithy source is ``lossy``;
* **the profile option** — ``profile`` (default ``corba``) writes interfaces and exceptions, checked by
  ``omniidl``; ``dds`` writes the topic-friendly data-type subset (no interfaces) with ``@key`` on identifier
  fields (or the ``key_fields`` chosen), checked by Cyclone DDS ``idlc``. ``module`` names the module and
  ``include_comments`` the header comment. Every pinned choice re-parses through the OMG IDL reader
  (:func:`app.corbaidl_emitter.validate_corbaidl_document`);
* **browse** — the public ``…/document`` route delivers the ``.idl`` itself;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-corbaidl.json`` and
  ``apiome-ui/tests/fixtures/export-targets-corbaidl-{rest,corbaidl}.json`` carry the live descriptor, options
  schema, defaults and card badge; ``apiome-cli/tests/fixtures/export-job-completed-corbaidl-lossy.json``
  carries the live fidelity summary and file name of the Petstore export.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest

from app.catalog_conversion import build_conversion_source
from app.corbaidl_emitter import validate_corbaidl_document
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_routes import build_target_fidelity_entries, render_emitted_document
from app.export_validation import validate_emitted_artifact
from app.omg_idl_compile import idl_compiler_for

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "corbaidl_target" / "outcomes.json"
_CLI_FIXTURES = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures"
_CLI_TARGETS = _CLI_FIXTURES / "export-targets-corbaidl.json"
_CLI_JOB = _CLI_FIXTURES / "export-job-completed-corbaidl-lossy.json"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_CORBAIDL_TARGET"))
_TARGET = "corbaidl"

#: One corpus source per kind, and three CORBA IDL sources: the file and the format it is imported as.
#: Every one imports without an external toolchain, so the fixture is reproducible on any machine.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "rpc": ("thrift/01-user-service.thrift", "thrift"),
    "graphql": ("graphql/06-union-types.graphql", "graphql"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "wsdl": ("wsdl/02-order-service.wsdl", "wsdl"),
    "raml": ("raml/03-orders-service.raml", "raml"),
    "smithy": ("smithy/06-orders-service.smithy", "smithy"),
    "idl-bank": ("corba-idl/01-bank.idl", "corbaidl"),
    "idl-nested": ("corba-idl/04-nested-modules.idl", "corbaidl"),
    "idl-stress": ("corba-idl/05-trading-stress.idl", "corbaidl"),
}

#: The kinds imported from CORBA IDL: they export back losslessly.
IDL_KINDS = ("idl-bank", "idl-nested", "idl-stress")

#: The option choices pinned, and the emit options that pick each.
OPTIONS: Dict[str, Dict[str, Any]] = {
    "default": {},
    "dds": {"profile": "dds"},
    "dds-keys": {"profile": "dds", "key_fields": {"Pet": ["name"]}},
    "module": {"module": "acme::pets"},
    "no-comments": {"include_comments": False},
}

#: The sources whose exports are pinned for every option choice.
OPTION_SOURCES = ("rest", "idl-bank")


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


def _reparses(text: str) -> bool:
    try:
        validate_corbaidl_document(text)
    except Exception:  # noqa: BLE001 - any reader failure means "does not re-parse"
        return False
    return True


def _outcome(api: Any, options: Dict[str, Any]) -> Dict[str, Any]:
    """The pinned facts of one export: its files, tier, preserved share, and what the document carries."""
    result = _emit(api, options)
    text = str(result.files[0].content)
    summary = build_export_fidelity(api, get_emitter(_TARGET), options=options or None).summary
    return {
        "files": [emitted.path for emitted in result.files],
        "tier": summary.tier.value,
        "preserved_percent": summary.preserved_percent,
        "reparses": _reparses(text),
        "compiler": idl_compiler_for(text),
        "interfaces": text.count("interface "),
        "keys": [line.strip() for line in text.splitlines() if "@key" in line],
        "modules": [line.strip() for line in text.splitlines() if line.strip().startswith("module ")],
        "header_comment": text.startswith("//"),
    }


def _measure() -> Dict[str, Any]:
    return {
        "cards": {kind: {"available": _card(_source(kind)).descriptor.available,
                         "tier": _card(_source(kind)).fidelity.tier.value} for kind in SOURCES},
        "options": {kind: {choice: _outcome(_source(kind), options) for choice, options in OPTIONS.items()}
                    for kind in OPTION_SOURCES},
    }


def _targets_body(kind: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to the OMG IDL target."""
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


@pytest.mark.parametrize("kind", ["rest", "corbaidl"])
def test_the_ui_targets_fixtures_are_the_live_registry(kind: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-corbaidl-{kind}.json",
                    _targets_body("rest" if kind == "rest" else "idl-bank"))


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


@pytest.mark.parametrize("kind", IDL_KINDS)
def test_an_imported_corba_idl_badges_lossless(kind: str) -> None:
    """Its field numbers are member positions the writer keeps — not reported as dropped (MFX-28.4)."""
    assert _card(_source(kind)).fidelity.tier.value == "lossless"


@pytest.mark.parametrize("choice", OPTIONS)
@pytest.mark.parametrize("kind", OPTION_SOURCES)
def test_each_option_choice_writes_idl_the_reader_parses(kind: str, choice: str) -> None:
    outcome = _outcome(_source(kind), OPTIONS[choice])
    assert outcome["reparses"] is True
    assert [path.rsplit(".", 1)[-1] for path in outcome["files"]] == ["idl"]
    assert outcome["header_comment"] is (choice != "no-comments")
    dds = choice.startswith("dds")
    assert outcome["compiler"] == ("idlc" if dds else "omniidl")
    if dds:
        assert outcome["interfaces"] == 0 and outcome["keys"]


def test_the_dds_profile_keys_the_chosen_fields() -> None:
    assert any("@key" in line and "name" in line for line in _outcome(_source("rest"), OPTIONS["dds-keys"])["keys"])


def test_the_module_option_names_the_module() -> None:
    assert _outcome(_source("rest"), OPTIONS["module"])["modules"][:2] == ["module acme {", "module pets {"]


def test_the_options_are_in_the_descriptor() -> None:
    card = _card(_source("rest"))
    assert set(card.options_schema["properties"]) == {"include_comments", "key_fields", "module", "profile"}
    assert card.options_schema["properties"]["profile"]["enum"] == ["corba", "dds"]
    assert card.default_options == {"include_comments": True, "key_fields": {}, "module": None, "profile": "corba"}


def test_browse_delivers_the_idl_itself() -> None:
    response = render_emitted_document(_source("rest"), _TARGET, {}, None, bundle_multi_file=True)
    assert response.media_type != "application/zip"
    assert response.headers["content-disposition"].endswith('.idl"')
    assert "module " in response.body.decode("utf-8")


@pytest.mark.parametrize("choice", ["default", "dds"])
@pytest.mark.parametrize("kind", OPTION_SOURCES)
def test_the_validation_gate_passes_the_export(kind: str, choice: str) -> None:
    """The MFX-28.3 gate: omniidl / idlc where installed, and the OMG IDL reader's re-parse."""
    api = _source(kind)
    verdict = asyncio.run(validate_emitted_artifact(_TARGET, _emit(api, OPTIONS[choice]), api=api))
    assert verdict.applicable and verdict.validated and verdict.valid, verdict.errors
