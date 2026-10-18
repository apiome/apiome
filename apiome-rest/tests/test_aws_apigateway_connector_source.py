"""The AWS API Gateway connector source (CDG-1.3, #5954).

moto stands in for STS and API Gateway's inventory; ``GetExport`` / ``ExportApi`` answer from the
FMT-7.1 corpus fixtures (see ``tests/aws_apigateway_fake.py``). The real source runs through
:func:`app.catalog_connector_sync.run_connector_sync` over the in-memory store. Covers the
acceptance criteria: one REST API with two stages and one HTTP API yield three catalog items whose
canonical output equals a direct FMT-7.1 import of the same exports; an unchanged ``deploymentId``
is reported as unchanged with its reason; a role-assumption failure names the missing permission;
an empty region is a successful run with ``candidates: 0``.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, List

import pytest
from aws_apigateway_fake import (
    EMPTY_REGION,
    EXTERNAL_ID,
    REGION,
    ROLE_ARN,
    moto_estate,
    session_factory_with,
)
from catalog_connector_fakes import FakeConnectorStore, FakeDb, restore_builtin_sources

from app import aws_apigateway_connector_source as aws
from app.aws_apigateway_import_source import AwsApiGatewayImportSource
from app.catalog_connector_sync import (
    check_connector_connection,
    connector_accepts_credentials,
    run_connector_sync,
    source_factory_for,
    validate_connector_scope,
)
from app.catalog_connectors import ConnectorError
from app.config import settings
from app.import_source import canonical_fingerprint

TENANT = "11111111-1111-4111-8111-111111111111"
ACTOR = "33333333-3333-4333-8333-333333333333"
SCOPE = {"roleArn": ROLE_ARN, "externalId": EXTERNAL_ID, "regions": [REGION]}


class _Importer:
    """Records every export the engine imports; one catalog item per stage."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, connector, candidate, document, item_row, actor_id):
        self.calls.append({"candidate": candidate, "document": document, "prior": item_row.get("project_id")})
        return item_row.get("project_id") or f"proj-{candidate.remote_id}"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    yield
    restore_builtin_sources()


@pytest.fixture
def estate(monkeypatch):
    with moto_estate(monkeypatch) as built:
        built["export_calls"] = []
        monkeypatch.setattr(
            aws,
            "session_factory",
            session_factory_with(
                built["exports"], http_deployments=built["http_deployments"], calls=built["export_calls"]
            ),
        )
        yield built


@pytest.fixture
def store(monkeypatch):
    return FakeConnectorStore().install(monkeypatch)


def _connector(store, scope=None):
    return store.add_connector(TENANT, kind=aws.KIND, name="AWS prod", scope=scope or dict(SCOPE), created_by=ACTOR)


def _sync(store, connector, importer=None):
    importer = importer or _Importer()
    db = FakeDb()
    result = run_connector_sync(db, store.connectors[connector["id"]], actor_id=ACTOR, importer=importer)
    return result, importer, db


def _canonical(content: bytes):
    adapter = AwsApiGatewayImportSource()
    return adapter.normalize(adapter.parse(content.decode("utf-8")))


# --- acceptance --------------------------------------------------------------------------


def test_two_rest_stages_and_one_http_api_yield_three_items_equal_to_a_direct_import(store, estate):
    connector = _connector(store)
    result, importer, _ = _sync(store, connector)

    assert result.status == "succeeded"
    assert result.summary["candidates"] == 3 and result.summary["imported"] == 3
    by_id = {call["candidate"].remote_id: call for call in importer.calls}
    rest, http = estate["rest_id"], estate["http_id"]
    assert sorted(by_id) == sorted(
        [f"{REGION}/rest/{rest}/prod", f"{REGION}/rest/{rest}/dev", f"{REGION}/http/{http}/$default"]
    )
    for call in importer.calls:
        candidate, document = call["candidate"], call["document"]
        assert document.import_kind == "aws-apigateway"
        exported = estate["exports"][(candidate.raw["apiId"], candidate.environment)]
        assert document.content == exported  # the bytes go to FMT-7.1 unchanged
        synced, direct = _canonical(document.content), _canonical(exported)
        assert canonical_fingerprint(synced) == canonical_fingerprint(direct)
        assert synced.model_dump() == direct.model_dump()
    assert ("GetExport", rest, "prod") in estate["export_calls"]
    assert ("ExportApi", http, "$default") in estate["export_calls"]


def test_each_stage_is_an_environment_with_its_invoke_url_and_deployment(store, estate):
    _sync(store, _connector(store))
    rows = {row["environment"]: row for row in store.items.values()}
    rest = estate["rest_id"]
    prod = rows["prod"]
    assert prod["hosts"] == [f"https://{rest}.execute-api.{REGION}.amazonaws.com/prod"]
    assert prod["remote_revision"] == estate["deployments"]["prod"] and prod["base_path"] == "/prod"
    assert prod["remote_name"] == "orders (prod)"
    deployment = prod["deployment"]
    assert deployment["apiType"] == "rest" and deployment["accountId"] == "123456789012"
    assert deployment["suggestedOwners"] == [
        {"team": "payments", "source": "gateway_tag", "sourceRef": "apiome:owner=payments"}
    ]
    http = rows["$default"]
    assert http["remote_revision"] == "h7x2k9" and http["deployment"]["apiType"] == "http"
    assert http["hosts"][0].startswith(f"https://{estate['http_id']}.execute-api.")


