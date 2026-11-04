"""xRegistry target card + CLI + fixtures — MFX-34.4 (#4309).

What the ``xregistry`` export target (MFX-34.1, checked by MFX-34.3) shows and writes on every export
surface, pinned in ``fixtures/xregistry_target/outcomes.json`` (regenerate with
``APIOME_REGEN_XREGISTRY_TARGET=1``):

* **the card** — per source kind (an imported xRegistry, a CloudEvents event, a REST API, a GraphQL
  schema, a JSON Schema item and a gateway configuration): whether it is offered, and the fidelity
  tier and preserved share its badge shows (:func:`app.export_routes.build_target_fidelity_entries` —
  what the Export dialog, Browse and ``apiome export targets`` read). A gateway configuration has
  neither a type nor an event, so its card is greyed out with the reason;
* **the transcoding guard** — an event source needs no confirmation; a REST source does, with the
  critical event-registry advisory (MFX-34.3);
* **the options** — ``registry_id``, ``source``, ``indent``; each pinned choice writes one document
  that passes the export gate (structure, the official xRegistry schema, the round trip);
* **the round trip** — every export re-imports through the xRegistry importer (MFI-19.2) with its
  schemas and messages;
* **browse** — the public ``…/document`` route delivers the document as JSON;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-xregistry.json`` and
  ``apiome-ui/tests/fixtures/export-targets-xregistry-{rest,xregistry,gateway}.json`` carry the live
  descriptor, options schema, defaults and card badge;
  ``apiome-cli/tests/fixtures/export-job-completed-xregistry-lossy.json`` carries the Petstore export's
  live fidelity envelope (summary, **report**, advisory) and file name.

The pinned outcomes use only sources that import without an external toolchain, so they reproduce anywhere.
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
from app.import_source import get_import_source, load_builtin_import_sources
from app.transcoding_guards import classify_transcode

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "xregistry_target" / "outcomes.json"
_CLI_FIXTURES = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_XREGISTRY_TARGET"))
_TARGET = "xregistry"
_ARTIFACT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

#: One corpus source per kind: the file and the format it is imported as.
SOURCES: Dict[str, tuple[str, str]] = {
    "xregistry": ("xregistry/02-typical-order-events.json", "xregistry"),
    "cloudevents": ("cloudevents/06-user-signedup.json", "cloudevents"),
    "rest": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "graphql": ("graphql/06-union-types.graphql", "graphql"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "gateway": ("kong/01-minimal-single-service.yaml", "kong"),
}
#: Event sources: no confirmation, no event-registry advisory.
EVENT_KINDS = ("xregistry", "cloudevents")
#: Sources with request/response operations: the critical advisory and a confirmation.
OPERATION_KINDS = ("rest", "graphql")
#: The option choices pinned, and the emit options that pick each.
PICKS: Dict[str, Dict[str, Any]] = {
    "default": {},
    "named": {"registry_id": "shop", "source": "/shop/orders"},
    "compact": {"indent": 0},
}
#: The sources whose exports are pinned for every option choice.
PICK_SOURCES = ("xregistry", "rest")
#: The UI fixtures recorded beside the REST one: the target's own format, and a source it cannot export.
UI_SOURCES = {"rest": "rest", "xregistry": "xregistry", "gateway": "gateway"}


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
    """The pinned facts of one export: file, tier, gate verdict, what it holds and what reads back."""
    result = _emit(api, options)
    text = str(result.files[0].content)
    document = json.loads(text)
    summary = build_export_fidelity(api, get_emitter(_TARGET), options=options or None).summary
    verdict = asyncio.run(validate_emitted_artifact(_TARGET, result, api=api, options=options))
    source = get_import_source(_TARGET)
    back = source.normalize(source.parse(text))
    schemas = sorted(sid for group in (document.get("schemagroups") or {}).values() for sid in group["schemas"])
    messages = sorted(f"{gid}.{mid}" for gid, group in (document.get("messagegroups") or {}).items()
                      for mid in group["messages"])
    return {
        "files": [emitted.path for emitted in result.files],
        "tier": summary.tier.value,
        "preserved_percent": summary.preserved_percent,
        "valid": bool(verdict.valid),
        "lines": len(text.splitlines()),
        "registryid": document["registryid"],
        "schemas": schemas,
        "messages": messages,
        "reimported_messages": sorted(op.key for op in back.operations()),
    }


def _measure() -> Dict[str, Any]:
    cards = {}
    for kind in SOURCES:
        api = _source(kind)
        card = _card(api)
        guard = classify_transcode(api, get_emitter(_TARGET))
        cards[kind] = {"available": card.descriptor.available, "tier": card.fidelity.tier.value,
                       "preserved_percent": card.fidelity.preserved_percent,
                       "guard": guard.verdict.value, "requires_confirmation": guard.requires_confirmation}
    picks = {kind: {pick: _outcome(_source(kind), options) for pick, options in PICKS.items()}
             for kind in PICK_SOURCES}
    return {"cards": cards, "picks": picks}


def _targets_body(kind: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to the xRegistry target."""
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
    _check_recorded(_CLI_FIXTURES / "export-targets-xregistry.json", _targets_body("rest"))


