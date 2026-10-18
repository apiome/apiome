"""The Azure API Management connector source (CDG-1.4, #5955).

A fake Azure (``tests/azure_apim_fake.py``) serves recorded Entra ID, ARM and export-link responses
for one APIM instance, and the real source runs through
:func:`app.catalog_connector_sync.run_connector_sync` over the in-memory store. Covers the
acceptance criteria: a fixture service with two APIs, one with an operation-level policy, yields
items whose policy-derived facts match a direct FMT-7.2 import; a policy element FMT-7.2 does not
map is in the item's extras and on its coverage ledger; and an expired client secret gives a
``failing`` run with the AAD error code.
"""

from __future__ import annotations

import base64
import io
import json
import os
import zipfile
from typing import Any, Dict, List

import pytest
from azure_apim_fake import (
    CLIENT_SECRET,
    EXPORTS,
    SCOPE,
    SERVICE,
    FakeAzure,
    response_body,
)
from catalog_connector_fakes import FakeConnectorStore, FakeDb, restore_builtin_sources

from app import azure_apim_connector_source as azure
from app import import_source_pipeline
from app.azure_apim_import_source import AzureApimImportSource
from app.catalog_connector_sync import (
    connector_accepts_credentials,
    register_connector_source,
    run_connector_sync,
    validate_connector_scope,
)
from app.catalog_connectors import ConnectorError
from app.config import settings
from app.fileset import IntakeFileset
from app.import_preview_manifest import CoverageClass, build_import_preview_manifest, paginate_import_preview_manifest
from app.mcp_credential_crypto import seal_credential_payload

TENANT = "11111111-1111-4111-8111-111111111111"
ACTOR = "33333333-3333-4333-8333-333333333333"
POLICY_KEYS = ("security", "rate_limits", "backend", "rewrite", "cors", "access", "azure_apim")


