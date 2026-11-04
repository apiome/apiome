"""HL7 v2 segment-guide target card + fixtures — MFX-26.3 (#4159).

What the ``hl7v2-guide`` export target shows and writes, pinned in ``fixtures/hl7v2_guide_target/outcomes.json``
(regenerate with ``APIOME_REGEN_HL7V2_GUIDE_TARGET=1``):

* **the card** — every source (a REST API, a JSON Schema item, an imported HL7 v2 message, an X12 interchange; an
  RPC service where the toolchain has ``buf``) is ``types-only``, as for the X12 and EDIFACT guides: a guide
  invents segment IDs, lengths and tables and drops operations;
* **the message picker** — ``message_type`` and ``version`` choose the message the guide describes (``ZZZ^Z01`` /
  ``2.5.1`` by default, an imported HL7 v2 item's own otherwise); each pinned choice writes the three files, names
  the message in ``MSH-9`` and the version in ``MSH-12`` and passes the checks;
* **browse** — the public ``…/document`` route delivers the three files as one zip;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-hl7v2-guide.json`` and
  ``apiome-ui/tests/fixtures/export-targets-hl7v2-guide-{rest,hl7v2}.json`` carry the live descriptor, options
  schema, defaults and card badge.

The pinned outcomes use only sources that import without an external toolchain, so they reproduce anywhere.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path
from typing import Any, Dict

import pytest

from app.catalog_conversion import build_conversion_source
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_routes import build_target_fidelity_entries, render_emitted_document
from app.hl7v2_guide_validation import check_guide_files

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "hl7v2_guide_target" / "outcomes.json"
_CLI_TARGETS = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures" / "export-targets-hl7v2-guide.json"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_HL7V2_GUIDE_TARGET"))
_TARGET = "hl7v2-guide"

#: One corpus source per kind: the file and the format it is imported as.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "rpc": ("protobuf/02-grpc-service.proto", "protobuf"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "x12": ("edi-x12/01-850-purchase-order.edi", "edix12"),
    "hl7v2": ("hl7v2/01-adt-a01.hl7", "hl7v2"),
}
#: The sources the pinned outcomes cover: every one imports without an external toolchain.
PINNED_SOURCES = ("rest", "json-schema", "x12", "hl7v2")

#: The message choices pinned, and the emit options that pick each.
PICKS: Dict[str, Dict[str, Any]] = {
    "default": {},
    "oru-r01-251": {"message_type": "ORU^R01", "version": "2.5.1"},
    "zpm-z01-28": {"message_type": "ZPM^Z01", "version": "2.8"},
}
PICKED_SOURCES = ("rest", "hl7v2")


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()


def _source(kind: str) -> Any:
    path, fmt = SOURCES[kind]
    file = _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    try:
        return build_conversion_source(
            {"id": "item-1", "name": file.stem, "source_format": fmt,
             "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}
        ).api
    except Exception as exc:  # noqa: BLE001 — a protobuf source needs buf, which a bare checkout may not have
        if "not available in this runtime" in str(exc):
            pytest.skip(f"{path} needs a toolchain this runtime does not have: {exc}")
        raise


def _card(api: Any) -> Any:
    return next(entry for entry in build_target_fidelity_entries(api) if entry.descriptor.key == _TARGET)


def _emit(api: Any, options: Dict[str, Any]) -> Any:
    emitter = get_emitter(_TARGET)
    return emitter().emit(api, opts=coerce_emit_options(emitter, options))


def _outcome(api: Any, options: Dict[str, Any]) -> Dict[str, Any]:
    """The pinned facts of one guide: its files, message, version, ``MSH-9``/``MSH-12``, tier and check result."""
    result = _emit(api, options)
    guide = json.loads(result.files[0].content)
    msh = {field["seq"]: field.get("value") for field in guide["segments"][0]["fields"]}
    return {
        "files": [emitted.path for emitted in result.files],
        "message": guide["message"]["type"],
        "version": guide["version"],
        "msh9": msh.get(9),
        "msh12": msh.get(12),
        "segments": [segment["id"] for segment in guide["segments"]],
        "tables": [table["id"] for table in guide["tables"]],
        "tier": build_export_fidelity(api, get_emitter(_TARGET), options=options or None).summary.tier.value,
        "problems": [p.rule for p in check_guide_files({e.path: str(e.content) for e in result.files})],
    }


def _measure() -> Dict[str, Any]:
    return {
        "cards": {kind: {"available": _card(_source(kind)).descriptor.available,
                         "tier": _card(_source(kind)).fidelity.tier.value} for kind in PINNED_SOURCES},
        "picks": {kind: {pick: _outcome(_source(kind), options) for pick, options in PICKS.items()}
                  for kind in PICKED_SOURCES},
    }


def _targets_body(kind: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to the HL7 v2 guide target."""
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


@pytest.mark.parametrize("kind", ["rest", "hl7v2"])
def test_the_ui_targets_fixtures_are_the_live_registry(kind: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-hl7v2-guide-{kind}.json", _targets_body(kind))


@pytest.mark.parametrize("kind", SOURCES)
def test_every_source_badges_types_only(kind: str) -> None:
    card = _card(_source(kind))
    assert card.descriptor.available is True and card.descriptor.multi_file is True
    assert card.fidelity.tier.value == "types-only"


@pytest.mark.parametrize("pick", PICKS)
@pytest.mark.parametrize("kind", PICKED_SOURCES)
def test_each_message_pick_writes_a_guide_that_passes_the_checks(kind: str, pick: str) -> None:
    outcome = _outcome(_source(kind), PICKS[pick])
    assert outcome["problems"] == []
    assert len(outcome["files"]) == 3
    if PICKS[pick]:
        assert outcome["msh9"] == PICKS[pick]["message_type"]
        assert outcome["msh12"] == PICKS[pick]["version"]


def test_an_imported_hl7v2_item_keeps_its_own_message_by_default() -> None:
    hl7 = _outcome(_source("hl7v2"), {})
    assert (hl7["message"], hl7["version"]) == ("ADT^A01", "2.5")
    assert hl7["segments"][:5] == ["MSH", "EVN", "PID", "NK1", "PV1"]
    rest = _outcome(_source("rest"), {})
    assert (rest["message"], rest["version"]) == ("ZZZ^Z01", "2.5.1")


def test_the_picker_options_are_in_the_descriptor() -> None:
    card = _card(_source("rest"))
    properties = card.options_schema["properties"]
    assert {"message_type", "version", "default_field_length", "max_code_length", "first_table_number"} <= set(
        properties)
    assert card.default_options["message_type"] is None and card.default_options["first_table_number"] == 9001


def test_browse_delivers_the_three_files_as_one_zip() -> None:
    api = _source("rest")
    response = render_emitted_document(api, _TARGET, {"message_type": "ORU^R01"}, None, bundle_multi_file=True)
    assert response.media_type == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        names = set(archive.namelist())
        guide = json.loads(archive.read(next(n for n in names if n.endswith(".hl7v2-guide.json"))))
    assert any(n.endswith(".hl7v2-segments.csv") for n in names)
    assert any(n.endswith(".hl7v2-guide.md") for n in names)
    assert guide["message"]["type"] == "ORU^R01"
