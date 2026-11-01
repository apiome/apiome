"""RAML target card + fixtures — MFX-17.4 (#3904).

What the ``raml`` export target shows and writes, pinned in ``fixtures/raml_target/outcomes.json``
(regenerate with ``APIOME_REGEN_RAML_TARGET=1``):

* **the card** — the tier the Export dialog, browse and ``apiome export targets`` draw for a source of each
  kind (:func:`app.export_routes.build_target_fidelity_entries`). An imported RAML API is written back as it
  was read (``lossless``); a REST, RPC, GraphQL, JSON Schema or WSDL source is ``lossy``;
* **the REST-only warning** — RAML is a legacy, REST-only target: the fidelity report of every source that is
  not a REST API (RPC, GraphQL, JSON Schema) leads with :data:`app.raml_emitter.REST_ONLY_WARNING` ("RAML
  captures REST only"), and a REST source's report (OpenAPI, RAML, WSDL) does not carry it;
* **the options** — ``include_comments`` (default on) writes the generated-file comment under the
  ``#%RAML 1.0`` header; ``media_type`` (default ``application/json``) is the document ``mediaType`` when the
  source names none. Every pinned choice writes one ``.raml`` the export gate (AMF where installed, else the
  RAML reader) accepts;
* **browse** — the public ``…/document`` route delivers the ``.raml`` itself (one file, no zip);
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-raml.json`` and
  ``apiome-ui/tests/fixtures/export-targets-raml-{rest,raml,graphql}.json`` carry the live descriptor,
  options schema, defaults and card badge; ``apiome-cli/tests/fixtures/export-job-completed-raml-lossy.json``
  carries the Petstore export's live fidelity summary and file name, and
  ``export-job-completed-raml-graphql-lossy.json`` / ``apiome-ui/tests/fixtures/export-preview-raml-graphql.json``
  the GraphQL source's live report with its REST-only warning.
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
from app.raml_emitter import REST_ONLY_WARNING
from app.raml_roundtrip import validate_emitted_raml

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "raml_target" / "outcomes.json"
_CLI_FIXTURES = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures"
_CLI_TARGETS = _CLI_FIXTURES / "export-targets-raml.json"
_CLI_JOB = _CLI_FIXTURES / "export-job-completed-raml-lossy.json"
_CLI_GRAPHQL_JOB = _CLI_FIXTURES / "export-job-completed-raml-graphql-lossy.json"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_UI_GRAPHQL_PREVIEW = _UI_FIXTURES / "export-preview-raml-graphql.json"
_REGEN = bool(os.environ.get("APIOME_REGEN_RAML_TARGET"))
_TARGET = "raml"

#: One corpus source per kind: the file and the format it is imported as. Every one imports without an
#: external toolchain, so the fixture is reproducible on any machine.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "rpc": ("thrift/01-user-service.thrift", "thrift"),
    "graphql": ("graphql/06-union-types.graphql", "graphql"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "wsdl": ("wsdl/02-order-service.wsdl", "wsdl"),
    "raml": ("raml/03-orders-service.raml", "raml"),
}

#: The source kinds that are REST APIs: their reports carry no REST-only warning. A WSDL import is a REST
#: API too (its operations are bound to HTTP endpoints), so RAML writes it without the warning.
REST_KINDS = frozenset({"rest", "raml", "wsdl"})

#: The option choices pinned, and the emit options that pick each.
OPTIONS: Dict[str, Dict[str, Any]] = {
    "default": {},
    "no-comments": {"include_comments": False},
    "xml-media-type": {"media_type": "application/xml"},
}

#: The sources whose exports are pinned for every option choice. The JSON Schema source has no bodies, so
#: ``media_type`` names its document ``mediaType``; the other two name theirs from the source.
OPTION_SOURCES = ("rest", "raml", "json-schema")

#: The fidelity envelope blocks the recorded GraphQL job and preview carry.
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


def _rest_only_warned(api: Any) -> bool:
    """Whether the first item of the source's RAML fidelity report is the REST-only warning."""
    items = build_export_fidelity(api, get_emitter(_TARGET)).report.items
    return bool(items) and REST_ONLY_WARNING in items[0].message


def _outcome(api: Any, options: Dict[str, Any]) -> Dict[str, Any]:
    """The pinned facts of one export: its files, tier, preserved share, and what the document carries."""
    result = _emit(api, options)
    text = str(result.files[0].content)
    summary = build_export_fidelity(api, get_emitter(_TARGET), options=options or None).summary
    _, violations = validate_emitted_raml(result)
    return {
        "files": [emitted.path for emitted in result.files],
        "tier": summary.tier.value,
        "preserved_percent": summary.preserved_percent,
        "violations": [violation["message"] for violation in violations],
        "header_comment": text.splitlines()[1].startswith("# Generated by Apiome") if "\n" in text else False,
        "media_type_line": next((line for line in text.splitlines() if line.startswith("mediaType:")), None),
    }


