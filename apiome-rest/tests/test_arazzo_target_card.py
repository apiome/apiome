"""Arazzo target card + fixtures — MFX-10.4 (#3873).

What the ``arazzo`` export target shows and writes, pinned in ``fixtures/arazzo_target/outcomes.json``
(regenerate with ``APIOME_REGEN_ARAZZO_TARGET=1``):

* **the card, across paradigms** — the tier the Export dialog, browse and ``apiome export arazzo`` draw for a
  source of each paradigm (:func:`app.export_routes.build_target_fidelity_entries`): REST (OpenAPI, WSDL, RAML),
  RPC (Thrift, Smithy) and graph (GraphQL) are ``lossy`` — Arazzo captures workflows, not the full API surface;
  an imported Arazzo document (1.0 or 1.1) is ``lossless``; a data schema (JSON Schema) has nothing to sequence,
  so the card is unavailable with the reason;
* **the warning** — every non-Arazzo report leads with *this target captures workflows, not the full API
  surface* (MFX-10.2);
* **the options** — ``pretty_print`` (default on; off writes flow-style YAML) and ``arazzo_version`` (default:
  the imported version, else 1.0.1). Every pinned choice passes the export gate (the Arazzo JSON Schema and the
  re-import, MFX-10.3);
* **browse** — the public ``…/document`` route delivers the ``.arazzo.yaml`` itself;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-arazzo{,-data}.json`` and
  ``apiome-ui/tests/fixtures/export-targets-arazzo-{rest,arazzo,data}.json`` carry the live descriptor, options
  schema, defaults and card badge; ``apiome-cli/tests/fixtures/export-job-completed-arazzo-lossy.json`` carries
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
import yaml

from app.arazzo_emitter import WORKFLOWS_ONLY_WARNING
from app.catalog_conversion import build_conversion_source
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_routes import build_target_fidelity_entries, render_emitted_document
from app.export_validation import validate_emitted_artifact

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "arazzo_target" / "outcomes.json"
_CLI_FIXTURES = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures"
_CLI_TARGETS = _CLI_FIXTURES / "export-targets-arazzo.json"
_CLI_DATA_TARGETS = _CLI_FIXTURES / "export-targets-arazzo-data.json"
_CLI_JOB = _CLI_FIXTURES / "export-job-completed-arazzo-lossy.json"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_ARAZZO_TARGET"))
_TARGET = "arazzo"

#: One corpus source per paradigm (and several of the REST and RPC ones), and Arazzo sources: the file and the
#: format it is imported as. Every one imports without an external toolchain.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest-openapi": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "rest-wsdl": ("wsdl/02-order-service.wsdl", "wsdl"),
    "rest-raml": ("raml/03-orders-service.raml", "raml"),
    "rpc-thrift": ("thrift/01-user-service.thrift", "thrift"),
    "rpc-smithy": ("smithy/06-orders-service.smithy", "smithy"),
    "graph-graphql": ("graphql/06-union-types.graphql", "graphql"),
    "data-json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "arazzo-1-0": ("arazzo/simple-workflow.yaml", "arazzo"),
    "arazzo-1-1": ("arazzo-1.1/02-typical-checkout-flow.yaml", "arazzo"),
}

#: The Arazzo sources: they export back losslessly.
ARAZZO_KINDS = ("arazzo-1-0", "arazzo-1-1")

#: The sources with nothing to sequence: Arazzo is not offered for them.
UNSEQUENCEABLE_KINDS = ("data-json-schema",)

#: The non-Arazzo sources Arazzo is offered for: lossy, with the workflows-only warning.
SEQUENCED_KINDS = tuple(kind for kind in SOURCES if kind not in ARAZZO_KINDS + UNSEQUENCEABLE_KINDS)

#: The option choices pinned, and the emit options that pick each.
OPTIONS: Dict[str, Dict[str, Any]] = {
    "default": {},
    "flow-style": {"pretty_print": False},
    "version-1-1": {"arazzo_version": "1.1.0"},
}

#: The sources whose exports are pinned for every option choice.
OPTION_SOURCES = ("rest-openapi", "arazzo-1-0")


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
    document = yaml.safe_load(text)
    return {
        "files": [emitted.path for emitted in result.files],
        "tier": summary.tier.value,
        "preserved_percent": summary.preserved_percent,
        "valid": bool(verdict.valid),
        "lines": len(text.splitlines()),
        "arazzo": document.get("arazzo"),
        "workflows": len(document.get("workflows") or []),
        "steps": sum(len(workflow.get("steps") or []) for workflow in document.get("workflows") or []),
    }


def _measure() -> Dict[str, Any]:
    cards = {}
    for kind in SOURCES:
        card = _card(_source(kind))
        cards[kind] = {"paradigm": _source(kind).paradigm.value, "available": card.descriptor.available,
                       "tier": card.fidelity.tier.value, "preserved_percent": card.fidelity.preserved_percent}
    return {
        "cards": cards,
        "options": {kind: {choice: _outcome(_source(kind), options) for choice, options in OPTIONS.items()}
                    for kind in OPTION_SOURCES},
    }


def _targets_body(kind: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to the Arazzo target."""
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
    _check_recorded(_CLI_DATA_TARGETS, _targets_body("data-json-schema"))


