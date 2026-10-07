"""AGX-2.1 vault injection (#4533): the MCP runtime opens the AGX-2.2 vault like apiome-rest does.

Credentials are sealed with apiome-rest's own cipher under a throwaway master key, served by the
recording pool, and opened by :func:`~apiome_mcp.agent_upstream_auth.resolve_upstream_injection`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any

import pytest
from app.config import settings
from app.upstream_credentials import _CIPHER

from agent_invocation_fakes import RecordingPool
from agent_runtime_fakes import TENANT_ID, TOOLSET_ID
from apiome_mcp.agent_upstream_auth import UpstreamCredentialUnavailableError, resolve_upstream_injection

SECRET = "sk_live_upstream_value_123"


@pytest.fixture
def vault_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure one upstream-vault master key in this process."""
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "upstream_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "upstream_credential_active_key_version", None)


def _row(server_url: str, **fields: Any) -> dict[str, Any]:
    blob, version = _CIPHER.seal({"value": SECRET})
    row = {
        "id": "55555555-5555-4555-8555-555555555555",
        "server_url": server_url,
        "kind": "apiKey",
        "api_key_in": "header",
        "api_key_name": "X-Api-Key",
        "encrypted_secret": blob,
        "key_version": version,
    }
    row.update(fields)
    return row


def _pool(rows: list[dict[str, Any]]) -> RecordingPool:
    return RecordingPool(lambda sql, params: rows if "upstream_credentials c" in sql else None)


def _uses(pool: RecordingPool) -> list[Any]:
    return [params for sql, params in pool.statements if "upstream_credential_uses" in sql]


def _resolve(pool: RecordingPool, url: str) -> Any:
    return asyncio.run(resolve_upstream_injection(pool, TENANT_ID, TOOLSET_ID, url))  # type: ignore[arg-type]


def test_a_bound_credential_is_injected_and_its_use_recorded(vault_key: None) -> None:
    pool = _pool([_row("https://api.example.com/v1")])
    injection = _resolve(pool, "https://api.example.com/v1/pets")
    assert injection is not None
    url, headers = injection.apply("https://api.example.com/v1/pets", {"X-Api-Key": "agent-supplied"})
    assert headers == {"X-Api-Key": SECRET}
    assert _uses(pool) == [(TENANT_ID, "55555555-5555-4555-8555-555555555555", TOOLSET_ID, "injected")]
    assert SECRET not in repr(injection)


def test_nothing_is_injected_for_an_unbound_host(vault_key: None) -> None:
    pool = _pool([_row("https://api.example.com/v1")])
    assert _resolve(pool, "https://other.example.com/v1/pets") is None
    assert _resolve(pool, "https://api.example.com/v10/pets") is None
    assert _uses(pool) == []


def test_a_credential_that_cannot_open_fails_closed(vault_key: None, monkeypatch: pytest.MonkeyPatch) -> None:
    row = _row("https://api.example.com/v1")
    monkeypatch.setattr(settings, "upstream_credential_encryption_keys", None)
    pool = _pool([row])
    with pytest.raises(UpstreamCredentialUnavailableError):
        _resolve(pool, "https://api.example.com/v1/pets")
    assert [use[3] for use in _uses(pool)] == ["unavailable"]


def test_a_ledger_failure_does_not_fail_the_injection(vault_key: None) -> None:
    rows = [_row("https://api.example.com/v1")]
    pool = RecordingPool(
        lambda sql, params: rows if "upstream_credentials c" in sql else None, fail_on="upstream_credential_uses"
    )
    assert _resolve(pool, "https://api.example.com/v1/pets") is not None
