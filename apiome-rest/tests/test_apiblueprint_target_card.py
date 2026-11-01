"""API Blueprint target card + fixtures — MFX-18.4 (#3908).

What the ``apiblueprint`` export target shows and writes, pinned in ``fixtures/apiblueprint_target/outcomes.json``
(regenerate with ``APIOME_REGEN_APIBLUEPRINT_TARGET=1``):

* **the card** — the tier the Export dialog, browse and ``apiome export targets`` draw for a source of each
  kind (:func:`app.export_routes.build_target_fidelity_entries`). An imported API Blueprint is written back as
  it was read (``lossless``); a REST, RPC, GraphQL, JSON Schema, WSDL or RAML source is ``lossy``. The
  descriptor positions the target as a human-readable documentation export;
* **MSON constraints** — MSON has no validation facets, so a source's rich constraints (``format``,
  ``minimum`` / ``maximum``, exclusive bounds) are ``DROP`` lines in its report: pinned as the count of
  "MSON has no validation facets" drops per source;
* **the options** — ``include_comments`` (default on) writes the generated-file HTML comment under the API
  title; ``format_version`` (``1A``) is the ``FORMAT`` line; ``media_type`` (default ``application/json``) is
  the media type of a request body whose source names none. Every pinned choice writes one ``.apib`` the
  export gate (drafter, 0 warnings, where installed; else the API Blueprint reader) accepts;
* **browse** — the public ``…/document`` route delivers the ``.apib`` itself (one file, no zip);
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-apiblueprint.json`` and
  ``apiome-ui/tests/fixtures/export-targets-apiblueprint-{rest,apiblueprint}.json`` carry the live descriptor,
  options schema, defaults and card badge; ``apiome-cli/tests/fixtures/export-job-completed-apiblueprint-lossy.json``
  carries the Petstore export's live fidelity (with its report) and file name.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest

from app.apiblueprint_roundtrip import validate_emitted_apiblueprint
from app.catalog_conversion import build_conversion_source
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_routes import build_target_fidelity_entries, render_emitted_document
from app.export_validation import validate_emitted_artifact

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "apiblueprint_target" / "outcomes.json"
_CLI_FIXTURES = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures"
_CLI_TARGETS = _CLI_FIXTURES / "export-targets-apiblueprint.json"
_CLI_JOB = _CLI_FIXTURES / "export-job-completed-apiblueprint-lossy.json"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_APIBLUEPRINT_TARGET"))
_TARGET = "apiblueprint"

#: The report message that marks a constraint MSON cannot express.
MSON_CONSTRAINT_DROP = "MSON has no validation facets"

#: One corpus source per kind: the file and the format it is imported as. Every one imports without an
#: external toolchain, so the fixture is reproducible on any machine.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "rpc": ("thrift/01-user-service.thrift", "thrift"),
    "graphql": ("graphql/06-union-types.graphql", "graphql"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "wsdl": ("wsdl/02-order-service.wsdl", "wsdl"),
    "raml": ("raml/03-orders-service.raml", "raml"),
    "apiblueprint": ("api-blueprint/03-bookstore-service.apib", "apiblueprint"),
}

#: The option choices pinned, and the emit options that pick each.
OPTIONS: Dict[str, Dict[str, Any]] = {
    "default": {},
    "no-comments": {"include_comments": False},
}

#: The sources whose exports are pinned for every option choice.
OPTION_SOURCES = ("rest", "apiblueprint")

#: The fidelity envelope blocks the recorded CLI job carries.
_ENVELOPE_KEYS = ("target", "summary", "report", "advisory")


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


def _mson_constraint_drops(api: Any) -> int:
    """How many ``DROP`` lines of the source's report are constraints MSON cannot express."""
    items = build_export_fidelity(api, get_emitter(_TARGET)).report.items
    return sum(1 for item in items if item.kind.value == "drop" and MSON_CONSTRAINT_DROP in item.message)


def _outcome(api: Any, options: Dict[str, Any]) -> Dict[str, Any]:
    """The pinned facts of one export: its files, tier, preserved share, and what the document carries."""
    result = _emit(api, options)
    text = str(result.files[0].content)
    summary = build_export_fidelity(api, get_emitter(_TARGET), options=options or None).summary
    _, problems = validate_emitted_apiblueprint(result)
    return {
        "files": [emitted.path for emitted in result.files],
        "tier": summary.tier.value,
        "preserved_percent": summary.preserved_percent,
        "problems": [problem["message"] for problem in problems],
        "format_line": text.splitlines()[0],
        "header_comment": "<!-- Generated by Apiome" in text,
    }


