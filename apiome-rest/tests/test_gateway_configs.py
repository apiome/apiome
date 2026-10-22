"""Gateway configs as entities — CDG-5.3 (#5981).

* **Posture** is read from both shapes the gateway import sources write: Kong's
  ``extras["gateway"]`` (auth hints, unmodeled and global plugins, redactions) and the
  ``extras["security"]`` / ``extras["rate_limits"]`` of AWS API Gateway, Azure APIM and Apigee — names
  and schemes only, merged and de-duplicated.
* **Refresh** keeps one row per (connector, environment): new environments are inserted with a
  unique slug, seen ones updated, vanished ones soft-deleted; a revision whose model cannot be
  rebuilt is skipped; the sync refreshes them before re-deriving ``deployed_on``.
* **Graph**: ``deployed_on`` now points at the gateway config, and ``gateway_config`` is a node kind.
* **Push-back**: Kong → the ``kong`` target; AWS, Azure APIM and Apigee wait on FMT-7.7 (#5461).
* **Routes**: ``imports:view``, a 404 for an unknown config, no credential in any response.
"""

from __future__ import annotations

import inspect
import json
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import catalog_connector_sync, gateway_config_store
from app.auth import validate_authentication
from app.catalog_entities import kind
from app.catalog_graph import _FAMILY_SQL, NODE_KINDS
from app.gateway_configs import (
    GATEWAY_DECLARED_LOSSES,
    GatewayConfigOut,
    GatewayConnectorRef,
    GatewayPosture,
    GatewayPushBack,
    gateway_config_name,
    gateway_config_slug,
    merge_postures,
    posture_from_api,
    push_back,
)
from app.main import app
from app.permissions import Resource

_TENANT = "11111111-1111-4111-8111-111111111111"
_USER = "33333333-3333-4333-8333-333333333333"
_CONNECTOR = "44444444-4444-4444-8444-444444444444"


def _api(extras: Dict[str, Any] | None = None, operations: List[Dict[str, Any]] | None = None) -> Any:
    ops = [SimpleNamespace(extras=op) for op in operations or []]
    return SimpleNamespace(extras=extras or {}, services=[SimpleNamespace(operations=ops)])


# ---------------------------------------------------------------------------------------------
# Posture
# ---------------------------------------------------------------------------------------------


def test_kong_posture_comes_from_the_gateway_report() -> None:
    api = _api({
        "gateway": {
            "auth": [{"scheme": "apiKey", "plugin": "key-auth", "scope": "route"}],
            "unmodeled_plugins": [{"name": "rate-limiting", "scope": "route"}, {"name": "cors", "scope": "global"}],
            "global_plugins": ["prometheus"],
            "credential_redactions": 2,
        }
    })
    assert posture_from_api(api) == {
        "auth": [{"scheme": "apiKey", "via": "key-auth"}],
        "rate_limits": [{"name": "rate-limiting", "kind": "rate-limiting"}],
        "policies": ["cors", "prometheus"],
        "credential_redactions": 2,
    }


def test_aws_azure_and_apigee_posture_comes_from_security_and_rate_limits() -> None:
    aws = _api(operations=[{"security": [{"scheme": "oauth2", "name": "cognito"}]}])
    azure = _api(
        {"rate_limits": [{"policy": "rate-limit-by-key", "calls": 100}]},
        [{"security": [{"scheme": "bearer", "policy": "validate-jwt"}]}],
    )
    apigee = _api(operations=[{"rate_limits": [{"kind": "spike-arrest", "policy": "SA-1", "rate": "30ps"}]}])
    merged = merge_postures([posture_from_api(aws), posture_from_api(azure), posture_from_api(apigee)])
    assert merged["auth"] == [{"scheme": "bearer", "via": "validate-jwt"}, {"scheme": "oauth2", "via": "cognito"}]
    assert merged["rate_limits"] == [
        {"name": "SA-1", "kind": "spike-arrest"},
        {"name": "rate-limit-by-key", "kind": "rate-limit-by-key"},
    ]


def test_postures_merge_without_duplicates_and_sum_redactions() -> None:
    one = {"auth": [{"scheme": "apiKey", "via": "key-auth"}], "rate_limits": [], "policies": ["cors"],
           "credential_redactions": 1}
    merged = merge_postures([one, one])
    assert merged["auth"] == one["auth"] and merged["policies"] == ["cors"] and merged["credential_redactions"] == 2


