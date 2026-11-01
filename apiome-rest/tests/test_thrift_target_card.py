"""Thrift target card + fixtures — MFX-25.5 (#4155).

What the ``thrift`` export target shows and writes, pinned in ``fixtures/thrift_target/outcomes.json``
(regenerate with ``APIOME_REGEN_THRIFT_TARGET=1``):

* **the card** — the tier the Export dialog, browse and ``apiome export targets`` draw for a source of each
  kind (:func:`app.export_routes.build_target_fidelity_entries`). An imported Thrift IDL is written back as it
  was read (``lossless``); a REST, GraphQL, JSON Schema, WSDL, RAML or Smithy source is ``lossy``;
* **the options** — ``include_comments`` (default on) writes the generated-file header comment; ``namespaces``
  writes the ``namespace`` lines; ``persisted_field_numbers`` carries the stable ids an earlier export stored
  (MFX-25.2). Every pinned choice writes one ``.thrift`` that thriftpy2 and the Thrift reader agree on
  (:func:`app.thrift_roundtrip.spot_check_thrift`). The two map options are not drawn in the Export dialog's
  options panel (it shows scalar options only); the CLI and REST API take them;
* **re-export id stability** (MFX-25.2) — a source without field ids (the Petstore) gets ids on its first
  export; re-exported after a field is added and another removed, with the ids the first export stored, every
  surviving field keeps its id, the new one gets a fresh id and the removed one's id is not reused. Without the
  stored ids the positions shift — which is why the export service stores them. A Thrift source's own ids
  always win;
* **browse** — the public ``…/document`` route delivers the ``.thrift`` itself;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-thrift.json`` and
  ``apiome-ui/tests/fixtures/export-targets-thrift-{rest,thrift}.json`` carry the live descriptor, options
  schema, defaults and card badge; ``apiome-cli/tests/fixtures/export-job-completed-thrift-lossy.json``
  carries the live fidelity summary and file name of the Petstore export.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest

from app.canonical_model import CanonicalApi, CanonicalField, TypeRef
from app.catalog_conversion import build_conversion_source
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_routes import build_target_fidelity_entries, render_emitted_document
from app.export_validation import validate_emitted_artifact
from app.thrift_roundtrip import reimport_thrift, spot_check_thrift

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "thrift_target" / "outcomes.json"
_CLI_FIXTURES = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures"
_CLI_TARGETS = _CLI_FIXTURES / "export-targets-thrift.json"
_CLI_JOB = _CLI_FIXTURES / "export-job-completed-thrift-lossy.json"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_THRIFT_TARGET"))
_TARGET = "thrift"

#: One corpus source per kind: the file and the format it is imported as. Every one imports without an
#: external toolchain, so the fixture is reproducible on any machine.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "graphql": ("graphql/06-union-types.graphql", "graphql"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "wsdl": ("wsdl/02-order-service.wsdl", "wsdl"),
    "raml": ("raml/03-orders-service.raml", "raml"),
    "smithy": ("smithy/06-orders-service.smithy", "smithy"),
    "thrift": ("thrift/01-user-service.thrift", "thrift"),
    "thrift-payments": ("thrift/06-payment-service.thrift", "thrift"),
}

#: The option choices pinned, and the emit options that pick each.
OPTIONS: Dict[str, Dict[str, Any]] = {
    "default": {},
    "no-comments": {"include_comments": False},
    "java-namespace": {"namespaces": {"java": "com.acme.pets"}},
}

#: The sources whose exports are pinned for every option choice.
OPTION_SOURCES = ("rest", "thrift")

#: The Petstore record the id-stability fixture changes between exports.
_PET = "Pet"


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


def _files(result: Any) -> Dict[str, str]:
    return {emitted.path: str(emitted.content) for emitted in result.files}


def _outcome(api: Any, options: Dict[str, Any]) -> Dict[str, Any]:
    """The pinned facts of one export: its files, tier, preserved share, and what the document carries."""
    result = _emit(api, options)
    text = str(result.files[0].content)
    summary = build_export_fidelity(api, get_emitter(_TARGET), options=options or None).summary
    return {
        "files": [emitted.path for emitted in result.files],
        "tier": summary.tier.value,
        "preserved_percent": summary.preserved_percent,
        "problems": [problem["message"] for problem in spot_check_thrift(_files(result))],
        "header_comment": text.startswith("//") or text.startswith("/*") or text.startswith("#"),
        "java_namespace": "namespace java com.acme.pets" in text,
    }


def _ids(result: Any, type_name: str) -> Dict[str, int]:
    """The field ids the exported ``.thrift`` gives ``type_name``, read back through the Thrift import."""
    type_ = next(t for t in reimport_thrift(result).types if t.name == type_name)
    return {field.name: field.field_number for field in type_.fields}


def _changed_petstore(api: CanonicalApi) -> CanonicalApi:
    """The Petstore with a ``nickname`` field added ahead of the others and ``tag`` removed from ``Pet``."""
    pet = next(t for t in api.types if t.name == _PET)
    nickname = CanonicalField(key=f"{pet.key}.nickname", name="nickname", type=TypeRef(name="string", nullable=True))
    fields = [nickname, *(field for field in pet.fields if field.name != "tag")]
    changed = pet.model_copy(update={"fields": fields})
    return api.model_copy(update={"types": [changed if t.key == pet.key else t for t in api.types]})


def _id_stability() -> Dict[str, Any]:
    """The Petstore ``Pet`` ids: first export, re-export with the stored ids, and re-export without them."""
    api = _source("rest")
    first = _emit(api, {})
    stored = dict(first.field_identity_assignments)
    changed = _changed_petstore(api)
    with_store = _emit(changed, {"persisted_field_numbers": stored})
    without_store = _emit(changed, {})
    return {
        "first": _ids(first, _PET),
        "re_export_with_stored_ids": _ids(with_store, _PET),
        "re_export_without_stored_ids": _ids(without_store, _PET),
        "new_assignments": dict(with_store.field_identity_assignments),
    }


def _measure() -> Dict[str, Any]:
    return {
        "cards": {kind: {"available": _card(_source(kind)).descriptor.available,
                         "tier": _card(_source(kind)).fidelity.tier.value} for kind in SOURCES},
        "options": {kind: {choice: _outcome(_source(kind), options) for choice, options in OPTIONS.items()}
                    for kind in OPTION_SOURCES},
        "id_stability": _id_stability(),
    }


def _targets_body(kind: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to the Thrift target."""
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


