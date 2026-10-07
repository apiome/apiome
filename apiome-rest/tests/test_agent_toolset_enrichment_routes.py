"""Agent toolset enrichment endpoints — AGX-1.3 (#4531).

Authentication is overridden, the store is :class:`~agent_toolset_fakes.FakeToolsetStore` and the
copilot is scripted. These tests pin the HTTP contract: each route's ``api_keys`` permission, the
status of every refusal, one metadata-only audit row per run and review, and the review loop end to
end (flag → propose → accept → compiled).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from agent_toolset_fakes import FakeToolsetStore
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_agent_toolset_enrichment import SPEC

import app.agent_toolset_enrichment as enrichment
import app.agent_toolsets as toolsets
from app.agent_toolset_routes import AUDIT_ENRICHMENT_REVIEW, AUDIT_ENRICHMENT_RUN
from app.auth import validate_authentication
from app.database import db
from app.main import app
from app.openapi_normalizer import OpenApiNormalizer
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt", "user_email": "a@x.io"}
_MISSING = "77777777-7777-4777-8777-777777777777"
_MODEL = "llama3.1:8b"

_BASE = "/v1/tenants/acme/agent-toolsets"

_REPLY = {"tool": "Lists the pets in the store.", "parameters": {"query.limit": "Maximum pets to return."}}


@pytest.fixture(autouse=True)
def _auth():
    """Authenticate every request as a member of ``_TENANT``."""
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def store(monkeypatch) -> FakeToolsetStore:
    """The toolset accessors in memory, every version reading as the enrichment :data:`SPEC`."""
    monkeypatch.setattr(
        toolsets, "_load_version_api", lambda *_args: OpenApiNormalizer().normalize(SPEC)
    )
    monkeypatch.setattr(enrichment.settings, "agent_enrichment_model", None)
    return FakeToolsetStore().install(monkeypatch, db)


@pytest.fixture
def copilot(monkeypatch) -> None:
    """Configure a model whose every answer is :data:`_REPLY`."""
    monkeypatch.setattr(enrichment.settings, "agent_enrichment_model", _MODEL)
    monkeypatch.setattr(enrichment, "_ollama_json", lambda *_args: json.dumps(_REPLY))


@pytest.fixture
def audits(monkeypatch) -> List[Dict[str, Any]]:
    """Capture access-audit rows instead of writing them."""
    rows: List[Dict[str, Any]] = []
    monkeypatch.setattr(db, "write_access_audit", lambda **fields: rows.append(fields))
    return rows


def _create(store: FakeToolsetStore) -> Dict[str, Any]:
    response = client.post(_BASE, json={"versionId": store.seed_version(_TENANT)})
    assert response.status_code == 201, response.text
    return response.json()


def _run(toolset_id: str, body: Any = None) -> Dict[str, Any]:
    kwargs = {"json": body} if body is not None else {}
    response = client.post(f"{_BASE}/{toolset_id}/enrichment", **kwargs)
    assert response.status_code == 200, response.text
    return response.json()


# ============================================================================
# Permissions
# ============================================================================
@pytest.mark.parametrize(
    ("method", "suffix", "body", "action"),
    [
        ("get", "/enrichment", None, Action.VIEW),
        ("post", "/enrichment", None, Action.EDIT),
        ("patch", f"/enrichment/{_MISSING}", {"decision": "accept"}, Action.EDIT),
        ("get", "/compiled", None, Action.VIEW),
    ],
)
def test_each_route_enforces_its_api_keys_permission(store, audits, method, suffix, body, action):
    toolset = _create(store)
    audits.clear()
    with patch(
        "app.agent_toolset_routes.enforce_permission",
        side_effect=HTTPException(status_code=403, detail="forbidden"),
    ) as guard:
        kwargs = {"json": body} if body is not None else {}
        response = getattr(client, method)(f"{_BASE}/{toolset['id']}{suffix}", **kwargs)
    assert response.status_code == 403
    _db, _auth, resource, granted = guard.call_args.args
    assert (resource, granted) == (Resource.API_KEYS, action)
    assert audits == []


# ============================================================================
# The review loop
# ============================================================================
def test_flag_only_without_a_copilot(store, audits):
    toolset = _create(store)
    audits.clear()
    result = _run(toolset["id"])
    assert result["schemaVersion"] == "agx.toolset-enrichment.v1"
    assert (result["mode"], result["model"], result["generated"]) == ("flag-only", None, 0)
    assert [flag["operation"] for flag in result["flags"]] == ["GET /pets", "POST /pets"]
    assert result["flags"][0]["toolName"] == "listPets"
    assert {"code", "message"} <= set(result["flags"][0]["reasons"][0])
    [row] = audits
    assert row["action"] == AUDIT_ENRICHMENT_RUN
    assert row["detail"]["mode"] == "flag-only" and row["detail"]["flagged"] == 2


def test_propose_accept_compile_end_to_end(store, copilot, audits):
    """Acceptance: proposals are visible for review, and accepted ones appear in the toolset."""
    toolset = _create(store)
    before = client.get(f"{_BASE}/{toolset['id']}/compiled").json()

    result = _run(toolset["id"])
    assert (result["mode"], result["model"], result["generated"]) == ("copilot", _MODEL, 3)
    listed = client.get(f"{_BASE}/{toolset['id']}/enrichment").json()
    assert listed["counts"] == {"flagged": 2, "proposed": 3, "accepted": 0, "rejected": 0}
    proposal = next(p for p in listed["proposals"] if p["targetKey"] == "GET /pets")
    assert proposal["status"] == "proposed" and proposal["acceptedDescription"] is None
    assert proposal["targetKind"] == "tool" and proposal["proposedDescription"] == _REPLY["tool"]

    # Not served while merely proposed.
    unreviewed = client.get(f"{_BASE}/{toolset['id']}/compiled").json()
    assert unreviewed["fingerprint"] == before["fingerprint"]

    audits.clear()
    response = client.patch(
        f"{_BASE}/{toolset['id']}/enrichment/{proposal['id']}",
        json={"decision": "accept", "description": "Lists every pet in the store."},
    )
    assert response.status_code == 200, response.text
    accepted = response.json()
    assert accepted["status"] == "accepted" and accepted["reviewedBy"] == _ACTOR
    [row] = audits
    assert row["action"] == AUDIT_ENRICHMENT_REVIEW
    assert row["target"] == proposal["id"]
    assert row["detail"] == {
        "toolsetId": toolset["id"],
        "operation": "GET /pets",
        "targetKey": "GET /pets",
        "statusBefore": "proposed",
        "statusAfter": "accepted",
        "edited": True,
    }

    compiled = client.get(f"{_BASE}/{toolset['id']}/compiled").json()
    assert compiled["enrichedTargets"] == ["GET /pets"]
    assert compiled["descriptionEnrichment"] is True
    tool = next(t for t in compiled["tools"] if t["name"] == "listPets")
    assert tool["description"].startswith("Lists every pet in the store.")
    assert compiled["fingerprint"] != before["fingerprint"]

    # Opting out serves the spec's text again.
    assert client.patch(f"{_BASE}/{toolset['id']}", json={"descriptionEnrichment": False}).status_code == 200
    raw = client.get(f"{_BASE}/{toolset['id']}/compiled").json()
    assert raw["fingerprint"] == before["fingerprint"] and raw["enrichedTargets"] == []


def test_a_run_can_name_its_operations(store, copilot):
    toolset = _create(store)
    result = _run(toolset["id"], {"operations": ["POST /pets"]})
    assert [p["targetKey"] for p in result["proposals"]] == ["POST /pets"]


# ============================================================================
# Refusals
# ============================================================================
@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("get", "/enrichment", None),
        ("post", "/enrichment", None),
        ("get", "/compiled", None),
    ],
)
def test_a_missing_toolset_is_404(store, audits, method, suffix, body):
    response = getattr(client, method)(f"{_BASE}/{_MISSING}{suffix}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "agent-toolset-not-found"
    assert audits == []


def test_a_missing_proposal_is_404(store, audits):
    toolset = _create(store)
    audits.clear()
    response = client.patch(
        f"{_BASE}/{toolset['id']}/enrichment/{_MISSING}", json={"decision": "reject"}
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "agent-toolset-enrichment-not-found"
    assert audits == []


def test_an_invalid_review_is_422(store, copilot, audits):
    toolset = _create(store)
    proposal = _run(toolset["id"])["proposals"][0]
    audits.clear()
    response = client.patch(
        f"{_BASE}/{toolset['id']}/enrichment/{proposal['id']}",
        json={"decision": "reject", "description": "no"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "agent-toolset-enrichment-invalid"
    assert audits == []


def test_an_unknown_operation_in_a_run_is_422(store, copilot):
    toolset = _create(store)
    response = client.post(f"{_BASE}/{toolset['id']}/enrichment", json={"operations": ["GET /nope"]})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "agent-toolset-enrichment-invalid"


def test_a_bad_decision_is_rejected_by_validation(store):
    toolset = _create(store)
    response = client.patch(
        f"{_BASE}/{toolset['id']}/enrichment/{_MISSING}", json={"decision": "maybe"}
    )
    assert response.status_code == 422