def test_no_credential_value_reaches_the_posture() -> None:
    api = _api({"gateway": {"auth": [{"scheme": "apiKey", "plugin": "key-auth", "detail": {"key": "s3cr3t"}}]}},
               [{"security": [{"scheme": "apiKey", "name": "x", "value": "s3cr3t"}]}])
    assert "s3cr3t" not in json.dumps(posture_from_api(api))


# ---------------------------------------------------------------------------------------------
# Names, slugs, push-back
# ---------------------------------------------------------------------------------------------


def test_names_and_slugs() -> None:
    assert gateway_config_name("Kong Konnect", "prod") == "Kong Konnect · prod"
    assert gateway_config_name("Kong Konnect", "") == "Kong Konnect"
    assert gateway_config_slug("Kong Konnect", "prod") == "kong-konnect-prod"
    assert gateway_config_slug("Kong Konnect", "prod", {"kong-konnect-prod"}) == "kong-konnect-prod-2"
    assert gateway_config_slug("!!!", "") == "gateway"


@pytest.mark.parametrize(
    ("connector_kind", "expected"),
    [
        ("kong-konnect", {"target": "kong", "reason": None}),
        ("kong-admin", {"target": "kong", "reason": None}),
        ("aws-apigateway", {"target": "aws-apigateway", "reason": None}),
        ("azure-apim", {"target": "azure-apim", "reason": None}),
        ("apigee", {"target": "apigee", "reason": None}),
        ("url", {"target": None, "reason": "unsupported"}),
    ],
)
def test_push_back_targets(connector_kind: str, expected: Dict[str, Any]) -> None:
    assert push_back(connector_kind) == expected


def test_every_gateway_config_declares_it_carries_no_schemas() -> None:
    assert [loss["construct"] for loss in GATEWAY_DECLARED_LOSSES] == ["request-response-schemas"]
    assert "no request/response schemas" in GATEWAY_DECLARED_LOSSES[0]["reason"]


# ---------------------------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------------------------


class _Cursor:
    def __init__(self, db: "_Db") -> None:
        self.db = db
        self._rows: List[Dict[str, Any]] = []

    def execute(self, sql: str, params: Tuple[Any, ...] = ()) -> None:
        sql = " ".join(sql.split())
        self.db.writes.append((sql, params))
        if sql.startswith("SELECT id::text AS id, environment"):
            self._rows = [{"id": cid, "environment": env} for env, cid in self.db.existing.items()]
        elif sql.startswith("SELECT slug"):
            self._rows = [{"slug": slug} for slug in self.db.slugs]
        else:
            self._rows = []

    def fetchall(self) -> List[Dict[str, Any]]:
        return self._rows


