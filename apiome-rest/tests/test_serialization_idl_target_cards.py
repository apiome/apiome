"""FlatBuffers and Cap'n Proto target cards + fixtures — MFX-30.4 (#4181).

What the ``flatbuffers`` and ``capnproto`` export targets show and write, pinned per target in
``fixtures/serialization_idl_target/<target>.json`` (regenerate with ``APIOME_REGEN_SERIALIZATION_IDL_TARGET=1``):

* **the cards** — the tier the Export dialog, browse and ``apiome export flatbuffers`` / ``apiome export capnp``
  draw for a source of each kind (:func:`app.export_routes.build_target_fidelity_entries`). FlatBuffers is a
  types-only target (a REST, RPC, GraphQL, JSON Schema, WSDL, RAML or Smithy source badges ``types-only``);
  Cap'n Proto also writes interfaces (those sources badge ``lossy``). A source imported in the target's own
  format badges ``lossless``;
* **the options** — ``include_comments`` (both; default on) and FlatBuffers' ``root_type``. Every pinned choice
  passes the export gate (``flatc`` / ``capnp compile`` where installed, else the format's reader);
* **re-export id stability** (MFX-12.2 store, MFX-30.1 / 30.2) — a source without ids (the Petstore) gets ids
  on its first export; re-exported after ``Pet`` gains a field and loses ``tag``, with the ids the first export
  stored, every surviving field keeps its id, the new field gets a fresh one, and ``tag``'s id is kept by a
  placeholder (FlatBuffers ``deprecated``, Cap'n Proto ``obsoleteTag :AnyPointer``) so ids stay dense; Cap'n
  Proto also keeps its file id. Without the stored ids the positions shift;
* **browse** — the public ``…/document`` route delivers the ``.fbs`` / ``.capnp`` itself;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-<target>.json`` and
  ``apiome-ui/tests/fixtures/export-targets-<target>-{rest,<target>}.json`` carry the live descriptor, options
  schema, defaults and card badge; ``apiome-cli/tests/fixtures/export-job-completed-<target>-<tier>.json``
  carries the live fidelity summary and file name of the Petstore export.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Dict

import pytest

from app.canonical_model import CanonicalApi, CanonicalField, TypeRef
from app.catalog_conversion import build_conversion_source
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_routes import build_target_fidelity_entries, render_emitted_document
from app.export_validation import validate_emitted_artifact

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN_DIR = _TESTS / "fixtures" / "serialization_idl_target"
_CLI_FIXTURES = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_SERIALIZATION_IDL_TARGET"))

#: Per target: its own corpus source, the file extension, the Petstore tier and its extra option choices.
TARGETS: Dict[str, Dict[str, Any]] = {
    "flatbuffers": {"own": ("flatbuffers/01-monster.fbs", "flatbuffers"), "extension": "fbs",
                    "rest_tier": "types-only", "options": {"root-type": {"root_type": "Pet"}}},
    "capnproto": {"own": ("capnproto/01-address-book.capnp", "capnproto"), "extension": "capnp",
                  "rest_tier": "lossy", "options": {}},
}

#: One corpus source per kind; each target adds its own format as ``own``.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "rpc": ("thrift/01-user-service.thrift", "thrift"),
    "graphql": ("graphql/06-union-types.graphql", "graphql"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "wsdl": ("wsdl/02-order-service.wsdl", "wsdl"),
    "raml": ("raml/03-orders-service.raml", "raml"),
    "smithy": ("smithy/06-orders-service.smithy", "smithy"),
}

#: The Petstore record the id-stability fixture changes between exports.
_PET = "Pet"


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()


def _load(path: str, fmt: str) -> CanonicalApi:
    file = _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": file.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}
    ).api


def _source(target: str, kind: str) -> CanonicalApi:
    return _load(*TARGETS[target]["own"]) if kind == "own" else _load(*SOURCES[kind])


def _card(target: str, api: CanonicalApi) -> Any:
    return next(entry for entry in build_target_fidelity_entries(api) if entry.descriptor.key == target)


def _emit(target: str, api: CanonicalApi, options: Dict[str, Any]) -> Any:
    emitter = get_emitter(target)
    return emitter().emit(api, opts=coerce_emit_options(emitter, options))


def _options(target: str, kind: str = "rest") -> Dict[str, Dict[str, Any]]:
    """The option choices pinned for ``kind``: the target's extra choices name Petstore types, so REST only."""
    extra = TARGETS[target]["options"] if kind == "rest" else {}
    return {"default": {}, "no-comments": {"include_comments": False}, **extra}


