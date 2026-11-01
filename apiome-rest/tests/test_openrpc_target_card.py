"""OpenRPC target card + fixtures — MFX-33.4 (#4304).

What the ``openrpc`` export target shows and writes, pinned in ``fixtures/openrpc_target/outcomes.json``
(regenerate with ``APIOME_REGEN_OPENRPC_TARGET=1``):

* **the card, across paradigms** — the tier the Export dialog, browse and ``apiome export openrpc`` draw for a
  source of each paradigm (:func:`app.export_routes.build_target_fidelity_entries`): REST (OpenAPI, WSDL, RAML),
  RPC (Thrift, Smithy), graph (GraphQL) and data schema (JSON Schema) are ``lossy`` — each with its own preserved
  share; an imported OpenRPC document is ``lossless``;
* **the option** — ``indent`` (default ``2``; ``0`` writes compact JSON). Every pinned choice passes the export
  gate (the OpenRPC meta-schema, ``$ref`` resolution and the re-import, MFX-33.3);
* **browse** — the public ``…/document`` route delivers the ``.openrpc.json`` itself;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-openrpc.json`` and
  ``apiome-ui/tests/fixtures/export-targets-openrpc-{rest,openrpc}.json`` carry the live descriptor, options
  schema, defaults and card badge; ``apiome-cli/tests/fixtures/export-job-completed-openrpc-lossy.json`` carries
  the Petstore export's live fidelity envelope — summary, **report** and advisory — and file name, so the CLI's
  loss table is tested against the real report.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest

from app.catalog_conversion import build_conversion_source
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_routes import build_target_fidelity_entries, render_emitted_document
from app.export_validation import validate_emitted_artifact

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "openrpc_target" / "outcomes.json"
_CLI_FIXTURES = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures"
_CLI_TARGETS = _CLI_FIXTURES / "export-targets-openrpc.json"
_CLI_JOB = _CLI_FIXTURES / "export-job-completed-openrpc-lossy.json"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_OPENRPC_TARGET"))
_TARGET = "openrpc"

#: One corpus source per paradigm (and several of the REST and RPC ones), and OpenRPC sources: the file and
#: the format it is imported as. Every one imports without an external toolchain.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest-openapi": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "rest-wsdl": ("wsdl/02-order-service.wsdl", "wsdl"),
    "rest-raml": ("raml/03-orders-service.raml", "raml"),
    "rpc-thrift": ("thrift/01-user-service.thrift", "thrift"),
    "rpc-smithy": ("smithy/06-orders-service.smithy", "smithy"),
    "graph-graphql": ("graphql/06-union-types.graphql", "graphql"),
    "data-json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "openrpc-wallet": ("openrpc/01-wallet-api.json", "openrpc"),
    "openrpc-refs": ("openrpc/03-components-refs.json", "openrpc"),
}

#: The OpenRPC sources: they export back losslessly.
OPENRPC_KINDS = ("openrpc-wallet", "openrpc-refs")

#: The option choices pinned, and the emit options that pick each.
OPTIONS: Dict[str, Dict[str, Any]] = {
    "default": {},
    "compact": {"indent": 0},
    "indent-4": {"indent": 4},
}

#: The sources whose exports are pinned for every option choice.
OPTION_SOURCES = ("rest-openapi", "openrpc-wallet")


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
    """The pinned facts of one export: its files, tier, preserved share, layout and gate verdict."""
    result = _emit(api, options)
    text = str(result.files[0].content)
    summary = build_export_fidelity(api, get_emitter(_TARGET), options=options or None).summary
    verdict = asyncio.run(validate_emitted_artifact(_TARGET, result, api=api))
    document = json.loads(text)
    return {
        "files": [emitted.path for emitted in result.files],
        "tier": summary.tier.value,
        "preserved_percent": summary.preserved_percent,
        "valid": bool(verdict.valid),
        "lines": len(text.splitlines()),
        "openrpc": document.get("openrpc"),
        "methods": len(document.get("methods") or []),
    }


def _measure() -> Dict[str, Any]:
    return {
        "cards": {kind: {"paradigm": _source(kind).paradigm.value, "tier": _card(_source(kind)).fidelity.tier.value,
                         "preserved_percent": _card(_source(kind)).fidelity.preserved_percent} for kind in SOURCES},
        "options": {kind: {choice: _outcome(_source(kind), options) for choice, options in OPTIONS.items()}
                    for kind in OPTION_SOURCES},
    }


def _targets_body(kind: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to the OpenRPC target."""
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
    _check_recorded(_CLI_TARGETS, _targets_body("rest-openapi"))


@pytest.mark.parametrize("kind", ["rest", "openrpc"])
def test_the_ui_targets_fixtures_are_the_live_registry(kind: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-openrpc-{kind}.json",
                    _targets_body("rest-openapi" if kind == "rest" else "openrpc-wallet"))


def test_the_cli_job_fixture_carries_the_live_report_and_file() -> None:
    """The completed-job envelope the CLI tests replay carries what the Petstore export really reports."""
    if not _CLI_JOB.is_file():
        pytest.skip(f"{_CLI_JOB.parent} is not checked out")
    api = _source("rest-openapi")
    job = json.loads(_CLI_JOB.read_text(encoding="utf-8"))["result"]
    live = build_export_fidelity(api, get_emitter(_TARGET)).model_dump(mode="json")
    assert {key: job["fidelity"][key] for key in ("target", "summary", "report", "advisory")} == {
        key: live[key] for key in ("target", "summary", "report", "advisory")}
    assert [row["path"] for row in job["files"]] == [emitted.path for emitted in _emit(api, {}).files]


@pytest.mark.parametrize("kind", SOURCES)
def test_every_paradigm_is_offered_as_a_single_file_target(kind: str) -> None:
    card = _card(_source(kind))
    assert card.descriptor.available is True and card.descriptor.multi_file is False


@pytest.mark.parametrize("kind", [kind for kind in SOURCES if kind not in OPENRPC_KINDS])
def test_a_source_of_another_format_badges_lossy_with_its_share(kind: str) -> None:
    fidelity = _card(_source(kind)).fidelity
    assert fidelity.tier.value == "lossy" and 0 <= fidelity.preserved_percent < 100


@pytest.mark.parametrize("kind", OPENRPC_KINDS)
def test_an_imported_openrpc_document_badges_lossless(kind: str) -> None:
    assert _card(_source(kind)).fidelity.tier.value == "lossless"


@pytest.mark.parametrize("choice", OPTIONS)
@pytest.mark.parametrize("kind", OPTION_SOURCES)
def test_each_option_choice_writes_a_document_the_gate_accepts(kind: str, choice: str) -> None:
    outcome = _outcome(_source(kind), OPTIONS[choice])
    assert outcome["valid"] is True
    assert len(outcome["files"]) == 1 and outcome["files"][0].endswith(".openrpc.json")
    assert (outcome["lines"] == 1) is (choice == "compact")


def test_the_options_are_in_the_descriptor() -> None:
    card = _card(_source("rest-openapi"))
    assert set(card.options_schema["properties"]) == {"indent"}
    assert card.default_options == {"indent": 2}


def test_browse_delivers_the_openrpc_document_itself() -> None:
    response = render_emitted_document(_source("rest-openapi"), _TARGET, {}, None, bundle_multi_file=True)
    assert response.media_type != "application/zip"
    assert response.headers["content-disposition"].endswith('.openrpc.json"')
    assert "openrpc" in json.loads(response.body.decode("utf-8"))