def test_the_cli_job_fixture_carries_the_live_report_and_file() -> None:
    _check_recorded(_CLI_FIXTURES / "export-job-completed-xregistry-lossy.json", _job_body())


@pytest.mark.parametrize("name", UI_SOURCES)
def test_the_ui_targets_fixtures_are_the_live_registry(name: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-xregistry-{name}.json", _targets_body(UI_SOURCES[name]))


# ===========================================================================
# The card and the guard
# ===========================================================================


@pytest.mark.parametrize("kind", SOURCES)
def test_the_card_is_an_event_target_offered_or_greyed_out(kind: str) -> None:
    card = _card(_source(kind))
    assert card.descriptor.paradigm == "event" and card.descriptor.multi_file is False
    if kind == "gateway":
        assert card.descriptor.available is False
        assert (card.descriptor.unavailable_reason or "").startswith(
            "xRegistry export needs at least one type or event")
    else:
        assert card.descriptor.available is True


@pytest.mark.parametrize("kind", ["cloudevents", "rest", "graphql", "json-schema"])
def test_a_source_of_another_format_badges_lossy_with_its_share(kind: str) -> None:
    fidelity = _card(_source(kind)).fidelity
    assert fidelity.tier.value == "lossy" and 0 <= fidelity.preserved_percent < 100


@pytest.mark.parametrize("kind", EVENT_KINDS)
def test_an_event_source_needs_no_confirmation(kind: str) -> None:
    guard = classify_transcode(_source(kind), get_emitter(_TARGET))
    assert not guard.requires_confirmation and guard.dropped_operations == 0


@pytest.mark.parametrize("kind", OPERATION_KINDS)
def test_an_operation_bearing_source_needs_confirmation(kind: str) -> None:
    guard = classify_transcode(_source(kind), get_emitter(_TARGET))
    assert guard.requires_confirmation and any("event registry" in reason for reason in guard.reasons)


def test_the_options_are_in_the_descriptor() -> None:
    card = _card(_source("rest"))
    assert set(card.options_schema["properties"]) == {"registry_id", "source", "indent"}
    assert card.default_options == {"registry_id": None, "source": None, "indent": 2}


# ===========================================================================
# Options, the gate, the round trip and browse
# ===========================================================================


@pytest.mark.parametrize("pick", PICKS)
@pytest.mark.parametrize("kind", PICK_SOURCES)
def test_each_pick_writes_one_document_the_gate_accepts(kind: str, pick: str) -> None:
    outcome = _outcome(_source(kind), PICKS[pick])
    assert outcome["valid"] is True
    assert len(outcome["files"]) == 1 and outcome["files"][0].endswith(".xregistry.json")
    assert (outcome["lines"] == 1) is (pick == "compact")
    if pick == "named":
        assert outcome["registryid"] == "shop" and outcome["files"] == ["shop.xregistry.json"]


@pytest.mark.parametrize("kind", PICK_SOURCES)
def test_every_message_reads_back(kind: str) -> None:
    outcome = _outcome(_source(kind), {})
    assert set(outcome["messages"]) <= set(outcome["reimported_messages"])


def test_the_named_source_reaches_every_message() -> None:
    document = json.loads(str(_emit(_source("xregistry"), {"source": "/shop/orders"}).files[0].content))
    sources = {message["envelopemetadata"]["source"]["value"]
               for group in document["messagegroups"].values() for message in group["messages"].values()}
    # The imported registry states its own sources; the option fills only a missing one.
    assert sources == {"/orders"}


def test_browse_delivers_the_document_as_json() -> None:
    response = render_emitted_document(_source("xregistry"), _TARGET, {}, None, bundle_multi_file=True)
    assert response.media_type.startswith("application/json")
    assert json.loads(response.body)["registryid"] == "orders"


def test_a_rest_source_writes_its_types_as_schemas_and_no_messages() -> None:
    outcome = _outcome(_source("rest"), {})
    assert outcome["schemas"] and outcome["messages"] == []
