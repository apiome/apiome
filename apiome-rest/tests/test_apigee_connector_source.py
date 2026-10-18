"""The Apigee connector source (CDG-1.5, #5956).

A fake Google (``tests/apigee_fake.py``) serves recorded token and Apigee Management API responses
for one organization, and the real source runs through
:func:`app.catalog_connector_sync.run_connector_sync` over the in-memory store. Covers the acceptance
criteria: two proxies, one deployed to ``test`` and ``prod`` at different revisions, yield two
environments on one item with the right revisions; a bundle whose route has no target endpoint
surfaces FMT-7.3's declared condition on the item; and a scope or permission failure names what is
missing.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, List

import pytest
from apigee_fake import ORDERS_REV3, ORDERS_REV5, ORG, STORE_REV1, FakeGoogle
from catalog_connector_fakes import FakeConnectorStore, FakeDb, restore_builtin_sources
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app import apigee_connector_source as apigee
from app.apigee_import_source import ApigeeImportSource
from app.catalog_connector_sync import register_connector_source, run_connector_sync, validate_connector_scope
from app.catalog_connectors import ConnectorError
from app.config import settings
from app.import_source_pipeline import _resolve_intake
from app.mcp_credential_crypto import seal_credential_payload

TENANT = "11111111-1111-4111-8111-111111111111"
ACTOR = "33333333-3333-4333-8333-333333333333"


def _service_account_json() -> str:
    """A throwaway service-account key (a fresh RSA key; the fake token endpoint accepts any signature)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    return json.dumps(
        {
            "type": "service_account",
            "project_id": ORG,
            "private_key_id": "k1",
            "private_key": pem,
            "client_email": f"apiome-catalog@{ORG}.iam.gserviceaccount.com",
            "client_id": "1",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


SA_JSON = _service_account_json()


class _Importer:
    """Records imports; a row already linked (or sharing an item) keeps that item."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, connector, candidate, document, item_row, actor_id):
        self.calls.append({"candidate": candidate, "document": document, "prior": item_row.get("project_id")})
        return item_row.get("project_id") or f"proj-{candidate.name}"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "ssrf_allow_private", True)
    yield
    restore_builtin_sources()


@pytest.fixture
def store(monkeypatch):
    return FakeConnectorStore().install(monkeypatch)


def _use(fake: FakeGoogle) -> None:
    register_connector_source(
        apigee.KIND,
        lambda c, creds: apigee.ApigeeSource(c, creds, transport=fake.transport()),
        scope_validator=apigee.validate_apigee_scope,
    )


def _connector(store, *, credential: str = SA_JSON, **scope: Any):
    connector = store.add_connector(
        TENANT,
        kind=apigee.KIND,
        name="Apigee prod",
        base_url=None,
        scope={"organization": ORG, **scope},
        created_by=ACTOR,
    )
    if credential:
        sealed, version = seal_credential_payload({"credentialJson": credential})
        store.credentials[connector["id"]] = {"encrypted_payload": sealed, "key_version": version}
    return connector


def _sync(store, connector, importer=None):
    importer = importer or _Importer()
    result = run_connector_sync(FakeDb(), store.connectors[connector["id"]], actor_id=ACTOR, importer=importer)
    return result, importer


def _rows(store) -> Dict[str, Dict[str, Any]]:
    return {row["remote_id"]: row for row in store.items.values()}


# --- the acceptance criteria -------------------------------------------------------------


def test_one_proxy_in_two_environments_is_one_item_with_both_revisions(store):
    fake = FakeGoogle()
    _use(fake)
    result, importer = _sync(store, _connector(store))
    assert result.status == "succeeded", result.error_message
    rows = _rows(store)
    prod, test = rows[f"{ORG}/orders-v2/prod"], rows[f"{ORG}/orders-v2/test"]
    assert (prod["environment"], prod["remote_revision"]) == ("prod", "3")
    assert (test["environment"], test["remote_revision"]) == ("test", "5")
    assert prod["project_id"] == test["project_id"] == "proj-orders-v2"
    revisions = sorted(call["document"].revision for call in importer.calls if call["candidate"].name == "orders-v2")
    assert revisions == ["3", "5"]
    # The second environment was imported into the item the first one created.
    second = [c for c in importer.calls if c["candidate"].name == "orders-v2"][1]
    assert second["prior"] == "proj-orders-v2"


def test_a_proxy_deployed_nowhere_is_discovered_only(store):
    fake = FakeGoogle()
    _use(fake)
    result, importer = _sync(store, _connector(store))
    legacy = _rows(store)[f"{ORG}/legacy-billing"]
    assert legacy["status"] == "discovered" and legacy["remote_revision"] == "2" and legacy["environment"] is None
    assert "legacy-billing" not in {c["candidate"].name for c in importer.calls}
    assert result.summary["discovered"] == 1 and result.summary["imported"] == 3


def test_the_bundle_goes_to_fmt73_and_a_targetless_route_is_a_declared_condition(store):
    fake = FakeGoogle()
    _use(fake)
    _, importer = _sync(store, _connector(store))
    store_doc = next(c["document"] for c in importer.calls if c["candidate"].name == "store-v1")
    assert store_doc.import_kind == "apigee" and store_doc.filename == "store-v1-rev1.zip"
    assert store_doc.content == STORE_REV1
    intake = _resolve_intake(
        {"document_base64": base64.standard_b64encode(store_doc.content).decode(), "filename": store_doc.filename}, {}
    )
    adapter = ApigeeImportSource()
    model = adapter.normalize(adapter.parse_fileset(intake.fileset))
    declared = model.extras["apigee"]["declaredConditions"]
    assert any(c["kind"] == "route-without-target" and c["routeRule"] == "no-route" for c in declared)
    docs = {c["document"].revision: c["document"].content for c in importer.calls if c["candidate"].name == "orders-v2"}
    assert docs == {"3": ORDERS_REV3, "5": ORDERS_REV5}


def test_a_missing_permission_is_named(store):
    fake = FakeGoogle(deny={"/environments/prod/deployments": "permission-denied"})
    _use(fake)
    result, _ = _sync(store, _connector(store))
    assert result.status == "failed" and result.error_class == "auth" and result.http_status == 403
    assert "Missing permission apigee.deployments.list" in result.error_message


def test_a_missing_oauth_scope_is_named(store):
    fake = FakeGoogle(deny={"/apis": "scope-insufficient"})
    _use(fake)
    result, _ = _sync(store, _connector(store))
    assert result.status == "failed" and result.error_class == "auth"
    assert "https://www.googleapis.com/auth/cloud-platform" in result.error_message
    assert "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in result.error_message


# --- inventory, freshness and credentials ------------------------------------------------


def test_configured_environments_limit_the_inventory(store):
    fake = FakeGoogle()
    _use(fake)
    _sync(store, _connector(store, environments=["test"]))
    assert set(_rows(store)) == {f"{ORG}/orders-v2/test", f"{ORG}/store-v1/test", f"{ORG}/legacy-billing"}
    assert not any(r.url.path.endswith("/environments") for r in fake.requests)


def test_an_unchanged_deployment_is_not_refetched(store):
    fake = FakeGoogle()
    _use(fake)
    connector = _connector(store)
    _sync(store, connector)
    again, importer = _sync(store, connector)
    assert importer.calls == [] and again.summary["unchanged"] == 3
    assert "Revision 3 of orders-v2 deployed to prod is unchanged" in again.summary["unchangedItems"][0]["reason"]


def test_a_redeploy_imports_the_new_revision_into_the_same_item(store):
    fake = FakeGoogle()
    _use(fake)
    connector = _connector(store)
    _sync(store, connector)
    fake.overrides["/environments/prod/deployments"] = {
        "deployments": [
            {"environment": "prod", "apiProxy": "orders-v2", "revision": "5", "deployStartTime": "1760700000000"}
        ]
    }
    again, importer = _sync(store, connector)
    assert [(c["candidate"].environment, c["document"].revision, c["prior"]) for c in importer.calls] == [
        ("prod", "5", "proj-orders-v2")
    ]


def test_a_refused_credential_fails_the_run(store):
    fake = FakeGoogle(token_status=400)
    _use(fake)
    result, _ = _sync(store, _connector(store))
    assert result.status == "failed" and result.error_class == "auth" and "invalid_grant" in result.error_message
    assert "PRIVATE KEY" not in (result.error_message or "")


@pytest.mark.parametrize(
    "credential,fragment",
    [("", "No credential is stored"), ("not json", "not JSON"), ('{"type": "authorized_user"}', "type must be")],
)
def test_an_unusable_credential_is_an_invalid_configuration(store, credential, fragment):
    _use(FakeGoogle())
    result, _ = _sync(store, _connector(store, credential=credential))
    assert result.status == "failed" and result.error_class == "invalid-configuration"
    assert fragment in result.error_message


def test_the_access_token_is_sent_and_the_bundle_is_asked_for(store):
    fake = FakeGoogle()
    _use(fake)
    _sync(store, _connector(store))
    tokens = [r for r in fake.requests if r.url.host == "oauth2.googleapis.com"]
    assert len(tokens) == 1
    bundles = [r for r in fake.requests if "/revisions/" in r.url.path]
    assert bundles and all(r.url.params.get("format") == "bundle" for r in bundles)


# --- scope -------------------------------------------------------------------------------


def test_a_valid_scope_passes():
    validate_connector_scope(apigee.KIND, {"organization": ORG, "environments": ["test", "prod"]}, None)
    validate_connector_scope(apigee.KIND, {"organization": ORG}, None)


@pytest.mark.parametrize(
    "scope,base_url,fragment",
    [
        ({"organization": ORG}, "https://apigee.googleapis.com", "takes no base URL"),
        ({"organization": ORG, "credentialJson": "{}"}, None, "Unknown apigee scope key"),
        ({"organization": "Acme Prod"}, None, "organization must be"),
        ({}, None, "organization must be"),
        ({"organization": ORG, "environments": ["test", "test"]}, None, "environments must"),
        ({"organization": ORG, "environments": "test"}, None, "environments must"),
    ],
)
def test_a_malformed_scope_is_refused(scope, base_url, fragment):
    with pytest.raises(ConnectorError) as info:
        validate_connector_scope(apigee.KIND, scope, base_url)
    assert info.value.code == "connector-invalid" and fragment in str(info.value)


def test_describe_carries_no_credential():
    source = apigee.ApigeeSource(
        {"id": "c1", "kind": apigee.KIND, "scope": {"organization": ORG}}, {"credentialJson": SA_JSON}
    )
    assert apigee.ApigeeSource.describe(source)["organization"] == ORG
    assert "PRIVATE KEY" not in json.dumps(source.describe())