#: A field line and its id: FlatBuffers ``name: type (id: N…)``, Cap'n Proto ``name @N :Type``.
_FIELD_ID = {
    "flatbuffers": re.compile(r"^\s*(\w+): [^\s(]+ \(id: (\d+)", re.MULTILINE),
    "capnproto": re.compile(r"^\s*(\w+) @(\d+) :", re.MULTILINE),
}


def _ids(target: str, result: Any, type_name: str) -> Dict[str, int]:
    """The ids the exported schema writes for ``type_name``'s fields, read from its ``table`` / ``struct``."""
    text = str(result.files[0].content)
    keyword = "table" if target == "flatbuffers" else "struct"
    start = text.index(f"{keyword} {type_name} {{")
    block = text[start:text.index("}", start)]
    return {name: int(field_id) for name, field_id in _FIELD_ID[target].findall(block)}


def _changed_petstore(api: CanonicalApi) -> CanonicalApi:
    """The Petstore with a ``nickname`` field added ahead of the others and ``tag`` removed from ``Pet``."""
    pet = next(t for t in api.types if t.name == _PET)
    nickname = CanonicalField(key=f"{pet.key}.nickname", name="nickname", type=TypeRef(name="string", nullable=True))
    changed = pet.model_copy(update={"fields": [nickname, *(f for f in pet.fields if f.name != "tag")]})
    return api.model_copy(update={"types": [changed if t.key == pet.key else t for t in api.types]})


def _placeholder(target: str, text: str) -> str:
    """The line that holds the removed ``tag``'s id."""
    pattern = r"^\s*tag: \w+ \(id: \d+, deprecated\);" if target == "flatbuffers" else r"^\s*obsoleteTag @\d+ :\w+;"
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(0).strip() if match else ""


def _file_id(text: str) -> str:
    match = re.search(r"^@0x[0-9a-f]+;", text, re.MULTILINE)
    return match.group(0) if match else ""


def _id_stability(target: str) -> Dict[str, Any]:
    api = _source(target, "rest")
    first = _emit(target, api, {})
    changed = _changed_petstore(api)
    with_store = _emit(target, changed, {"persisted_field_numbers": dict(first.field_identity_assignments)})
    without_store = _emit(target, changed, {})
    again = str(with_store.files[0].content)
    return {
        "first": _ids(target, first, _PET),
        "re_export_with_stored_ids": _ids(target, with_store, _PET),
        "re_export_without_stored_ids": _ids(target, without_store, _PET),
        "placeholder": _placeholder(target, again),
        "file_id_kept": _file_id(again) == _file_id(str(first.files[0].content)),
    }


def _outcome(target: str, api: CanonicalApi, options: Dict[str, Any]) -> Dict[str, Any]:
    result = _emit(target, api, options)
    text = str(result.files[0].content)
    summary = build_export_fidelity(api, get_emitter(target), options=options or None).summary
    verdict = asyncio.run(validate_emitted_artifact(target, result, api=api))
    return {
        "files": [emitted.path for emitted in result.files],
        "tier": summary.tier.value,
        "preserved_percent": summary.preserved_percent,
        "valid": bool(verdict.valid),
        "header_comment": text.startswith("//") or text.startswith("#"),
        "root_type": next((line.strip() for line in text.splitlines() if line.startswith("root_type")), None),
    }


def _measure(target: str) -> Dict[str, Any]:
    kinds = (*SOURCES, "own")
    return {
        "cards": {kind: _card(target, _source(target, kind)).fidelity.tier.value for kind in kinds},
        "options": {kind: {choice: _outcome(target, _source(target, kind), options)
                           for choice, options in _options(target, kind).items()} for kind in ("rest", "own")},
        "id_stability": _id_stability(target),
    }


def _targets_body(target: str, kind: str) -> Dict[str, Any]:
    return {"artifact": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "version": "1.0.0",
            "targets": [_card(target, _source(target, kind)).model_dump(mode="json")]}


def _check_recorded(path: Path, live: Dict[str, Any]) -> None:
    """``path`` holds ``live`` (written first under regen); skipped when that package is not checked out."""
    if _REGEN and path.parent.is_dir():
        path.write_text(json.dumps(live, indent=2) + "\n", encoding="utf-8")
    if not path.is_file():
        pytest.skip(f"{path.parent} is not checked out")
    assert json.loads(path.read_text(encoding="utf-8")) == live


def _job_fixture(target: str) -> Path:
    return _CLI_FIXTURES / f"export-job-completed-{target}-{TARGETS[target]['rest_tier']}.json"