def test_an_unchanged_deployment_is_reported_unchanged_with_the_reason(store, estate):
    connector = _connector(store)
    _sync(store, connector)
    estate["export_calls"].clear()

    again, importer, _ = _sync(store, connector)
    assert again.status == "succeeded"
    assert again.summary["imported"] == 0 and again.summary["unchanged"] == 3
    assert importer.calls == [] and estate["export_calls"] == []  # nothing re-exported
    prod = next(i for i in again.summary["unchangedItems"] if i["remoteId"].endswith("/prod"))
    assert prod["revision"] == estate["deployments"]["prod"]
    assert prod["reasonCode"] == "checksum-fallback-unchanged"
    assert f"deploymentId {estate['deployments']['prod']} is unchanged" in prod["reason"]


def test_a_redeployed_stage_is_the_only_one_reimported(store, estate):
    import boto3

    connector = _connector(store)
    _sync(store, connector)
    gw = boto3.client("apigateway", region_name=REGION)
    gw.create_deployment(restApiId=estate["rest_id"], stageName="dev")
    # The new deployment changed the definition: one more route.
    export = json.loads(estate["exports"][(estate["rest_id"], "dev")])
    export["paths"]["/health"] = {
        "get": {"responses": {"200": {"description": "ok"}}, "x-amazon-apigateway-integration": {"type": "mock"}}
    }
    estate["exports"][(estate["rest_id"], "dev")] = json.dumps(export).encode()

    result, importer, _ = _sync(store, connector)
    assert result.summary["imported"] == 1 and result.summary["unchanged"] == 2
    [call] = importer.calls
    assert call["candidate"].environment == "dev" and call["prior"] is not None


def test_a_redeploy_with_an_identical_definition_imports_nothing(store, estate):
    import boto3

    connector = _connector(store)
    _sync(store, connector)
    boto3.client("apigateway", region_name=REGION).create_deployment(restApiId=estate["rest_id"], stageName="dev")
    result, importer, _ = _sync(store, connector)
    # The stage is exported (its deploymentId moved) but the bytes match: re-anchored, not imported.
    assert result.summary["fetched"] == 1 and result.summary["imported"] == 0 and importer.calls == []


def test_a_role_assumption_failure_names_the_missing_permission(store, estate, monkeypatch):
    monkeypatch.setattr(
        aws,
        "session_factory",
        session_factory_with(estate["exports"], refuse={"before-call.sts.AssumeRole": ("sts:AssumeRole", ROLE_ARN)}),
    )
    result, importer, _ = _sync(store, _connector(store))
    assert result.status == "failed" and result.connector_status == "failing"
    assert result.error_class == "auth" and result.http_status == 403
    assert f"Missing permission sts:AssumeRole on {ROLE_ARN}" in result.error_message
    assert importer.calls == []


def test_a_denied_api_gateway_call_names_the_action_and_resource(store, estate, monkeypatch):
    resource = f"arn:aws:apigateway:{REGION}::/restapis"
    monkeypatch.setattr(
        aws,
        "session_factory",
        session_factory_with(
            estate["exports"], refuse={"before-call.api-gateway.GetRestApis": ("apigateway:GET", resource)}
        ),
    )
    result, _, _ = _sync(store, _connector(store))
    assert result.status == "failed" and result.error_class == "auth"
    assert f"Missing permission apigateway:GET on {resource}" in result.error_message


def test_a_region_with_no_apis_is_a_successful_run_with_no_candidates(store, estate):
    result, importer, _ = _sync(store, _connector(store, scope={**SCOPE, "regions": [EMPTY_REGION]}))
    assert result.status == "succeeded" and result.connector_status == "active"
    assert result.summary["candidates"] == 0 and importer.calls == []
    assert result.summary["findings"] == [
        {
            "code": "region-empty",
            "severity": "info",
            "region": EMPTY_REGION,
            "message": "No REST or HTTP API with a deployed stage in this region.",
        }
    ]


def test_websocket_apis_are_a_finding_not_an_item(store, estate):
    result, importer, _ = _sync(store, _connector(store))
    [finding] = [f for f in result.summary["findings"] if f["code"] == "websocket-api-not-exported"]
    assert finding["apiName"] == "chat"
    assert all(call["candidate"].deployment["apiName"] != "chat" for call in importer.calls)


