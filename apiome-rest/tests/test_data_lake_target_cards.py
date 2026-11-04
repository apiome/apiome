"""Data-lake target cards + CLI + fixtures — MFX-36.5 (#4321).

What the ``arrow`` export target (Apache Arrow / Parquet, MFX-36.1, with its BigQuery and Spark ``output``
modes, MFX-36.2) and the ``iceberg`` target (MFX-36.3) show and write on every export surface, pinned in
``fixtures/data_lake_targets/outcomes.json`` (regenerate with ``APIOME_REGEN_DATA_LAKE_TARGETS=1``):

* **the cards** — per source kind (a REST API, an imported Arrow schema, a JSON Schema item and a gateway
  configuration): offered with their fidelity tier and preserved share — an API with operations badges
  **types-only** — or greyed out with the reason (a gateway configuration has no record type);
* **every mode** — ``arrow`` (with and without the Parquet message), ``bigquery`` and ``spark`` (per table and
  bundled) and ``iceberg``: each writes its files and passes the export gate (MFX-36.4);
* **browse** — the public ``…/document`` route delivers each mode;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-{arrow,iceberg}.json`` and
  ``apiome-ui/tests/fixtures/export-targets-arrow-{rest,arrow,gateway}.json`` /
  ``export-targets-iceberg-{rest,gateway}.json`` carry the live descriptor, options schema, defaults and card
  badge; ``apiome-cli/tests/fixtures/export-job-completed-{bigquery,iceberg}-types-only.json`` carry the
  Petstore export's live fidelity envelope (summary, **report**, advisory) and file name.
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
_GOLDEN = _TESTS / "fixtures" / "data_lake_targets" / "outcomes.json"
_CLI_FIXTURES = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_DATA_LAKE_TARGETS"))
_ARTIFACT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
TARGETS = ("arrow", "iceberg")

#: One corpus source per kind: the file and the format it is imported as.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "arrow": ("arrow/02-typical-orders-schema.json", "arrow"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "gateway": ("kong/01-minimal-single-service.yaml", "kong"),
}
#: Every mode the cards offer: (target, options).
MODES: Dict[str, tuple[str, Dict[str, Any]]] = {
    "arrow": ("arrow", {}),
    "arrow-no-parquet": ("arrow", {"parquet": False}),
    "bigquery": ("arrow", {"output": "bigquery"}),
    "bigquery-bundle": ("arrow", {"output": "bigquery", "bundle": True}),
    "spark": ("arrow", {"output": "spark"}),
    "spark-bundle": ("arrow", {"output": "spark", "bundle": True}),
    "iceberg": ("iceberg", {}),
}
#: The sources whose exports are pinned for every mode.
MODE_SOURCES = ("rest", "arrow")
#: The UI fixtures per target.
UI_SOURCES = {"arrow": ("rest", "arrow", "gateway"), "iceberg": ("rest", "gateway")}
#: The CLI job fixtures: the mode whose Petstore export the CLI replays.
JOB_MODES = {"bigquery": "bigquery", "iceberg": "iceberg"}


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


def _card(api: Any, target: str) -> Any:
    return next(entry for entry in build_target_fidelity_entries(api) if entry.descriptor.key == target)


def _emit(api: Any, target: str, options: Dict[str, Any]) -> Any:
    emitter = get_emitter(target)
    return emitter().emit(api, opts=coerce_emit_options(emitter, options))


def _outcome(api: Any, mode: str) -> Dict[str, Any]:
    """The pinned facts of one export: its files, tier, preserved share and gate verdict."""
    target, options = MODES[mode]
    result = _emit(api, target, options)
    summary = build_export_fidelity(api, get_emitter(target), options=options or None).summary
    verdict = asyncio.run(validate_emitted_artifact(target, result, api=api, options=options))
    return {
        "files": [emitted.path for emitted in result.files],
        "media_type": result.media_type,
        "tier": summary.tier.value,
        "preserved_percent": summary.preserved_percent,
        "valid": bool(verdict.valid),
        "failed": bool(verdict.failed),
    }


def _measure() -> Dict[str, Any]:
    cards: Dict[str, Any] = {}
    for target in TARGETS:
        for kind in SOURCES:
            card = _card(_source(kind), target)
            cards[f"{target}/{kind}"] = {"available": card.descriptor.available, "tier": card.fidelity.tier.value,
                                         "preserved_percent": card.fidelity.preserved_percent}
    modes = {kind: {mode: _outcome(_source(kind), mode) for mode in MODES} for kind in MODE_SOURCES}
    return {"cards": cards, "modes": modes}


def _targets_body(kind: str, target: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to one target."""
    card = _card(_source(kind), target).model_dump(mode="json")
    return {"artifact": _ARTIFACT, "version": "1.0.0", "targets": [card]}