def _measure() -> Dict[str, Any]:
    return {
        "cards": {kind: {"available": _card(_source(kind)).descriptor.available,
                         "tier": _card(_source(kind)).fidelity.tier.value,
                         "rest_only_warning": _rest_only_warned(_source(kind))} for kind in SOURCES},
        "options": {kind: {choice: _outcome(_source(kind), options) for choice, options in OPTIONS.items()}
                    for kind in OPTION_SOURCES},
    }


def _targets_body(kind: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to the RAML target."""
    return {"artifact": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "version": "1.0.0",
            "targets": [_card(_source(kind)).model_dump(mode="json")]}


def _envelope(kind: str) -> Dict[str, Any]:
    """The ``kind`` source's live RAML fidelity envelope, cut to the blocks the CLI and the dialog read."""
    fidelity = build_export_fidelity(_source(kind), get_emitter(_TARGET)).model_dump(mode="json")
    return {key: fidelity[key] for key in _ENVELOPE_KEYS}


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


@pytest.mark.parametrize("kind", ["rest", "raml", "graphql"])
def test_the_ui_targets_fixtures_are_the_live_registry(kind: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-raml-{kind}.json", _targets_body(kind))


def test_the_ui_graphql_preview_is_the_live_envelope() -> None:
    _check_recorded(_UI_GRAPHQL_PREVIEW, _envelope("graphql"))


def test_the_cli_job_fixture_carries_the_live_fidelity_and_file() -> None:
    """The completed-job envelope the CLI tests replay reports what the Petstore export really is."""
    if not _CLI_JOB.is_file():
        pytest.skip(f"{_CLI_JOB.parent} is not checked out")
    api = _source("rest")
    job = json.loads(_CLI_JOB.read_text(encoding="utf-8"))["result"]
    live = build_export_fidelity(api, get_emitter(_TARGET)).summary.model_dump(mode="json")
    assert job["fidelity"]["summary"] == live
    assert [row["path"] for row in job["files"]] == [emitted.path for emitted in _emit(api, {}).files]


def test_the_cli_graphql_job_fixture_carries_the_live_report() -> None:
    """The GraphQL job the CLI replays carries the live report, REST-only warning first."""
    if not _CLI_GRAPHQL_JOB.is_file():
        pytest.skip(f"{_CLI_GRAPHQL_JOB.parent} is not checked out")
    job = json.loads(_CLI_GRAPHQL_JOB.read_text(encoding="utf-8"))["result"]
    assert {key: job["fidelity"][key] for key in _ENVELOPE_KEYS} == _envelope("graphql")
    assert [row["path"] for row in job["files"]] == [emitted.path for emitted in _emit(_source("graphql"), {}).files]


@pytest.mark.parametrize("kind", SOURCES)
def test_every_source_is_offered_as_a_single_file_target(kind: str) -> None:
    card = _card(_source(kind))
    assert card.descriptor.available is True and card.descriptor.multi_file is False


def test_an_imported_raml_api_badges_lossless() -> None:
    assert _card(_source("raml")).fidelity.tier.value == "lossless"


@pytest.mark.parametrize("kind", SOURCES)
def test_a_non_rest_source_leads_with_the_rest_only_warning(kind: str) -> None:
    assert _rest_only_warned(_source(kind)) is (kind not in REST_KINDS)


@pytest.mark.parametrize("choice", OPTIONS)
@pytest.mark.parametrize("kind", OPTION_SOURCES)
def test_each_option_choice_writes_one_raml_document_that_validates(kind: str, choice: str) -> None:
    outcome = _outcome(_source(kind), OPTIONS[choice])
    assert outcome["violations"] == []
    assert [path.rsplit(".", 1)[-1] for path in outcome["files"]] == ["raml"]
    assert outcome["header_comment"] is (choice != "no-comments")


def test_the_media_type_option_applies_only_when_the_source_names_none() -> None:
    """A source with no bodies takes the option; the Petstore and RAML bodies name ``application/json``."""
    for kind, expected in (("json-schema", "application/xml"), ("rest", "application/json"),
                           ("raml", "application/json")):
        outcome = _outcome(_source(kind), OPTIONS["xml-media-type"])
        assert outcome["media_type_line"] == f"mediaType: {expected}"


def test_the_options_are_in_the_descriptor() -> None:
    card = _card(_source("rest"))
    assert set(card.options_schema["properties"]) == {"include_comments", "media_type"}
    assert card.default_options == {"include_comments": True, "media_type": "application/json"}


def test_browse_delivers_the_raml_document_itself() -> None:
    api = _source("rest")
    response = render_emitted_document(api, _TARGET, {}, None, bundle_multi_file=True)
    assert response.media_type != "application/zip"
    assert response.headers["content-disposition"].endswith('.raml"')
    assert response.body.decode("utf-8").startswith("#%RAML 1.0")


@pytest.mark.parametrize("kind", OPTION_SOURCES)
def test_the_validation_gate_passes_the_default_export(kind: str) -> None:
    """The MFX-17.3 gate: AMF (or the RAML reader without it), then the re-import."""
    api = _source(kind)
    verdict = asyncio.run(validate_emitted_artifact(_TARGET, _emit(api, {}), api=api))
    assert verdict.applicable and verdict.validated and verdict.valid, verdict.errors
