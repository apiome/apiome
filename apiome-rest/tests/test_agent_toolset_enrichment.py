"""Agent toolset description enrichment service — AGX-1.3 (#4531).

The service functions over the in-memory :class:`~agent_toolset_fakes.FakeToolsetStore`, with a
scripted copilot in place of Ollama. The acceptance criteria, each pinned here:

* a spec with description-less operations produces proposals for review, and accepted proposals
  appear in the compiled toolset;
* nothing generated reaches the compiled toolset without acceptance (proposed and rejected text
  never does, and opting out serves the spec's text even when accepted);
* agent-hostile operations are flagged with machine-readable reasons;
* with no copilot configured the pass is flag-only.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

import pytest
from agent_toolset_fakes import FakeToolsetStore

import app.agent_toolset_enrichment as enrichment
import app.agent_toolsets as toolsets
from app.agent_tool_enrichment import (
    REASON_MISSING_DESCRIPTION,
    REASON_MISSING_PARAM_DESCRIPTION,
    SYSTEM_PROMPT,
)
from app.agent_toolset_enrichment import (
    CODE_ENRICHMENT_INVALID,
    CODE_ENRICHMENT_NOT_FOUND,
    MAX_OPERATIONS_PER_RUN,
    MODE_COPILOT,
    MODE_FLAG_ONLY,
    EnrichmentReview,
    EnrichmentRun,
    compile_agent_toolset,
    get_toolset_enrichment,
    review_toolset_enrichment,
    run_toolset_enrichment,
)
from app.agent_toolsets import (
    CODE_TOOLSET_NOT_FOUND,
    CODE_TOOLSET_SOURCE_UNAVAILABLE,
    AgentToolsetCreate,
    AgentToolsetError,
    AgentToolsetUpdate,
    create_agent_toolset,
    update_agent_toolset,
)
from app.database import db
from app.export_source import ExportSourceError
from app.openapi_normalizer import OpenApiNormalizer

_TENANT = "11111111-1111-4111-8111-111111111111"
_OTHER_TENANT = "99999999-9999-4999-8999-999999999999"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_MISSING = "77777777-7777-4777-8777-777777777777"
_MODEL = "llama3.1:8b"

_DOCUMENTED = "Returns a single pet by its id, including owner and vaccination status."

#: Two undocumented reads (one with an undescribed parameter) and one documented read.
SPEC: Dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Pets", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer"}}],
                "responses": {"200": {"description": "ok"}},
            },
            "post": {"operationId": "createPet", "responses": {"201": {"description": "ok"}}},
        },
        "/pets/{id}": {
            "get": {
                "operationId": "getPet",
                "description": _DOCUMENTED,
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "description": "The pet's UUID, as returned by listPets.",
                        "example": "a1",
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {"200": {"description": "ok"}, "404": {"description": "missing"}},
            },
        },
    },
}

_GOOD_REPLY = {
    "tool": "Lists the pets in the store.",
    "parameters": {"query.limit": "Maximum number of pets to return."},
}


class Copilot:
    """A scripted :data:`~app.agent_toolset_enrichment.DescriptionGenerator`.

    Attributes:
        replies: The reply per operation key (absent → ``None``, an unreachable model).
        prompts: Every ``(model, system, user)`` it was called with.
    """

    def __init__(self, replies: Optional[Dict[str, Any]] = None) -> None:
        self.replies = replies if replies is not None else {}
        self.prompts: List[Tuple[str, str, str]] = []

    def __call__(self, model: str, system: str, user: str) -> Optional[str]:
        self.prompts.append((model, system, user))
        for key, reply in self.replies.items():
            if f"Operation: {key}\n" in user:
                return json.dumps(reply) if isinstance(reply, dict) else reply
        return None


@pytest.fixture
def store(monkeypatch) -> FakeToolsetStore:
    """The toolset accessors in memory, every version reading as :data:`SPEC`, no copilot."""
    monkeypatch.setattr(
        toolsets, "_load_version_api", lambda *_args: OpenApiNormalizer().normalize(SPEC)
    )
    monkeypatch.setattr(enrichment.settings, "agent_enrichment_model", None)
    return FakeToolsetStore().install(monkeypatch, db)


@pytest.fixture
def copilot(monkeypatch) -> Copilot:
    """Configure a model and route the default generator to a scripted copilot."""
    scripted = Copilot({"GET /pets": _GOOD_REPLY, "POST /pets": {"tool": "Adds a new pet to the store."}})
    monkeypatch.setattr(enrichment.settings, "agent_enrichment_model", _MODEL)
    monkeypatch.setattr(enrichment, "_ollama_json", scripted)
    return scripted


def _toolset(store: FakeToolsetStore, tenant: str = _TENANT) -> str:
    version = store.seed_version(tenant)
    return create_agent_toolset(tenant, AgentToolsetCreate(versionId=version), actor_id=_ACTOR).id


def _proposal(result: Any, target_key: str) -> Any:
    return next(p for p in result.proposals if p.target_key == target_key)


def _accept(toolset_id: str, proposal_id: str, description: Optional[str] = None) -> Any:
    _before, after = review_toolset_enrichment(
        _TENANT,
        toolset_id,
        proposal_id,
        EnrichmentReview(decision="accept", description=description),
        actor_id=_ACTOR,
    )
    return after


def _tool(compiled: Any, name: str) -> Dict[str, Any]:
    return next(tool for tool in compiled.tools if tool["name"] == name)


# ============================================================================
# Flags and flag-only mode
# ============================================================================
def test_without_a_copilot_the_pass_only_flags(store):
    """Acceptance: works with copilot infra disabled (the pass becomes flag-only)."""
    toolset_id = _toolset(store)
    result = run_toolset_enrichment(_TENANT, toolset_id)
    assert (result.mode, result.model) == (MODE_FLAG_ONLY, None)
    assert (result.generated, result.attempted_operations, result.proposals) == (0, 0, [])
    assert result.remaining_operations == 2
    assert "insert_agent_toolset_enrichments" not in store.calls


def test_flags_carry_machine_readable_reasons_and_tool_names(store):
    """Acceptance: agent-hostile operations are flagged with machine-readable reasons."""
    toolset_id = _toolset(store)
    report = get_toolset_enrichment(_TENANT, toolset_id)
    by_op = {flag.operation: flag for flag in report.flags}
    # GET /pets/{id} is described, has an example and documents its errors: not flagged.
    assert sorted(by_op) == ["GET /pets", "POST /pets"]
    listing = by_op["GET /pets"]
    assert listing.tool_name == "listPets"
    codes = [reason["code"] for reason in listing.reasons]
    assert codes[0] == REASON_MISSING_DESCRIPTION
    param = next(r for r in listing.reasons if r["code"] == REASON_MISSING_PARAM_DESCRIPTION)
    assert param["parameter"] == "query.limit"
    assert report.counts == {"flagged": 2, "proposed": 0, "accepted": 0, "rejected": 0}


def test_flags_cover_write_ops_even_while_disabled(store):
    toolset_id = _toolset(store)
    report = get_toolset_enrichment(_TENANT, toolset_id)
    assert "POST /pets" in {flag.operation for flag in report.flags}


# ============================================================================
# Proposals
# ============================================================================
def test_the_copilot_proposes_descriptions_for_thin_targets(store, copilot):
    """Acceptance: description-less operations produce proposals visible for review."""
    toolset_id = _toolset(store)
    result = run_toolset_enrichment(_TENANT, toolset_id)
    assert (result.mode, result.model) == (MODE_COPILOT, _MODEL)
    assert (result.generated, result.attempted_operations, result.failed_operations) == (3, 2, 0)
    assert result.remaining_operations == 0
    assert {(p.target_key, p.status) for p in result.proposals} == {
        ("GET /pets", "proposed"),
        ("GET /pets#query.limit", "proposed"),
        ("POST /pets", "proposed"),
    }
    limit = _proposal(result, "GET /pets#query.limit")
    assert (limit.target_kind, limit.parameter, limit.original_description) == (
        "parameter",
        "query.limit",
        None,
    )
    assert limit.proposed_description == "Maximum number of pets to return."
    assert limit.model == _MODEL and limit.accepted_description is None
    # Only the thin operations are asked about, with the shared system prompt.
    assert [model for model, _s, _u in copilot.prompts] == [_MODEL, _MODEL]
    assert all(system == SYSTEM_PROMPT for _m, system, _u in copilot.prompts)
    assert not any("Operation: GET /pets/{id}\n" in user for _m, _s, user in copilot.prompts)


def test_the_pass_is_idempotent(store, copilot):
    toolset_id = _toolset(store)
    first = run_toolset_enrichment(_TENANT, toolset_id)
    copilot.prompts.clear()
    again = run_toolset_enrichment(_TENANT, toolset_id)
    assert (again.generated, again.attempted_operations, again.remaining_operations) == (0, 0, 0)
    assert copilot.prompts == []
    assert [p.id for p in again.proposals] == [p.id for p in first.proposals]


def test_a_reviewed_proposal_is_never_regenerated(store, copilot):
    toolset_id = _toolset(store)
    first = run_toolset_enrichment(_TENANT, toolset_id)
    rejected = _proposal(first, "GET /pets")
    review_toolset_enrichment(
        _TENANT, toolset_id, rejected.id, EnrichmentReview(decision="reject"), actor_id=_ACTOR
    )
    again = run_toolset_enrichment(_TENANT, toolset_id)
    assert _proposal(again, "GET /pets").status == "rejected"
    assert again.generated == 0


def test_an_unreachable_copilot_counts_as_failed_and_stays_pending(store, copilot):
    copilot.replies = {}
    toolset_id = _toolset(store)
    result = run_toolset_enrichment(_TENANT, toolset_id)
    assert (result.generated, result.attempted_operations, result.failed_operations) == (0, 2, 2)
    assert result.proposals == []
    copilot.replies = {"GET /pets": _GOOD_REPLY}
    retry = run_toolset_enrichment(_TENANT, toolset_id)
    assert retry.generated == 2


def test_a_partial_reply_proposes_only_what_it_answers(store, copilot):
    copilot.replies = {"GET /pets": {"tool": "Lists the pets in the store."}}
    toolset_id = _toolset(store)
    result = run_toolset_enrichment(_TENANT, toolset_id, EnrichmentRun(operations=["GET /pets"]))
    assert [p.target_key for p in result.proposals] == ["GET /pets"]
    # The parameter is still undescribed, so the operation is still pending.
    again = run_toolset_enrichment(_TENANT, toolset_id, EnrichmentRun(operations=["GET /pets"]))
    assert again.attempted_operations == 1


def test_a_run_can_be_narrowed_to_named_operations(store, copilot):
    toolset_id = _toolset(store)
    result = run_toolset_enrichment(_TENANT, toolset_id, EnrichmentRun(operations=["POST /pets"]))
    assert [p.target_key for p in result.proposals] == ["POST /pets"]
    assert result.attempted_operations == 1 and result.remaining_operations == 0


def test_naming_an_unknown_operation_is_refused(store, copilot):
    toolset_id = _toolset(store)
    with pytest.raises(AgentToolsetError) as caught:
        run_toolset_enrichment(_TENANT, toolset_id, EnrichmentRun(operations=["GET /nope"]))
    assert caught.value.code == CODE_ENRICHMENT_INVALID
    assert copilot.prompts == []


def test_each_run_asks_about_a_bounded_number_of_operations(store, monkeypatch):
    paths = {
        f"/r{i:02d}": {"get": {"operationId": f"r{i:02d}", "responses": {"200": {"description": "ok"}}}}
        for i in range(MAX_OPERATIONS_PER_RUN + 3)
    }
    spec = {"openapi": "3.0.3", "info": {"title": "Many", "version": "1"}, "paths": paths}
    monkeypatch.setattr(
        toolsets, "_load_version_api", lambda *_args: OpenApiNormalizer().normalize(spec)
    )
    monkeypatch.setattr(enrichment.settings, "agent_enrichment_model", _MODEL)
    monkeypatch.setattr(enrichment, "_ollama_json", lambda *_a: '{"tool": "Reads one resource of the API."}')
    toolset_id = _toolset(store)
    first = run_toolset_enrichment(_TENANT, toolset_id)
    assert (first.attempted_operations, first.remaining_operations) == (MAX_OPERATIONS_PER_RUN, 3)
    second = run_toolset_enrichment(_TENANT, toolset_id)
    assert (second.attempted_operations, second.remaining_operations) == (3, 0)


# ============================================================================
# Review
# ============================================================================
def test_accepting_stamps_the_reviewer_and_the_served_text(store, copilot):
    toolset_id = _toolset(store)
    proposal = _proposal(run_toolset_enrichment(_TENANT, toolset_id), "GET /pets")
    before, after = review_toolset_enrichment(
        _TENANT, toolset_id, proposal.id, EnrichmentReview(decision="accept"), actor_id=_ACTOR
    )
    assert before.status == "proposed"
    assert (after.status, after.accepted_description) == ("accepted", proposal.proposed_description)
    assert after.reviewed_by == _ACTOR and after.reviewed_at is not None


def test_an_edit_is_served_instead_of_the_proposal(store, copilot):
    toolset_id = _toolset(store)
    proposal = _proposal(run_toolset_enrichment(_TENANT, toolset_id), "GET /pets")
    after = _accept(toolset_id, proposal.id, "  Lists every pet, newest first.  ")
    assert after.accepted_description == "Lists every pet, newest first."
    assert after.proposed_description == proposal.proposed_description


@pytest.mark.parametrize(
    ("decision", "description", "target"),
    [
        ("reject", "text with a reject", "GET /pets"),
        ("accept", "   ", "GET /pets"),
        ("accept", "x" * 301, "GET /pets#query.limit"),
    ],
)
def test_invalid_reviews_are_refused(store, copilot, decision, description, target):
    toolset_id = _toolset(store)
    proposal = _proposal(run_toolset_enrichment(_TENANT, toolset_id), target)
    with pytest.raises(AgentToolsetError) as caught:
        review_toolset_enrichment(
            _TENANT,
            toolset_id,
            proposal.id,
            EnrichmentReview(decision=decision, description=description),
            actor_id=_ACTOR,
        )
    assert caught.value.code == CODE_ENRICHMENT_INVALID
    assert store.enrichments[proposal.id]["status"] == "proposed"


def test_reviewing_another_tenants_proposal_is_not_found(store, copilot):
    toolset_id = _toolset(store)
    proposal = _proposal(run_toolset_enrichment(_TENANT, toolset_id), "GET /pets")
    for tenant, toolset, proposal_id in (
        (_OTHER_TENANT, toolset_id, proposal.id),
        (_TENANT, toolset_id, _MISSING),
        (_TENANT, _MISSING, proposal.id),
    ):
        with pytest.raises(AgentToolsetError) as caught:
            review_toolset_enrichment(
                tenant, toolset, proposal_id, EnrichmentReview(decision="accept"), actor_id=_ACTOR
            )
        assert caught.value.code == CODE_ENRICHMENT_NOT_FOUND


# ============================================================================
# Compiled toolset
# ============================================================================
def test_nothing_generated_is_served_before_acceptance(store, copilot):
    """Acceptance: nothing AI-generated reaches agents without human acceptance."""
    toolset_id = _toolset(store)
    raw = compile_agent_toolset(_TENANT, toolset_id)
    run_toolset_enrichment(_TENANT, toolset_id)
    compiled = compile_agent_toolset(_TENANT, toolset_id)
    assert compiled.fingerprint == raw.fingerprint
    assert compiled.enriched_targets == []
    assert "Lists the pets" not in _tool(compiled, "listPets").get("description", "")


def test_accepted_proposals_appear_in_the_compiled_toolset(store, copilot):
    """Acceptance: accepted proposals appear in the compiled toolset."""
    toolset_id = _toolset(store)
    result = run_toolset_enrichment(_TENANT, toolset_id)
    _accept(toolset_id, _proposal(result, "GET /pets").id)
    _accept(toolset_id, _proposal(result, "GET /pets#query.limit").id, "How many pets to return.")

    compiled = compile_agent_toolset(_TENANT, toolset_id)
    assert compiled.enriched_targets == ["GET /pets", "GET /pets#query.limit"]
    tool = _tool(compiled, "listPets")
    assert tool["description"].startswith("Lists the pets in the store.")
    assert tool["inputSchema"]["properties"]["limit"]["description"] == "How many pets to return."
    assert compiled.description_enrichment is True


def test_a_rejected_proposal_is_withdrawn(store, copilot):
    toolset_id = _toolset(store)
    proposal = _proposal(run_toolset_enrichment(_TENANT, toolset_id), "GET /pets")
    _accept(toolset_id, proposal.id)
    review_toolset_enrichment(
        _TENANT, toolset_id, proposal.id, EnrichmentReview(decision="reject"), actor_id=_ACTOR
    )
    assert compile_agent_toolset(_TENANT, toolset_id).enriched_targets == []


def test_opting_out_serves_the_raw_descriptions(store, copilot):
    toolset_id = _toolset(store)
    raw = compile_agent_toolset(_TENANT, toolset_id)
    _accept(toolset_id, _proposal(run_toolset_enrichment(_TENANT, toolset_id), "GET /pets").id)
    update_agent_toolset(
        _TENANT, toolset_id, AgentToolsetUpdate(descriptionEnrichment=False), actor_id=_ACTOR
    )
    compiled = compile_agent_toolset(_TENANT, toolset_id)
    assert compiled.description_enrichment is False
    assert compiled.enriched_targets == []
    assert compiled.fingerprint == raw.fingerprint


def test_only_enabled_tools_are_compiled_and_disabled_ones_get_no_overrides(store, copilot):
    toolset_id = _toolset(store)
    _accept(toolset_id, _proposal(run_toolset_enrichment(_TENANT, toolset_id), "POST /pets").id)
    compiled = compile_agent_toolset(_TENANT, toolset_id)
    # POST is a write op, disabled by default: not compiled, and its accepted text not applied.
    assert {tool["name"] for tool in compiled.tools} == {"listPets", "getPet"}
    assert compiled.enriched_targets == []


def test_a_disabled_toolset_compiles_to_no_tools(store):
    toolset_id = _toolset(store)
    update_agent_toolset(_TENANT, toolset_id, AgentToolsetUpdate(enabled=False), actor_id=_ACTOR)
    compiled = compile_agent_toolset(_TENANT, toolset_id)
    assert (compiled.enabled, compiled.tools) == (False, [])


# ============================================================================
# Refusals
# ============================================================================
@pytest.mark.parametrize(
    "call",
    [
        lambda t, i: get_toolset_enrichment(t, i),
        lambda t, i: run_toolset_enrichment(t, i),
        lambda t, i: compile_agent_toolset(t, i),
    ],
)
def test_another_tenants_toolset_is_not_found(store, call):
    toolset_id = _toolset(store)
    with pytest.raises(AgentToolsetError) as caught:
        call(_OTHER_TENANT, toolset_id)
    assert caught.value.code == CODE_TOOLSET_NOT_FOUND


def test_an_unreadable_version_is_reported(store, monkeypatch):
    toolset_id = _toolset(store)

    def broken(*_args):
        raise ExportSourceError("no captured source")

    monkeypatch.setattr(toolsets, "_load_version_api", broken)
    for call in (get_toolset_enrichment, run_toolset_enrichment, compile_agent_toolset):
        with pytest.raises(AgentToolsetError) as caught:
            call(_TENANT, toolset_id)
        assert caught.value.code == CODE_TOOLSET_SOURCE_UNAVAILABLE


def test_updating_with_only_the_opt_out_is_a_change(store):
    toolset_id = _toolset(store)
    before, after = update_agent_toolset(
        _TENANT, toolset_id, AgentToolsetUpdate(descriptionEnrichment=False), actor_id=_ACTOR
    )
    assert (before.description_enrichment, after.description_enrichment) == (True, False)
