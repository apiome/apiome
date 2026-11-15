"""Mock broker binding endpoints and vault — XPC-2.1 (#5735).

Authentication is overridden, the store is the in-memory
:class:`~mock_broker_binding_fakes.FakeBrokerStore`, DNS is faked and encryption uses a throwaway
key, so these tests assert the HTTP contract: which ``versions`` permission each route enforces,
how every refusal maps to a status (``422 broker-address-disallowed`` above all), that each
mutation writes a metadata-only audit row, that the credential is sealed and never returned, and
that ``/test`` reports through the probe without leaking anything.
"""

from __future__ import annotations

import base64
import json
import os
import socket
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from mock_broker_binding_fakes import FakeBrokerStore

from app import mock_broker_addresses as addresses
from app import mock_broker_probe
from app.auth import validate_authentication
from app.config import settings
from app.database import db
from app.main import app
from app.mock_broker_binding_routes import AUDIT_CREATE, AUDIT_DELETE, AUDIT_ROTATE, AUDIT_TEST
from app.mock_broker_bindings import open_credential
from app.mock_broker_probe import BrokerProbeResult, clear_probe_cache
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_PROJECT = "44444444-4444-4444-8444-444444444444"
_VERSION = "55555555-5555-4555-8555-555555555555"
_OTHER_VERSION = "66666666-6666-4666-8666-666666666666"
_MISSING = "77777777-7777-4777-8777-777777777777"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt", "user_email": "a@x.io"}

_USERNAME = "svc-apiome-mock"
_PASSWORD = "BROKER-p@ss-word-0001"
_ROTATED = "BROKER-p@ss-word-0002"

_BASE = f"/v1/versions/acme/{_PROJECT}/{_VERSION}/mock/broker-bindings"

_DNS = {
    "broker.example.com": ["8.8.8.8"],
    "b2.example.com": ["8.8.4.4"],
    "internal.example.com": ["10.0.0.5"],
    "redpanda": ["172.18.0.4"],
}


@pytest.fixture(autouse=True)
def _environment(monkeypatch):
    """Authenticate, grant every permission, fake DNS and configure one broker master key."""
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    monkeypatch.setattr("app.mock_broker_binding_routes.enforce_permission", lambda *a, **k: _ACTOR)

    def fake_getaddrinfo(host, port, *args, **kwargs):
        import ipaddress

        try:
            ipaddress.ip_address(host)
            ips = [host]
        except ValueError:
            if host not in _DNS:
                raise socket.gaierror("Name or service not known")
            ips = _DNS[host]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]

    monkeypatch.setattr(addresses.socket, "getaddrinfo", fake_getaddrinfo)
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "broker_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "broker_credential_active_key_version", None)
    monkeypatch.setattr(settings, "mock_broker_allow_private", False)
    monkeypatch.setattr(settings, "mock_dev_broker_bootstrap", None)
    clear_probe_cache()
    yield
    app.dependency_overrides.clear()
    clear_probe_cache()


@pytest.fixture
def store(monkeypatch) -> FakeBrokerStore:
    """The binding table, in memory, with one version in the project."""
    return FakeBrokerStore(tenant_id=_TENANT, versions={_VERSION: _PROJECT}).install(monkeypatch, db)


@pytest.fixture
def audits(monkeypatch) -> List[Dict[str, Any]]:
    """Capture access-audit rows instead of writing them."""
    rows: List[Dict[str, Any]] = []
    monkeypatch.setattr(db, "write_access_audit", lambda **fields: rows.append(fields))
    return rows


def _body(**overrides: Any) -> Dict[str, Any]:
    """A SASL/SCRAM-over-TLS create body."""
    data: Dict[str, Any] = {
        "protocol": "kafka",
        "bootstrap": ["Broker.Example.com:9093", "b2.example.com"],
        "tls": {"enabled": True, "verify": True},
        "saslMechanism": "SCRAM-SHA-512",
        "credential": {"username": _USERNAME, "password": _PASSWORD},
        "clientIdPrefix": "acme-mock",
    }
    data.update(overrides)
    return data


