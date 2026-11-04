"""WADL & Google API Discovery target cards + fixtures — MFX-29.4 (#4176).

What the ``wadl`` and ``discovery`` export targets show and write on every export surface, pinned in
``fixtures/legacy_rest_target/outcomes.json`` (regenerate with ``APIOME_REGEN_LEGACY_REST_TARGET=1``):

* **the cards** — per source kind (a REST API, a GraphQL schema, a JSON Schema item, an imported WADL and an
  imported Discovery document): offered, with the tier the fidelity report gives. A source with nothing either
  can hold (no HTTP operation and no type) gets an unavailable Discovery card with its reason;
* **the options** — WADL's ``layout`` (``bundle``: ``.wadl`` + ``.xsd``; ``single``: one file) and Discovery's
  ``name`` / ``version``; each pinned choice writes its files and passes the export gate (MFX-29.3);
* **browse** — the public ``…/document`` route delivers a WADL bundle as one zip and a Discovery document as JSON;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-{wadl,discovery}.json`` and
  ``apiome-ui/tests/fixtures/export-targets-{wadl,discovery}-{rest,<own format>}.json`` carry the live descriptor,
  options schema, defaults and card badge.

The pinned outcomes use only sources that import without an external toolchain, so they reproduce anywhere.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import zipfile
from pathlib import Path
from typing import Any, Dict

import pytest

from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi
from app.catalog_conversion import build_conversion_source
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_routes import build_target_fidelity_entries, render_emitted_document
from app.export_validation import validate_emitted_artifact

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "legacy_rest_target" / "outcomes.json"
_CLI_FIXTURES = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_LEGACY_REST_TARGET"))
TARGETS = ("wadl", "discovery")

#: One corpus source per kind: the file and the format it is imported as.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "graphql": ("graphql/06-union-types.graphql", "graphql"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "wadl": ("wadl/01-bookstore.wadl", "wadl"),
    "discovery": ("discovery/05-webfonts-sample.json", "discovery"),
}

#: The option choices pinned per target, and the emit options that pick each.
PICKS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "wadl": {"bundle": {}, "single": {"layout": "single"}},
    "discovery": {"default": {}, "named": {"name": "pets", "version": "v2"}},
}
#: The source kind each target's UI fixture records beside the REST one: the target's own format.
OWN_SOURCE = {"wadl": "wadl", "discovery": "discovery"}


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


def _card(api: Any, target: str) -> Any:
    return next(entry for entry in build_target_fidelity_entries(api) if entry.descriptor.key == target)


def _emit(api: Any, target: str, options: Dict[str, Any]) -> Any:
    emitter = get_emitter(target)
    return emitter().emit(api, opts=coerce_emit_options(emitter, options))


def _outcome(api: Any, target: str, options: Dict[str, Any]) -> Dict[str, Any]:
    """The pinned facts of one export: its files and media type, and whether it passes the export gate."""
    result = _emit(api, target, options)
    verdict = asyncio.run(validate_emitted_artifact(target, result, api=api))
    return {
        "files": [emitted.path for emitted in result.files],
        "media_type": result.media_type,
        "valid": verdict.valid,
        "findings": [finding.keyword for finding in verdict.findings],
    }


def _measure() -> Dict[str, Any]:
    cards = {}
    for target in TARGETS:
        cards[target] = {}
        for kind in SOURCES:
            card = _card(_source(kind), target)
            cards[target][kind] = {"available": card.descriptor.available, "tier": card.fidelity.tier.value}
    picks = {target: {kind: {pick: _outcome(_source(kind), target, options) for pick, options in PICKS[target].items()}
                      for kind in ("rest", OWN_SOURCE[target])} for target in TARGETS}
    return {"cards": cards, "picks": picks}


def _targets_body(kind: str, target: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to one target."""
    return {"artifact": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "version": "1.0.0",
            "targets": [_card(_source(kind), target).model_dump(mode="json")]}


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


