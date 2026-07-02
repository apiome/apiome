"""API + model tests for MCP outbound credential REST + redaction (V2-MCP-20.5 / MCAT-6.5, #3681).

Covers the tenant-scoped credential routes under
``/v1/mcp/{tenant_slug}/endpoints/{id}/credentials`` — set (PUT), redacted status (GET), and clear
(DELETE) — plus the redaction projection (:func:`mcp_credential_status_from_row`) and the write-time
payload validation (:func:`app.mcp_auth.validate_credential_payload`).

The encryption layer (MCAT-6.2) runs for real here (a per-test master key is configured), so the
tests prove the *whole* path: a plaintext secret is sealed to ciphertext on the way in and is never
returned on the way out — the central acceptance criterion ("secrets never returned").
"""

import base64
import datetime
import json
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.config import settings
from app.main import app
from app.mcp_auth import CredentialPayloadError, validate_credential_payload
from app.mcp_credential_crypto import unseal_credential_payload
from app.models import (
    MCP_CREDENTIAL_SECRET_MASK,
    McpCredentialUpsert,
    mcp_credential_status_from_row,
)

client = TestClient(app)

# Auth payload as produced by ``validate_authentication`` (scoping comes from the token tenant).
_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}

_EID = "11111111-1111-1111-1111-111111111111"
_BASE = f"/v1/mcp/acme/endpoints/{_EID}/credentials"
_ENDPOINT_ROW = {"id": _EID, "tenant_id": "t1", "name": "Acme", "slug": "acme"}
_NOW = datetime.datetime(2026, 6, 27, 12, 0, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture(autouse=True)
def _default_auth():
    """Default every test to an authenticated JWT caller in tenant ``t1``."""
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch):
    """Configure a single real master key so the seal/unseal path runs end-to-end."""
    key = base64.b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)
    return key