def _measure() -> Dict[str, Any]:
    return {
        "cards": {kind: {"available": _card(_source(kind)).descriptor.available,
                         "tier": _card(_source(kind)).fidelity.tier.value,
                         "mson_constraint_drops": _mson_constraint_drops(_source(kind))} for kind in SOURCES},
        "options": {kind: {choice: _outcome(_source(kind), options) for choice, options in OPTIONS.items()}
                    for kind in OPTION_SOURCES},
    }


def _targets_body(kind: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to the API Blueprint target."""
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


@pytest.mark.parametrize("kind", ["rest", "apiblueprint"])
def test_the_ui_targets_fixtures_are_the_live_registry(kind: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-apiblueprint-{kind}.json", _targets_body(kind))


def test_the_cli_job_fixture_carries_the_live_fidelity_and_file() -> None:
    """The completed-job envelope the CLI tests replay reports what the Petstore export really is."""
    if not _CLI_JOB.is_file():
        pytest.skip(f"{_CLI_JOB.parent} is not checked out")
    api = _source("rest")
    job = json.loads(_CLI_JOB.read_text(encoding="utf-8"))["result"]
    live = build_export_fidelity(api, get_emitter(_TARGET)).model_dump(mode="json")
    assert {key: job["fidelity"][key] for key in _ENVELOPE_KEYS} == {key: live[key] for key in _ENVELOPE_KEYS}
    assert [row["path"] for row in job["files"]] == [emitted.path for emitted in _emit(api, {}).files]


@pytest.mark.parametrize("kind", SOURCES)
def test_every_source_is_offered_as_a_single_file_target(kind: str) -> None:
    card = _card(_source(kind))
    assert card.descriptor.available is True and card.descriptor.multi_file is False


def test_the_card_is_positioned_as_a_documentation_export() -> None:
    assert "human-readable docs" in _card(_source("rest")).descriptor.description


def test_an_imported_api_blueprint_badges_lossless() -> None:
    assert _card(_source("apiblueprint")).fidelity.tier.value == "lossless"


def test_a_constrained_source_reports_its_constraints_as_dropped() -> None:
    """The Petstore's formats and bounds have no MSON form; an API Blueprint source has none to lose."""
    assert _mson_constraint_drops(_source("rest")) > 0
    assert _mson_constraint_drops(_source("apiblueprint")) == 0


@pytest.mark.parametrize("choice", OPTIONS)
@pytest.mark.parametrize("kind", OPTION_SOURCES)
def test_each_option_choice_writes_one_apib_document_that_validates(kind: str, choice: str) -> None:
    outcome = _outcome(_source(kind), OPTIONS[choice])
    assert outcome["problems"] == []
    assert [path.rsplit(".", 1)[-1] for path in outcome["files"]] == ["apib"]
    assert outcome["format_line"] == "FORMAT: 1A"
    assert outcome["header_comment"] is (choice != "no-comments")


def test_the_options_are_in_the_descriptor() -> None:
    card = _card(_source("rest"))
    assert set(card.options_schema["properties"]) == {"format_version", "include_comments", "media_type"}
    assert card.default_options == {"format_version": "1A", "include_comments": True,
                                    "media_type": "application/json"}


def test_browse_delivers_the_apib_document_itself() -> None:
    api = _source("rest")
    response = render_emitted_document(api, _TARGET, {}, None, bundle_multi_file=True)
    assert response.media_type != "application/zip"
    assert response.headers["content-disposition"].endswith('.apib"')
    assert response.body.decode("utf-8").startswith("FORMAT: 1A")


@pytest.mark.parametrize("kind", OPTION_SOURCES)
def test_the_validation_gate_passes_the_default_export(kind: str) -> None:
    """The MFX-18.3 gate: drafter with 0 warnings (or the reader without it), then the re-import."""
    api = _source(kind)
    verdict = asyncio.run(validate_emitted_artifact(_TARGET, _emit(api, {}), api=api))
    assert verdict.applicable and verdict.validated and verdict.valid, verdict.errors
