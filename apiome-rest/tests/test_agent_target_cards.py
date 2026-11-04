"""MCP & A2A target cards + CLI + fixtures — MFX-32.5 (#4299).

What the agent-interface export targets (``mcp``, MFX-32.1; ``a2a``, MFX-32.2) show and write on every
export surface, pinned in ``fixtures/agent_target/outcomes.json`` (regenerate with
``APIOME_REGEN_AGENT_TARGET=1``):

* **the cards** — per source kind (REST, GraphQL, RPC, JSON Schema, an imported MCP server and an imported
  A2A agent): whether each target is offered, and the fidelity tier and preserved share its badge shows
  (:func:`app.export_routes.build_target_fidelity_entries` — what the Export dialog, Browse and
  ``apiome export targets`` read). A source with nothing a tool or skill can be made of gets a greyed-out
  card with its reason;
* **the options** — MCP's ``grouping`` and ``protocol_version``, A2A's ``skills_from``; each pinned choice
  writes its files and passes the export gate;
* **the round trip** — every export re-imports through the matching importer (the MCP importer, the
  MFI-18.1 A2A importer) to the same tools or skills;
* **browse** — the public ``…/document`` route delivers the descriptor or card as JSON;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-{mcp,a2a}.json`` and
  ``apiome-ui/tests/fixtures/export-targets-{mcp,a2a}-{rest,<own format>,data}.json`` carry the live
  descriptor, options schema, defaults and card badge (``data``: a JSON Schema item, greyed out); ``apiome-cli/tests/fixtures/export-job-completed-{mcp,a2a}-lossy.json``
  carry the Petstore export's live fidelity envelope (summary, **report**, advisory) and file name, so the
  CLI's report is tested against the real one.

The pinned outcomes use only sources that import without an external toolchain, so they reproduce anywhere.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi, Operation, OperationKind, Service
from app.catalog_conversion import build_conversion_source
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_routes import build_target_fidelity_entries, render_emitted_document
from app.export_validation import validate_emitted_artifact
from app.import_source import get_import_source, load_builtin_import_sources

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "agent_target" / "outcomes.json"
_CLI_FIXTURES = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_AGENT_TARGET"))
TARGETS = ("mcp", "a2a")

#: One corpus source per kind: the file and the format it is imported as.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "graphql": ("graphql/06-union-types.graphql", "graphql"),
    "rpc": ("thrift/01-user-service.thrift", "thrift"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "mcp": ("mcp/02-typical-tickets-server.json", "mcp"),
    "a2a": ("a2a/02-typical-travel-concierge.json", "a2a"),
}

#: The option choices pinned per target, and the emit options that pick each.
PICKS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "mcp": {"default": {}, "per-service": {"grouping": "per-service"},
            "2025-03-26": {"protocol_version": "2025-03-26"}},
    "a2a": {"default": {}, "tags": {"skills_from": "tags"}},
}
#: The source kind each target's UI fixture records beside the REST one: the target's own format.
OWN_SOURCE = {"mcp": "mcp", "a2a": "a2a"}
#: The sources each target cannot export, and the start of the reason its greyed-out card gives.
UNAVAILABLE = {
    ("mcp", "json-schema"): "MCP Tool Definitions export needs at least one operation an agent can call",
    ("mcp", "a2a"): "MCP Tool Definitions export needs at least one operation an agent can call",
    ("a2a", "json-schema"): "A2A Agent Card export needs an agent or at least one operation",
}

_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_ARTIFACT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _source(kind: str) -> CanonicalApi:
    path, fmt = SOURCES[kind]
    file = _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": file.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}
    ).api


def _card(api: CanonicalApi, target: str) -> Any:
    return next(entry for entry in build_target_fidelity_entries(api) if entry.descriptor.key == target)


def _emit(api: CanonicalApi, target: str, options: Dict[str, Any]) -> Any:
    emitter = get_emitter(target)
    return emitter().emit(api, opts=coerce_emit_options(emitter, options))


def _units(target: str, document: Dict[str, Any]) -> List[str]:
    """The tool names of an MCP descriptor, or the skill ids of an A2A card."""
    if target == "mcp":
        return [tool["name"] for tool in document.get("tools") or []]
    return [skill["id"] for skill in document.get("skills") or []]


def _reimported(target: str, content: str) -> List[str]:
    """The tools (MCP) or skills (A2A) the matching importer reads back out of one exported file."""
    source = get_import_source(target)
    api = source.normalize(source.parse(content))
    if target == "a2a":
        return [skill.id for agent in api.agents for skill in agent.skills]
    return [operation.name for operation in api.operations()]


def _outcome(api: CanonicalApi, target: str, options: Dict[str, Any]) -> Dict[str, Any]:
    """The pinned facts of one export: files, tier, gate verdict, what it holds and what reads back."""
    result = _emit(api, target, options)
    summary = build_export_fidelity(api, get_emitter(target), options=options or None).summary
    verdict = asyncio.run(validate_emitted_artifact(target, result, api=api, options=options))
    written: List[str] = []
    reimported: List[str] = []
    for emitted in result.files:
        written += _units(target, json.loads(str(emitted.content)))
        reimported += _reimported(target, str(emitted.content))
    return {
        "files": [emitted.path for emitted in result.files],
        "tier": summary.tier.value,
        "preserved_percent": summary.preserved_percent,
        "valid": bool(verdict.valid),
        "written": written,
        "reimported": sorted(reimported),  # the importers order by name, not by the written order
    }


def _measure() -> Dict[str, Any]:
    cards: Dict[str, Any] = {}
    for target in TARGETS:
        cards[target] = {}
        for kind in SOURCES:
            card = _card(_source(kind), target)
            cards[target][kind] = {"available": card.descriptor.available, "tier": card.fidelity.tier.value,
                                   "preserved_percent": card.fidelity.preserved_percent}
    picks = {target: {kind: {pick: _outcome(_source(kind), target, options) for pick, options in PICKS[target].items()}
                      for kind in ("rest", OWN_SOURCE[target])} for target in TARGETS}
    return {"cards": cards, "picks": picks}


def _targets_body(kind: str, target: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to one target."""
    card = _card(_source(kind), target).model_dump(mode="json")
    return {"artifact": _ARTIFACT, "version": "1.0.0", "targets": [card]}