@pytest.mark.parametrize("kind", ["rest", "thrift"])
def test_the_ui_targets_fixtures_are_the_live_registry(kind: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-thrift-{kind}.json", _targets_body(kind))


def test_the_cli_job_fixture_carries_the_live_fidelity_and_file() -> None:
    """The completed-job envelope the CLI tests replay reports what the Petstore export really is."""
    if not _CLI_JOB.is_file():
        pytest.skip(f"{_CLI_JOB.parent} is not checked out")
    api = _source("rest")
    job = json.loads(_CLI_JOB.read_text(encoding="utf-8"))["result"]
    live = build_export_fidelity(api, get_emitter(_TARGET)).summary.model_dump(mode="json")
    assert job["fidelity"]["summary"] == live
    assert [row["path"] for row in job["files"]] == [emitted.path for emitted in _emit(api, {}).files]


@pytest.mark.parametrize("kind", SOURCES)
def test_every_source_is_offered_as_a_single_file_target(kind: str) -> None:
    card = _card(_source(kind))
    assert card.descriptor.available is True and card.descriptor.multi_file is False


@pytest.mark.parametrize("kind", ["thrift", "thrift-payments"])
def test_an_imported_thrift_idl_badges_lossless(kind: str) -> None:
    assert _card(_source(kind)).fidelity.tier.value == "lossless"


@pytest.mark.parametrize("choice", OPTIONS)
@pytest.mark.parametrize("kind", OPTION_SOURCES)
def test_each_option_choice_writes_one_thrift_idl_the_readers_agree_on(kind: str, choice: str) -> None:
    outcome = _outcome(_source(kind), OPTIONS[choice])
    assert outcome["problems"] == []
    assert [path.rsplit(".", 1)[-1] for path in outcome["files"]] == ["thrift"]
    assert outcome["java_namespace"] is (choice == "java-namespace")
    assert outcome["header_comment"] is (choice != "no-comments")


def test_a_re_export_with_the_stored_ids_keeps_every_surviving_field_s_id() -> None:
    stability = _id_stability()
    first, again = stability["first"], stability["re_export_with_stored_ids"]
    for name, field_id in first.items():
        if name != "tag":
            assert again[name] == field_id, name
    # The new field gets a fresh id: not one in use, and not the removed `tag`'s.
    assert again["nickname"] not in first.values()
    assert "tag" not in again
    assert stability["new_assignments"] == {"Pet.nickname": again["nickname"]}


def test_without_the_stored_ids_the_positions_shift() -> None:
    stability = _id_stability()
    first, shifted = stability["first"], stability["re_export_without_stored_ids"]
    assert any(shifted[name] != field_id for name, field_id in first.items() if name in shifted)


def test_a_thrift_source_s_own_ids_win_over_stored_ones() -> None:
    api = _source("thrift")
    own = {t.name: {f.name: f.field_number for f in t.fields} for t in api.types if t.fields}
    name, fields = next(iter(own.items()))
    type_key = next(t.key for t in api.types if t.name == name)
    clash = {f"{type_key}.{field}": 99 for field in fields}
    assert _ids(_emit(api, {"persisted_field_numbers": clash}), name) == fields


def test_the_options_are_in_the_descriptor() -> None:
    card = _card(_source("rest"))
    assert set(card.options_schema["properties"]) == {"include_comments", "namespaces", "persisted_field_numbers"}
    assert card.default_options == {"include_comments": True, "namespaces": {}, "persisted_field_numbers": {}}


def test_browse_delivers_the_thrift_idl_itself() -> None:
    response = render_emitted_document(_source("rest"), _TARGET, {}, None, bundle_multi_file=True)
    assert response.media_type != "application/zip"
    assert response.headers["content-disposition"].endswith('.thrift"')
    assert "struct Pet" in response.body.decode("utf-8")


@pytest.mark.parametrize("kind", OPTION_SOURCES)
def test_the_validation_gate_passes_the_default_export(kind: str) -> None:
    """The MFX-25.4 gate: the Thrift compiler where installed, thriftpy2 and the Thrift reader, the re-import."""
    api = _source(kind)
    verdict = asyncio.run(validate_emitted_artifact(_TARGET, _emit(api, {}), api=api))
    assert verdict.applicable and verdict.validated and verdict.valid, verdict.errors