class _Db:
    def __init__(self, items: List[Dict[str, Any]], existing: Dict[str, str], slugs: List[str]) -> None:
        self.items = items
        self.existing = existing
        self.slugs = slugs
        self.writes: List[Tuple[str, Tuple[Any, ...]]] = []

    def execute_query(self, sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        if "FROM apiome.catalog_connectors" in sql:
            return [{"id": _CONNECTOR, "name": "Kong Konnect", "kind": "kong-konnect"}]
        return self.items

    def _guarded_tx(self, work: Any) -> Any:
        return work(_Cursor(self))


def test_refresh_keeps_one_row_per_environment(monkeypatch) -> None:
    db = _Db(
        items=[
            {"environment": "prod", "project_id": "p-1"},
            {"environment": "prod", "project_id": "p-2"},
            {"environment": "prod", "project_id": "p-1"},
            {"environment": "", "project_id": None},
        ],
        existing={"prod": "g-prod", "staging": "g-staging"},
        slugs=["kong-konnect-prod", "kong-konnect-staging", "kong-konnect"],
    )
    loaded: List[str] = []

    def load(tenant_id: str, project_id: str) -> Any:
        loaded.append(project_id)
        if project_id == "p-2":
            raise ValueError("no captured source")
        return SimpleNamespace(api=_api({"gateway": {"auth": [{"scheme": "apiKey", "plugin": "key-auth"}]}}))

    monkeypatch.setattr("app.export_source.load_export_source", load)
    assert gateway_config_store.refresh_gateway_configs(db, _TENANT, _CONNECTOR) == 2
    assert loaded == ["p-1", "p-2"]  # each served project once; a broken one is skipped
    writes = [(sql.split()[0], params) for sql, params in db.writes if not sql.startswith("SELECT")]
    update = next(params for verb, params in writes if verb == "UPDATE" and "g-prod" in params)
    assert update[2] == 3  # api_count
    assert json.loads(update[3])["auth"] == [{"scheme": "apiKey", "via": "key-auth"}]
    insert = next(params for verb, params in writes if verb == "INSERT")
    assert insert[2] == "" and insert[3] == "kong-konnect-2" and insert[4] == "Kong Konnect"
    deleted = next(params for verb, params in writes if verb == "UPDATE" and params and params[0] == ["g-staging"])
    assert deleted == (["g-staging"],)


def test_refresh_of_an_unknown_connector_does_nothing() -> None:
    db = _Db([], {}, [])
    db.execute_query = lambda sql, params=(): []  # type: ignore[assignment]
    assert gateway_config_store.refresh_gateway_configs(db, _TENANT, _CONNECTOR) == 0
    assert db.writes == []


def test_the_sync_refreshes_gateway_configs_before_the_edges() -> None:
    source = inspect.getsource(catalog_connector_sync.run_connector_sync)
    assert source.index("refresh_gateway_configs(db, tenant_id, connector_id)") < source.index(
        'refresh_graph(tenant_id, ("deployed_on",)'
    )


# ---------------------------------------------------------------------------------------------
# Graph and registry
# ---------------------------------------------------------------------------------------------


def test_deployed_on_points_at_the_gateway_config() -> None:
    sql = " ".join(_FAMILY_SQL["deployed_on"].split())
    assert "'gateway_config' AS to_kind, g.id AS to_id" in sql
    assert "g.environment = COALESCE(i.environment, '')" in sql and "g.deleted_at IS NULL" in sql
    assert "gateway_config" in NODE_KINDS


def test_gateway_config_is_a_catalog_kind_with_owner_and_graph_node() -> None:
    entry = kind("gateway_config")
    assert entry.table == "apiome.catalog_gateway_configs"
    assert entry.owner_kind == "gateway_config" and entry.graph_kind == "gateway_config"
    assert entry.resource == Resource.IMPORTS
    assert entry.detail_route == "/ade/dashboard/connectors/environments/{slug}"


# ---------------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------------


def _config(**over: Any) -> GatewayConfigOut:
    return GatewayConfigOut(
        id="g-prod", slug="kong-konnect-prod", name="Kong Konnect · prod",
        connector=GatewayConnectorRef(id=_CONNECTOR, name="Kong Konnect", kind="kong-konnect"),
        environment="prod", flavor="kong-konnect", api_count=3,
        posture=GatewayPosture(auth=[{"scheme": "apiKey", "via": "key-auth"}], credential_redactions=2),
        declared_losses=list(GATEWAY_DECLARED_LOSSES),
        push_back=GatewayPushBack(target="kong"),
        **over,
    )


@pytest.fixture
def authed():
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT, "user_id": _USER, "auth_method": "jwt",
    }
    with patch("app.gateway_config_routes.enforce_permission", return_value=_USER) as permit:
        yield TestClient(app), permit
    app.dependency_overrides.clear()


def test_the_list_and_one_read(authed) -> None:
    client, permit = authed
    with patch("app.gateway_config_routes.store.list_gateway_configs", return_value=[_config()]) as listing, patch(
        "app.gateway_config_routes.store.get_gateway_config", return_value=_config()
    ):
        body = client.get(f"/v1/tenants/acme/gateway-configs?connector={_CONNECTOR}").json()
        one = client.get("/v1/tenants/acme/gateway-configs/kong-konnect-prod").json()
    assert body["gatewayConfigs"][0]["pushBack"] == {"target": "kong", "reason": None}
    assert listing.call_args.args[2] == _CONNECTOR
    assert one["declaredLosses"][0]["construct"] == "request-response-schemas"
    assert one["posture"]["credentialRedactions"] == 2
    assert all(call.args[2] == Resource.IMPORTS for call in permit.call_args_list)


def test_an_unknown_gateway_config_is_a_404(authed) -> None:
    client, _permit = authed
    with patch("app.gateway_config_routes.store.get_gateway_config", return_value=None):
        response = client.get("/v1/tenants/acme/gateway-configs/nope")
    assert response.status_code == 404 and response.json()["detail"]["code"] == "gateway-config-not-found"