def test_a_stage_without_a_deployment_is_a_finding(store, estate):
    import boto3

    boto3.client("apigatewayv2", region_name=REGION).create_stage(ApiId=estate["http_id"], StageName="beta")
    result, importer, _ = _sync(store, _connector(store))
    [finding] = [f for f in result.summary["findings"] if f["code"] == "stage-not-deployed"]
    assert finding["stage"] == "beta" and len(importer.calls) == 3


def test_a_malformed_owner_tag_is_a_finding(store, estate):
    import boto3

    gw = boto3.client("apigateway", region_name=REGION)
    legacy = gw.create_rest_api(name="legacy", tags={"apiome:owner": "Not A Slug!"})
    root = gw.get_resources(restApiId=legacy["id"])["items"][0]["id"]
    gw.put_method(restApiId=legacy["id"], resourceId=root, httpMethod="GET", authorizationType="NONE")
    gw.put_integration(restApiId=legacy["id"], resourceId=root, httpMethod="GET", type="MOCK")
    gw.create_deployment(restApiId=legacy["id"], stageName="live")
    estate["exports"][(legacy["id"], "live")] = estate["exports"][(estate["rest_id"], "prod")]

    result, _, _ = _sync(store, _connector(store))
    [finding] = [f for f in result.summary["findings"] if f["code"] == "owner-tag-invalid"]
    assert finding["apiName"] == "legacy" and finding["tag"] == "apiome:owner=Not A Slug!"
    row = next(r for r in store.items.values() if r["environment"] == "live")
    assert row["deployment"]["suggestedOwners"] == []


def test_no_aws_identity_is_an_invalid_configuration(store, estate, monkeypatch):
    from botocore.exceptions import NoCredentialsError

    def no_identity(**kwargs):
        session = session_factory_with(estate["exports"])(**kwargs)

        def refuse(**_):
            raise NoCredentialsError()

        session.events.register("before-call.sts.AssumeRole", refuse)
        return session

    monkeypatch.setattr(aws, "session_factory", no_identity)
    result, _, _ = _sync(store, _connector(store))
    assert result.status == "failed" and result.error_class == "invalid-configuration"
    assert "no AWS identity" in result.error_message


# --- the creation-time dry run ----------------------------------------------------------


def test_the_dry_run_passes_against_a_reachable_account(estate):
    assert check_connector_connection({"kind": aws.KIND, "scope": dict(SCOPE)}) is True


@pytest.mark.parametrize(
    "event,action,resource",
    [
        ("before-call.sts.AssumeRole", "sts:AssumeRole", ROLE_ARN),
        ("before-call.api-gateway.GetAccount", "apigateway:GET", f"arn:aws:apigateway:{REGION}::/account"),
        ("before-call.apigatewayv2.GetApis", "apigateway:GET", f"arn:aws:apigateway:{REGION}::/apis"),
    ],
)
def test_the_dry_run_names_the_missing_permission(estate, monkeypatch, event, action, resource):
    factory = session_factory_with(estate["exports"], refuse={event: (action, resource)})
    monkeypatch.setattr(aws, "session_factory", factory)
    with pytest.raises(ConnectorError) as info:
        check_connector_connection({"kind": aws.KIND, "scope": dict(SCOPE)})
    assert info.value.code == "connector-check-failed"
    assert info.value.reason == f"{action} on {resource}"


# --- scope and credentials --------------------------------------------------------------


@pytest.mark.parametrize(
    "scope,base_url,fragment",
    [
        ({**SCOPE, "roleArn": "arn:aws:iam::123:user/x"}, None, "roleArn"),
        ({k: v for k, v in SCOPE.items() if k != "externalId"}, None, "externalId"),
        ({**SCOPE, "regions": []}, None, "regions"),
        ({**SCOPE, "regions": ["eu-west-1", "eu-west-1"]}, None, "regions"),
        ({**SCOPE, "regions": ["Mars"]}, None, "regions"),
        ({**SCOPE, "accessKeyId": "AKIA"}, None, "Unknown"),
        (dict(SCOPE), "https://apigateway.example.com", "base URL"),
    ],
)
def test_invalid_aws_scopes_are_refused(scope, base_url, fragment):
    with pytest.raises(ConnectorError) as info:
        validate_connector_scope(aws.KIND, scope, base_url)
    assert info.value.code == "connector-invalid" and fragment in str(info.value)


def test_a_valid_scope_passes_and_the_kind_stores_no_credential():
    validate_connector_scope(aws.KIND, {**SCOPE, "regions": ["eu-west-1", "us-gov-west-1"]}, None)
    assert connector_accepts_credentials(aws.KIND) is False
    assert connector_accepts_credentials("kong-admin") is True
    assert source_factory_for(aws.KIND) is aws.AwsApiGatewaySource


def test_the_documented_policy_covers_every_resource_a_sync_reads():
    resources = set(aws.REQUIRED_POLICY["Statement"][0]["Resource"])
    for _, action, resource in aws.REQUIRED_ACTIONS[1:]:
        assert action == "apigateway:GET"
        assert resource.replace("{region}", "*") in resources