@pytest.mark.parametrize(("kind", "source"), [("rest", "rest-openapi"), ("arazzo", "arazzo-1-0"),
                                              ("data", "data-json-schema")])
def test_the_ui_targets_fixtures_are_the_live_registry(kind: str, source: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-arazzo-{kind}.json", _targets_body(source))


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


@pytest.mark.parametrize("kind", [kind for kind in SOURCES if kind not in UNSEQUENCEABLE_KINDS])
def test_a_source_with_operations_is_offered_as_a_single_file_target(kind: str) -> None:
    card = _card(_source(kind))
    assert card.descriptor.available is True and card.descriptor.multi_file is False


@pytest.mark.parametrize("kind", UNSEQUENCEABLE_KINDS)
def test_a_source_with_nothing_to_sequence_is_not_offered_with_the_reason(kind: str) -> None:
    descriptor = _card(_source(kind)).descriptor
    assert descriptor.available is False
    assert "at least one operation to sequence" in (descriptor.unavailable_reason or "")


@pytest.mark.parametrize("kind", SEQUENCED_KINDS)
def test_a_source_of_another_format_badges_lossy(kind: str) -> None:
    fidelity = _card(_source(kind)).fidelity
    assert fidelity.tier.value == "lossy" and 0 <= fidelity.preserved_percent < 100


@pytest.mark.parametrize("kind", SEQUENCED_KINDS)
def test_a_source_of_another_format_leads_with_the_workflows_only_warning(kind: str) -> None:
    items = build_export_fidelity(_source(kind), get_emitter(_TARGET)).report.items
    assert WORKFLOWS_ONLY_WARNING in items[0].message


@pytest.mark.parametrize("kind", ARAZZO_KINDS)
def test_an_imported_arazzo_document_badges_lossless(kind: str) -> None:
    assert _card(_source(kind)).fidelity.tier.value == "lossless"


@pytest.mark.parametrize("choice", OPTIONS)
@pytest.mark.parametrize("kind", OPTION_SOURCES)
def test_each_option_choice_writes_a_document_the_gate_accepts(kind: str, choice: str) -> None:
    outcome = _outcome(_source(kind), OPTIONS[choice])
    assert outcome["valid"] is True
    assert len(outcome["files"]) == 1 and outcome["files"][0].endswith(".arazzo.yaml")
    assert outcome["workflows"] >= 1 and outcome["steps"] >= 1
    assert (outcome["arazzo"] == "1.1.0") is (choice == "version-1-1")


def test_flow_style_writes_fewer_lines_than_the_pretty_default() -> None:
    api = _source("rest-openapi")
    assert _outcome(api, {"pretty_print": False})["lines"] < _outcome(api, {})["lines"]


def test_an_empty_version_field_keeps_the_default_version() -> None:
    """The dialog sends an untouched **Arazzo Version** field as ``""``: that is the default, not an error."""
    outcome = _outcome(_source("rest-openapi"), {"arazzo_version": ""})
    assert outcome["valid"] is True and outcome["arazzo"] == "1.0.1"


def test_the_options_are_in_the_descriptor() -> None:
    card = _card(_source("rest-openapi"))
    assert set(card.options_schema["properties"]) == {"pretty_print", "arazzo_version"}
    assert card.default_options == {"pretty_print": True, "arazzo_version": None}


def test_browse_delivers_the_arazzo_document_itself() -> None:
    response = render_emitted_document(_source("rest-openapi"), _TARGET, {}, None, bundle_multi_file=True)
    assert response.media_type != "application/zip"
    assert response.headers["content-disposition"].endswith('.arazzo.yaml"')
    assert yaml.safe_load(response.body.decode("utf-8"))["arazzo"].startswith("1.")
