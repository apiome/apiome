"""JSON Schema target card + fixtures — MFX-21.5 (#4130).

What the ``json-schema`` export target shows and writes, pinned in ``fixtures/jsonschema_target/``
(regenerate with ``APIOME_REGEN_JSONSCHEMA_TARGET=1``):

* **the card** — the tier the Export dialog, browse and ``apiome export targets`` draw for a source of
  each kind (:func:`app.export_routes.build_target_fidelity_entries`). An operation-bearing source (a REST
  API, an RPC service) is ``types-only``: its operations are dropped. A JSON Schema item exported again is
  ``lossless`` — JSON Schema names its properties and has no field numbers, so none are "synthesized";
* **the output modes** — one 2020-12 bundle, one file per type, and the draft-07 / draft-04 downgrades,
  each written as the files the export delivers (``<source>/<mode>/<file>``) and each valid against its
  metaschema and importing again (:func:`app.jsonschema_roundtrip.round_trip_jsonschema`);
* **browse** — the public ``…/document`` route delivers a per-type export as a zip of every file;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-json-schema.json`` and
  ``apiome-ui/tests/fixtures/export-targets-json-schema-{rest,json-schema}.json`` carry the live
  descriptor, options schema, defaults and card badge, so the CLI and Export-dialog tests run against what
  the registry really lists.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.catalog_conversion import build_conversion_source
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_routes import build_target_fidelity_entries, render_emitted_document
from app.jsonschema_roundtrip import round_trip_jsonschema

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "jsonschema_target"
_CLI_TARGETS = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures" / "export-targets-json-schema.json"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_JSONSCHEMA_TARGET"))

#: One corpus source per kind: the file, and the format it is imported as.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "rpc": ("protobuf/02-grpc-service.proto", "protobuf"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
}

#: The output modes the fixtures cover, and the emit options that select each.
MODES: Dict[str, Dict[str, Any]] = {
    "bundle": {},
    "per-type": {"packaging": "per-type"},
    "draft-07": {"draft": "draft-07"},
    "draft-04": {"draft": "draft-04"},
}

#: The sources whose emitted files are kept as fixtures (the RPC source is pinned by its card only).
WRITTEN_SOURCES = ("rest", "json-schema")


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()


def _source(kind: str) -> Any:
    """The canonical model of the corpus source for ``kind``, imported as the catalog would."""
    path, fmt = SOURCES[kind]
    file = _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": file.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}
    ).api


def _card(api: Any, key: str = "json-schema") -> Any:
    """The registry entry (descriptor + badge) the targets route lists for ``key``."""
    return next(entry for entry in build_target_fidelity_entries(api) if entry.descriptor.key == key)


def _emit(api: Any, options: Dict[str, Any]) -> Any:
    emitter = get_emitter("json-schema")
    return emitter().emit(api, opts=coerce_emit_options(emitter, options))


def _outcome(api: Any, options: Dict[str, Any]) -> Dict[str, Any]:
    """The pinned facts of one export: its files, losses, preview tier and round trip."""
    result = _emit(api, options)
    fidelity = build_export_fidelity(api, get_emitter("json-schema"), options=options or None)
    report = round_trip_jsonschema(api, opts=coerce_emit_options(get_emitter("json-schema"), options),
                                   emit_result=result)
    return {
        "files": [emitted.path for emitted in result.files],
        "loss_subjects": sorted({loss.subject for loss in result.losses}),
        "tier": fidelity.summary.tier.value,
        "valid": report.valid,
        "problems": [problem["rule"] for problem in report.problems],
    }


def _measure() -> Dict[str, Any]:
    """Every source's card, and each written source's outcome in every mode."""
    measured: Dict[str, Any] = {}
    for kind in SOURCES:
        api = _source(kind)
        card = _card(api)
        measured[kind] = {
            "card": {"available": card.descriptor.available, "tier": card.fidelity.tier.value},
            "modes": {mode: _outcome(api, options) for mode, options in MODES.items()}
            if kind in WRITTEN_SOURCES else {},
        }
    return measured


def _written_files() -> Dict[str, str]:
    """``<source>/<mode>/<file>`` → the text the export writes, for each written source and mode."""
    files: Dict[str, str] = {}
    for kind in WRITTEN_SOURCES:
        api = _source(kind)
        for mode, options in MODES.items():
            for emitted in _emit(api, options).files:
                files[f"{kind}/{mode}/{emitted.path}"] = emitted.content
    return files


def _targets_body(kind: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to the JSON Schema family."""
    api = _source(kind)
    entries = [entry.model_dump(mode="json") for entry in build_target_fidelity_entries(api)
               if entry.descriptor.key in ("json-schema", "jtd")]
    return {"artifact": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "version": "1.0.0", "targets": entries}


