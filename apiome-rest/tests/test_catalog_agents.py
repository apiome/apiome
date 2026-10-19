"""Agent and model entities — CDG-5.2 (#5980).

* **Rules**: slugs, operation keys to pointers (a GraphQL key is kept as unresolved), an agent's
  contract surface, deprecation.
* **The agent as a consumer** (``sync_agent_consumers``): one key whose toolset enables 4 operations
  yields one consumer and one ``agent`` contract with 4 operation pointers — which the CDG-3.1
  ``consumes`` family turns into 4 edges, one per pointer; revoking the key records an empty
  revision (those edges go stale); a re-sync with nothing changed records nothing; several projects
  give one consumer each.
* **Secrets**: no read selects ``key_hash``; no response carries a secret or a hash.
* **Routes**: RBAC, refusals and status codes; the AGX-3.1 revoke and allowlist hooks re-sync the
  agent; the usage page gets the agent's slug.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import agent_key_routes, catalog_agent_store
from app.agent_usage import build_agent_usage
from app.auth import validate_authentication
from app.catalog_agents import (
    AgentKeyRef,
    AgentOut,
    CatalogAgentError,
    ModelOut,
    agent_surface,
    is_deprecated,
    model_ref,
    operation_parts,
    resolve_slug,
)
from app.catalog_graph import _FAMILY_SQL
from app.consumer_contract import SOURCE_AGENT, contract_pointers
from app.consumer_contract_store import ConsumerActor, ConsumerRecord
from app.main import app
from app.permissions import Resource

_TENANT = "11111111-1111-4111-8111-111111111111"
_USER = "33333333-3333-4333-8333-333333333333"
_AGENT = "55555555-5555-4555-8555-555555555555"
_PROJECT_A = "66666666-6666-4666-8666-666666666666"
_PROJECT_B = "77777777-7777-4777-8777-777777777777"
_KEY = "88888888-8888-4888-8888-888888888888"
_ACTOR = ConsumerActor(user_id=_USER, label="ada@example.com")

FOUR_OPERATIONS = ["GET /pets", "POST /pets", "GET /pets/{petId}", "DELETE /pets/{petId}"]


# ---------------------------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------------------------


def test_operation_keys_become_the_classifier_pointer() -> None:
    assert operation_parts("GET /pets/{petId}") == ("get", "/pets/{petId}", "/paths/~1pets~1{petId}/get")
    assert operation_parts("post /a~b") == ("post", "/a~b", "/paths/~1a~0b/post")
    assert operation_parts("Query.user") is None
    assert operation_parts("FETCH /x") is None
    assert operation_parts("GET pets") is None


def test_the_agent_surface_holds_one_operation_per_tool_and_keeps_the_rest() -> None:
    surface, unplaced = agent_surface([*FOUR_OPERATIONS, "GET /pets", "Query.user"])
    assert [op.pointer for op in surface.operations] == [
        "/paths/~1pets/get",
        "/paths/~1pets/post",
        "/paths/~1pets~1{petId}/delete",
        "/paths/~1pets~1{petId}/get",
    ]
    assert all(op.fields == [] for op in surface.operations)
    assert unplaced == ["Query.user"]
    assert len(contract_pointers(surface)) == 4


def test_the_consumes_family_draws_one_edge_per_current_pointer() -> None:
    sql = _FAMILY_SQL["consumes"]
    assert "unnest(cc.surface_pointers)" in sql and "cc.is_current" in sql


@pytest.mark.parametrize(
    ("slug", "name", "expected"),
    [(None, "Support Bot!", "support-bot"), ("Orders-Agent", "x", "orders-agent")],
)
def test_slugs(slug: Optional[str], name: str, expected: str) -> None:
    assert resolve_slug(slug, name) == expected


@pytest.mark.parametrize("slug", ["-bad", "has space", ""])
def test_bad_slugs_are_refused(slug: str) -> None:
    with pytest.raises(CatalogAgentError):
        resolve_slug(slug, "x")


def test_deprecation_has_arrived_only_once_the_date_passes() -> None:
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)
    assert is_deprecated(None, now) is False
    assert is_deprecated(now - timedelta(days=1), now) is True
    assert is_deprecated(now + timedelta(days=1), now) is False
    assert is_deprecated(datetime(2026, 1, 1), now) is True  # naive dates are UTC


def test_an_agent_shows_its_models_deprecation() -> None:
    ref = model_ref({
        "m_id": "m-1", "m_slug": "claude-3", "m_name": "Claude 3", "m_provider": "Anthropic",
        "m_model_version": "2024-02", "m_deprecated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    })
    assert ref is not None and ref.deprecated and ref.deprecated_at.year == 2026
    assert model_ref({"m_id": None}) is None


# ---------------------------------------------------------------------------------------------
# The agent as a consumer
# ---------------------------------------------------------------------------------------------


class _Registry:
    """Fake consumer registry: consumers by project, current contracts, recorded revisions."""

    def __init__(self) -> None:
        self.consumers: Dict[str, ConsumerRecord] = {}
        self.current: Dict[str, Dict[str, Any]] = {}
        self.recorded: List[Dict[str, Any]] = []
        self.links: Dict[str, str] = {}

    def ensure_consumer(self, tenant_id, project_id, *, slug, name, actor, description=None, metadata=None):
        if project_id not in self.consumers:
            self.consumers[project_id] = ConsumerRecord(
                id=f"c-{project_id[:4]}", tenant_id=tenant_id, project_id=project_id, slug=slug, name=name,
                metadata=metadata or {},
            )
        return self.consumers[project_id]

    def get_consumer(self, tenant_id, project_id, consumer_id):
        return self.consumers[project_id]

    def record_contract(self, tenant_id, project_id, consumer, surface, **kwargs):
        pointers = contract_pointers(surface)
        self.recorded.append({"project_id": project_id, "consumer": consumer.id, "pointers": pointers, **kwargs})
        self.current[consumer.id] = {"surface_pointers": pointers}

    def link(self, tenant_id, agent_id, project_id, consumer_id):
        self.links[project_id] = consumer_id
        return True


@pytest.fixture
def registry(monkeypatch):
    fake = _Registry()
    monkeypatch.setattr(catalog_agent_store.consumer_contract_store, "ensure_consumer", fake.ensure_consumer)
    monkeypatch.setattr(catalog_agent_store.consumer_contract_store, "get_consumer", fake.get_consumer)
    monkeypatch.setattr(catalog_agent_store.consumer_contract_store, "record_contract", fake.record_contract)
    monkeypatch.setattr(catalog_agent_store, "_link_consumer", fake.link)
    monkeypatch.setattr(
        catalog_agent_store, "_agent_identity", lambda t, a: {"id": a, "slug": "support-bot", "name": "Support bot"}
    )
    db = MagicMock()
    db.execute_query.side_effect = lambda sql, params=(): [
        {"project_id": p, "consumer_id": c} for p, c in fake.links.items()
    ]
    db.get_current_consumer_contract.side_effect = lambda consumer_id, tenant_id: fake.current.get(consumer_id)
    monkeypatch.setattr(catalog_agent_store, "db", db)
    return fake


def _operations(monkeypatch, wanted: Dict[str, List[str]]) -> None:
    grouped = {
        project: {"version_id": f"v-{project[:4]}", "version_label": "1.0.0", "keys": keys}
        for project, keys in wanted.items()
    }
    monkeypatch.setattr(catalog_agent_store, "operations_by_project", lambda t, a: grouped)


def test_one_key_enabling_four_operations_is_one_consumer_with_four_pointers(registry, monkeypatch) -> None:
    _operations(monkeypatch, {_PROJECT_A: FOUR_OPERATIONS})
    assert catalog_agent_store.sync_agent_consumers(_TENANT, _AGENT, actor=_ACTOR) == 1
    assert list(registry.consumers) == [_PROJECT_A]
    assert registry.consumers[_PROJECT_A].slug == "support-bot"
    assert registry.links == {_PROJECT_A: registry.consumers[_PROJECT_A].id}
    [revision] = registry.recorded
    assert revision["source"] == SOURCE_AGENT
    assert len(revision["pointers"]) == 4  # → four `consumes` edges
    assert revision["version_id"] == f"v-{_PROJECT_A[:4]}"


def test_revoking_the_key_records_an_empty_revision(registry, monkeypatch) -> None:
    _operations(monkeypatch, {_PROJECT_A: FOUR_OPERATIONS})
    catalog_agent_store.sync_agent_consumers(_TENANT, _AGENT, actor=_ACTOR)
    _operations(monkeypatch, {})  # the key is revoked: nothing is callable any more
    assert catalog_agent_store.sync_agent_consumers(_TENANT, _AGENT, actor=_ACTOR) == 1
    assert registry.recorded[-1]["pointers"] == []
    assert registry.recorded[-1]["source"] == SOURCE_AGENT


def test_a_resync_with_nothing_changed_records_nothing(registry, monkeypatch) -> None:
    _operations(monkeypatch, {_PROJECT_A: FOUR_OPERATIONS})
    catalog_agent_store.sync_agent_consumers(_TENANT, _AGENT, actor=_ACTOR)
    assert catalog_agent_store.sync_agent_consumers(_TENANT, _AGENT, actor=_ACTOR) == 0
    assert len(registry.recorded) == 1


def test_an_agent_with_nothing_callable_and_no_consumer_records_nothing(registry, monkeypatch) -> None:
    _operations(monkeypatch, {})
    assert catalog_agent_store.sync_agent_consumers(_TENANT, _AGENT, actor=_ACTOR) == 0
    assert registry.recorded == [] and registry.consumers == {}


def test_two_projects_give_two_consumers(registry, monkeypatch) -> None:
    _operations(monkeypatch, {_PROJECT_A: FOUR_OPERATIONS[:2], _PROJECT_B: ["GET /orders", "Query.order"]})
    assert catalog_agent_store.sync_agent_consumers(_TENANT, _AGENT, actor=_ACTOR) == 2
    assert set(registry.consumers) == {_PROJECT_A, _PROJECT_B}
    by_project = {r["project_id"]: r for r in registry.recorded}
    assert len(by_project[_PROJECT_B]["pointers"]) == 1
    unresolved = by_project[_PROJECT_B]["unresolved"]
    assert [entry.reason for entry in unresolved] == ["method-not-declared"]


def test_losing_one_project_empties_only_that_consumer(registry, monkeypatch) -> None:
    _operations(monkeypatch, {_PROJECT_A: FOUR_OPERATIONS, _PROJECT_B: ["GET /orders"]})
    catalog_agent_store.sync_agent_consumers(_TENANT, _AGENT, actor=_ACTOR)
    _operations(monkeypatch, {_PROJECT_A: FOUR_OPERATIONS})
    assert catalog_agent_store.sync_agent_consumers(_TENANT, _AGENT, actor=_ACTOR) == 1
    assert registry.recorded[-1]["project_id"] == _PROJECT_B and registry.recorded[-1]["pointers"] == []


def test_the_operations_read_respects_revocation_toolsets_and_the_allowlist() -> None:
    sql = " ".join(catalog_agent_store._AGENT_OPERATIONS_SQL.split())
    for fragment in (
        "k.kind = 'agent'",
        "k.deleted_at IS NULL AND k.enabled",
        "t.enabled",
        "tt.enabled",
        "COALESCE(k.tool_allowlist, '[]'::jsonb) ? tt.tool_name",
        "a.deleted_at IS NULL AND a.status = 'active'",
    ):
        assert fragment in sql


# ---------------------------------------------------------------------------------------------
# No secret is ever shown
# ---------------------------------------------------------------------------------------------


def test_no_agent_read_selects_the_key_hash() -> None:
    for sql in (catalog_agent_store._AGENT_KEYS_SQL, catalog_agent_store._AGENT_COLUMNS):
        assert "key_hash" not in sql
    assert "key_hash" not in AgentKeyRef.model_fields


def _agent(**over: Any) -> AgentOut:
    return AgentOut(
        id=_AGENT, slug="support-bot", name="Support bot", status="active",
        keys=[AgentKeyRef(id=_KEY, name="support", key_prefix="ak_1a2b3c4d5...", status="active", enabled_tools=4)],
        **over,
    )


# ---------------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def authed():
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT, "user_id": _USER, "auth_method": "jwt",
    }
    with patch("app.catalog_agent_routes.enforce_permission", return_value=_USER) as permit:
        yield TestClient(app), permit
    app.dependency_overrides.clear()


def test_an_agent_read_carries_no_secret(authed) -> None:
    client, _permit = authed
    with patch("app.catalog_agent_routes.store.get_agent", return_value=_agent()):
        response = client.get("/v1/tenants/acme/catalog-agents/support-bot")
    assert response.status_code == 200
    text = json.dumps(response.json())
    assert "keyPrefix" in text and "ak_1a2b3c4d5..." in text
    assert "key_hash" not in text and "keyHash" not in text and "secret" not in text.lower()


def test_registering_an_agent_with_keys_needs_api_keys_view(authed) -> None:
    client, permit = authed
    with patch("app.catalog_agent_routes.store.create_agent", return_value=_agent()) as create:
        response = client.post(
            "/v1/tenants/acme/catalog-agents", json={"name": "Support bot", "keyIds": [_KEY], "model": "claude"}
        )
    assert response.status_code == 201
    resources = [call.args[2] for call in permit.call_args_list]
    assert resources == [Resource.CONSUMER_CONTRACTS, Resource.API_KEYS]
    assert create.call_args.args[1].key_ids == [_KEY]


@pytest.mark.parametrize(
    ("code", "status"),
    [("agent-not-found", 404), ("agent-slug-taken", 409), ("agent-key-taken", 409), ("agent-key-invalid", 400)],
)
def test_refusals_keep_their_code(authed, code: str, status: int) -> None:
    client, _permit = authed
    with patch("app.catalog_agent_routes.store.link_key", side_effect=CatalogAgentError(code, "no")):
        response = client.put(f"/v1/tenants/acme/catalog-agents/support-bot/keys/{_KEY}")
    assert response.status_code == status and response.json()["detail"]["code"] == code


def test_unknown_fields_are_refused(authed) -> None:
    client, _permit = authed
    response = client.post("/v1/tenants/acme/catalog-agents", json={"name": "x", "secret": "ak_..."})
    assert response.status_code == 422


def test_models_list_and_change(authed) -> None:
    client, permit = authed
    model = ModelOut(id="m-1", slug="claude", name="Claude", provider="Anthropic", model_name="claude",
                     hosting="api", deprecated=False)
    with patch("app.catalog_agent_routes.store.list_models", return_value=[model]), patch(
        "app.catalog_agent_routes.store.update_model", return_value=model
    ) as update:
        assert client.get("/v1/tenants/acme/catalog-models").json()["models"][0]["slug"] == "claude"
        response = client.patch("/v1/tenants/acme/catalog-models/claude", json={"deprecatedAt": None})
    assert response.status_code == 200
    assert "deprecated_at" in update.call_args.args[2].model_fields_set


def test_deleting_an_agent_is_a_204(authed) -> None:
    client, _permit = authed
    with patch("app.catalog_agent_routes.store.delete_agent") as delete:
        assert client.delete("/v1/tenants/acme/catalog-agents/support-bot").status_code == 204
    delete.assert_called_once()


# ---------------------------------------------------------------------------------------------
# AGX hooks
# ---------------------------------------------------------------------------------------------


def test_revoking_a_key_resyncs_the_agent_that_uses_it() -> None:
    with patch.object(catalog_agent_store, "agent_id_for_key", return_value=_AGENT), patch.object(
        catalog_agent_store, "sync_agent_consumers"
    ) as sync:
        agent_key_routes._sync_owning_agent(_TENANT, _KEY, {"user_id": _USER}, _USER)
    assert sync.call_args.args[:2] == (_TENANT, _AGENT)


def test_a_key_no_agent_uses_syncs_nothing_and_a_failure_is_not_raised() -> None:
    with patch.object(catalog_agent_store, "agent_id_for_key", return_value=None), patch.object(
        catalog_agent_store, "sync_agent_consumers"
    ) as sync:
        agent_key_routes._sync_owning_agent(_TENANT, _KEY, {}, None)
    sync.assert_not_called()
    with patch.object(catalog_agent_store, "agent_id_for_key", side_effect=RuntimeError("db down")):
        agent_key_routes._sync_owning_agent(_TENANT, _KEY, {}, None)


def test_the_usage_page_learns_the_agent_slug() -> None:
    day = date(2026, 10, 18)
    usage = build_agent_usage(
        [{"day": day, "key_id": _KEY, "tool_name": "listPets", "calls": 3, "success_calls": 3,
          "key_name": "support", "key_prefix": "ak_1...", "key_revoked": False, "agent_slug": "support-bot"}],
        start_day=day, end_day=day, as_of=datetime(2026, 10, 19, tzinfo=timezone.utc),
    )
    assert usage.agents[0].agent_slug == "support-bot"
    assert usage.model_dump(by_alias=True)["agents"][0]["agentSlug"] == "support-bot"
