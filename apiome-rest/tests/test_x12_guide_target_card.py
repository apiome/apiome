"""X12 implementation-guide target card + fixtures — MFX-24.5 (#4149).

What the ``x12-guide`` export target shows and writes, pinned in ``fixtures/x12_guide_target/outcomes.json``
(regenerate with ``APIOME_REGEN_X12_GUIDE_TARGET=1``):

* **the card** — the tier the Export dialog, browse and ``apiome export targets`` draw for a source of each
  kind (:func:`app.export_routes.build_target_fidelity_entries`). An X12 guide invents most of what it
  says (lengths, codes, segment IDs, a fixed layout) and drops operations, so every source — a REST API,
  an RPC service, a JSON Schema item and an imported X12 or EDIFACT interchange — is ``types-only``;
* **the transaction-set picker** — ``transaction_set`` and ``version`` choose the set and release the guide
  describes (``850`` / ``005010`` by default, an imported X12 item's own otherwise); each pinned choice
  writes the three files, names the set in ``ST01`` and passes the MFX-24.4 guide checks;
* **browse** — the public ``…/document`` route delivers the three files as one zip;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-x12-guide.json`` and
  ``apiome-ui/tests/fixtures/export-targets-x12-guide-{rest,x12}.json`` carry the live descriptor, options
  schema, defaults and card badge.

The UN/EDIFACT message guide (MFX-24.2, #4146) has no emitter yet, so it has no card here.
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
from app.x12_guide_validation import check_guide_files

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "x12_guide_target" / "outcomes.json"
_CLI_TARGETS = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures" / "export-targets-x12-guide.json"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_X12_GUIDE_TARGET"))
_TARGET = "x12-guide"

#: One corpus source per kind: the file and the format it is imported as.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "rpc": ("protobuf/02-grpc-service.proto", "protobuf"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "x12": ("edi-x12/01-850-purchase-order.edi", "edix12"),
    "edifact": ("edifact/01-minimal-orders-d96a.edi", "edifact"),
}

#: The transaction-set / release choices pinned, and the emit options that pick each.
PICKS: Dict[str, Dict[str, Any]] = {
    "default": {},
    "invoice-810": {"transaction_set": "810"},
    "claim-837-004010": {"transaction_set": "837", "version": "004010"},
}

#: The sources whose guides are pinned for every pick.
PICKED_SOURCES = ("rest", "x12")


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
    """The pinned facts of one guide: its files, set, release, ``ST`` elements, tier and check result."""
    result = _emit(api, options)
    guide = json.loads(result.files[0].content)
    st = next(segment for segment in guide["segments"] if segment["id"] == "ST")
    check = check_guide_files({emitted.path: str(emitted.content) for emitted in result.files})
    return {
        "files": [emitted.path for emitted in result.files],
        "transaction_set": guide["transactionSet"]["id"],
        "version": guide["version"],
        "st_elements": [element["ref"] for element in st["elements"]],
        "st01_codes": st["elements"][0]["codes"],
        "tier": build_export_fidelity(api, get_emitter(_TARGET), options=options or None).summary.tier.value,
        "problems": [problem.rule for problem in check.problems],
    }


def _measure() -> Dict[str, Any]:
    return {
        "cards": {kind: {"available": _card(_source(kind)).descriptor.available,
                         "tier": _card(_source(kind)).fidelity.tier.value} for kind in SOURCES},
        "picks": {kind: {pick: _outcome(_source(kind), options) for pick, options in PICKS.items()}
                  for kind in PICKED_SOURCES},
    }


def _targets_body(kind: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to the X12 guide target."""
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


@pytest.mark.parametrize("kind", ["rest", "x12"])
def test_the_ui_targets_fixtures_are_the_live_registry(kind: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-x12-guide-{kind}.json", _targets_body(kind))


@pytest.mark.parametrize("kind", SOURCES)
def test_every_source_badges_types_only(kind: str) -> None:
    card = _card(_source(kind))
    assert card.descriptor.available is True and card.descriptor.multi_file is True
    assert card.fidelity.tier.value == "types-only"


@pytest.mark.parametrize("pick", PICKS)
@pytest.mark.parametrize("kind", PICKED_SOURCES)
def test_each_transaction_set_pick_writes_a_guide_that_passes_the_checks(kind: str, pick: str) -> None:
    outcome = _outcome(_source(kind), PICKS[pick])
    assert outcome["problems"] == []
    assert len(outcome["files"]) == 3
    expected = PICKS[pick].get("transaction_set")
    if expected:
        assert outcome["transaction_set"] == expected and outcome["st01_codes"] == [expected]


def test_an_imported_x12_item_keeps_its_own_transaction_set_by_default() -> None:
    assert _outcome(_source("x12"), {})["transaction_set"] == "850"
    assert _outcome(_source("rest"), {})["transaction_set"] == "850"


def test_the_picker_options_are_in_the_descriptor() -> None:
    card = _card(_source("rest"))
    properties = card.options_schema["properties"]
    assert {"transaction_set", "version", "default_element_length", "max_code_length"} <= set(properties)
    assert card.default_options["transaction_set"] is None


def test_browse_delivers_the_three_files_as_one_zip() -> None:
    api = _source("rest")
    response = render_emitted_document(api, _TARGET, {"transaction_set": "810"}, None, bundle_multi_file=True)
    assert response.media_type == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        names = set(archive.namelist())
        guide_name = next(name for name in names if name.endswith(".x12-guide.json"))
        guide = json.loads(archive.read(guide_name))
    assert {name.rsplit(".", 2)[-2] + "." + name.rsplit(".", 1)[-1] for name in names if name != "manifest.json"} >= {
        "x12-guide.json", "x12-segments.csv", "x12-guide.md"}
    assert guide["transactionSet"]["id"] == "810"