def _check_recorded(path: Path, live: Dict[str, Any]) -> None:
    """``path`` holds ``live`` (written first under regen); skipped when that package is not checked out."""
    if _REGEN and path.parent.is_dir():
        path.write_text(json.dumps(live, indent=2) + "\n", encoding="utf-8")
    if not path.is_file():
        pytest.skip(f"{path.parent} is not checked out")
    assert json.loads(path.read_text(encoding="utf-8")) == live


def test_the_outcomes_match_the_fixture() -> None:
    measured = _measure()
    golden = _GOLDEN / "outcomes.json"
    if _REGEN:
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert measured == json.loads(golden.read_text(encoding="utf-8"))


def test_the_written_files_match_the_fixtures() -> None:
    files = _written_files()
    if _REGEN:
        for kind in WRITTEN_SOURCES:
            shutil.rmtree(_GOLDEN / kind, ignore_errors=True)
        for name, text in files.items():
            (_GOLDEN / name).parent.mkdir(parents=True, exist_ok=True)
            (_GOLDEN / name).write_text(text, encoding="utf-8")
    on_disk = {
        str(path.relative_to(_GOLDEN)): path.read_text(encoding="utf-8")
        for kind in WRITTEN_SOURCES for path in sorted((_GOLDEN / kind).rglob("*.json"))
    }
    assert on_disk == files


def test_the_cli_targets_fixture_is_the_live_registry() -> None:
    _check_recorded(_CLI_TARGETS, _targets_body("rest"))


@pytest.mark.parametrize("kind", ["rest", "json-schema"])
def test_the_ui_targets_fixtures_are_the_live_registry(kind: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-json-schema-{kind}.json", _targets_body(kind))


@pytest.mark.parametrize("kind", ["rest", "rpc"])
def test_an_operation_bearing_source_badges_types_only(kind: str) -> None:
    card = _card(_source(kind))
    assert card.descriptor.available is True
    assert card.fidelity.tier.value == "types-only"
    assert card.fidelity.dropped > 0


def test_a_json_schema_item_badges_lossless() -> None:
    card = _card(_source("json-schema"))
    assert card.fidelity.tier.value == "lossless"
    assert card.fidelity.synthesized == 0


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("kind", WRITTEN_SOURCES)
def test_every_mode_writes_valid_json_schema_that_imports_again(kind: str, mode: str) -> None:
    outcome = _outcome(_source(kind), MODES[mode])
    assert outcome["valid"], outcome["problems"]


def test_per_type_writes_one_file_per_type() -> None:
    api = _source("json-schema")
    paths: List[str] = [emitted.path for emitted in _emit(api, MODES["per-type"]).files]
    assert len(paths) == len(api.types) > 1
    assert all(path.endswith(".schema.json") for path in paths)


def test_draft_04_reports_what_the_older_draft_rewrites() -> None:
    subjects = {loss.subject for loss in _emit(_source("rest"), MODES["draft-04"]).losses}
    assert "exclusive-bound-boolean" in subjects
    for draft, uri in (("draft-07", "http://json-schema.org/draft-07/schema#"),
                       ("draft-04", "http://json-schema.org/draft-04/schema#")):
        document = json.loads(_emit(_source("rest"), MODES[draft]).files[0].content)
        assert document["$schema"] == uri


def test_browse_delivers_a_per_type_export_as_a_zip_of_every_file() -> None:
    api = _source("json-schema")
    response = render_emitted_document(api, "json-schema", MODES["per-type"], None, bundle_multi_file=True)
    assert response.media_type == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        names = set(archive.namelist())
    assert {emitted.path for emitted in _emit(api, MODES["per-type"]).files} <= names


def test_browse_delivers_a_bundle_as_one_document() -> None:
    response = render_emitted_document(_source("rest"), "json-schema", {}, None, bundle_multi_file=True)
    document = json.loads(response.body)
    assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert set(document["$defs"]) == {"Category", "Pet"}
