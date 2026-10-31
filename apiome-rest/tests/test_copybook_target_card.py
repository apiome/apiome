"""COBOL copybook target card + fixtures — MFX-23.5 (#4143).

What the ``cobolcopybook`` export target shows and writes, pinned in ``fixtures/copybook_target/``
(regenerate with ``APIOME_REGEN_COPYBOOK_TARGET=1``):

* **the card** — the tier the Export dialog, browse and ``apiome export targets`` draw for a source of
  each kind (:func:`app.export_routes.build_target_fidelity_entries`). Copybook is one of the lossiest
  targets: a REST API, an RPC service and a JSON Schema item are ``types-only`` (operations dropped,
  lengths, counts and names synthesized), while a copybook item exported again is ``lossless``;
* **the cases** — ``source.openapi.yaml`` exercises **nested** groups (``Order → Address → GeoPoint``),
  **arrays** (a ``maxItems`` table and an unbounded one, both ``OCCURS … DEPENDING ON``) and **long
  names** (camelCase properties over COBOL's 30-character limit). OpenAPI numbers are floats, so the
  **decimal** case (``S9(p)V9(s) COMP-3``) comes from copybook corpus items exported again. Each case is
  written under the default options and under ``display`` / free format (``<case>/<mode>/<file>``),
  and every written copybook imports again;
* **browse** — the public ``…/document`` route delivers the copybook as plain text;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-copybook.json`` and
  ``apiome-ui/tests/fixtures/export-targets-copybook-{rest,copybook}.json`` carry the live descriptor,
  options schema, defaults and card badge.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.catalog_conversion import build_conversion_source
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_routes import build_target_fidelity_entries, render_emitted_document
from app.import_source import get_import_source, load_builtin_import_sources
from app.roundtrip_matrix import reimport_emitted

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "copybook_target"
_CLI_TARGETS = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures" / "export-targets-copybook.json"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_COPYBOOK_TARGET"))
_TARGET = "cobolcopybook"

#: One source per kind for the card: the file (relative to the corpus, or ``fixture:`` this folder) and its format.
CARD_SOURCES: Dict[str, tuple[str, str]] = {
    "rest": ("fixture:source.openapi.yaml", "openapi"),
    "rpc": ("protobuf/02-grpc-service.proto", "protobuf"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "copybook": ("cobol-copybook/02-order-line.cpy", "cobolcopybook"),
}

#: The written cases: nested / array / long-name from the OpenAPI fixture, decimals from copybook items.
CASES: Dict[str, tuple[str, str]] = {
    "nested-array-long-name": ("fixture:source.openapi.yaml", "openapi"),
    "decimal-redefines": ("cobol-copybook/03-payment-redefines.cpy", "cobolcopybook"),
    "decimal-occurs-depending": ("cobol-copybook/04-warehouse-stress.cpy", "cobolcopybook"),
}

#: The output modes each case is written in, and the emit options that select each.
MODES: Dict[str, Dict[str, Any]] = {
    "default": {},
    "display-free": {"numeric_usage": "display", "fixed_format": False},
}


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _load(ref: tuple[str, str]) -> Any:
    """The canonical model of one source, imported as the catalog would."""
    path, fmt = ref
    file = _GOLDEN / path[len("fixture:"):] if path.startswith("fixture:") else _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"source {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": file.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}
    ).api


def _card(api: Any) -> Any:
    """The registry entry (descriptor + badge) the targets route lists for the copybook target."""
    return next(entry for entry in build_target_fidelity_entries(api) if entry.descriptor.key == _TARGET)


def _emit(api: Any, options: Dict[str, Any]) -> Any:
    emitter = get_emitter(_TARGET)
    return emitter().emit(api, opts=coerce_emit_options(emitter, options))


def _outcome(api: Any, options: Dict[str, Any]) -> Dict[str, Any]:
    """The pinned facts of one export: its files, losses, preview tier and what it re-imports as."""
    result = _emit(api, options)
    fidelity = build_export_fidelity(api, get_emitter(_TARGET), options=options or None)
    back = reimport_emitted(get_import_source(_TARGET), result, multi_file=False)
    return {
        "files": [emitted.path for emitted in result.files],
        "loss_subjects": sorted({loss.subject for loss in result.losses}),
        "tier": fidelity.summary.tier.value,
        "reimported_types": sorted(t.key for t in back.types),
    }


def _measure() -> Dict[str, Any]:
    return {
        "cards": {kind: {"available": _card(_load(ref)).descriptor.available,
                         "tier": _card(_load(ref)).fidelity.tier.value}
                  for kind, ref in CARD_SOURCES.items()},
        "cases": {case: {mode: _outcome(_load(ref), options) for mode, options in MODES.items()}
                  for case, ref in CASES.items()},
    }


def _written_files() -> Dict[str, str]:
    """``<case>/<mode>/<file>`` → the copybook text the export writes."""
    files: Dict[str, str] = {}
    for case, ref in CASES.items():
        api = _load(ref)
        for mode, options in MODES.items():
            for emitted in _emit(api, options).files:
                files[f"{case}/{mode}/{emitted.path}"] = emitted.content
    return files


def _targets_body(kind: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` card source, cut to the copybook target."""
    entries = [_card(_load(CARD_SOURCES[kind])).model_dump(mode="json")]
    return {"artifact": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "version": "1.0.0", "targets": entries}