@pytest.mark.parametrize("target", TARGETS)
def test_the_outcomes_match_the_fixture(target: str) -> None:
    measured = _measure(target)
    golden = _GOLDEN_DIR / f"{target}.json"
    if _REGEN:
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert measured == json.loads(golden.read_text(encoding="utf-8"))


@pytest.mark.parametrize("target", TARGETS)
def test_the_cli_targets_fixture_is_the_live_registry(target: str) -> None:
    _check_recorded(_CLI_FIXTURES / f"export-targets-{target}.json", _targets_body(target, "rest"))


@pytest.mark.parametrize("kind", ["rest", "own"])
@pytest.mark.parametrize("target", TARGETS)
def test_the_ui_targets_fixtures_are_the_live_registry(target: str, kind: str) -> None:
    name = "rest" if kind == "rest" else target
    _check_recorded(_UI_FIXTURES / f"export-targets-{target}-{name}.json", _targets_body(target, kind))


@pytest.mark.parametrize("target", TARGETS)
def test_the_cli_job_fixture_carries_the_live_fidelity_and_file(target: str) -> None:
    path = _job_fixture(target)
    if not path.is_file():
        pytest.skip(f"{path.parent} is not checked out")
    api = _source(target, "rest")
    job = json.loads(path.read_text(encoding="utf-8"))["result"]
    assert job["fidelity"]["summary"] == build_export_fidelity(api, get_emitter(target)).summary.model_dump(mode="json")
    assert [row["path"] for row in job["files"]] == [emitted.path for emitted in _emit(target, api, {}).files]


@pytest.mark.parametrize("kind", [*SOURCES, "own"])
@pytest.mark.parametrize("target", TARGETS)
def test_every_source_is_offered_as_a_single_file_target(target: str, kind: str) -> None:
    card = _card(target, _source(target, kind))
    assert card.descriptor.available is True and card.descriptor.multi_file is False


@pytest.mark.parametrize("kind", SOURCES)
@pytest.mark.parametrize("target", TARGETS)
def test_another_format_s_source_badges_the_target_s_tier(target: str, kind: str) -> None:
    assert _card(target, _source(target, kind)).fidelity.tier.value == TARGETS[target]["rest_tier"]


@pytest.mark.parametrize("target", TARGETS)
def test_a_source_in_the_target_s_own_format_badges_lossless(target: str) -> None:
    assert _card(target, _source(target, "own")).fidelity.tier.value == "lossless"


@pytest.mark.parametrize("target", TARGETS)
def test_each_option_choice_writes_one_schema_the_gate_accepts(target: str) -> None:
    for kind in ("rest", "own"):
        for choice, options in _options(target, kind).items():
            outcome = _outcome(target, _source(target, kind), options)
            assert outcome["valid"] is True, (kind, choice)
            assert [p.rsplit(".", 1)[-1] for p in outcome["files"]] == [TARGETS[target]["extension"]]
            assert outcome["header_comment"] is (choice != "no-comments"), (kind, choice)


def test_the_flatbuffers_root_type_option_names_the_root() -> None:
    outcome = _outcome("flatbuffers", _source("flatbuffers", "rest"), {"root_type": "Pet"})
    assert outcome["root_type"] == "root_type Pet;"


@pytest.mark.parametrize("target", TARGETS)
def test_a_re_export_with_the_stored_ids_keeps_every_surviving_field_s_id(target: str) -> None:
    stability = _id_stability(target)
    first, again = stability["first"], stability["re_export_with_stored_ids"]
    for name, field_id in first.items():
        if name != "tag":
            assert again[name] == field_id, name
    assert again["nickname"] not in first.values()
    # The removed field's id is held by a placeholder, so the ids stay dense and an old reader still decodes.
    assert stability["placeholder"]
    if target == "capnproto":
        assert stability["file_id_kept"] is True


@pytest.mark.parametrize("target", TARGETS)
def test_without_the_stored_ids_the_positions_shift(target: str) -> None:
    stability = _id_stability(target)
    first, shifted = stability["first"], stability["re_export_without_stored_ids"]
    assert any(shifted[name] != field_id for name, field_id in first.items() if name in shifted)


@pytest.mark.parametrize("target", TARGETS)
def test_browse_delivers_the_schema_itself(target: str) -> None:
    response = render_emitted_document(_source(target, "rest"), target, {}, None, bundle_multi_file=True)
    assert response.media_type != "application/zip"
    assert response.headers["content-disposition"].endswith(f'.{TARGETS[target]["extension"]}"')
