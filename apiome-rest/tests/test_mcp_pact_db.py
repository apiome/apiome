"""The MCP pact routes against a live Postgres — PFX-4.5 (#6942).

* ``list`` — the latest pact per integration (a newer consumer version replaces the older one), its latest
  verification, filters, keyset pages, and nothing from another tenant;
* the key lookup — a live key acts as its owner; a revoked key, another tenant's key and an ownerless key are
  refused;
* ``can-i-deploy`` / ``matrix`` — the same verdict the broker route reaches, bounded;
* ``record-deployment`` — by environment name, then read back by ``can-i-deploy``.

Runs inside one always-rolled-back transaction (the ``broker`` fixture of ``test_pact_matrix_db``). Skipped
when no database is reachable or the pact migrations are not applied.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app import mcp_pact_routes as routes
from app.consumer_contract_store import ConsumerActor
from app.pact_contract_settings import AgentSettings, save_agents
from tests import test_pact_environment_db as environment_db
from tests import test_pact_matrix_db as matrix_db

tx = matrix_db.tx
stack = matrix_db.stack
broker = matrix_db.broker

pytestmark = pytest.mark.requires_db


@pytest.fixture
def mcp(broker: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The broker stack with the MCP pact routes on its transaction and one live MCP key."""
    cursor = broker["cursor"]
    cursor.execute("SELECT id::text AS id FROM apiome.users LIMIT 1")
    broker["owner"] = cursor.fetchone()["id"]
    broker["key"] = _key(broker, broker["seed"]["tenant"], broker["owner"])
    with (
        patch.object(routes, "db", broker["db"]),
        patch.object(routes, "enforce_permission", return_value=broker["owner"]),
    ):
        yield broker


def _key(stack: Dict[str, Any], tenant: str, owner: Any, revoked: bool = False) -> str:
    stack["cursor"].execute(
        """INSERT INTO apiome.mcp_api_keys (key_hash, prefix, label, tenant_id, created_by, revoked_at)
           VALUES (md5(random()::text), 'mcp_test...', 'agent', %s::uuid, %s::uuid,
                   CASE WHEN %s THEN CURRENT_TIMESTAMP END)
           RETURNING id::text AS id""",
        (tenant, owner, revoked),
    )
    return stack["cursor"].fetchone()["id"]


def _list(stack: Dict[str, Any], **fields: Any) -> Dict[str, Any]:
    body = routes.McpPactListRequest.model_validate(
        {"tenantId": stack["seed"]["tenant"], "keyId": stack["key"], **fields}
    )
    return routes.list_latest_pacts(body).model_dump(by_alias=True)


def test_list_returns_the_latest_pact_of_each_integration(mcp: Dict[str, Any]) -> None:
    matrix_db._publish(mcp, "1.0.0")
    sha = matrix_db._publish(mcp, "1.1.0", total=2001)
    matrix_db._provider_version(mcp, "p-1")
    matrix_db._verify(mcp, sha, "p-1", False)
    page = _list(mcp)
    assert page["hasMore"] is False and page["nextCursor"] is None
    [item] = page["items"]
    assert item["consumer"]["slug"] == "billing-service" and item["provider"]["slug"] == "ledger-api"
    assert item["consumerVersion"] == "1.1.0" and item["sha"] == sha
    assert item["latestVerification"]["success"] is False
    assert item["latestVerification"]["providerVersion"] == "p-1"
    assert item["latestVerification"]["kind"] == "native"


def test_list_filters_and_unknown_filters(mcp: Dict[str, Any]) -> None:
    matrix_db._publish(mcp, "1.0.0")
    assert len(_list(mcp, provider="Ledger API")["items"]) == 1
    assert len(_list(mcp, consumer="billing-service")["items"]) == 1
    with pytest.raises(HTTPException) as caught:
        _list(mcp, provider="Nope")
    assert caught.value.status_code == 404


def test_list_pages_by_provider_then_consumer(mcp: Dict[str, Any]) -> None:
    document = matrix_db.publication_db._pact(total=10)
    other = {**document, "provider": {"name": "Audit API"}}
    response = mcp["client"].post(
        f"{matrix_db.BASE}/contracts/publish", json=matrix_db.publication_db._bulk("1.0.0", document, other)
    )
    assert response.status_code == 200, response.text
    first = _list(mcp, limit=1)
    assert [i["provider"]["slug"] for i in first["items"]] == ["audit-api"] and first["hasMore"] is True
    second = _list(mcp, limit=1, cursor=first["nextCursor"])
    assert [i["provider"]["slug"] for i in second["items"]] == ["ledger-api"] and second["hasMore"] is False