def _create(**overrides: Any) -> Dict[str, Any]:
    """Create a binding through the API and return the response body."""
    response = client.post(_BASE, json=_body(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


# ============================================================================
# Permissions
# ============================================================================
@pytest.mark.parametrize(
    ("method", "suffix", "body", "action"),
    [
        ("get", "", None, Action.VIEW),
        ("post", "", "create", Action.EDIT),
        ("post", "/{id}/rotate", {"credential": {"username": "u", "password": _ROTATED}}, Action.EDIT),
        ("post", "/{id}/test", None, Action.EDIT),
        ("delete", "/{id}", None, Action.EDIT),
    ],
)
def test_each_route_enforces_its_versions_permission(store, audits, monkeypatch, method, suffix, body, action):
    # Seed a binding on a second version, so the create case still has a free version to bind.
    store.versions[_OTHER_VERSION] = _PROJECT
    other_base = f"/v1/versions/acme/{_PROJECT}/{_OTHER_VERSION}/mock/broker-bindings"
    seeded = client.post(other_base, json=_body()).json()
    path = _BASE if body == "create" else other_base + suffix.replace("{id}", seeded["id"])
    monkeypatch.setattr(
        "app.mock_broker_binding_routes.probe_binding",
        lambda row: _async_result(row, "reachable"),
    )
    with patch("app.mock_broker_binding_routes.enforce_permission", return_value=_ACTOR) as guard:
        response = client.request(method.upper(), path, json=_body() if body == "create" else body)
    assert response.status_code < 400, response.text
    guard.assert_called_once()
    assert guard.call_args.args[2:] == (Resource.VERSIONS, action)


async def _async_result(row: Dict[str, Any], status: str, reason: Any = None) -> BrokerProbeResult:
    """A canned probe result."""
    from datetime import datetime, timezone

    return BrokerProbeResult(
        binding_id=str(row["id"]),
        status=status,
        reason=reason,
        summary=status if not reason else f"{status}: {reason}",
        checked_at=datetime.now(timezone.utc),
    )


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("get", "", None),
        ("post", "", "create"),
        ("post", f"/{_MISSING}/rotate", {"credential": {"username": "u", "password": "p"}}),
        ("post", f"/{_MISSING}/test", None),
        ("delete", f"/{_MISSING}", None),
    ],
)
def test_a_denied_caller_changes_nothing(store, audits, method, suffix, body):
    denied = HTTPException(status_code=403, detail="Permission denied")
    with patch("app.mock_broker_binding_routes.enforce_permission", side_effect=denied):
        response = client.request(
            method.upper(), _BASE + suffix, json=_body() if body == "create" else body
        )
    assert response.status_code == 403
    assert store.rows == {}
    assert audits == []


def test_a_caller_who_does_not_own_the_mock_cannot_bind(store, audits):
    store.not_owner.add(_VERSION)
    response = client.post(_BASE, json=_body())
    assert response.status_code == 403
    assert store.rows == {}


def test_an_unknown_version_or_wrong_project_is_a_404(store):
    assert client.get(f"/v1/versions/acme/{_PROJECT}/{_MISSING}/mock/broker-bindings").status_code == 404
    other_project = "88888888-8888-4888-8888-888888888888"
    path = f"/v1/versions/acme/{other_project}/{_VERSION}/mock/broker-bindings"
    assert client.post(path, json=_body()).status_code == 404