class _Importer:
    """Records every document the engine imports and hands back one catalog item per API."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, connector, candidate, document, item_row, actor_id):
        self.calls.append({"candidate": candidate, "document": document, "prior": item_row.get("project_id")})
        return item_row.get("project_id") or f"proj-{candidate.raw['apiId']}"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    # The fake hosts never resolve; the SSRF guard's address rule is covered by the Kong suite.
    monkeypatch.setattr(settings, "ssrf_allow_private", True)
    yield
    restore_builtin_sources()


@pytest.fixture
def store(monkeypatch):
    return FakeConnectorStore().install(monkeypatch)


def _use_fake(fake: FakeAzure) -> None:
    register_connector_source(
        azure.KIND,
        lambda c, creds: azure.AzureApimSource(c, creds, transport=fake.transport()),
        scope_validator=azure.validate_azure_scope,
    )


def _connector(store: FakeConnectorStore, *, secret: str = CLIENT_SECRET, **scope: Any):
    connector = store.add_connector(
        TENANT, kind=azure.KIND, name="Contoso APIM", base_url=None, scope={**SCOPE, **scope}, created_by=ACTOR
    )
    if secret:
        sealed, version = seal_credential_payload({"clientSecret": secret})
        store.credentials[connector["id"]] = {"encrypted_payload": sealed, "key_version": version}
    return connector


def _sync(store, connector, importer=None, db=None):
    db = db or FakeDb()
    importer = importer or _Importer()
    result = run_connector_sync(db, store.connectors[connector["id"]], actor_id=ACTOR, importer=importer)
    return result, importer, db


def _by_api(importer: _Importer) -> Dict[str, Any]:
    return {call["candidate"].raw["apiId"]: call for call in importer.calls}


def _members(content: bytes) -> Dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return {name: archive.read(name).decode("utf-8") for name in archive.namelist()}


def _import_archive(content: bytes, filename: str):
    """Import a fetched archive the way the pipeline does: unpack, pick a root, parse the fileset."""
    intake = import_source_pipeline._resolve_intake(
        {"document_base64": base64.standard_b64encode(content).decode(), "filename": filename}, {}
    )
    adapter = AzureApimImportSource()
    return adapter.normalize(adapter.parse_fileset(intake.fileset, source_label=filename))


def _direct_orders_import():
    """A direct FMT-7.2 import of the same API, assembled by hand from the recorded files."""
    named_values = response_body("namedValues")["value"]
    template = {
        "resources": [
            {"type": "Microsoft.ApiManagement/service/namedValues", "name": f"{SERVICE}/{nv['name']}", "properties": {}}
            for nv in named_values
        ]
        + [
            {
                "type": "Microsoft.ApiManagement/service/backends",
                "name": f"{SERVICE}/orders-backend",
                "properties": {"url": "https://orders.internal.example.com/v2"},
            }
        ]
    }
    members = {
        "orders.openapi.json": (EXPORTS / "orders-api.json").read_text(),
        "policy.xml": response_body("policy-orders-api")["properties"]["value"],
        "get-order.policy.xml": response_body("policy-orders-api-get-order")["properties"]["value"],
        "service.json": json.dumps(template),
    }
    adapter = AzureApimImportSource()
    return adapter.normalize(adapter.parse_fileset(IntakeFileset.from_members(members, root="orders.openapi.json")))


def _policy_facts(model) -> Dict[str, Any]:
    ops = {op.key: {k: op.extras.get(k) for k in POLICY_KEYS} for op in model.operations()}
    report = model.extras["azure_apim"]
    return {"operations": ops, "unmapped": report["unmapped"], "mapped": report["mapped"], "servers": model.servers}


# --- the acceptance criteria -------------------------------------------------------------


def test_a_sync_imports_each_current_revision_and_records_the_rest(store):
    fake = FakeAzure()
    _use_fake(fake)
    result, importer, _ = _sync(store, _connector(store))
    assert result.status == "succeeded" and result.connector_status == "active"
    assert sorted(_by_api(importer)) == ["billing-api", "orders-api"]
    summary = result.summary
    assert summary["candidates"] == 3 and summary["imported"] == 2 and summary["discovered"] == 1
    assert [f["code"] for f in summary["findings"]] == ["api-type-not-exported"]

    items = {row["remote_id"]: row for row in store.items.values()}
    assert items[f"{SERVICE}/orders-api;rev=1"]["status"] == "discovered"
    assert items[f"{SERVICE}/orders-api"]["status"] == "imported"
    orders = items[f"{SERVICE}/orders-api"]
    assert orders["environment"] == SERVICE
    assert orders["hosts"] == ["https://contoso-apim.azure-api.net/orders"]
    assert orders["deployment"]["apiRevision"] == "2" and orders["deployment"]["isCurrent"] is True
    assert orders["deployment"]["products"] == ["Starter", "Unlimited"]


def test_policy_derived_facts_match_a_direct_fmt72_import(store):
    fake = FakeAzure()
    _use_fake(fake)
    _, importer, _ = _sync(store, _connector(store))
    document = _by_api(importer)["orders-api"]["document"]
    assert document.import_kind == "azure-apim" and document.filename == "orders-api.zip"
    synced = _import_archive(document.content, document.filename)
    assert _policy_facts(synced) == _policy_facts(_direct_orders_import())

    get_order = {op.key: op for op in synced.operations()}["GET /orders/{orderId}"]
    assert get_order.extras["rewrite"]["policyScope"] == "operation"
    assert {r["name"] for r in get_order.extras["security"]} == {"apiKeyHeader", "validate-jwt"}


def test_an_unmapped_policy_element_is_in_extras_and_on_the_ledger(store):
    fake = FakeAzure()
    _use_fake(fake)
    _, importer, _ = _sync(store, _connector(store))
    document = _by_api(importer)["orders-api"]["document"]
    model = _import_archive(document.content, document.filename)
    unknown = [u for u in model.extras["azure_apim"]["unmapped"] if u["name"] == "example-unknown-policy"]
    assert unknown and unknown[0]["operation"] == "get-order" and unknown[0]["status"] == "unknown"
    page = paginate_import_preview_manifest(build_import_preview_manifest(model, adapter_key="azure-apim", options={}))
    rows = {row.source_construct: row for row in page.coverage}
    assert rows["apim#unknown-policy.example-unknown-policy"].coverage is CoverageClass.PARTIALLY_MAPPED


def test_an_expired_client_secret_fails_the_run_with_the_aad_error_code(store):
    fake = FakeAzure(token_status=401)
    _use_fake(fake)
    connector = _connector(store)
    result, importer, _ = _sync(store, connector)
    assert result.status == "failed" and result.connector_status == "failing"
    assert store.connectors[connector["id"]]["status"] == "failing"
    assert result.error_class == "auth" and result.http_status == 401
    assert "AADSTS7000222" in result.error_message
    assert CLIENT_SECRET not in (result.error_message or "")
    assert importer.calls == []


# --- inventory, fetch and tags -----------------------------------------------------------


def test_non_current_revisions_import_when_opted_in(store):
    fake = FakeAzure()
    _use_fake(fake)
    result, importer, _ = _sync(store, _connector(store, includeNonCurrentRevisions=True))
    assert sorted(_by_api(importer)) == ["billing-api", "orders-api", "orders-api;rev=1"]
    assert "discovered" not in result.summary
    rev1 = _by_api(importer)["orders-api;rev=1"]
    assert rev1["candidate"].name == "Orders API (revision 1)"
    assert rev1["document"].revision.startswith("rev1-")


def test_the_archive_carries_the_definition_policies_and_named_value_names_only(store):
    fake = FakeAzure()
    _use_fake(fake)
    _, importer, _ = _sync(store, _connector(store))
    orders = _members(_by_api(importer)["orders-api"]["document"].content)
    assert sorted(orders) == ["operations/get-order.xml", "orders-api.openapi.json", "policy.xml", "service.json"]
    service = json.loads(orders["service.json"])
    names = sorted(r["name"] for r in service["resources"])
    assert names == [f"{SERVICE}/billing-key", f"{SERVICE}/orders-backend", f"{SERVICE}/tenant-header"]
    assert "acme-tenant-7" not in orders["service.json"]  # a named value's value is never copied
    assert "x-key" not in orders["service.json"]  # nor a backend's credentials
    billing = _members(_by_api(importer)["billing-api"]["document"].content)
    assert "policy.xml" not in billing  # ARM answered 404: the API has no policy

    exports = [r for r in fake.requests if r.url.host == "apimexports.blob.core.windows.net"]
    assert exports and all("authorization" not in r.headers for r in exports)
    token_forms = [r.content.decode() for r in fake.requests if r.url.host == "login.microsoftonline.com"]
    assert len(token_forms) == 1 and "scope=https%3A%2F%2Fmanagement.azure.com%2F.default" in token_forms[0]


def test_identical_content_is_re_anchored_and_a_policy_change_re_imports(store):
    fake = FakeAzure()
    _use_fake(fake)
    connector = _connector(store)
    _sync(store, connector)
    again, importer, _ = _sync(store, connector)
    assert importer.calls == [] and again.summary["unchanged"] == 2

    changed_policy = response_body("policy-orders-api-get-order")
    changed_policy["properties"]["value"] = (
        '<policies><inbound><base /><rate-limit calls="5" renewal-period="1" /></inbound>'
        "<backend><base /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>"
    )
    fake.overrides["policy-orders-api-get-order"] = changed_policy
    changed, importer, _ = _sync(store, connector)
    assert sorted(_by_api(importer)) == ["orders-api"] and changed.summary["imported"] == 1
    assert _by_api(importer)["orders-api"]["prior"] == "proj-orders-api"


def test_products_become_tags_and_stale_product_tags_are_removed(store):
    fake = FakeAzure()
    _use_fake(fake)
    connector = _connector(store)
    db = FakeDb()
    _sync(store, connector, db=db)
    tags = {(t["project_id"], t["name"]) for t in db.get_tags_for_project("proj-orders-api")}
    assert tags == {("proj-orders-api", "Starter"), ("proj-orders-api", "Unlimited")}
    assert {t["name"] for t in db.get_tags_for_project("proj-billing-api")} == {"Starter"}

    db.create_tag("proj-orders-api", "team-payments", "default", "Added by a person")
    fake.overrides["products-unlimited-apis"] = {"value": []}
    _sync(store, connector, db=db)
    names = {t["name"] for t in db.get_tags_for_project("proj-orders-api")}
    assert names == {"Starter", "team-payments"}


def test_a_failing_tag_step_never_fails_the_import(store, monkeypatch):
    fake = FakeAzure()
    _use_fake(fake)

    class _BrokenDb(FakeDb):
        def get_tags_for_project(self, project_id):
            raise RuntimeError("tags table unavailable")

    result, importer, _ = _sync(store, _connector(store), db=_BrokenDb())
    assert result.status == "succeeded" and result.summary["imported"] == 2
    assert result.summary["postImportFailed"] == 2


# --- failures ----------------------------------------------------------------------------


def test_an_arm_refusal_names_the_arm_error_code(store):
    fake = FakeAzure(deny=["/apis"])
    _use_fake(fake)
    result, _, _ = _sync(store, _connector(store))
    assert result.status == "failed" and result.error_class == "auth" and result.http_status == 403
    assert "AuthorizationFailed" in result.error_message and "apis/read" in result.error_message


def test_no_stored_secret_is_an_invalid_configuration(store):
    _use_fake(FakeAzure())
    result, _, _ = _sync(store, _connector(store, secret=""))
    assert result.status == "failed" and result.error_class == "invalid-configuration"
    assert "PUT …/credentials" in result.error_message


def test_federated_credentials_send_an_assertion_and_no_secret(store, monkeypatch):
    fake = FakeAzure()
    _use_fake(fake)
    monkeypatch.setattr(azure, "federated_token_reader", lambda: "workload-identity-jwt")
    result, importer, _ = _sync(store, _connector(store, secret="", authMethod="federated"))
    assert result.status == "succeeded" and len(importer.calls) == 2
    (form,) = [r.content.decode() for r in fake.requests if r.url.host == "login.microsoftonline.com"]
    assert "client_assertion=workload-identity-jwt" in form and "client_secret" not in form


def test_federated_without_a_workload_identity_is_an_invalid_configuration(store, monkeypatch):
    _use_fake(FakeAzure())
    monkeypatch.setattr(azure, "federated_token_reader", lambda: None)
    result, _, _ = _sync(store, _connector(store, secret="", authMethod="federated"))
    assert result.error_class == "invalid-configuration" and "AZURE_FEDERATED_TOKEN_FILE" in result.error_message


# --- scope -------------------------------------------------------------------------------


def test_a_valid_scope_passes_and_the_kind_accepts_a_credential():
    validate_connector_scope(azure.KIND, {**SCOPE, "authMethod": "federated", "includeNonCurrentRevisions": True}, None)
    assert connector_accepts_credentials(azure.KIND) is True


@pytest.mark.parametrize(
    "change,base_url,fragment",
    [
        ({}, "https://management.azure.com", "takes no base URL"),
        ({"clientSecret": "x"}, None, "Unknown azure-apim scope key"),
        ({"tenantId": "contoso.onmicrosoft.com"}, None, "tenantId must be"),
        ({"subscriptionId": None}, None, "subscriptionId must be"),
        ({"resourceGroup": "rg/../x"}, None, "resourceGroup must be"),
        ({"serviceName": "-apim"}, None, "serviceName must be"),
        ({"authMethod": "certificate"}, None, "authMethod must be"),
        ({"includeNonCurrentRevisions": "yes"}, None, "includeNonCurrentRevisions"),
    ],
)
def test_a_malformed_scope_is_refused(change, base_url, fragment):
    with pytest.raises(ConnectorError) as info:
        validate_connector_scope(azure.KIND, {**SCOPE, **change}, base_url)
    assert info.value.code == "connector-invalid" and fragment in str(info.value)


# --- the archive -------------------------------------------------------------------------


def test_the_archive_is_deterministic():
    kwargs = dict(
        api_policy="<policies><inbound /></policies>",
        operation_policies={"b": "<policies><inbound /></policies>", "a": "<policies><inbound /></policies>"},
        named_values=[{"name": "z", "displayName": "z"}],
        backends={},
        service_name="svc",
    )
    first = azure.build_policy_archive("api.openapi.json", b"{}", **kwargs)
    second = azure.build_policy_archive("api.openapi.json", b"{}", **kwargs)
    assert first == second
    assert sorted(_members(first)) == [
        "api.openapi.json",
        "operations/a.xml",
        "operations/b.xml",
        "policy.xml",
        "service.json",
    ]
    bare = azure.build_policy_archive(
        "api.openapi.json",
        b"{}",
        api_policy=None,
        operation_policies={},
        named_values=[],
        backends={},
        service_name="s",
    )
    assert sorted(_members(bare)) == ["api.openapi.json"]


def test_describe_carries_no_credential():
    source = azure.AzureApimSource({"id": "c1", "kind": azure.KIND, "scope": SCOPE}, {"clientSecret": CLIENT_SECRET})
    described = source.describe()
    assert described["serviceName"] == SERVICE and described["authMethod"] == "client-secret"
    assert CLIENT_SECRET not in json.dumps(described)


def test_a_catalog_item_imported_from_an_archive_is_rebuilt_from_its_capture(store):
    from app.catalog_parsed_model import reconstruct_catalog_api

    fake = FakeAzure()
    _use_fake(fake)
    _, importer, _ = _sync(store, _connector(store))
    document = _by_api(importer)["orders-api"]["document"]
    item = {
        "id": "proj-orders-api",
        "source_format": "azure-apim",
        "format_metadata": {
            "intakeKind": "archive",
            "filesetRoot": "service.json",  # the root archive intake picked: the adapter still finds the definition
            "sourceEncoding": "base64",
            "sourceContent": base64.standard_b64encode(document.content).decode(),
            "sourceLabel": document.filename,
        },
    }
    rebuilt = reconstruct_catalog_api(item)
    assert rebuilt is not None
    assert _policy_facts(rebuilt) == _policy_facts(_import_archive(document.content, document.filename))
