"""Catalog facts for per-kind scorecards — CDG-5.4 (#5982).

* **The catalogue**: every registry kind but ``team`` carries facts; each fact has a label; counts are
  met from one; freshness is met within twice the cadence and unmet beyond it (or never).
* **No silent success**: unknown data is ``not_assessed`` (a paused source, a stale shadow inventory,
  agent readiness), a fact the entity cannot have is ``not_applicable`` (no source, no subjects), and
  ``score`` is always ``null``.
* **Each read**: owner, consumers (API and agent), declared dependencies and deployments (current
  edges only), freshness (repository, connector, MCP discovery, gateway sync), shadow (scoped to the
  connector and environment), registry level, trust baseline.
* **Route**: 422 for an unknown kind, 403 without the kind's view permission, 404 for an unknown
  entity, the envelope otherwise.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Tuple
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import catalog_fact_store
from app.auth import validate_authentication
from app.catalog_entities import REGISTRY, kind
from app.catalog_fact_store import CadenceSettings, read_facts
from app.catalog_facts import APPLICABLE_FACTS, FACT_LABELS, CatalogFactsOut, count_status, facts_for_kind, freshness
from app.main import app
from app.permissions import Resource

_TENANT = "11111111-1111-4111-8111-111111111111"
_ID = "22222222-2222-4222-8222-222222222222"
_USER = "33333333-3333-4333-8333-333333333333"
_NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
_CADENCE = CadenceSettings(refresh_default=300, refresh_floor=60, mcp_default=3600)


class FakeDb:
    """Answers each query by the first registered SQL fragment it contains; records every query."""

    def __init__(self, answers: Dict[str, Any] | None = None) -> None:
        self.answers = answers or {}
        self.queries: List[Tuple[str, Tuple[Any, ...]]] = []
        self.baseline: Any = None

    def execute_query(self, sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        flat = " ".join(sql.split())
        self.queries.append((flat, tuple(params)))
        for fragment, answer in self.answers.items():
            if fragment in flat:
                return answer(params) if callable(answer) else answer
        return []

    def get_active_mcp_trust_baseline(self, endpoint_id: str) -> Any:
        return self.baseline


def _facts(db: FakeDb, kind_key: str, owner: Dict[str, bool] | None = None) -> Dict[str, Any]:
    with patch(
        "app.ownership_policy.owner_facts", return_value=owner or {"owner.present": False, "owner.contactable": False}
    ):
        out = read_facts(db, kind(kind_key), _TENANT, _ID, "Thing", cadence=_CADENCE, now=_NOW)
    assert out.score is None
    return {fact.key: fact for fact in out.facts}


# ---------------------------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------------------------


def test_every_kind_but_team_carries_facts_and_every_fact_is_labelled() -> None:
    assert {entry.key for entry in REGISTRY} - set(APPLICABLE_FACTS) == {"team"}
    assert facts_for_kind("team") == ()
    for keys in APPLICABLE_FACTS.values():
        assert keys[:2] == ("owner.present", "owner.contactable")
        assert all(key in FACT_LABELS for key in keys)
    assert "registry.level-set" in facts_for_kind("spec") and "registry.level-set" not in facts_for_kind("api")
    assert facts_for_kind("mcp_server")[-1] == "mcp.baseline-approved"


def test_counts_and_freshness() -> None:
    assert count_status(None) == "not_assessed"
    assert count_status(0) == "unmet" and count_status(3) == "met"
    assert freshness(None, 300, _NOW) == "unmet"
    assert freshness(_NOW - timedelta(seconds=600), 300, _NOW) == "met"
    assert freshness(_NOW - timedelta(seconds=601), 300, _NOW) == "unmet"
    assert freshness(datetime(2026, 10, 19, 11, 55), 300, _NOW) == "met"  # naive is UTC


def test_the_score_is_always_null() -> None:
    out = CatalogFactsOut(kind="spec", id=_ID, name="x", facts=[])
    assert out.model_dump(by_alias=True)["score"] is None


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


def test_owner_facts_with_and_without_an_owner() -> None:
    facts = _facts(FakeDb(), "model", {"owner.present": True, "owner.contactable": False})
    assert facts["owner.present"].status == "met"
    assert facts["owner.contactable"].status == "unmet"
    facts = _facts(FakeDb(), "model")
    assert facts["owner.present"].status == "unmet"
    assert facts["owner.contactable"].status == "not_applicable"


def test_a_spec_counts_consumers_dependencies_and_deployments_from_current_edges() -> None:
    db = FakeDb(
        {
            "FROM apiome.consumer WHERE": [{"n": 2}],
            "edge_kind = %s AND stale_since IS NULL AND provenance": [{"n": 0}],
            "edge_kind = %s AND stale_since IS NULL": [{"n": 1}],
        }
    )
    facts = _facts(db, "spec")
    assert (facts["consumers.declared"].status, facts["consumers.declared"].value) == ("met", 2)
    assert facts["dependencies.declared"].status == "unmet"
    assert facts["deployment.known"].status == "met"
    edge_queries = [params for sql, params in db.queries if "catalog_edges" in sql]
    assert all(params[1] == ["project", "catalog_item"] for params in edge_queries)
    assert ("depends_on" in edge_queries[0]) and edge_queries[0][-1] == "declared"
    assert "deployed_on" in edge_queries[1]


def test_a_gateway_config_counts_the_apis_deployed_on_it() -> None:
    db = FakeDb({"edge_kind = %s AND stale_since IS NULL": [{"n": 4}]})
    with (
        patch.object(catalog_fact_store, "_shadow", return_value=catalog_fact_store._agent_readiness()),
        patch.object(catalog_fact_store, "_freshness", return_value=catalog_fact_store._agent_readiness()),
    ):
        facts = _facts(db, "gateway_config")
    assert facts["deployment.known"].value == 4
    assert "to_kind = ANY" in next(sql for sql, _ in db.queries if "catalog_edges" in sql)


def test_an_agent_counts_the_apis_it_consumes_and_readiness_is_not_assessed() -> None:
    facts = _facts(FakeDb({"catalog_agent_consumers": [{"n": 3}]}), "agent")
    assert facts["consumers.declared"].value == 3 and facts["consumers.declared"].status == "met"
    assert facts["agent.readiness"].status == "not_assessed"
    assert "ATQ-2" in facts["agent.readiness"].detail


@pytest.mark.parametrize(
    ("repos", "connectors", "expected"),
    [
        ([], [], "not_applicable"),
        (
            [
                {
                    "id": "r1",
                    "name": "acme/api",
                    "last_success": _NOW - timedelta(minutes=5),
                    "interval": 300,
                    "auto": True,
                    "paused_at": None,
                }
            ],
            [],
            "met",
        ),
        (
            [
                {
                    "id": "r1",
                    "name": "acme/api",
                    "last_success": _NOW - timedelta(hours=1),
                    "interval": 300,
                    "auto": True,
                    "paused_at": None,
                }
            ],
            [],
            "unmet",
        ),
        (
            [{"id": "r1", "name": "acme/api", "last_success": None, "interval": 300, "auto": False, "paused_at": None}],
            [],
            "not_assessed",
        ),
        (
            [],
            [
                {
                    "id": "c1",
                    "name": "Kong",
                    "status": "active",
                    "interval": None,
                    "last_success": _NOW - timedelta(minutes=2),
                }
            ],
            "met",
        ),
        (
            [{"id": "r1", "name": "acme/api", "last_success": None, "interval": 300, "auto": True, "paused_at": None}],
            [
                {
                    "id": "c1",
                    "name": "Kong",
                    "status": "active",
                    "interval": 600,
                    "last_success": _NOW - timedelta(minutes=15),
                }
            ],
            "met",
        ),
    ],
    ids=["no-source", "repo-fresh", "repo-stale", "repo-paused", "connector-fresh", "any-source-fresh"],
)
def test_api_freshness(repos, connectors, expected) -> None:
    db = FakeDb(
        {
            "FROM apiome.repository_import_spec": repos,
            "FROM apiome.catalog_connector_items i": connectors,
            "FROM apiome.versions": [{"at": _NOW - timedelta(days=3)}],
        }
    )
    fact = _facts(db, "api")["refresh.fresh"]
    assert fact.status == expected
    assert "Last revision" in fact.detail


def test_mcp_freshness_and_baseline() -> None:
    db = FakeDb(
        {
            "FROM apiome.mcp_endpoints": [
                {"last_discovered_at": _NOW - timedelta(hours=1), "discovery_cadence_seconds": None, "enabled": True}
            ]
        }
    )
    db.baseline = {"created_at": _NOW - timedelta(days=1)}
    facts = _facts(db, "mcp_server")
    assert facts["refresh.fresh"].status == "met"  # 1 h within 2 × the 1 h default
    assert facts["mcp.baseline-approved"].status == "met"
    db.baseline = None
    db.answers["FROM apiome.mcp_endpoints"] = [
        {"last_discovered_at": None, "discovery_cadence_seconds": 60, "enabled": False}
    ]
    facts = _facts(db, "mcp_server")
    assert facts["refresh.fresh"].status == "not_assessed"
    assert facts["mcp.baseline-approved"].status == "unmet"


def test_connector_freshness_respects_pausing() -> None:
    connector = {
        "id": _ID,
        "name": "Kong",
        "kind": "kong-konnect",
        "status": "paused",
        "interval": 300,
        "last_success": _NOW - timedelta(days=2),
    }
    db = FakeDb({"FROM apiome.catalog_connectors c WHERE c.id": [connector]})
    with patch.object(catalog_fact_store, "_shadow", return_value=catalog_fact_store._agent_readiness()):
        facts = _facts(db, "connector")
    assert facts["refresh.fresh"].status == "not_assessed"
    connector["status"] = "active"
    with patch.object(catalog_fact_store, "_shadow", return_value=catalog_fact_store._agent_readiness()):
        facts = _facts(db, "connector")
    assert facts["refresh.fresh"].status == "unmet"


def _shadow_fact(db: FakeDb, kind_key: str, report: Dict[str, Any], items: List[Dict[str, Any]]):
    calls: Dict[str, Any] = {}

    def build(**kwargs: Any) -> Dict[str, Any]:
        calls.update(kwargs)
        return report

    with (
        patch("app.shadow_api_store.load_report_connectors", return_value=[{"id": "c1"}]),
        patch(
            "app.shadow_api_store.load_report_items",
            side_effect=lambda _db, ids, env: (calls.update(env=env), items)[1],
        ),
        patch("app.shadow_api_store.load_catalog_entries", return_value=[]),
        patch("app.shadow_api_report.build_shadow_report", side_effect=build),
    ):
        fact = catalog_fact_store._shadow(db, kind(kind_key), _TENANT, _ID)
    return fact, calls


def test_shadow_none_is_scoped_and_never_met_on_a_stale_inventory() -> None:
    fact, _ = _shadow_fact(FakeDb(), "connector", {"stale": [], "summary": {"shadow": 0}}, [])
    assert fact.status == "met"
    fact, _ = _shadow_fact(FakeDb(), "connector", {"stale": [], "summary": {"shadow": 2}}, [])
    assert fact.status == "unmet" and fact.detail == "2 shadow APIs."
    fact, _ = _shadow_fact(FakeDb(), "connector", {"stale": [{"connectorId": "c1"}], "summary": {"shadow": 0}}, [])
    assert fact.status == "not_assessed"


def test_shadow_for_the_no_environment_gateway_config_keeps_only_unlabelled_items() -> None:
    db = FakeDb({"FROM apiome.catalog_gateway_configs WHERE id": [{"connector_id": "c1", "environment": ""}]})
    _, calls = _shadow_fact(
        db, "gateway_config", {"stale": [], "summary": {"shadow": 0}}, [{"environment": None}, {"environment": "prod"}]
    )
    assert calls["env"] is None
    assert calls["items"] == [{"environment": None}]


def test_registry_level_set() -> None:
    entry = kind("spec")
    none = catalog_fact_store._registry_level(FakeDb(), entry, _TENANT, _ID)
    assert none.status == "not_applicable"
    unset = catalog_fact_store._registry_level(
        FakeDb(
            {
                "FROM apiome.schema_subjects": [
                    {"name": "a", "compatibility_level": "NONE"},
                    {"name": "b", "compatibility_level": None},
                ]
            }
        ),
        entry,
        _TENANT,
        _ID,
    )
    assert unset.status == "unmet" and "b" in unset.detail
    good = catalog_fact_store._registry_level(
        FakeDb({"FROM apiome.schema_subjects": [{"name": "a", "compatibility_level": "FULL"}]}), entry, _TENANT, _ID
    )
    assert good.status == "met" and good.evidence[0].href.endswith("?tab=subjects")


# ---------------------------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def client():
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT,
        "user_id": _USER,
        "auth_method": "jwt",
    }
    yield TestClient(app)
    app.dependency_overrides.clear()


def _get(client: TestClient, path: str, *, allowed: Callable[[str], bool] = lambda r: True, name: Any = "Orders"):
    with (
        patch(
            "app.catalog_entity_routes.has_permission", side_effect=lambda _db, _a, resource, _act: allowed(resource)
        ),
        patch("app.catalog_entity_routes.entity_name", return_value=name),
        patch(
            "app.catalog_entity_routes.read_facts",
            side_effect=lambda db, entry, t, i, n, cadence: CatalogFactsOut(kind=entry.key, id=i, name=n, facts=[]),
        ),
    ):
        return client.get(path)


def test_the_route_returns_the_envelope(client) -> None:
    response = _get(client, f"/v1/catalog/acme/entities/spec/{_ID}/facts")
    assert response.status_code == 200
    assert response.json() == {"kind": "spec", "id": _ID, "name": "Orders", "facts": [], "score": None}


def test_the_route_refuses_unknown_kinds_entities_and_missing_permission(client) -> None:
    assert _get(client, f"/v1/catalog/acme/entities/galaxy/{_ID}/facts").status_code == 422
    assert _get(client, f"/v1/catalog/acme/entities/spec/{_ID}/facts", name=None).status_code == 404
    assert _get(client, "/v1/catalog/acme/entities/spec/not-a-uuid/facts").status_code == 404
    denied = _get(client, f"/v1/catalog/acme/entities/connector/{_ID}/facts", allowed=lambda r: r != Resource.IMPORTS)
    assert denied.status_code == 403
