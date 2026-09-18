"""No API reads an upstream credential back — AGX-2.2 (#4534) acceptance criterion.

*"Credential secret is unreadable post-create via any API (verified by test sweeping all
endpoints)."* This module is that sweep, in three parts:

1. **Every GET endpoint the app serves.** Credentials of all three kinds are stored through the
   real create route (and one is rotated), then every ``GET`` route in the application is
   called, with path parameters filled with the credential's ids so that a route which *could*
   find it gets the chance. No response body or header may contain any form of any secret: the
   plaintext, its URL- and base64-encoded forms, the ``basic`` header value, the username, or
   the stored ciphertext.
2. **The OpenAPI contract.** No response schema of the vault's routes has a field a secret could
   travel in.
3. **The source.** Only the vault module opens a secret, and only the vault module and the
   database layer touch the ciphertext. A future route that reads one back has to change this
   test to do it.

The vault's store is the in-memory :class:`~upstream_credential_fakes.FakeUpstreamStore`, so the
sweep runs the same way with or without a database; every other route runs against whatever
database the suite has (none in CI, the dev database locally), and its response is checked all
the same.
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set
from urllib.parse import quote, quote_plus

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from upstream_credential_fakes import FakeUpstreamStore

from app.auth import validate_authentication
from app.config import settings
from app.database import db
from app.main import app

_TENANT = "11111111-1111-4111-8111-111111111111"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_TOOLSET = "22222222-2222-4222-8222-222222222222"
_BASE = f"/v1/tenants/acme/agent-toolsets/{_TOOLSET}/upstream-credentials"

_API_KEY = "sk_live_SWEEP_apikey_value_0001"
_API_KEY_ROTATED = "sk_live_SWEEP_apikey_value_0002"
_BEARER = "eyJhbGciOiJIUzI1NiJ9.SWEEP-bearer-token.sig"
_USERNAME = "sweep-basic-user@example"
_PASSWORD = "SWEEP p@ss/word+&=%"

_SRC = Path(__file__).resolve().parents[1] / "src" / "app"


def _forms(secret: str) -> Set[str]:
    """Every rendering of a secret a response could plausibly carry."""
    raw = secret.encode("utf-8")
    return {
        secret,
        quote(secret, safe=""),
        quote_plus(secret),
        json.dumps(secret)[1:-1],
        base64.b64encode(raw).decode(),
        base64.urlsafe_b64encode(raw).decode(),
        raw.hex(),
    }


def _blob_forms(blob: bytes) -> Set[str]:
    """Every rendering of stored ciphertext a response could plausibly carry."""
    return {
        base64.b64encode(blob).decode(),
        base64.urlsafe_b64encode(blob).decode(),
        blob.hex(),
        "\\x" + blob.hex(),
    }


def _fill(path: str, ids: Dict[str, str]) -> str:
    """Fill a route template's parameters so a route that could find the credential gets to.

    ``toolset_id`` and ``credential_id`` get the stored credential's ids, and every other
    ``*id*`` parameter gets the credential id too. A tenant slug is ``acme``, and anything else
    is a placeholder.
    """

    def value(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name in ids:
            return ids[name]
        if "tenant" in name:
            return "acme"
        if "id" in name:
            return ids["credential_id"]
        return "x"

    return re.sub(r"\{(\w+)(?::\w+)?\}", value, path)


def _get_routes() -> List[APIRoute]:
    """Every GET route the application serves."""
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and "GET" in (route.methods or set())
    ]


@pytest.fixture
def vault(monkeypatch):
    """Authenticate, configure a master key, and swap the vault's store for the fake."""
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "upstream_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "upstream_credential_active_key_version", None)
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT,
        "user_id": _ACTOR,
        "auth_method": "jwt",
    }
    store = FakeUpstreamStore().install(monkeypatch, db)
    yield store
    app.dependency_overrides.clear()


def _store_credentials(client: TestClient, store: FakeUpstreamStore) -> Dict[str, Any]:
    """Store one credential of each kind and rotate the apiKey one.

    Returns:
        ``{"ids", "writes", "retired_blobs"}``: the credential ids, the four write responses, and
        the ciphertext the rotation replaced (still secret material, though no longer stored).
    """
    responses = [
        client.post(
            _BASE,
            json={
                "serverUrl": "https://api.example.com/v1",
                "kind": "apiKey",
                "in": "query",
                "name": "api_key",
                "secret": {"value": _API_KEY},
            },
        ),
        client.post(
            _BASE,
            json={
                "serverUrl": "https://bearer.example.com",
                "kind": "bearer",
                "secret": {"token": _BEARER},
            },
        ),
        client.post(
            _BASE,
            json={
                "serverUrl": "https://basic.example.com",
                "kind": "basic",
                "secret": {"username": _USERNAME, "password": _PASSWORD},
            },
        ),
    ]
    for response in responses:
        assert response.status_code == 201, response.text
    api_key_id = responses[0].json()["id"]
    retired = store.rows[api_key_id]["encrypted_secret"]
    rotated = client.post(
        f"{_BASE}/{api_key_id}/rotate", json={"secret": {"value": _API_KEY_ROTATED}}
    )
    assert rotated.status_code == 200, rotated.text
    return {
        "ids": [response.json()["id"] for response in responses],
        "writes": [*responses, rotated],
        "retired_blobs": [retired],
    }


