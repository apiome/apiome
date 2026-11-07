"""``Database.regenerate_mcp_api_key``: the secret rolls in place, the old one stops verifying."""

import hashlib
from unittest.mock import MagicMock

import bcrypt

from app.database import Database

_TENANT = "6f1c2a9e-3b4d-4e5f-8a7b-9c0d1e2f3a4b"
_KEY_ID = "0d9e8f7a-6b5c-4d3e-9f2a-1b0c9d8e7f6a"


def _db_with_rows(rows):
    db = Database.__new__(Database)
    db.execute_query = MagicMock(return_value=rows)
    return db


def _row(prefix: str):
    return {
        "id": _KEY_ID,
        "prefix": prefix,
        "label": "Claude Desktop",
        "scope_json": {"tenants": [], "projects": []},
        "capability_mode": "explicit",
        "enabled_tools": ["spec_list"],
        "created_at": None,
        "expires_at": None,
        "revoked_at": None,
        "last_used_at": None,
        "created_by": None,
    }


def test_regenerate_stores_hash_and_prefix_of_the_returned_secret():
    db = _db_with_rows([_row("placeholder...")])
    meta, secret = db.regenerate_mcp_api_key(_TENANT, _KEY_ID)

    sql, params = db.execute_query.call_args.args
    key_hash, prefix, tenant_id, key_id = params
    assert "UPDATE apiome.mcp_api_keys" in sql
    assert "revoked_at IS NULL" in sql
    assert "expires_at > CURRENT_TIMESTAMP" in sql
    assert "last_used_at = NULL" in sql
    assert (tenant_id, key_id) == (_TENANT, _KEY_ID)
    assert prefix == Database.mcp_api_key_prefix(secret)
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    assert bcrypt.checkpw(digest, key_hash.encode("ascii"))
    # Settings attached to the key come back unchanged.
    assert meta["capability_mode"] == "explicit"
    assert meta["enabled_tools"] == ["spec_list"]


def test_regenerate_returns_none_for_revoked_expired_or_missing():
    db = _db_with_rows([])
    assert db.regenerate_mcp_api_key(_TENANT, _KEY_ID) is None


def test_regenerate_rejects_non_uuid_ids_without_querying():
    db = _db_with_rows([])
    assert db.regenerate_mcp_api_key("t1", _KEY_ID) is None
    assert db.regenerate_mcp_api_key(_TENANT, "nope") is None
    db.execute_query.assert_not_called()