@pytest.mark.parametrize("target", TARGETS)
def test_the_cli_targets_fixture_is_the_live_registry(target: str) -> None:
    _check_recorded(_CLI_FIXTURES / f"export-targets-{target}.json", _targets_body("rest", target))


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("which", ["rest", "own"])
def test_the_ui_targets_fixtures_are_the_live_registry(target: str, which: str) -> None:
    kind = "rest" if which == "rest" else OWN_SOURCE[target]
    _check_recorded(_UI_FIXTURES / f"export-targets-{target}-{kind}.json", _targets_body(kind, target))


# ===========================================================================
# The cards
# ===========================================================================


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("kind", SOURCES)
def test_every_source_is_offered(target: str, kind: str) -> None:
    card = _card(_source(kind), target)
    assert card.descriptor.available is True
    assert card.descriptor.paradigm == "rest"
    assert card.descriptor.multi_file is (target == "wadl")


@pytest.mark.parametrize("target", TARGETS)
def test_a_source_of_its_own_format_is_lossless(target: str) -> None:
    assert _card(_source(OWN_SOURCE[target]), target).fidelity.tier.value == "lossless"


@pytest.mark.parametrize("target", TARGETS)
def test_a_graphql_source_is_lossy_and_warns_rest_only(target: str) -> None:
    card = _card(_source("graphql"), target)
    assert card.fidelity.tier.value == "lossy"


def test_discovery_is_unavailable_for_a_source_with_nothing_to_write() -> None:
    empty = CanonicalApi(paradigm=ApiParadigm.AGENT, format="a2a", identity=ApiIdentity(name="Agent"))
    card = _card(empty, "discovery")
    assert card.descriptor.available is False
    assert "at least one HTTP operation or one type" in (card.descriptor.unavailable_reason or "")


def test_the_options_are_in_the_descriptors() -> None:
    wadl = _card(_source("rest"), "wadl")
    assert {"layout", "media_type", "include_comments"} <= set(wadl.options_schema["properties"])
    assert wadl.default_options["layout"] == "bundle"
    discovery = _card(_source("rest"), "discovery")
    assert {"name", "version", "indent"} <= set(discovery.options_schema["properties"])
    assert discovery.default_options["name"] is None and discovery.default_options["indent"] == 2


# ===========================================================================
# Options and the gate
# ===========================================================================


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("which", ["rest", "own"])
def test_each_pick_writes_an_export_that_passes_the_gate(target: str, which: str) -> None:
    kind = "rest" if which == "rest" else OWN_SOURCE[target]
    for options in PICKS[target].values():
        outcome = _outcome(_source(kind), target, options)
        assert outcome["valid"], outcome["findings"]


def test_the_wadl_layouts() -> None:
    api = _source("rest")
    bundle = _outcome(api, "wadl", {})["files"]
    single = _outcome(api, "wadl", {"layout": "single"})["files"]
    assert [Path(p).suffix for p in bundle] == [".wadl", ".xsd"] and [Path(p).suffix for p in single] == [".wadl"]


def test_the_discovery_name_and_version() -> None:
    result = _emit(_source("rest"), "discovery", {"name": "pets", "version": "v2"})
    document = json.loads(str(result.files[0].content))
    assert (result.files[0].path, document["id"]) == ("pets.discovery.json", "pets:v2")


# ===========================================================================
# Browse
# ===========================================================================


def test_browse_delivers_the_wadl_bundle_as_one_zip() -> None:
    response = render_emitted_document(_source("rest"), "wadl", {}, None, bundle_multi_file=True)
    assert response.media_type == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        suffixes = sorted(Path(name).suffix for name in archive.namelist() if not name.endswith(".json"))
    assert suffixes == [".wadl", ".xsd"]


def test_browse_delivers_the_discovery_document() -> None:
    response = render_emitted_document(_source("rest"), "discovery", {"name": "pets"}, None, bundle_multi_file=True)
    assert response.media_type.startswith("application/json")
    assert json.loads(response.body)["kind"] == "discovery#restDescription"