# ============================================================================
# Create
# ============================================================================
def test_create_returns_201_with_metadata_only(store, audits):
    response = client.post(_BASE, json=_body())
    assert response.status_code == 201, response.text
    body = response.json()
    assert _PASSWORD not in response.text and _USERNAME not in response.text
    assert body["schemaVersion"] == "xpc.mock-broker-binding.v1"
    assert body["versionId"] == _VERSION
    assert body["protocol"] == "kafka"
    assert body["bootstrap"] == ["broker.example.com:9093", "b2.example.com:9092"]
    assert body["tls"] == {"enabled": True, "verify": True}
    assert body["saslMechanism"] == "SCRAM-SHA-512"
    assert body["hasCredential"] is True and body["keyVersion"] == 1 and body["readable"] is True
    assert body["clientIdPrefix"] == "acme-mock"
    assert body["devBroker"] is False
    assert body["createdBy"] == _ACTOR and body["rotatedAt"] is None
    assert "credential" not in body and "credentialCiphertext" not in body


def test_the_credential_is_stored_sealed_and_opens_in_memory(store):
    created = _create()
    row = store.rows[created["id"]]
    blob = row["credential_ciphertext"]
    assert isinstance(blob, bytes) and blob[:4] == b"OMBB"
    assert _PASSWORD.encode() not in blob and _USERNAME.encode() not in blob
    credential = open_credential(row)
    assert (credential.username, credential.password) == (_USERNAME, _PASSWORD)
    assert _PASSWORD not in repr(credential)


def test_a_binding_without_sasl_stores_no_ciphertext(store):
    created = _create(saslMechanism=None, credential=None, tls={"enabled": False, "verify": True})
    row = store.rows[created["id"]]
    assert row["credential_ciphertext"] is None and row["key_version"] is None
    assert created["hasCredential"] is False and created["readable"] is True


def test_create_is_audited_with_metadata_only(store, audits):
    created = _create()
    (row,) = audits
    assert row["action"] == AUDIT_CREATE
    assert (row["tenant_id"], row["actor_id"], row["target"], row["source"]) == (
        _TENANT,
        _ACTOR,
        created["id"],
        "api",
    )
    assert row["detail"] == {
        "versionId": _VERSION,
        "protocol": "kafka",
        "bootstrap": ["broker.example.com:9093", "b2.example.com:9092"],
        "tls": True,
        "tlsVerify": True,
        "saslMechanism": "SCRAM-SHA-512",
        "keyVersion": 1,
    }
    dumped = json.dumps(row, default=str)
    assert _PASSWORD not in dumped and _USERNAME not in dumped


def test_a_failing_audit_does_not_fail_the_create(store, monkeypatch):
    def boom(**_fields):
        raise RuntimeError("audit down")

    monkeypatch.setattr(db, "write_access_audit", boom)
    assert client.post(_BASE, json=_body()).status_code == 201


def test_a_second_kafka_binding_for_the_version_is_a_409(store, audits):
    _create()
    response = client.post(_BASE, json=_body(credential={"username": "x", "password": _ROTATED}))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "broker-binding-exists"
    assert _ROTATED not in response.text
    assert len(audits) == 1


def test_a_private_address_is_refused_422_broker_address_disallowed(store, audits):
    response = client.post(_BASE, json=_body(bootstrap=["internal.example.com:9092"]))
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "broker-address-disallowed"
    assert any("internal.example.com" in error for error in detail["errors"])
    assert "10.0.0.5" not in response.text  # no internal-DNS oracle
    assert _PASSWORD not in response.text
    assert store.rows == {} and audits == []


@pytest.mark.parametrize("bootstrap", [["127.0.0.1:9092"], ["169.254.169.254:80"], ["nowhere.example.com"]])
def test_loopback_metadata_and_unresolvable_hosts_are_disallowed(store, bootstrap):
    response = client.post(_BASE, json=_body(bootstrap=bootstrap))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "broker-address-disallowed"


def test_the_dev_broker_is_bindable_only_when_the_profile_variable_is_set(store, monkeypatch):
    plain = {"bootstrap": ["redpanda:9092"], "tls": {"enabled": False}, "saslMechanism": None, "credential": None}
    refused = client.post(_BASE, json=_body(**plain))
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "broker-address-disallowed"

    monkeypatch.setattr(settings, "mock_dev_broker_bootstrap", "redpanda:9092")
    created = client.post(_BASE, json=_body(**plain))
    assert created.status_code == 201, created.text
    assert created.json()["devBroker"] is True


