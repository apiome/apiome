"""A reader session is never a REST credential — PCX-1.1 (#5889) acceptance criterion.

*"A reader session cannot call any route outside the browse/portal tags (sweep test over every
GET route, as AGX-2.2's secret sweep does)."* This module is that sweep, plus the direct checks
behind it:

1. **Every GET route the app serves** outside the ``browse``, ``portal-auth`` and ``portal-feedback`` (COL-4.4) tags is called
   twice — anonymously, and with a *live* ``Authorization: Reader <token>``. The session must buy
   nothing an anonymous caller does not already have: a route that answers the reader a 2xx must
   answer the anonymous caller a 2xx with the same body. (Refusing the reader where an anonymous
   caller is served is fine — the MCP registry reads any non-JWT ``Authorization`` as an MCP key
   and refuses it.)
2. **The two credential gates** — ``validate_authentication`` and
   ``validate_session_credentials`` — refuse the ``Reader`` scheme outright.
3. **The browse routes** check the session (a revoked one is a 401 on the next request) but serve
   the public slice: until PCX-1.3 a reader is not a workspace member.

Storage is the in-memory fake, so the sweep runs the same way with or without a database; every
other route runs against whatever database the suite has, and is compared all the same.
"""

from __future__ import annotations

import re
from typing import List

import pytest
from fake_portal_auth_repo import FakePortalAuthRepository, RecordingMailer
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from app import portal_auth_store
from app.auth import (
    resolve_optional_tenant_member_auth,
    validate_authentication,
    validate_session_credentials,
)
from app.main import app

_ALLOWED_TAGS = {"browse", "portal-auth", "portal-feedback"}
_ID = "33333333-3333-4333-8333-333333333333"


@pytest.fixture
def repo(monkeypatch):
    fake = FakePortalAuthRepository()
    monkeypatch.setattr(portal_auth_store, "default_repository", lambda: fake)
    return fake


@pytest.fixture
def reader_token(repo):
    """A live reader session for tenant ``acme``."""
    mailer = RecordingMailer()
    portal_auth_store.request_magic_link(
        repo,
        mailer,
        tenant_slug="acme",
        email="ada@example.com",
        return_to=None,
        browse_url="",
        signup_rejection=lambda _email: None,
    )
    from datetime import timedelta

    grant = portal_auth_store.exchange_token(
        repo, tenant_slug="acme", token=mailer.last_token(), user_agent=None, session_ttl=timedelta(days=1)
    )
    return grant.session_token


def _fill(path: str) -> str:
    """Fill a route template: tenant-ish params get ``acme``, id-ish a UUID, anything else ``x``."""

    def value(match: "re.Match[str]") -> str:
        name = match.group(1)
        if "tenant" in name:
            return "acme"
        if "id" in name:
            return _ID
        return "x"

    return re.sub(r"\{(\w+)(?::\w+)?\}", value, path)


def _get_routes() -> List[APIRoute]:
    """Every GET route outside the tags a reader session is meant for."""
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and "GET" in (route.methods or set())
        and not _ALLOWED_TAGS.intersection(route.tags or [])
    ]


def test_a_reader_session_buys_nothing_on_any_other_get_route(reader_token):
    client = TestClient(app, raise_server_exceptions=False)
    headers = {"Authorization": f"Reader {reader_token}"}
    elevated = {}
    routes = _get_routes()
    for route in routes:
        path = _fill(route.path)
        anonymous = client.get(path)
        with_reader = client.get(path, headers=headers)
        if not 200 <= with_reader.status_code < 300:
            continue  # refused — what a reader session should get everywhere outside the tags
        if not 200 <= anonymous.status_code < 300:
            elevated[f"GET {route.path}"] = (anonymous.status_code, with_reader.status_code)
        elif with_reader.content != anonymous.content:
            elevated[f"GET {route.path}"] = "a different body than the anonymous caller gets"
    assert elevated == {}
    # The sweep is not vacuous: it covered the whole app.
    assert len(routes) >= 300


def _request(method: str = "GET", path: str = "/v1/projects/acme") -> MagicMock:
    request = MagicMock()
    request.method = method
    request.url.path = path
    return request


def test_validate_authentication_refuses_a_live_reader_session(reader_token):
    with pytest.raises(HTTPException) as exc:
        validate_authentication(
            request=_request(), tenant_slug="acme", authorization=f"Reader {reader_token}", x_api_key=None
        )
    assert exc.value.status_code == 401


def test_validate_session_credentials_refuses_a_live_reader_session(reader_token):
    with pytest.raises(HTTPException) as exc:
        validate_session_credentials(
            request=_request(), authorization=f"Reader {reader_token}", x_api_key=None
        )
    assert exc.value.status_code == 401


def test_a_reader_token_sent_as_a_bearer_is_refused_too(reader_token):
    with pytest.raises(HTTPException) as exc:
        validate_authentication(
            request=_request(), tenant_slug="acme", authorization=f"Bearer {reader_token}", x_api_key=None
        )
    assert exc.value.status_code == 401


def test_browse_auth_accepts_a_live_session_as_the_public_slice(reader_token):
    assert (
        resolve_optional_tenant_member_auth("acme", authorization=f"Reader {reader_token}", x_api_key=None)
        is False
    )


def test_browse_auth_refuses_a_revoked_session_on_the_next_request(repo, reader_token):
    portal_auth_store.revoke_session(repo, reader_token)
    with pytest.raises(HTTPException) as exc:
        resolve_optional_tenant_member_auth("acme", authorization=f"Reader {reader_token}", x_api_key=None)
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "portal-session-invalid"


def test_browse_auth_refuses_a_malformed_reader_header(repo):
    with pytest.raises(HTTPException) as exc:
        resolve_optional_tenant_member_auth("acme", authorization="Reader sk_live_key", x_api_key=None)
    assert exc.value.status_code == 401