def _job_body(mode: str) -> Dict[str, Any]:
    """The completed export-job envelope for the Petstore export in ``mode`` (what the CLI replays)."""
    target, options = MODES[mode]
    api = _source("rest")
    result = _emit(api, target, options)
    return {
        "job_id": _JOB_ID,
        "state": "completed",
        "percent": 100,
        "events": [],
        "result": {
            "artifact": _ARTIFACT,
            "version_record_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "version_label": "1.0.0",
            "target": target,
            "dry_run": False,
            "fidelity": build_export_fidelity(api, get_emitter(target), options=options or None).model_dump(
                mode="json"),
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


@pytest.mark.parametrize("target", TARGETS)
def test_the_cli_targets_fixtures_are_the_live_registry(target: str) -> None:
    _check_recorded(_CLI_FIXTURES / f"export-targets-{target}.json", _targets_body("rest", target))


@pytest.mark.parametrize("mode", JOB_MODES)
def test_the_cli_job_fixtures_carry_the_live_report_and_file(mode: str) -> None:
    _check_recorded(_CLI_FIXTURES / f"export-job-completed-{mode}-types-only.json", _job_body(mode))


@pytest.mark.parametrize(("target", "kind"), [(t, k) for t, kinds in UI_SOURCES.items() for k in kinds])
def test_the_ui_targets_fixtures_are_the_live_registry(target: str, kind: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-{target}-{kind}.json", _targets_body(kind, target))


# ===========================================================================
# The cards
# ===========================================================================


@pytest.mark.parametrize("target", TARGETS)
def test_an_api_with_operations_badges_types_only(target: str) -> None:
    card = _card(_source("rest"), target)
    assert card.descriptor.available and card.fidelity.tier.value == "types-only"
    assert card.descriptor.paradigm == "data_schema" and card.descriptor.multi_file is True


@pytest.mark.parametrize("target", TARGETS)
def test_every_source_with_a_record_type_badges_types_only(target: str) -> None:
    # A data-lake schema holds tables only: the card badges types-only for every source it can export — except
    # an imported Arrow schema on the Arrow card, which exports back as it was read (lossless).
    for kind in ("arrow", "json-schema"):
        card = _card(_source(kind), target)
        expected = "lossless" if (target, kind) == ("arrow", "arrow") else "types-only"
        assert card.descriptor.available and card.fidelity.tier.value == expected, (target, kind)


@pytest.mark.parametrize("target", TARGETS)
def test_a_source_with_no_record_type_is_greyed_out(target: str) -> None:
    card = _card(_source("gateway"), target)
    assert card.descriptor.available is False
    assert "at least one record type" in (card.descriptor.unavailable_reason or "")


def test_the_arrow_card_offers_every_mode() -> None:
    schema = _card(_source("rest"), "arrow").options_schema
    assert schema["properties"]["output"]["enum"] == ["arrow", "bigquery", "spark"]
    assert schema["properties"]["output"]["default"] == "arrow"
    assert {"table", "parquet", "bundle", "indent"} <= set(schema["properties"])


def test_the_iceberg_card_hides_the_stored_field_ids() -> None:
    schema = _card(_source("rest"), "iceberg").options_schema
    assert {"table", "indent"} <= set(schema["properties"])
    # The export service fills the stored IDs; a person never types them (MFX-12.2).
    assert "persisted_field_numbers" not in schema["properties"]


# ===========================================================================
# Every mode: written, through the gate, delivered
# ===========================================================================


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("kind", MODE_SOURCES)
def test_each_mode_writes_files_the_gate_accepts(kind: str, mode: str) -> None:
    outcome = _outcome(_source(kind), mode)
    assert outcome["valid"] and not outcome["failed"], outcome
    assert outcome["files"]


def test_the_file_names_of_each_mode() -> None:
    names = {mode: _outcome(_source("rest"), mode)["files"] for mode in MODES}
    assert names["arrow"] == ["Pet.arrow.json", "Pet.parquet.txt"]
    assert names["arrow-no-parquet"] == ["Pet.arrow.json"]
    assert names["bigquery"] == ["Pet.bigquery.json"] and names["bigquery-bundle"] == ["schemas.bigquery.json"]
    assert names["spark"] == ["Pet.spark.ddl"] and names["spark-bundle"] == ["schemas.spark.ddl"]
    assert names["iceberg"] == ["Pet.iceberg.json"]


@pytest.mark.parametrize(("mode", "media", "needle"), [
    ("arrow", "application/zip", b"PK"),
    ("bigquery", "application/json", b'"mode": "REQUIRED"'),
    ("spark", "text/plain", b"`id` BIGINT NOT NULL"),
    ("iceberg", "application/json", b'"schema-id": 0'),
])
def test_browse_delivers_each_mode(mode: str, media: str, needle: bytes) -> None:
    target, options = MODES[mode]
    response = render_emitted_document(_source("rest"), target, options, None, bundle_multi_file=True)
    assert response.media_type.startswith(media)
    assert needle in response.body