def test_allow_private_is_the_local_escape_hatch(store, monkeypatch):
    monkeypatch.setattr(settings, "mock_broker_allow_private", True)
    response = client.post(_BASE, json=_body(bootstrap=["internal.example.com:9092"]))
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("protocol", ["mqtt", "amqp"])
def test_reserved_protocols_are_refused(store, protocol):
    response = client.post(_BASE, json=_body(protocol=protocol))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "broker-protocol-unsupported"


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"bootstrap": ["kafka://broker.example.com"]}, "scheme"),
        ({"bootstrap": ["u:p@broker.example.com"]}, "credentials"),
        ({"bootstrap": []}, "at least one"),
        ({"credential": None}, "credential is required"),
        ({"saslMechanism": None}, "applies only with a saslMechanism"),
        ({"credential": {"username": " ", "password": _PASSWORD}}, "username must not be empty"),
        ({"credential": {"username": _USERNAME, "password": ""}}, "password must not be empty"),
        ({"credential": {"username": "a\nb", "password": _PASSWORD}}, "control characters"),
        ({"tls": {"enabled": False, "verify": False}}, "tls.verify applies only"),
        ({"clientIdPrefix": "has space"}, "clientIdPrefix"),
    ],
)
def test_invalid_bodies_are_refused_with_every_problem_named(store, overrides, fragment):
    response = client.post(_BASE, json=_body(**overrides))
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "broker-binding-invalid"
    assert any(fragment in error for error in detail["errors"]), detail
    assert _PASSWORD not in response.text
    assert store.rows == {}


def test_a_malformed_body_422_does_not_echo_the_credential(store):
    body = _body()
    body["credential"]["extra"] = _PASSWORD  # extra="forbid": pydantic would echo the object
    response = client.post(_BASE, json=body)
    assert response.status_code == 422
    assert _PASSWORD not in response.text and _USERNAME not in response.text


def test_a_credential_without_an_encryption_key_is_a_503_and_nothing_is_stored(store, monkeypatch):
    monkeypatch.setattr(settings, "broker_credential_encryption_keys", None)
    response = client.post(_BASE, json=_body())
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "broker-credential-encryption-unconfigured"
    assert "APIOME_BROKER_CREDENTIAL_ENCRYPTION_KEYS" in detail["message"]
    assert store.rows == {}
    # …but an unauthenticated binding needs no key.
    plain = _body(saslMechanism=None, credential=None)
    assert client.post(_BASE, json=plain).status_code == 201


# ============================================================================
# List
# ============================================================================
def test_list_describes_bindings_and_the_deployment(store, monkeypatch):
    monkeypatch.setattr(settings, "mock_dev_broker_bootstrap", "redpanda:9092")
    _create()
    response = client.get(_BASE)
    assert response.status_code == 200
    body = response.json()
    assert body["versionId"] == _VERSION
    assert body["encryptionConfigured"] is True
    assert body["protocols"] == ["kafka"]
    assert body["reservedProtocols"] == ["mqtt", "amqp"]
    assert body["saslMechanisms"] == ["PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"]
    assert body["devBrokerBootstrap"] == ["redpanda:9092"]
    (binding,) = body["bindings"]
    assert binding["readable"] is True
    assert _PASSWORD not in response.text


def test_list_reports_an_unreadable_credential_after_the_key_is_lost(store, monkeypatch):
    _create()
    other = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "broker_credential_encryption_keys", json.dumps({"1": other}))
    (binding,) = client.get(_BASE).json()["bindings"]
    assert binding["readable"] is False


def test_list_without_bindings_or_dev_broker(store):
    body = client.get(_BASE).json()
    assert body["bindings"] == [] and body["devBrokerBootstrap"] is None