def _check_recorded(path: Path, live: Dict[str, Any]) -> None:
    """``path`` holds ``live`` (written first under regen); skipped when that package is not checked out."""
    if _REGEN and path.parent.is_dir():
        path.write_text(json.dumps(live, indent=2) + "\n", encoding="utf-8")
    if not path.is_file():
        pytest.skip(f"{path.parent} is not checked out")
    assert json.loads(path.read_text(encoding="utf-8")) == live


def _entries(text: str) -> List[str]:
    """The data-description lines of a copybook (comments and blank lines left out)."""
    return [line for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith(("*", "*>")) and line[6:7] != "*"]


def test_the_outcomes_match_the_fixture() -> None:
    measured = _measure()
    golden = _GOLDEN / "outcomes.json"
    if _REGEN:
        golden.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert measured == json.loads(golden.read_text(encoding="utf-8"))


def test_the_written_copybooks_match_the_fixtures() -> None:
    files = _written_files()
    if _REGEN:
        for case in CASES:
            shutil.rmtree(_GOLDEN / case, ignore_errors=True)
        for name, text in files.items():
            (_GOLDEN / name).parent.mkdir(parents=True, exist_ok=True)
            (_GOLDEN / name).write_text(text, encoding="utf-8")
    on_disk = {
        str(path.relative_to(_GOLDEN)): path.read_text(encoding="utf-8")
        for case in CASES for path in sorted((_GOLDEN / case).rglob("*.cpy"))
    }
    assert on_disk == files


def test_the_cli_targets_fixture_is_the_live_registry() -> None:
    _check_recorded(_CLI_TARGETS, _targets_body("rest"))


@pytest.mark.parametrize("kind", ["rest", "copybook"])
def test_the_ui_targets_fixtures_are_the_live_registry(kind: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-copybook-{kind}.json", _targets_body(kind))


@pytest.mark.parametrize("kind", ["rest", "rpc", "json-schema"])
def test_a_source_of_another_format_badges_types_only(kind: str) -> None:
    card = _card(_load(CARD_SOURCES[kind]))
    assert card.descriptor.available is True
    assert card.fidelity.tier.value == "types-only"


def test_a_copybook_item_badges_lossless() -> None:
    card = _card(_load(CARD_SOURCES["copybook"]))
    assert card.fidelity.tier.value == "lossless"


def test_nested_groups_step_down_a_level_each() -> None:
    text = _emit(_load(CASES["nested-array-long-name"]), {}).files[0].content
    levels = {line.split()[1].rstrip("."): line.split()[0] for line in _entries(text)}
    assert (levels["SHIP-TO"], levels["GEO"], levels["LATITUDE"]) == ("05", "10", "15")


def test_arrays_are_tables_with_a_synthesized_counter() -> None:
    api = _load(CASES["nested-array-long-name"])
    text = _emit(api, {}).files[0].content
    assert "05  LINES-X OCCURS 0 TO 50 TIMES DEPENDING ON LINES-X-COUNT." in text
    # An unbounded list gets the default maximum (and its items the default length); the report says so.
    assert re.search(r"NOTES PIC X\(255\) OCCURS 0 TO 10 TIMES\s+DEPENDING ON NOTES-COUNT", text)
    assert {"counter-synthesized", "occurs-synthesized"} <= {loss.subject for loss in _emit(api, {}).losses}


def test_long_names_are_cut_to_thirty_characters_and_reported() -> None:
    api = _load(CASES["nested-array-long-name"])
    result = _emit(api, {})
    names = [line.split()[1].rstrip(".") for line in _entries(result.files[0].content)]
    assert all(len(name) <= 30 for name in names)
    assert "CUSTOMER-LOYALTY-PROGRAM-MEMBE" in names and "WAREHOUSE-BIN-LOCATION-REFEREN" in names
    assert "name-mangled" in {loss.subject for loss in result.losses}


def test_fixed_format_keeps_every_line_inside_column_72() -> None:
    for case, ref in CASES.items():
        text = _emit(_load(ref), {}).files[0].content
        assert all(len(line) <= 72 for line in text.splitlines()), case


@pytest.mark.parametrize("case", ["decimal-redefines", "decimal-occurs-depending"])
def test_decimals_are_packed_with_an_implied_point(case: str) -> None:
    text = _emit(_load(CASES[case]), {}).files[0].content
    # A copybook item keeps its own picture spelling (`S9(9)V99`), a synthesized one is `S9(p)V9(s)`.
    assert re.search(r"PIC S9\(\d+\)V(9+|9\(\d+\)) COMP-3", text)


def test_display_usage_writes_floats_as_zoned_decimals() -> None:
    api = _load(CASES["nested-array-long-name"])
    result = _emit(api, MODES["display-free"])
    assert "COMP-2" not in result.files[0].content
    assert re.search(r"TOTAL PIC S9\(\d+\)V9\(\d+\)\.", result.files[0].content)
    assert "float-as-decimal" in {loss.subject for loss in result.losses}


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("case", CASES)
def test_every_written_copybook_imports_again(case: str, mode: str) -> None:
    outcome = _outcome(_load(CASES[case]), MODES[mode])
    assert outcome["reimported_types"], outcome


def test_browse_delivers_the_copybook_as_plain_text() -> None:
    api = _load(CASES["nested-array-long-name"])
    response = render_emitted_document(api, _TARGET, {}, None, bundle_multi_file=True)
    assert response.media_type.startswith("text/plain")
    assert response.body.decode() == _emit(api, {}).files[0].content
    assert "Order.cpy" in response.headers["content-disposition"]