def test_list_never_reads_another_tenant(mcp: Dict[str, Any]) -> None:
    matrix_db._publish(mcp, "1.0.0")
    other_key = _key(mcp, mcp["other"]["tenant"], mcp["owner"])
    body = routes.McpPactListRequest.model_validate({"tenantId": mcp["other"]["tenant"], "keyId": other_key})
    assert routes.list_latest_pacts(body).items == []


def test_the_key_lookup_acts_as_the_owner_and_refuses_the_rest(mcp: Dict[str, Any]) -> None:
    tenant = mcp["seed"]["tenant"]
    assert routes.key_auth_data(tenant, mcp["key"])["user_id"] == mcp["owner"]
    for key, code in (
        (_key(mcp, tenant, mcp["owner"], revoked=True), "mcp-pact-key-unknown"),
        (_key(mcp, mcp["other"]["tenant"], mcp["owner"]), "mcp-pact-key-unknown"),
        (_key(mcp, tenant, None), "mcp-pact-key-has-no-owner"),
    ):
        with pytest.raises(HTTPException) as caught:
            routes.key_auth_data(tenant, key)
        assert caught.value.detail["code"] == code


def test_record_deployment_then_can_i_deploy(mcp: Dict[str, Any]) -> None:
    environment_db._create_environment(mcp, "staging", production=False)
    sha = matrix_db._publish(mcp, "1.0.0", branch="main")
    matrix_db._provider_version(mcp, "p-1")
    matrix_db._verify(mcp, sha, "p-1", True)
    tenant, key = mcp["seed"]["tenant"], mcp["key"]
    # PFX-8.15: recording is off for agents until the workspace allows it.
    save_agents(mcp["db"], tenant, AgentSettings(record=True), actor=ConsumerActor(label="admin"))

    record = routes.McpPactRecordDeploymentRequest.model_validate(
        {"tenantId": tenant, "keyId": key, "pacticipant": "Ledger API", "version": "p-1", "environment": "staging"}
    )
    deployed = routes.record_mcp_deployment(record)
    assert deployed.created is True and deployed.deployment["environment"]["name"] == "staging"
    assert routes.record_mcp_deployment(record).created is False

    ask = routes.McpPactCanIDeployRequest.model_validate(
        {
            "tenantId": tenant,
            "keyId": key,
            "pacticipant": "Billing Service",
            "version": "1.0.0",
            "toEnvironment": "staging",
        }
    )
    answer = routes.answer_matrix(
        tenant,
        routes.key_auth_data(tenant, key),
        routes.can_i_deploy_query_string(ask),
        routes.parse_can_i_deploy_query,
        ask.max_rows,
    )
    assert answer.summary["deployable"] is True and answer.rows_total == 1
    assert answer.rows[0]["provider"]["version"] == "p-1" and answer.rows[0]["reason"]["code"] == "verified"

    matrix = routes.McpPactMatrixRequest.model_validate(
        {
            "tenantId": tenant,
            "keyId": key,
            "selectors": [{"pacticipant": "Billing Service", "version": "1.0.0"}],
            "latestby": "cvpv",
            "toEnvironment": "staging",
            "maxRows": 1,
        }
    )
    same = routes.answer_matrix(
        tenant, routes.key_auth_data(tenant, key), routes.matrix_query_string(matrix), routes.parse_matrix_query, 1
    )
    assert same.summary == answer.summary


def test_an_agent_refusal_is_audited_for_the_workspace(mcp: Dict[str, Any]) -> None:
    """PFX-8.15: recording is off by default; production is refused even when it is on."""
    environment_db._create_environment(mcp, "production", production=True)
    matrix_db._publish(mcp, "1.0.0", branch="main")
    matrix_db._provider_version(mcp, "p-1")
    tenant, key = mcp["seed"]["tenant"], mcp["key"]
    record = routes.McpPactRecordDeploymentRequest.model_validate(
        {"tenantId": tenant, "keyId": key, "pacticipant": "Ledger API", "version": "p-1", "environment": "production"}
    )
    with pytest.raises(HTTPException) as off:
        routes.record_mcp_deployment(record)
    assert off.value.detail["code"] == "mcp-pact-agent-action-off"
    save_agents(mcp["db"], tenant, AgentSettings(record=True), actor=ConsumerActor(label="admin"))
    with pytest.raises(HTTPException) as production:
        routes.record_mcp_deployment(record)
    assert production.value.detail["code"] == "mcp-pact-agent-production"
    mcp["cursor"].execute(
        "SELECT detail->>'code' AS code FROM apiome.access_audit WHERE tenant_id = %s::uuid "
        "AND action = 'pacts.agent.refused' ORDER BY created_at",
        (tenant,),
    )
    codes = [row["code"] for row in mcp["cursor"].fetchall()]
    assert codes == ["mcp-pact-agent-action-off", "mcp-pact-agent-production"]