# ============================================================================
# Rotate
# ============================================================================
def test_rotate_replaces_the_credential_in_place(store, audits):
    created = _create()
    before = store.rows[created["id"]]["credential_ciphertext"]
    response = client.post(
        f"{_BASE}/{created['id']}/rotate",
        json={"credential": {"username": _USERNAME, "password": _ROTATED}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == created["id"] and body["rotatedAt"] and body["rotatedBy"] == _ACTOR
    row = store.rows[created["id"]]
    assert row["credential_ciphertext"] != before
    assert open_credential(row).password == _ROTATED
    assert "delete_mock_broker_binding" not in store.calls
    assert [audit["action"] for audit in audits] == [AUDIT_CREATE, AUDIT_ROTATE]
    assert _ROTATED not in response.text


def test_rotating_a_binding_without_sasl_is_refused(store):
    created = _create(saslMechanism=None, credential=None)
    response = client.post(
        f"{_BASE}/{created['id']}/rotate", json={"credential": {"username": "u", "password": "p"}}
    )
    assert response.status_code == 422
    assert "no SASL mechanism" in response.json()["detail"]["errors"][0]


def test_rotating_an_unknown_binding_is_a_404(store):
    response = client.post(
        f"{_BASE}/{_MISSING}/rotate", json={"credential": {"username": "u", "password": "p"}}
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "broker-binding-not-found"


def test_a_binding_of_another_version_is_not_addressable(store):
    store.versions[_OTHER_VERSION] = _PROJECT
    other = client.post(
        f"/v1/versions/acme/{_PROJECT}/{_OTHER_VERSION}/mock/broker-bindings", json=_body()
    ).json()
    assert client.delete(f"{_BASE}/{other['id']}").status_code == 404
    assert other["id"] in store.rows


# ============================================================================
# Test
# ============================================================================
def test_test_reports_the_probe_result_and_audits_it(store, audits, monkeypatch):
    created = _create()
    seen: List[Dict[str, Any]] = []

    async def fake_probe(row):
        seen.append(row)
        return await _async_result(row, "unreachable", "auth")

    monkeypatch.setattr("app.mock_broker_binding_routes.probe_binding", fake_probe)
    response = client.post(f"{_BASE}/{created['id']}/test")
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["status"], body["reason"], body["summary"]) == ("unreachable", "auth", "unreachable: auth")
    # The probe got the sealed row to open; the response and the audit got neither.
    assert seen[0]["credential_ciphertext"] == store.rows[created["id"]]["credential_ciphertext"]
    assert _PASSWORD not in response.text
    test_audit = audits[-1]
    assert test_audit["action"] == AUDIT_TEST
    assert test_audit["detail"]["status"] == "unreachable" and test_audit["detail"]["reason"] == "auth"
    assert _PASSWORD not in json.dumps(test_audit, default=str)


def test_test_through_the_real_probe_with_a_fake_connector(store, monkeypatch):
    """End to end through ``probe_binding``: a broker refusing SCRAM is ``unreachable: auth``."""
    from aiokafka.errors import SaslAuthenticationFailed

    created = _create()

    async def refuse(attempt):
        raise SaslAuthenticationFailed(f"Authentication failed for user {_USERNAME}")

    monkeypatch.setattr(mock_broker_probe, "kafka_connect", refuse)
    response = client.post(f"{_BASE}/{created['id']}/test")
    assert response.status_code == 200
    assert response.json()["summary"] == "unreachable: auth"
    assert _USERNAME not in response.text and _PASSWORD not in response.text


def test_testing_an_unknown_binding_is_a_404(store):
    assert client.post(f"{_BASE}/{_MISSING}/test").status_code == 404


# ============================================================================
# Delete
# ============================================================================
def test_delete_removes_the_binding_and_audits_it(store, audits):
    created = _create()
    response = client.delete(f"{_BASE}/{created['id']}")
    assert response.status_code == 204
    assert store.rows == {}
    assert audits[-1]["action"] == AUDIT_DELETE
    assert audits[-1]["target"] == created["id"]
    assert client.delete(f"{_BASE}/{created['id']}").status_code == 404
