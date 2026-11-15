"""No API reads a broker credential back — XPC-2.1 (#5735) acceptance criterion.

*"The secret sweep test (``tests/test_upstream_credential_secret_sweep.py`` pattern) finds no
rendering of the SASL secret or its ciphertext on any ``GET``."* This module is that sweep, in the
same three parts:

1. **Every GET endpoint the app serves.** A SASL binding is stored through the real create route
   and rotated, then every ``GET`` route in the application is called with its path parameters
   filled with the binding's ids. No response body or header may contain any rendering of the
   username, either password, or the stored (or retired) ciphertext.
2. **The OpenAPI contract.** No 2xx response schema of the binding routes has a field a credential
   could travel in.
3. **The source.** Only the binding vault opens a credential, and only the vault and the database
   layer touch the ciphertext column.

The binding store is the in-memory :class:`~mock_broker_binding_fakes.FakeBrokerStore`, so the
sweep runs the same way with or without a database.
"""

from __future__ import annotations

import base64
import json
import os
import re
import socket
from pathlib import Path
from typing import Any, Dict, List, Set

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from mock_broker_binding_fakes import FakeBrokerStore
from test_upstream_credential_secret_sweep import _blob_forms, _forms, _leaks, _schema_properties

from app import mock_broker_addresses as addresses
from app.auth import validate_authentication
from app.config import settings
from app.database import db
from app.main import app

_TENANT = "11111111-1111-4111-8111-111111111111"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_PROJECT = "44444444-4444-4444-8444-444444444444"
_VERSION = "55555555-5555-4555-8555-555555555555"
_BASE = f"/v1/versions/acme/{_PROJECT}/{_VERSION}/mock/broker-bindings"

_USERNAME = "sweep-broker-user"
_PASSWORD = "SWEEP broker p@ss/word+&=%"
_ROTATED = "SWEEP broker rotated 0002"

_SRC = Path(__file__).resolve().parents[1] / "src" / "app"


@pytest.fixture
def vault(monkeypatch):
    """Authenticate, configure a master key, fake DNS, and swap the binding store for the fake."""
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "broker_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "broker_credential_active_key_version", None)
    monkeypatch.setattr(settings, "mock_broker_allow_private", False)
    monkeypatch.setattr(
        addresses.socket,
        "getaddrinfo",
        lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))],
    )
    monkeypatch.setattr("app.mock_broker_binding_routes.enforce_permission", lambda *a, **k: _ACTOR)
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT,
        "user_id": _ACTOR,
        "auth_method": "jwt",
    }
    store = FakeBrokerStore(tenant_id=_TENANT, versions={_VERSION: _PROJECT}).install(monkeypatch, db)
    yield store
    app.dependency_overrides.clear()


def _store_binding(client: TestClient, store: FakeBrokerStore) -> Dict[str, Any]:
    """Store a SCRAM binding and rotate its credential.

    Returns:
        ``{"id", "writes", "retired_blobs"}``.
    """
    created = client.post(
        _BASE,
        json={
            "bootstrap": ["broker.example.com:9093"],
            "tls": {"enabled": True},
            "saslMechanism": "SCRAM-SHA-512",
            "credential": {"username": _USERNAME, "password": _PASSWORD},
        },
    )
    assert created.status_code == 201, created.text
    binding_id = created.json()["id"]
    retired = store.rows[binding_id]["credential_ciphertext"]
    rotated = client.post(
        f"{_BASE}/{binding_id}/rotate",
        json={"credential": {"username": _USERNAME, "password": _ROTATED}},
    )
    assert rotated.status_code == 200, rotated.text
    return {"id": binding_id, "writes": [created, rotated], "retired_blobs": [retired]}


def _needles(store: FakeBrokerStore, retired: List[bytes]) -> Set[str]:
    """Every string whose presence in a response would mean credential material leaked."""
    needles: Set[str] = set()
    for secret in (_USERNAME, _PASSWORD, _ROTATED):
        needles |= _forms(secret)
    for blob in [*(row["credential_ciphertext"] for row in store.rows.values()), *retired]:
        needles |= _blob_forms(blob)
    return needles


