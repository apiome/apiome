"""FIX Orchestra target card + CLI + fixtures — MFX-37.4 (#4326).

What the ``fix-orchestra`` export target (MFX-37.1 emitter, MFX-37.2 fidelity pack, MFX-37.3 validation) shows
and writes on every export surface, pinned in ``fixtures/fix_orchestra_target/outcomes.json`` (regenerate with
``APIOME_REGEN_FIX_ORCHESTRA_TARGET=1``):

* **the card** — per source kind (a REST API, an imported Orchestra repository, a JSON Schema item, a GraphQL
  schema and a gateway configuration): offered with its fidelity tier and preserved share, or greyed out with
  the reason (a gateway configuration has no record type);
* **the export** — writes one ``<name>.orchestra.xml`` that passes the export gate (the official XSD and the
  round trip), with its ``version`` option;
* **browse** — the public ``…/document`` route delivers the repository;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-fix-orchestra.json`` and
  ``apiome-ui/tests/fixtures/export-targets-fix-orchestra-{rest,orchestra,gateway}.json`` carry the live
  descriptor, options schema, defaults and card badge;
  ``apiome-cli/tests/fixtures/export-job-completed-fix-orchestra.json`` carries the Petstore export's live
  fidelity envelope (summary, **report**, advisory) and file name.
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
from app.import_source import load_builtin_import_sources

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "fix_orchestra_target" / "outcomes.json"
_CLI_FIXTURES = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_FIX_ORCHESTRA_TARGET"))
_TARGET = "fix-orchestra"
_ARTIFACT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

#: One corpus source per kind: the file and the format it is imported as.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "orchestra": ("fix-orchestra/02-typical-order-repository.xml", "fix-orchestra"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "graphql": ("graphql/06-union-types.graphql", "graphql"),
    "gateway": ("kong/01-minimal-single-service.yaml", "kong"),
}
#: The exports pinned per source: the default, and an explicit FIX version.
PICKS: Dict[str, Dict[str, Any]] = {"default": {}, "fix-5": {"version": "FIX.5.0SP2"}}
PICK_SOURCES = ("rest", "orchestra", "json-schema")
#: The UI fixtures: a REST API, an imported Orchestra repository, and a source the target cannot export.
UI_SOURCES = ("rest", "orchestra", "gateway")


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


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
    """The pinned facts of one export: its file, tier, preserved share and gate verdict."""
    result = _emit(api, options)
    summary = build_export_fidelity(api, get_emitter(_TARGET), options=options or None).summary
    verdict = asyncio.run(validate_emitted_artifact(_TARGET, result, api=api, options=options))
    return {
        "files": [emitted.path for emitted in result.files],
        "media_type": result.media_type,
        "tier": summary.tier.value,
        "preserved_percent": summary.preserved_percent,
        "valid": bool(verdict.valid),
        "failed": bool(verdict.failed),
    }


def _measure() -> Dict[str, Any]:
    cards = {}
    for kind in SOURCES:
        card = _card(_source(kind))
        cards[kind] = {"available": card.descriptor.available, "tier": card.fidelity.tier.value,
                       "preserved_percent": card.fidelity.preserved_percent}
    picks = {kind: {pick: _outcome(_source(kind), options) for pick, options in PICKS.items()}
             for kind in PICK_SOURCES}
    return {"cards": cards, "picks": picks}


def _targets_body(kind: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to the FIX Orchestra target."""
    card = _card(_source(kind)).model_dump(mode="json")
    return {"artifact": _ARTIFACT, "version": "1.0.0", "targets": [card]}


def _job_body() -> Dict[str, Any]:
    """The completed export-job envelope for the Petstore export (what the CLI replays)."""
    api = _source("rest")
    result = _emit(api, {})
    return {
        "job_id": _JOB_ID,
        "state": "completed",
        "percent": 100,
        "events": [],
        "result": {
            "artifact": _ARTIFACT,
            "version_record_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "version_label": "1.0.0",
            "target": _TARGET,
            "dry_run": False,
            "fidelity": build_export_fidelity(api, get_emitter(_TARGET)).model_dump(mode="json"),
            "files": [{"path": emitted.path, "media_type": emitted.media_type,
                       "size_bytes": len(str(emitted.content).encode("utf-8"))} for emitted in result.files],
            "media_type": result.media_type,
            "download_path": f"/v1/export/acme-corp/jobs/{_JOB_ID}/download",
        },
        "error": None,
    }


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
    _check_recorded(_CLI_FIXTURES / "export-targets-fix-orchestra.json", _targets_body("rest"))


def test_the_cli_job_fixture_carries_the_live_report_and_file() -> None:
    _check_recorded(_CLI_FIXTURES / "export-job-completed-fix-orchestra.json", _job_body())


@pytest.mark.parametrize("kind", UI_SOURCES)
def test_the_ui_targets_fixtures_are_the_live_registry(kind: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-fix-orchestra-{kind}.json", _targets_body(kind))


# ===========================================================================
# The card
# ===========================================================================


@pytest.mark.parametrize("kind", ["rest", "orchestra", "json-schema", "graphql"])
def test_every_typed_source_offers_the_card_with_its_tier(kind: str) -> None:
    card = _card(_source(kind))
    assert card.descriptor.available and card.fidelity.tier.value
    assert card.descriptor.label == "FIX Orchestra" and card.descriptor.paradigm == "data_schema"
    assert card.descriptor.multi_file is False


def test_an_orchestra_source_badges_better_than_a_rest_api() -> None:
    orchestra, rest = _card(_source("orchestra")).fidelity, _card(_source("rest")).fidelity
    assert orchestra.preserved_percent > rest.preserved_percent


def test_a_source_with_no_record_type_is_greyed_out() -> None:
    card = _card(_source("gateway"))
    assert card.descriptor.available is False
    assert "at least one record type" in (card.descriptor.unavailable_reason or "")


def test_the_options_offer_the_version_and_hide_the_stored_tags() -> None:
    schema = _card(_source("rest")).options_schema
    assert "version" in schema["properties"]
    assert "persisted_field_numbers" not in schema["properties"]


# ===========================================================================
# The export: written, through the gate, delivered
# ===========================================================================


@pytest.mark.parametrize("pick", PICKS)
@pytest.mark.parametrize("kind", PICK_SOURCES)
def test_each_export_writes_one_repository_the_gate_accepts(kind: str, pick: str) -> None:
    outcome = _outcome(_source(kind), PICKS[pick])
    assert outcome["valid"] and not outcome["failed"], outcome
    assert len(outcome["files"]) == 1 and outcome["files"][0].endswith(".orchestra.xml")


def test_the_version_option_reaches_the_repository() -> None:
    text = str(_emit(_source("rest"), {"version": "FIX.5.0SP2"}).files[0].content)
    assert 'version="FIX.5.0SP2"' in text


def test_browse_delivers_the_repository() -> None:
    response = render_emitted_document(_source("rest"), _TARGET, {}, None, bundle_multi_file=True)
    assert response.media_type.startswith("application/xml")
    assert b"fixr:repository" in response.body