def _needles(store: FakeUpstreamStore, extra_blobs: Iterable[bytes]) -> Set[str]:
    """Every string whose presence in a response would mean secret material leaked."""
    needles: Set[str] = set()
    for secret in (_API_KEY, _API_KEY_ROTATED, _BEARER, _USERNAME, _PASSWORD):
        needles |= _forms(secret)
    needles |= _forms(f"{_USERNAME}:{_PASSWORD}")
    for blob in [*(row["encrypted_secret"] for row in store.rows.values()), *extra_blobs]:
        needles |= _blob_forms(blob)
    return needles


def _leaks(text: str, needles: Set[str]) -> List[str]:
    """The needles found in ``text`` (abbreviated, so the failure message is itself safe)."""
    return sorted({needle[:6] + "…" for needle in needles if needle and needle in text})


def test_no_get_endpoint_returns_upstream_secret_material(vault):
    client = TestClient(app, raise_server_exceptions=False)
    stored = _store_credentials(client, vault)
    needles = _needles(vault, stored["retired_blobs"])

    # The writes themselves (create ×3, rotate) answer with metadata only.
    for response in stored["writes"]:
        assert _leaks(response.text, needles) == []

    offenders: Dict[str, List[str]] = {}
    swept = 0
    vault_list_seen = False
    for credential_id in stored["ids"]:
        ids = {"toolset_id": _TOOLSET, "credential_id": credential_id}
        for route in _get_routes():
            path = _fill(route.path, ids)
            response = client.get(path)
            swept += 1
            header_text = "\n".join(f"{k}: {v}" for k, v in response.headers.items())
            found = _leaks(response.text, needles) + _leaks(header_text, needles)
            if found:
                offenders[f"GET {route.path} -> {response.status_code}"] = found
            if route.path.endswith("/upstream-credentials") and response.status_code == 200:
                vault_list_seen = True
                assert len(response.json()["credentials"]) == 3

    assert offenders == {}
    # The sweep is not vacuous: it covered the whole app, including the vault's own read.
    assert swept >= 3 * 300
    assert vault_list_seen


def test_the_rotated_away_secret_is_not_readable_either(vault):
    client = TestClient(app, raise_server_exceptions=False)
    _store_credentials(client, vault)
    listing = client.get(_BASE)
    assert listing.status_code == 200
    assert _leaks(listing.text, _forms(_API_KEY) | _forms(_API_KEY_ROTATED)) == []


# ============================================================================
# The OpenAPI contract
# ============================================================================
_SECRET_FIELD_NAMES = {
    "secret",
    "value",
    "token",
    "username",
    "password",
    "encryptedSecret",
    "encrypted_secret",
    "ciphertext",
    "plaintext",
}


def _schema_properties(schema: Any, components: Dict[str, Any], seen: Set[str]) -> Set[str]:
    """Every property name reachable from a JSON schema (following ``$ref``)."""
    names: Set[str] = set()
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            name = ref.rsplit("/", 1)[-1]
            if name not in seen:
                seen.add(name)
                names |= _schema_properties(components.get(name, {}), components, seen)
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                names |= set(value)
            names |= _schema_properties(value, components, seen)
    elif isinstance(schema, list):
        for item in schema:
            names |= _schema_properties(item, components, seen)
    return names


def test_no_vault_response_schema_has_a_field_a_secret_could_travel_in():
    document = app.openapi()
    components = document.get("components", {}).get("schemas", {})
    vault_paths = {
        path: item for path, item in document["paths"].items() if "upstream-credentials" in path
    }
    assert len(vault_paths) == 3  # collection, /{id}, /{id}/rotate

    for path, item in vault_paths.items():
        for method, operation in item.items():
            for status, response in operation.get("responses", {}).items():
                if status.startswith("2"):
                    names = _schema_properties(response, components, set())
                    assert names & _SECRET_FIELD_NAMES == set(), f"{method.upper()} {path} {status}"


# ============================================================================
# The source
# ============================================================================
def _python_sources() -> Dict[str, str]:
    return {
        path.relative_to(_SRC).as_posix(): path.read_text(encoding="utf-8")
        for path in _SRC.rglob("*.py")
    }


def test_only_the_vault_opens_an_upstream_secret():
    callers = sorted(
        name
        for name, text in _python_sources().items()
        if "resolve_injection(" in text or "get_upstream_credential_bindings(" in text
    )
    assert callers == ["database.py", "upstream_credentials.py"]


def test_only_the_vault_and_the_database_layer_touch_the_ciphertext():
    # SQL that reads or writes the table; a comment that merely names it does not count.
    table = re.compile(r"\b(?:FROM|INTO|UPDATE|JOIN)\s+apiome\.upstream_credentials\b")
    touching = sorted(
        name
        for name, text in _python_sources().items()
        if "encrypted_secret" in text or table.search(text)
    )
    assert touching == ["database.py", "upstream_credentials.py"]