def _fill(path: str, binding_id: str) -> str:
    """Fill a route template so a route that could find the binding gets the chance."""
    ids = {"project_id": _PROJECT, "version_record_id": _VERSION, "binding_id": binding_id}

    def value(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name in ids:
            return ids[name]
        if "tenant" in name:
            return "acme"
        if "version" in name:
            return _VERSION
        if "project" in name:
            return _PROJECT
        if "id" in name:
            return binding_id
        return "x"

    return re.sub(r"\{(\w+)(?::\w+)?\}", value, path)


def test_no_get_endpoint_returns_broker_credential_material(vault):
    client = TestClient(app, raise_server_exceptions=False)
    stored = _store_binding(client, vault)
    needles = _needles(vault, stored["retired_blobs"])

    for response in stored["writes"]:
        assert _leaks(response.text, needles) == []

    offenders: Dict[str, List[str]] = {}
    swept = 0
    listing_seen = False
    for route in app.routes:
        if not isinstance(route, APIRoute) or "GET" not in (route.methods or set()):
            continue
        response = client.get(_fill(route.path, stored["id"]))
        swept += 1
        header_text = "\n".join(f"{k}: {v}" for k, v in response.headers.items())
        found = _leaks(response.text, needles) + _leaks(header_text, needles)
        if found:
            offenders[f"GET {route.path} -> {response.status_code}"] = found
        if route.path.endswith("/mock/broker-bindings") and response.status_code == 200:
            listing_seen = True
            assert len(response.json()["bindings"]) == 1

    assert offenders == {}
    assert swept >= 300
    assert listing_seen


_CREDENTIAL_FIELD_NAMES = {
    "credential",
    "username",
    "password",
    "secret",
    "credentialCiphertext",
    "credential_ciphertext",
    "ciphertext",
    "plaintext",
}


def test_no_binding_response_schema_has_a_field_a_credential_could_travel_in():
    document = app.openapi()
    components = document.get("components", {}).get("schemas", {})
    paths = {path: item for path, item in document["paths"].items() if "broker-bindings" in path}
    assert len(paths) == 4  # collection, /{id}, /{id}/rotate, /{id}/test

    for path, item in paths.items():
        for method, operation in item.items():
            for status, response in operation.get("responses", {}).items():
                if status.startswith("2"):
                    names = _schema_properties(response, components, set())
                    assert names & _CREDENTIAL_FIELD_NAMES == set(), f"{method.upper()} {path} {status}"


def _python_sources() -> Dict[str, str]:
    return {
        path.relative_to(_SRC).as_posix(): path.read_text(encoding="utf-8")
        for path in _SRC.rglob("*.py")
    }


def test_only_the_binding_vault_opens_a_broker_credential():
    callers = sorted(name for name, text in _python_sources().items() if "open_credential(" in text)
    # The vault defines it; the probe opens one for its single connection.
    assert callers == ["mock_broker_bindings.py", "mock_broker_probe.py"]


def test_only_the_database_layer_queries_the_table_and_only_the_vault_reads_the_ciphertext():
    # SQL that reads or writes the table; a comment that merely names it does not count.
    table = re.compile(r"\b(?:FROM|INTO|UPDATE|JOIN)\s+apiome\.mock_broker_bindings\b")
    sources = _python_sources()
    assert sorted(name for name, text in sources.items() if table.search(text)) == ["database.py"]
    # Slate's CDN vault (V368) has a column of the same name, so look only at broker modules.
    broker_modules = {name: text for name, text in sources.items() if name.startswith("mock_broker")}
    touching = sorted(name for name, text in broker_modules.items() if "credential_ciphertext" in text)
    assert touching == ["mock_broker_bindings.py"]