def _job_body(target: str) -> Dict[str, Any]:
    """The completed export-job envelope for the Petstore export to ``target`` (what the CLI replays)."""
    api = _source("rest")
    result = _emit(api, target, {})
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
            "fidelity": build_export_fidelity(api, get_emitter(target)).model_dump(mode="json"),
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
def test_the_cli_targets_fixture_is_the_live_registry(target: str) -> None:
    _check_recorded(_CLI_FIXTURES / f"export-targets-{target}.json", _targets_body("rest", target))


@pytest.mark.parametrize("target", TARGETS)
def test_the_cli_job_fixture_carries_the_live_report_and_file(target: str) -> None:
    _check_recorded(_CLI_FIXTURES / f"export-job-completed-{target}-lossy.json", _job_body(target))


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("which", ["rest", "own", "data"])
def test_the_ui_targets_fixtures_are_the_live_registry(target: str, which: str) -> None:
    """``rest`` and the target's own format badge the card; ``data`` (a JSON Schema item) greys it out."""
    kind = {"rest": "rest", "own": OWN_SOURCE[target], "data": "json-schema"}[which]
    name = "data" if which == "data" else kind
    _check_recorded(_UI_FIXTURES / f"export-targets-{target}-{name}.json", _targets_body(kind, target))


# ===========================================================================
# The cards
# ===========================================================================


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("kind", SOURCES)
def test_each_card_is_offered_or_greyed_out_with_its_reason(target: str, kind: str) -> None:
    card = _card(_source(kind), target)
    assert card.descriptor.paradigm == "agent"  # the *Agents & tools* heading
    assert card.descriptor.multi_file is False
    reason = UNAVAILABLE.get((target, kind))
    assert card.descriptor.available is (reason is None)
    if reason is not None:
        assert (card.descriptor.unavailable_reason or "").startswith(reason)


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("kind", ["rest", "graphql", "rpc"])
def test_an_api_badges_lossy_with_its_share(target: str, kind: str) -> None:
    fidelity = _card(_source(kind), target).fidelity
    assert fidelity.tier.value == "lossy" and 0 <= fidelity.preserved_percent < 100


def test_an_imported_a2a_agent_badges_lossless() -> None:
    fidelity = _card(_source("a2a"), "a2a").fidelity
    assert (fidelity.tier.value, fidelity.preserved_percent) == ("lossless", 100)


def test_an_imported_mcp_server_is_lossy_only_for_its_resources_and_prompts() -> None:
    api = _source("mcp")
    report = build_export_fidelity(api, get_emitter("mcp")).report
    dropped = [item for item in report.items if item.kind.value == "drop"]
    assert dropped and all("not a tool" in item.message or "servers" in item.message for item in dropped)


@pytest.mark.parametrize("target", TARGETS)
def test_an_event_only_source_is_greyed_out(target: str) -> None:
    events = CanonicalApi(
        paradigm=ApiParadigm.EVENT, format="asyncapi-3.0", identity=ApiIdentity(name="Orders"),
        services=[Service(key="orders", name="orders", operations=[
            Operation(key="orderPlaced.publish", name="orderPlaced", kind=OperationKind.PUBLISH)])],
    )
    card = _card(events, target)
    assert card.descriptor.available is False and card.descriptor.unavailable_reason


def test_the_options_are_in_the_descriptors() -> None:
    mcp = _card(_source("rest"), "mcp")
    options = set(mcp.options_schema["properties"])
    assert {"protocol_version", "grouping", "output_schema", "include_deprecated"} <= options
    assert (mcp.default_options["protocol_version"], mcp.default_options["grouping"]) == ("2025-06-18", "single")
    a2a = _card(_source("rest"), "a2a")
    assert {"skills_from", "url", "include_deprecated"} <= set(a2a.options_schema["properties"])
    assert a2a.default_options["skills_from"] == "operations"


# ===========================================================================
# Options, the gate and the round trip
# ===========================================================================


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("which", ["rest", "own"])
def test_each_pick_passes_the_gate_and_reads_back(target: str, which: str) -> None:
    kind = "rest" if which == "rest" else OWN_SOURCE[target]
    for pick, options in PICKS[target].items():
        outcome = _outcome(_source(kind), target, options)
        assert outcome["valid"], (pick, outcome)
        assert outcome["written"] and outcome["reimported"] == sorted(outcome["written"]), pick


def test_per_service_grouping_writes_a_descriptor_per_service() -> None:
    files = _outcome(_source("rest"), "mcp", {"grouping": "per-service"})["files"]
    assert len(files) >= 1 and all(path.endswith(".mcp.json") for path in files)


def test_tag_skills_group_the_operations() -> None:
    by_operation = _outcome(_source("rest"), "a2a", {})["written"]
    by_tag = _outcome(_source("rest"), "a2a", {"skills_from": "tags"})["written"]
    assert len(by_tag) < len(by_operation)


# ===========================================================================
# Browse
# ===========================================================================


@pytest.mark.parametrize("target", TARGETS)
def test_browse_delivers_the_document_as_json(target: str) -> None:
    response = render_emitted_document(_source("rest"), target, {}, None, bundle_multi_file=True)
    assert response.media_type.startswith("application/json")
    document = json.loads(response.body)
    assert _units(target, document)