def _stored_row(auth_type, encrypted_payload, key_version, oauth_metadata=None):
    """Build a credential row shaped like the DB would return after an upsert."""
    return {
        "id": "cred-1",
        "endpoint_id": _EID,
        "auth_type": auth_type,
        "encrypted_payload": encrypted_payload,
        "key_version": key_version,
        "oauth_metadata": oauth_metadata or {},
        "last_refreshed_at": _NOW,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


# ===========================================================================
# PUT — set / replace a credential
# ===========================================================================


def test_put_bearer_seals_and_redacts():
    """A bearer secret is sealed (ciphertext only) and never echoed back."""
    secret = "super-secret-token-value"
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW

        def _upsert(*, endpoint_id, auth_type, encrypted_payload, key_version, oauth_metadata):
            # The blob handed to the DB must be ciphertext — not the plaintext token.
            assert isinstance(encrypted_payload, (bytes, bytearray))
            assert secret.encode() not in bytes(encrypted_payload)
            # …and it must round-trip back to the original payload under the active key.
            assert unseal_credential_payload(bytes(encrypted_payload), key_version) == {
                "token": secret
            }
            return _stored_row(auth_type, encrypted_payload, key_version)

        mdb.upsert_mcp_endpoint_credentials.side_effect = _upsert
        r = client.put(_BASE, json={"auth_type": "bearer", "payload": {"token": secret}})

    assert r.status_code == 200
    body = r.json()
    cred = body["credential"]
    assert cred["auth_type"] == "bearer"
    assert cred["configured"] is True
    assert cred["masked_secret"] == MCP_CREDENTIAL_SECRET_MASK
    assert cred["key_version"] == 1
    # The acceptance criterion: the secret never appears anywhere in the response.
    assert secret not in r.text


def test_put_header_credential_ok():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.upsert_mcp_endpoint_credentials.side_effect = (
            lambda *, endpoint_id, auth_type, encrypted_payload, key_version, oauth_metadata: _stored_row(
                auth_type, encrypted_payload, key_version
            )
        )
        r = client.put(
            _BASE,
            json={"auth_type": "header", "payload": {"name": "X-Api-Key", "value": "abc123"}},
        )
    assert r.status_code == 200
    assert r.json()["credential"]["auth_type"] == "header"
    assert "abc123" not in r.text


def test_put_oauth2_stores_metadata_cleartext():
    """oauth_metadata is non-secret and is round-tripped in the redacted status."""
    meta = {"token_endpoint": "https://as.example/token", "scopes": ["read"]}
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW

        def _upsert(*, endpoint_id, auth_type, encrypted_payload, key_version, oauth_metadata):
            assert oauth_metadata == meta
            return _stored_row(auth_type, encrypted_payload, key_version, oauth_metadata)

        mdb.upsert_mcp_endpoint_credentials.side_effect = _upsert
        r = client.put(
            _BASE,
            json={
                "auth_type": "oauth2",
                "payload": {"access_token": "tok-123"},
                "oauth_metadata": meta,
            },
        )
    assert r.status_code == 200
    assert r.json()["credential"]["oauth_metadata"] == meta
    assert "tok-123" not in r.text


def test_put_accepts_camelcase_keys():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.upsert_mcp_endpoint_credentials.side_effect = (
            lambda *, endpoint_id, auth_type, encrypted_payload, key_version, oauth_metadata: _stored_row(
                auth_type, encrypted_payload, key_version, oauth_metadata
            )
        )
        r = client.put(
            _BASE,
            json={"authType": "bearer", "payload": {"token": "t"}, "oauthMetadata": {"a": 1}},
        )
    assert r.status_code == 200
    assert r.json()["credential"]["oauth_metadata"] == {"a": 1}


def test_put_rejects_none_auth_type():
    """'none' is not settable — it is reached by clearing the credential (DELETE)."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.put(_BASE, json={"auth_type": "none", "payload": {}})
    assert r.status_code == 422
    mdb.upsert_mcp_endpoint_credentials.assert_not_called()


def test_put_rejects_unsupported_auth_type():
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.put(_BASE, json={"auth_type": "kerberos", "payload": {}})
    assert r.status_code == 422
    mdb.upsert_mcp_endpoint_credentials.assert_not_called()


def test_put_rejects_malformed_payload():
    """A bearer payload missing 'token' fails write-time validation (422), nothing is stored."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.put(_BASE, json={"auth_type": "bearer", "payload": {"nope": "x"}})
    assert r.status_code == 422
    mdb.upsert_mcp_endpoint_credentials.assert_not_called()


def test_put_rejects_header_injection_payload():
    """A header value carrying CRLF is rejected before it can be sealed/stored."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.put(
            _BASE,
            json={
                "auth_type": "header",
                "payload": {"name": "X-Evil", "value": "a\r\nX-Injected: 1"},
            },
        )
    assert r.status_code == 422
    mdb.upsert_mcp_endpoint_credentials.assert_not_called()


def test_put_cross_tenant_endpoint_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.put(_BASE, json={"auth_type": "bearer", "payload": {"token": "t"}})
    assert r.status_code == 404
    mdb.upsert_mcp_endpoint_credentials.assert_not_called()


def test_put_503_when_encryption_unconfigured(monkeypatch):
    """With no master key configured, a secret cannot be sealed → 503, nothing stored."""
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", None)
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.put(_BASE, json={"auth_type": "bearer", "payload": {"token": "t"}})
    assert r.status_code == 503
    mdb.upsert_mcp_endpoint_credentials.assert_not_called()


def test_put_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.put(_BASE, json={"auth_type": "bearer", "payload": {"token": "t"}})
    assert r.status_code == 401


# ===========================================================================
# GET — redacted status
# ===========================================================================


def test_get_status_when_configured():
    """Setting then GET shows masked status (acceptance criterion)."""
    blob = b"OMCV\x01sealed-bytes-not-plaintext"
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_credentials.return_value = _stored_row("bearer", blob, 1)
        r = client.get(_BASE)
    assert r.status_code == 200
    cred = r.json()["credential"]
    assert cred["auth_type"] == "bearer"
    assert cred["configured"] is True
    assert cred["masked_secret"] == MCP_CREDENTIAL_SECRET_MASK
    assert cred["key_version"] == 1
    # The ciphertext is not leaked either.
    assert "sealed-bytes" not in r.text


def test_get_status_when_unset_is_anonymous():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_credentials.return_value = None
        r = client.get(_BASE)
    assert r.status_code == 200
    cred = r.json()["credential"]
    assert cred["auth_type"] == "none"
    assert cred["configured"] is False
    assert cred["masked_secret"] is None


def test_get_status_cross_tenant_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.get(_BASE)
    assert r.status_code == 404
    mdb.get_mcp_endpoint_credentials.assert_not_called()


# ===========================================================================
# DELETE — clear
# ===========================================================================


def test_delete_removes_row():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.delete_mcp_endpoint_credentials.return_value = True
        r = client.delete(_BASE)
    assert r.status_code == 200
    body = r.json()
    assert body["removed"] is True
    assert body["endpoint_id"] == _EID
    mdb.delete_mcp_endpoint_credentials.assert_called_once_with(_EID)


def test_delete_is_idempotent_when_absent():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.delete_mcp_endpoint_credentials.return_value = False
        r = client.delete(_BASE)
    assert r.status_code == 200
    assert r.json()["removed"] is False


def test_delete_cross_tenant_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.delete(_BASE)
    assert r.status_code == 404
    mdb.delete_mcp_endpoint_credentials.assert_not_called()


def test_routes_reject_non_uuid_endpoint():
    """The endpoint id is typed uuid.UUID → a non-UUID is a 422 before any DB hit."""
    bad = "/v1/mcp/acme/endpoints/not-a-uuid/credentials"
    with patch("app.mcp_catalog_routes.db") as mdb:
        assert client.get(bad).status_code == 422
        assert client.delete(bad).status_code == 422
        assert client.put(bad, json={"auth_type": "bearer", "payload": {"token": "t"}}).status_code == 422
        mdb.get_mcp_endpoint.assert_not_called()


# ===========================================================================
# Redaction projection — mcp_credential_status_from_row
# ===========================================================================


def test_status_projection_strips_secret_and_ciphertext():
    row = _stored_row("bearer", b"ciphertext-bytes", 3, {"scopes": ["a"]})
    out = mcp_credential_status_from_row(_EID, row)
    dumped = out.model_dump()
    assert "encrypted_payload" not in dumped
    assert out.configured is True
    assert out.masked_secret == MCP_CREDENTIAL_SECRET_MASK
    assert out.key_version == 3
    assert out.oauth_metadata == {"scopes": ["a"]}
    # No field in the serialized model carries the ciphertext.
    assert b"ciphertext-bytes".decode() not in json.dumps(dumped, default=str)


def test_status_projection_none_row():
    out = mcp_credential_status_from_row(_EID, None)
    assert out.auth_type == "none"
    assert out.configured is False
    assert out.masked_secret is None
    assert out.key_version is None


# ===========================================================================
# Write-time payload validation — validate_credential_payload
# ===========================================================================


@pytest.mark.parametrize(
    "auth_type, payload",
    [
        ("bearer", {"token": "t"}),
        ("header", {"name": "X-Api-Key", "value": "v"}),
        ("oauth2", {"access_token": "tok"}),
        ("env", {"vars": {"API_KEY": "v"}}),
        ("none", {}),
    ],
)
def test_validate_payload_accepts_valid(auth_type, payload):
    validate_credential_payload(auth_type, payload)  # must not raise


@pytest.mark.parametrize(
    "auth_type, payload",
    [
        ("bearer", {}),
        ("bearer", {"token": ""}),
        ("header", {"name": "Bad Name", "value": "v"}),
        ("header", {"name": "X", "value": "a\nb"}),
        ("oauth2", {}),
        ("env", {}),
        ("env", {"vars": {}}),
        ("kerberos", {"token": "t"}),
    ],
)
def test_validate_payload_rejects_invalid(auth_type, payload):
    with pytest.raises(CredentialPayloadError):
        validate_credential_payload(auth_type, payload)


def test_upsert_model_rejects_none():
    with pytest.raises(ValueError):
        McpCredentialUpsert(auth_type="none", payload={})
