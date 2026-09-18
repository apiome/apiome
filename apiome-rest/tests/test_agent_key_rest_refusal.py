"""An agent key is never a REST credential — AGX-3.1 (#4537).

Agent keys live in ``api_keys`` beside workspace keys (V269), so every existing reader of that
table would accept one unless told otherwise. Two independent defences keep an agent key, which
is scoped to one toolset and a tool allowlist, from becoming a tenant-wide REST key:

1. ``db.validate_api_key`` only selects ``kind = 'workspace'`` rows, falling back to the older
   queries only when the ``kind`` column does not exist (a pre-V269 database, with no agent keys).
2. An agent key carries exactly the ``agent:invoke`` scope, and no entry in the REST scope
   allowlist accepts it, so it would be refused on every route even if (1) were bypassed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app import auth
from app.auth import (
    API_KEY_SCOPE_AGENT_INVOKE,
    enforce_api_key_scopes,
    validate_authentication,
    validate_session_credentials,
)
from app.database import Database


class _UndefinedColumnError(Exception):
    """A psycopg2-shaped ``42703`` error."""

    pgcode = "42703"


def _database_with(responses):
    """A ``Database`` whose ``execute_query`` plays ``responses`` in order and records the SQL.

    Args:
        responses: Each item is a list of rows to return, or an exception to raise.

    Returns:
        ``(database, queries)`` — the handle and the list the SQL of each call is appended to.
    """
    database = Database()
    queries = []
    remaining = list(responses)

    def _execute(query, params=None):
        queries.append(query)
        outcome = remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    database.execute_query = _execute
    return database, queries


# ============================================================================
# Defence 1: validate_api_key selects workspace keys only
# ============================================================================
def test_the_lookup_only_selects_workspace_keys():
    database, queries = _database_with([[]])
    assert database.validate_api_key("ak_0123456789abcdef") is None
    assert len(queries) == 1
    assert "ak.kind = 'workspace'" in queries[0]


def test_a_pre_v269_database_falls_back_to_the_scopes_query():
    database, queries = _database_with([_UndefinedColumnError('column ak.kind does not exist'), []])
    assert database.validate_api_key("sk_0123456789abcdef") is None
    assert len(queries) == 2
    assert "ak.kind" not in queries[1]
    assert "ak.scopes" in queries[1]


def test_the_fallback_chain_still_reaches_the_legacy_queries():
    database, queries = _database_with(
        [
            _UndefinedColumnError("column ak.kind does not exist"),
            _UndefinedColumnError("column ak.scopes does not exist"),
            [],
        ]
    )
    assert database.validate_api_key("sk_0123456789abcdef") is None
    assert len(queries) == 3
    assert "ak.scopes" not in queries[2]


def test_any_other_error_propagates():
    database, _ = _database_with([RuntimeError("connection lost")])
    with pytest.raises(RuntimeError, match="connection lost"):
        database.validate_api_key("sk_0123456789abcdef")


# ============================================================================
# Defence 2: agent:invoke is accepted by no REST route
# ============================================================================
def test_no_allowlist_entry_accepts_the_agent_scope():
    assert API_KEY_SCOPE_AGENT_INVOKE == "agent:invoke"
    assert all(
        scope != API_KEY_SCOPE_AGENT_INVOKE for _, _, scope in auth._API_KEY_SCOPE_ALLOWLIST
    )


def _request(method: str, path: str) -> MagicMock:
    req = MagicMock()
    req.method = method
    req.url.path = path
    return req


# Every allowlisted route, plus ordinary reads and writes.
_ROUTES = [
    (method, pattern.pattern.strip("^$").replace("[^/]+", "x").replace("/?", ""))
    for method, pattern, _ in auth._API_KEY_SCOPE_ALLOWLIST
] + [
    ("GET", "/v1/tenants/acme/agent-keys"),
    ("POST", "/v1/tenants/acme/agent-keys"),
    ("GET", "/v1/projects/acme"),
    ("DELETE", "/v1/projects/acme/pets"),
]


@pytest.mark.parametrize(("method", "path"), _ROUTES)
def test_an_agent_scoped_key_is_refused_on_every_route(method, path):
    with pytest.raises(HTTPException) as exc:
        enforce_api_key_scopes(
            {"auth_method": "api_key", "scopes": [API_KEY_SCOPE_AGENT_INVOKE]},
            _request(method, path),
        )
    assert exc.value.status_code == 403


def test_validate_authentication_refuses_an_agent_scoped_row():
    """Even a lookup that returned an agent row would not authenticate a REST call."""
    row = {
        "id": "key-agent",
        "tenant_id": "tenant-1",
        "tenant_slug": "acme",
        "tenant_name": "Acme",
        "created_by_user_id": "user-1",
        "scopes": [API_KEY_SCOPE_AGENT_INVOKE],
    }
    with patch("app.auth.db") as mock_db:
        mock_db.validate_api_key.return_value = dict(row)
        with pytest.raises(HTTPException) as exc:
            validate_authentication(
                request=_request("GET", "/v1/versions/acme/p/v/lint"),
                tenant_slug="acme",
                authorization=None,
                x_api_key="ak_0123456789abcdef",
            )
        assert exc.value.status_code == 403
        with pytest.raises(HTTPException) as exc:
            validate_session_credentials(
                request=_request("GET", "/v1/tenants/me"),
                authorization=None,
                x_api_key="ak_0123456789abcdef",
            )
        assert exc.value.status_code == 403
