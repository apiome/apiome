"""OAuth 2.1 authorization code + PKCE + refresh for MCP endpoints — MCAT-6.4 (#3680).

Three layers:

* **Protocol** — :mod:`app.mcp_oauth_flow` units: PKCE, redirect-URI rules, scope choice, client
  registration (RFC 7591), the authorization URL (PKCE + RFC 8707 ``resource``), code exchange and
  refresh requests, token-response validation and the audience check.
* **Service** — :mod:`app.mcp_oauth_service` against :class:`ReferenceAuthorizationServer`, an
  in-process authorization server that enforces PKCE ``S256``, requires the ``resource`` on every
  request, issues JWT access tokens whose ``aud`` is that resource, rotates refresh tokens and
  supports dynamic registration. The credential table is an in-memory stand-in. This is the
  acceptance criterion: tokens are obtained, scoped to the resource, and refreshed transparently
  when :func:`app.mcp_credentials.load_endpoint_auth_headers` — the seam discovery, the sweep and
  the test harness all use — finds an expiring token.
* **Routes** — ``POST …/endpoints/{id}/oauth/authorize`` and ``POST …/oauth/callback``.

The credential encryption runs for real (a per-test master key), so the tokens are sealed exactly
as in production and the tests check that no response carries one.
"""

from __future__ import annotations

import base64
import copy
import datetime
import hashlib
import json
import os
import secrets
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, parse_qsl, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from app import mcp_credentials, mcp_oauth_flow, mcp_oauth_service
from app.auth import validate_authentication
from app.config import settings
from app.main import app
from app.mcp_credential_crypto import unseal_credential_payload
from app.mcp_oauth_flow import (
    OAuthFlowError,
    build_authorization_url,
    check_callback_issuer,
    check_redirect_uri,
    check_token_audience,
    choose_auth_method,
    exchange_code,
    generate_pkce_pair,
    jwt_audiences,
    needs_refresh,
    pkce_challenge,
    refresh_tokens,
    register_client,
    requested_scopes,
    require_flow_metadata,
    token_payload_from_response,
)

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 8, 12, 0, 0, tzinfo=UTC)

ISSUER = "https://auth.example.com"
RESOURCE = "https://mcp.example.com/mcp"
REDIRECT = "https://app.apiome.test/ade/dashboard/mcp/oauth/callback"
EID = "11111111-1111-1111-1111-111111111111"
TENANT = "t1"
USER = "user-1"


def _metadata(**overrides: Any) -> Dict[str, Any]:
    """Discovered ``oauth_metadata`` as MCAT-6.3 stores it."""
    data = {
        "source": "oauth_discovery",
        "resource": RESOURCE,
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "registration_endpoint": f"{ISSUER}/register",
        "revocation_endpoint": None,
        "scopes_supported": ["mcp:read", "mcp:write"],
        "challenge_scopes": ["mcp:read"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_basic"],
        "code_challenge_methods_supported": ["S256"],
        "pkce_s256_supported": True,
    }
    data.update(overrides)
    return data


def _jwt(claims: Dict[str, Any]) -> str:
    """An unsigned-looking JWT carrying ``claims`` (Apiome never verifies the signature)."""

    def seg(obj: Dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{seg({'alg': 'RS256', 'typ': 'at+jwt'})}.{seg(claims)}.c2ln"


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch):
    """Configure a real master key so tokens and states are sealed as in production."""
    key = base64.b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)


# ===========================================================================
# Reference authorization server + in-memory credential store
# ===========================================================================


class ReferenceAuthorizationServer:
    """A small, strict OAuth 2.1 authorization server served through ``httpx.MockTransport``.

    * ``POST /register`` — RFC 7591; issues a public client.
    * ``authorize(url)`` — stands in for the user consenting in the browser: validates the request
      (PKCE S256, ``resource``, registered redirect URI) and returns the redirect's query params.
    * ``POST /token`` — ``authorization_code`` (checks the verifier against the challenge, the
      redirect URI and the ``resource``) and ``refresh_token`` (rotates the refresh token, so a
      replayed one fails).
    """

    def __init__(self, *, expires_in: int = 3600, audience: Optional[str] = None) -> None:
        self.expires_in = expires_in
        self.audience = audience
        self.clients: Dict[str, Dict[str, Any]] = {}
        self.codes: Dict[str, Dict[str, Any]] = {}
        self.refresh: Dict[str, Dict[str, Any]] = {}
        self.requests: List[httpx.Request] = []
        self.issued = 0

    # -- transport ---------------------------------------------------------
    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/register":
            return self._register(json.loads(request.content))
        if path == "/token":
            return self._token(dict(parse_qsl(request.content.decode())))
        return httpx.Response(404)

    # -- endpoints ---------------------------------------------------------
    def _register(self, body: Dict[str, Any]) -> httpx.Response:
        client_id = f"client-{len(self.clients) + 1}"
        self.clients[client_id] = {"redirect_uris": body["redirect_uris"]}
        return httpx.Response(201, json={"client_id": client_id, "token_endpoint_auth_method": "none", **body})

    def authorize(self, url: str) -> Dict[str, str]:
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert q["response_type"] == "code"
        assert q["code_challenge_method"] == "S256"
        assert q["resource"] == RESOURCE
        client = self.clients.get(q["client_id"])
        assert client is None or q["redirect_uri"] in client["redirect_uris"]
        code = secrets.token_urlsafe(16)
        self.codes[code] = {
            "challenge": q["code_challenge"],
            "redirect_uri": q["redirect_uri"],
            "client_id": q["client_id"],
            "scope": q.get("scope"),
        }
        return {"code": code, "state": q["state"], "iss": ISSUER}

    def _tokens(self, client_id: str, scope: Optional[str]) -> Dict[str, Any]:
        self.issued += 1
        refresh = f"rt-{self.issued}-{secrets.token_hex(4)}"
        self.refresh[refresh] = {"client_id": client_id, "scope": scope}
        return {
            "access_token": _jwt({"aud": self.audience or RESOURCE, "n": self.issued}),
            "token_type": "Bearer",
            "expires_in": self.expires_in,
            "refresh_token": refresh,
            "scope": scope,
        }

    def _token(self, form: Dict[str, str]) -> httpx.Response:
        if form.get("resource") != RESOURCE:
            return httpx.Response(400, json={"error": "invalid_target"})
        if form.get("grant_type") == "authorization_code":
            grant = self.codes.pop(form.get("code", ""), None)
            if grant is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            if pkce_challenge(form.get("code_verifier", "")) != grant["challenge"]:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "PKCE"})
            if form.get("redirect_uri") != grant["redirect_uri"] or form.get("client_id") != grant["client_id"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json=self._tokens(grant["client_id"], grant["scope"]))
        if form.get("grant_type") == "refresh_token":
            grant = self.refresh.pop(form.get("refresh_token", ""), None)
            if grant is None or grant["client_id"] != form.get("client_id"):
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json=self._tokens(grant["client_id"], grant["scope"]))
        return httpx.Response(400, json={"error": "unsupported_grant_type"})


class MemoryCredentialStore:
    """In-memory stand-in for the ``mcp_endpoint_credentials`` methods the flow uses."""

    def __init__(self, metadata: Optional[Dict[str, Any]] = None) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.clock = 0
        if metadata is not None:
            self.rows[EID] = {
                "id": "cred-1",
                "endpoint_id": EID,
                "auth_type": "none",
                "encrypted_payload": None,
                "key_version": None,
                "oauth_metadata": copy.deepcopy(metadata),
                "last_refreshed_at": None,
            }

    def _tick(self) -> datetime.datetime:
        self.clock += 1
        return NOW + datetime.timedelta(microseconds=self.clock)

    def get_mcp_endpoint_credentials(self, endpoint_id: str) -> Optional[Dict[str, Any]]:
        row = self.rows.get(endpoint_id)
        return copy.deepcopy(row) if row else None

    def merge_mcp_endpoint_oauth_metadata(self, endpoint_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        row = self.rows[endpoint_id]
        row["oauth_metadata"] = {**row["oauth_metadata"], **copy.deepcopy(patch)}
        return copy.deepcopy(row)

    def consume_mcp_endpoint_oauth_pending(self, endpoint_id: str, nonce_sha256: str):
        row = self.rows.get(endpoint_id)
        pending = (row or {}).get("oauth_metadata", {}).get("pending_authorization")
        if not pending or pending.get("nonce_sha256") != nonce_sha256:
            return None
        del row["oauth_metadata"]["pending_authorization"]
        return copy.deepcopy(row)

    def store_mcp_endpoint_oauth_tokens(
        self,
        *,
        endpoint_id,
        encrypted_payload,
        key_version,
        metadata_patch,
        expected_last_refreshed_at=None,
        compare=False,
    ):
        row = self.rows.get(endpoint_id)
        if row is None:
            return None
        if compare and row["last_refreshed_at"] != expected_last_refreshed_at:
            return None
        row.update(
            auth_type="oauth2",
            encrypted_payload=encrypted_payload,
            key_version=key_version,
            last_refreshed_at=self._tick(),
        )
        row["oauth_metadata"] = {**row["oauth_metadata"], **copy.deepcopy(metadata_patch)}
        return copy.deepcopy(row)


@pytest.fixture
def server(monkeypatch) -> ReferenceAuthorizationServer:
    """The reference authorization server, wired in as every flow HTTP client."""
    reference = ReferenceAuthorizationServer()
    monkeypatch.setattr(mcp_oauth_flow, "_http_client", reference.client)
    return reference


@pytest.fixture
def store(monkeypatch) -> MemoryCredentialStore:
    """An endpoint whose discovery stored OAuth metadata and no secret yet."""
    memory = MemoryCredentialStore(_metadata())
    for name in (
        "get_mcp_endpoint_credentials",
        "merge_mcp_endpoint_oauth_metadata",
        "consume_mcp_endpoint_oauth_pending",
        "store_mcp_endpoint_oauth_tokens",
    ):
        monkeypatch.setattr(mcp_oauth_service.db, name, getattr(memory, name))
    return memory


def _payload(store: MemoryCredentialStore) -> Dict[str, Any]:
    row = store.rows[EID]
    return unseal_credential_payload(row["encrypted_payload"], row["key_version"])


def _connect(server: ReferenceAuthorizationServer, *, now=NOW, **start_kwargs) -> Dict[str, Any]:
    """Start, consent at the reference server and complete — the whole browser round trip."""
    started = mcp_oauth_service.start_authorization(
        endpoint_id=EID, tenant_id=TENANT, user_id=USER, redirect_uri=REDIRECT, now=now, **start_kwargs
    )
    redirect = server.authorize(started["authorization_url"])
    endpoint_id, row = mcp_oauth_service.complete_authorization(tenant_id=TENANT, user_id=USER, now=now, **redirect)
    return {"started": started, "endpoint_id": endpoint_id, "row": row}


# ===========================================================================
# Protocol units
# ===========================================================================


def test_pkce_pair_is_s256_of_a_valid_verifier():
    verifier, challenge = generate_pkce_pair()
    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected
    assert generate_pkce_pair()[0] != verifier


def test_pkce_rfc7636_appendix_b_vector():
    assert (
        pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )


@pytest.mark.parametrize(
    "uri",
    [REDIRECT, "http://localhost:3000/cb", "http://127.0.0.1/cb", "https://10.0.0.5/cb"],
)
def test_redirect_uri_allowed(uri):
    assert check_redirect_uri(uri) == uri


@pytest.mark.parametrize(
    "uri",
    [
        "",
        "/relative",
        "ftp://x/cb",
        "http://app.example.com/cb",
        "https://app.example.com/cb#frag",
        "https://u:p@app.example.com/cb",
    ],
)
def test_redirect_uri_refused(uri):
    with pytest.raises(OAuthFlowError) as err:
        check_redirect_uri(uri)
    assert err.value.code == "invalid_redirect_uri"


def test_flow_metadata_requires_discovery_and_pkce():
    assert require_flow_metadata(_metadata())["issuer"] == ISSUER
    with pytest.raises(OAuthFlowError) as err:
        require_flow_metadata({})
    assert err.value.code == "not_discovered"
    with pytest.raises(OAuthFlowError) as err:
        require_flow_metadata(_metadata(pkce_s256_supported=False))
    assert err.value.code == "pkce_unsupported"


def test_requested_scopes_order():
    assert requested_scopes(_metadata(), ["a", "a", " b "]) == ["a", "b"]
    assert requested_scopes(_metadata(), None) == ["mcp:read"]
    assert requested_scopes(_metadata(challenge_scopes=[]), None) == ["mcp:read", "mcp:write"]
    assert requested_scopes(_metadata(challenge_scopes=[], scopes_supported=[]), None) == []


def test_choose_auth_method():
    assert choose_auth_method(_metadata(), False) == "none"
    assert choose_auth_method(_metadata(), True) == "client_secret_basic"
    assert (
        choose_auth_method(_metadata(token_endpoint_auth_methods_supported=["client_secret_post"]), True)
        == "client_secret_post"
    )
    assert choose_auth_method(_metadata(token_endpoint_auth_methods_supported=[]), True) == "client_secret_basic"


def test_authorization_url_carries_pkce_resource_state_and_scope():
    url = build_authorization_url(
        _metadata(authorization_endpoint=f"{ISSUER}/authorize?tenant=x"),
        client_id="c1",
        redirect_uri=REDIRECT,
        code_challenge="CH",
        state="1.abc",
        scopes=["mcp:read", "mcp:write"],
    )
    parts = urlsplit(url)
    q = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert parts.netloc == "auth.example.com" and parts.path == "/authorize"
    assert q == {
        "tenant": "x",
        "response_type": "code",
        "client_id": "c1",
        "redirect_uri": REDIRECT,
        "code_challenge": "CH",
        "code_challenge_method": "S256",
        "state": "1.abc",
        "resource": RESOURCE,
        "scope": "mcp:read mcp:write",
    }


def test_authorization_url_omits_empty_scope_and_refuses_bad_endpoint():
    url = build_authorization_url(
        _metadata(), client_id="c", redirect_uri=REDIRECT, code_challenge="x", state="s", scopes=[]
    )
    assert "scope=" not in url
    with pytest.raises(OAuthFlowError) as err:
        build_authorization_url(
            _metadata(authorization_endpoint="http://auth.example.com/a"),
            client_id="c",
            redirect_uri=REDIRECT,
            code_challenge="x",
            state="s",
            scopes=[],
        )
    assert err.value.code == "invalid_url"


def test_callback_issuer_rfc9207():
    check_callback_issuer(_metadata(), None)
    check_callback_issuer(_metadata(), ISSUER)
    with pytest.raises(OAuthFlowError) as err:
        check_callback_issuer(_metadata(), "https://evil.example.com")
    assert err.value.code == "issuer_mismatch"


def _mock(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_register_client_sends_rfc7591_body():
    seen: List[Dict[str, Any]] = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(201, json={"client_id": "abc"})

    client = register_client(_metadata(), REDIRECT, client=_mock(handler))
    assert client == {"client_id": "abc", "client_secret": None, "token_endpoint_auth_method": "none"}
    assert seen[0]["redirect_uris"] == [REDIRECT]
    assert seen[0]["grant_types"] == ["authorization_code", "refresh_token"]
    assert seen[0]["token_endpoint_auth_method"] == "none"


def test_register_client_keeps_issued_secret():
    def handler(_):
        return httpx.Response(201, json={"client_id": "abc", "client_secret": "s3"})

    client = register_client(_metadata(), REDIRECT, client=_mock(handler))
    assert client["client_secret"] == "s3"
    assert client["token_endpoint_auth_method"] == "client_secret_basic"


def test_register_client_failures():
    with pytest.raises(OAuthFlowError) as err:
        register_client(_metadata(registration_endpoint=None), REDIRECT)
    assert err.value.code == "client_required"
    with pytest.raises(OAuthFlowError) as err:
        register_client(
            _metadata(), REDIRECT, client=_mock(lambda _: httpx.Response(400, json={"error": "invalid_redirect_uri"}))
        )
    assert err.value.code == "registration_failed" and "invalid_redirect_uri" in err.value.message
    with pytest.raises(OAuthFlowError) as err:
        register_client(_metadata(), REDIRECT, client=_mock(lambda _: httpx.Response(201, json={})))
    assert err.value.code == "registration_failed"


def test_exchange_code_public_client_form():
    seen: List[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"access_token": "a", "token_type": "Bearer"})

    exchange_code(
        _metadata(),
        code="C",
        code_verifier="V",
        redirect_uri=REDIRECT,
        client_id="c1",
        client_secret=None,
        auth_method="none",
        client=_mock(handler),
    )
    form = dict(parse_qsl(seen[0].content.decode()))
    assert form == {
        "grant_type": "authorization_code",
        "code": "C",
        "redirect_uri": REDIRECT,
        "code_verifier": "V",
        "resource": RESOURCE,
        "client_id": "c1",
    }
    assert "authorization" not in seen[0].headers


def test_exchange_code_basic_and_post_client_auth():
    seen: List[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={})

    common = dict(code="C", code_verifier="V", redirect_uri=REDIRECT, client_id="c 1", client_secret="s:2")
    exchange_code(_metadata(), auth_method="client_secret_basic", client=_mock(handler), **common)
    expected = base64.b64encode(b"c%201:s%3A2").decode()
    assert seen[0].headers["authorization"] == f"Basic {expected}"
    assert "client_secret" not in seen[0].content.decode()
    exchange_code(_metadata(), auth_method="client_secret_post", client=_mock(handler), **common)
    form = dict(parse_qsl(seen[1].content.decode()))
    assert form["client_id"] == "c 1" and form["client_secret"] == "s:2"


def test_token_error_names_the_oauth_error_but_no_secret():
    def handler(_):
        return httpx.Response(400, json={"error": "invalid_grant", "error_description": "expired"})

    with pytest.raises(OAuthFlowError) as err:
        exchange_code(
            _metadata(),
            code="SECRET-CODE",
            code_verifier="SECRET-VERIFIER",
            redirect_uri=REDIRECT,
            client_id="c",
            client_secret=None,
            auth_method="none",
            client=_mock(handler),
        )
    assert err.value.code == "token_error"
    assert "invalid_grant" in err.value.message and "expired" in err.value.message
    assert "SECRET" not in str(err.value)


def test_token_request_network_failure_and_oversize(monkeypatch):
    def boom(_):
        raise httpx.ConnectError("nope")

    with pytest.raises(OAuthFlowError) as err:
        refresh_tokens(_metadata(), {"refresh_token": "r", "client_id": "c"}, client=_mock(boom))
    assert err.value.code == "token_error"
    monkeypatch.setattr(mcp_oauth_flow, "MAX_METADATA_BYTES", 10)
    with pytest.raises(OAuthFlowError) as err:
        refresh_tokens(
            _metadata(),
            {"refresh_token": "r", "client_id": "c"},
            client=_mock(lambda _: httpx.Response(200, content=b"x" * 50)),
        )
    assert "larger" in err.value.message


def test_redirects_are_not_followed_on_token_requests():
    def handler(_):
        return httpx.Response(302, headers={"location": "https://evil.example.com/token"})

    with pytest.raises(OAuthFlowError) as err:
        refresh_tokens(_metadata(), {"refresh_token": "r", "client_id": "c"}, client=_mock(handler))
    assert err.value.code == "token_error" and "302" in err.value.message


def test_refresh_request_form_and_not_refreshable():
    seen: List[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={})

    refresh_tokens(_metadata(), {"refresh_token": "R", "client_id": "c", "scope": "mcp:read"}, client=_mock(handler))
    assert dict(parse_qsl(seen[0].content.decode())) == {
        "grant_type": "refresh_token",
        "refresh_token": "R",
        "scope": "mcp:read",
        "resource": RESOURCE,
        "client_id": "c",
    }
    with pytest.raises(OAuthFlowError) as err:
        refresh_tokens(_metadata(), {"client_id": "c"})
    assert err.value.code == "not_refreshable"


def test_jwt_audiences():
    assert jwt_audiences("opaque-token") is None
    assert jwt_audiences("a.b.c") is None
    assert jwt_audiences(_jwt({"aud": RESOURCE})) == [RESOURCE]
    assert jwt_audiences(_jwt({"aud": ["x", RESOURCE, 3]})) == ["x", RESOURCE]
    assert jwt_audiences(_jwt({"sub": "u"})) is None


def test_audience_check():
    check_token_audience("opaque", RESOURCE)
    check_token_audience(_jwt({"aud": RESOURCE + "/"}), RESOURCE)
    check_token_audience(_jwt({"aud": "https://mcp.example.com"}), RESOURCE)
    check_token_audience(_jwt({"aud": ["other", RESOURCE]}), RESOURCE)
    with pytest.raises(OAuthFlowError) as err:
        check_token_audience(_jwt({"aud": "https://other.example.com/mcp"}), RESOURCE)
    assert err.value.code == "audience_mismatch"


def _validate(response, previous=None):
    return token_payload_from_response(
        response,
        metadata=_metadata(),
        client_id="c",
        client_secret=None,
        auth_method="none",
        previous=previous,
        now=NOW,
    )


def test_token_payload_from_response():
    payload = _validate(
        {"access_token": "a", "token_type": "bearer", "expires_in": 120, "refresh_token": "r", "scope": "mcp:read"}
    )
    assert payload["token_type"] == "Bearer"
    assert payload["expires_at"] == (NOW + datetime.timedelta(seconds=120)).isoformat()
    assert payload["refresh_token"] == "r" and payload["resource"] == RESOURCE and payload["issuer"] == ISSUER


def test_refresh_response_without_refresh_token_keeps_the_old_one():
    payload = _validate({"access_token": "a2", "token_type": "Bearer"}, previous={"refresh_token": "r1", "scope": "s"})
    assert payload["refresh_token"] == "r1" and payload["scope"] == "s" and payload["expires_at"] is None


@pytest.mark.parametrize(
    "response",
    [
        {"token_type": "Bearer"},
        {"access_token": "a", "token_type": "mac"},
        {"access_token": "a"},
        {"access_token": "a", "token_type": "Bearer", "expires_in": -1},
        {"access_token": "a", "token_type": "Bearer", "expires_in": "soon"},
        {"access_token": "a\r\nX-Evil: 1", "token_type": "Bearer"},
    ],
)
def test_invalid_token_responses(response):
    with pytest.raises(OAuthFlowError) as err:
        _validate(response)
    assert err.value.code == "invalid_token_response"


def test_token_for_another_audience_is_refused():
    with pytest.raises(OAuthFlowError) as err:
        _validate({"access_token": _jwt({"aud": "https://other.example.com"}), "token_type": "Bearer"})
    assert err.value.code == "audience_mismatch"


def test_needs_refresh():
    soon = (NOW + datetime.timedelta(seconds=30)).isoformat()
    later = (NOW + datetime.timedelta(hours=1)).isoformat()
    assert needs_refresh({"refresh_token": "r", "expires_at": soon}, now=NOW)
    assert not needs_refresh({"refresh_token": "r", "expires_at": later}, now=NOW)
    assert not needs_refresh({"expires_at": soon}, now=NOW)
    assert not needs_refresh({"refresh_token": "r"}, now=NOW)
    assert needs_refresh({"refresh_token": "r", "expires_at": "2026-11-08T12:00:30"}, now=NOW)


# ===========================================================================
# Service against the reference authorization server
# ===========================================================================


def test_state_is_sealed_and_tamper_evident():
    verifier = "verifier-" + "x" * 40
    state = mcp_oauth_service.seal_state({"purpose": mcp_oauth_service.STATE_PURPOSE, "code_verifier": verifier})
    raw = base64.urlsafe_b64decode(state.split(".", 1)[1] + "==")
    assert verifier.encode() not in raw and verifier not in state
    assert mcp_oauth_service.unseal_state(state)["code_verifier"] == verifier
    flipped = state[:-2] + ("A" if state[-2] != "A" else "B") + state[-1]
    for bad in (flipped, "garbage", "", "1.!!!"):
        with pytest.raises(OAuthFlowError) as err:
            mcp_oauth_service.unseal_state(bad)
        assert err.value.code == "invalid_state"


def test_state_cannot_be_a_credential_blob():
    from app.mcp_credential_crypto import seal_credential_payload

    blob, version = seal_credential_payload({"purpose": mcp_oauth_service.STATE_PURPOSE})
    forged = f"{version}." + base64.urlsafe_b64encode(blob).rstrip(b"=").decode()
    with pytest.raises(OAuthFlowError):
        mcp_oauth_service.unseal_state(forged)


def test_connect_obtains_tokens_scoped_to_the_resource(server, store):
    result = _connect(server)
    started = result["started"]
    assert started["client_registration"] == "dynamic" and started["client_id"] == "client-1"
    assert started["scopes"] == ["mcp:read"]
    assert result["endpoint_id"] == EID

    row = store.rows[EID]
    assert row["auth_type"] == "oauth2"
    payload = _payload(store)
    assert jwt_audiences(payload["access_token"]) == [RESOURCE]
    assert payload["refresh_token"] and payload["client_id"] == "client-1"
    token = row["oauth_metadata"]["token"]
    assert token["refreshable"] is True and token["client_registration"] == "dynamic"
    assert token["expires_at"] == (NOW + datetime.timedelta(seconds=3600)).isoformat()
    assert "pending_authorization" not in row["oauth_metadata"]
    # The public client is cached, and nothing secret is in the cleartext metadata.
    assert row["oauth_metadata"]["client"]["client_id"] == "client-1"
    assert payload["access_token"] not in json.dumps(row["oauth_metadata"])
    assert payload["refresh_token"] not in json.dumps(row["oauth_metadata"])


def test_second_connect_reuses_the_registered_client(server, store):
    _connect(server)
    _connect(server)
    assert list(server.clients) == ["client-1"]


def test_preregistered_client_skips_registration(server, store):
    result = _connect(server, client_id="pre-1")
    assert result["started"]["client_registration"] == "preregistered"
    assert not server.clients
    assert _payload(store)["client_id"] == "pre-1"


def test_start_without_registration_endpoint_needs_client_id(server, store):
    store.rows[EID]["oauth_metadata"]["registration_endpoint"] = None
    with pytest.raises(OAuthFlowError) as err:
        mcp_oauth_service.start_authorization(endpoint_id=EID, tenant_id=TENANT, user_id=USER, redirect_uri=REDIRECT)
    assert err.value.code == "client_required"


def test_start_refuses_without_pkce(server, store):
    store.rows[EID]["oauth_metadata"]["pkce_s256_supported"] = False
    with pytest.raises(OAuthFlowError) as err:
        mcp_oauth_service.start_authorization(endpoint_id=EID, tenant_id=TENANT, user_id=USER, redirect_uri=REDIRECT)
    assert err.value.code == "pkce_unsupported"


def _started_redirect(server):
    started = mcp_oauth_service.start_authorization(
        endpoint_id=EID, tenant_id=TENANT, user_id=USER, redirect_uri=REDIRECT, now=NOW
    )
    return server.authorize(started["authorization_url"])


def test_state_is_single_use(server, store):
    redirect = _started_redirect(server)
    mcp_oauth_service.complete_authorization(tenant_id=TENANT, user_id=USER, now=NOW, **redirect)
    with pytest.raises(OAuthFlowError) as err:
        mcp_oauth_service.complete_authorization(tenant_id=TENANT, user_id=USER, now=NOW, **redirect)
    assert err.value.code == "invalid_state"


def test_newer_authorization_supersedes_older(server, store):
    first = _started_redirect(server)
    _started_redirect(server)
    with pytest.raises(OAuthFlowError) as err:
        mcp_oauth_service.complete_authorization(tenant_id=TENANT, user_id=USER, now=NOW, **first)
    assert err.value.code == "invalid_state"


def test_state_bound_to_user_tenant_and_time(server, store):
    redirect = _started_redirect(server)
    for kwargs in ({"tenant_id": "t2", "user_id": USER}, {"tenant_id": TENANT, "user_id": "someone-else"}):
        with pytest.raises(OAuthFlowError) as err:
            mcp_oauth_service.complete_authorization(now=NOW, **kwargs, **redirect)
        assert err.value.code == "invalid_state"
    with pytest.raises(OAuthFlowError) as err:
        mcp_oauth_service.complete_authorization(
            tenant_id=TENANT, user_id=USER, now=NOW + datetime.timedelta(minutes=11), **redirect
        )
    assert err.value.code == "state_expired"


def test_declined_consent_and_wrong_issuer(server, store):
    redirect = _started_redirect(server)
    with pytest.raises(OAuthFlowError) as err:
        mcp_oauth_service.complete_authorization(
            tenant_id=TENANT, user_id=USER, now=NOW, state=redirect["state"], error="access_denied"
        )
    assert err.value.code == "authorization_denied"
    redirect = _started_redirect(server)
    redirect["iss"] = "https://evil.example.com"
    with pytest.raises(OAuthFlowError) as err:
        mcp_oauth_service.complete_authorization(tenant_id=TENANT, user_id=USER, now=NOW, **redirect)
    assert err.value.code == "issuer_mismatch"
    assert store.rows[EID]["auth_type"] == "none"


def test_wrong_audience_token_is_not_stored(server, store):
    server.audience = "https://other.example.com/mcp"
    with pytest.raises(OAuthFlowError) as err:
        _connect(server)
    assert err.value.code == "audience_mismatch"
    assert store.rows[EID]["encrypted_payload"] is None


def test_load_headers_refreshes_an_expiring_token_transparently(server, store, monkeypatch):
    server.expires_in = 30  # inside the refresh skew: the next load must refresh
    _connect(server, now=datetime.datetime.now(UTC))
    first = _payload(store)
    monkeypatch.setattr(mcp_credentials.db, "get_mcp_endpoint_credentials", store.get_mcp_endpoint_credentials)

    server.expires_in = 3600
    headers = mcp_credentials.load_endpoint_auth_headers(EID)

    second = _payload(store)
    assert headers == {"Authorization": f"Bearer {second['access_token']}"}
    assert second["access_token"] != first["access_token"]
    assert second["refresh_token"] != first["refresh_token"]  # rotated
    token = store.rows[EID]["oauth_metadata"]["token"]
    assert token["refreshed_at"] and token["last_refresh_error"] is None
    # A live token is used as is: no further token request.
    before = len(server.requests)
    assert mcp_credentials.load_endpoint_auth_headers(EID) == headers
    assert len(server.requests) == before


def test_failed_refresh_keeps_the_token_and_records_the_error(server, store, monkeypatch):
    server.expires_in = 30
    _connect(server, now=datetime.datetime.now(UTC))
    old = _payload(store)
    server.refresh.clear()  # the server forgot the refresh token
    monkeypatch.setattr(mcp_credentials.db, "get_mcp_endpoint_credentials", store.get_mcp_endpoint_credentials)

    headers = mcp_credentials.load_endpoint_auth_headers(EID)

    assert headers == {"Authorization": f"Bearer {old['access_token']}"}
    error = store.rows[EID]["oauth_metadata"]["token"]["last_refresh_error"]
    assert error["code"] == "token_error" and "invalid_grant" in error["message"]


def test_forced_refresh_after_401(server, store, monkeypatch):
    _connect(server)  # a long-lived token: no proactive refresh
    old = _payload(store)
    monkeypatch.setattr(mcp_credentials.db, "get_mcp_endpoint_credentials", store.get_mcp_endpoint_credentials)

    headers = mcp_credentials.refresh_endpoint_auth_headers(EID)

    new = _payload(store)
    assert new["access_token"] != old["access_token"]
    assert headers == {"Authorization": f"Bearer {new['access_token']}"}


def test_forced_refresh_returns_none_when_nothing_changes(server, store, monkeypatch):
    monkeypatch.setattr(mcp_credentials.db, "get_mcp_endpoint_credentials", store.get_mcp_endpoint_credentials)
    assert mcp_credentials.refresh_endpoint_auth_headers(EID) is None  # auth_type none
    _connect(server)
    server.refresh.clear()
    assert mcp_credentials.refresh_endpoint_auth_headers(EID) is None  # refresh refused


def test_refresh_skipped_when_another_caller_already_refreshed(server, store):
    _connect(server)
    stale = store.get_mcp_endpoint_credentials(EID)
    mcp_oauth_service.refresh_endpoint_credential(EID, stale, force=True)
    requests = len(server.requests)
    result = mcp_oauth_service.refresh_endpoint_credential(EID, stale, force=True)
    assert len(server.requests) == requests
    assert result["last_refreshed_at"] != stale["last_refreshed_at"]


def test_lost_compare_and_set_returns_the_winner(server, store, monkeypatch):
    _connect(server)
    row = store.get_mcp_endpoint_credentials(EID)
    real_store = store.store_mcp_endpoint_oauth_tokens

    def racing_store(**kwargs):
        # Another replica writes first, so this compare-and-set loses.
        store.rows[EID]["last_refreshed_at"] = NOW + datetime.timedelta(days=1)
        return real_store(**kwargs)

    monkeypatch.setattr(mcp_oauth_service.db, "store_mcp_endpoint_oauth_tokens", racing_store)
    result = mcp_oauth_service.refresh_endpoint_credential(EID, row, force=True)
    assert result["last_refreshed_at"] == NOW + datetime.timedelta(days=1)


def test_non_oauth_credentials_pass_through_untouched(store):
    row = {"auth_type": "bearer", "last_refreshed_at": None}
    assert mcp_oauth_service.refresh_endpoint_credential(EID, row) is row
    assert mcp_oauth_service.refresh_endpoint_credential(EID, None) is None


# ===========================================================================
# Routes
# ===========================================================================

client = TestClient(app)
_AUTH = {"tenant_id": TENANT, "user_id": USER, "auth_method": "jwt"}
_ENDPOINT = {"id": EID, "tenant_id": TENANT, "name": "Acme"}


@pytest.fixture
def routes(monkeypatch, server, store):
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    monkeypatch.setattr(
        "app.mcp_catalog_routes.db.get_mcp_endpoint",
        lambda tenant_id, endpoint_id: _ENDPOINT if (tenant_id, endpoint_id) == (TENANT, EID) else None,
    )
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_routes_connect_round_trip(routes, server, store):
    res = client.post(f"/v1/mcp/acme/endpoints/{EID}/oauth/authorize", json={"redirectUri": REDIRECT})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["endpoint_id"] == EID and body["client_registration"] == "dynamic"
    redirect = server.authorize(body["authorization_url"])

    res = client.post("/v1/mcp/acme/oauth/callback", json=redirect)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["endpoint_id"] == EID
    assert out["credential"]["auth_type"] == "oauth2" and out["credential"]["configured"] is True
    assert out["credential"]["oauth_metadata"]["token"]["refreshable"] is True
    payload = _payload(store)
    assert payload["access_token"] not in res.text and payload["refresh_token"] not in res.text


def test_route_authorize_errors(routes, store, monkeypatch):
    other = "22222222-2222-2222-2222-222222222222"
    assert (
        client.post(f"/v1/mcp/acme/endpoints/{other}/oauth/authorize", json={"redirect_uri": REDIRECT}).status_code
        == 404
    )
    res = client.post(
        f"/v1/mcp/acme/endpoints/{EID}/oauth/authorize", json={"redirect_uri": "http://evil.example.com/cb"}
    )
    assert res.status_code == 422 and "invalid_redirect_uri" in res.json()["detail"]
    store.rows[EID]["oauth_metadata"] = {}
    res = client.post(f"/v1/mcp/acme/endpoints/{EID}/oauth/authorize", json={"redirect_uri": REDIRECT})
    assert res.status_code == 409 and "not_discovered" in res.json()["detail"]


def test_route_authorize_fails_closed_without_encryption(routes, monkeypatch):
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", None)
    res = client.post(f"/v1/mcp/acme/endpoints/{EID}/oauth/authorize", json={"redirect_uri": REDIRECT})
    assert res.status_code == 503


def test_route_callback_errors(routes, server):
    res = client.post("/v1/mcp/acme/oauth/callback", json={"state": "nope", "code": "x"})
    assert res.status_code == 400 and "invalid_state" in res.json()["detail"]
    body = client.post(f"/v1/mcp/acme/endpoints/{EID}/oauth/authorize", json={"redirect_uri": REDIRECT}).json()
    redirect = server.authorize(body["authorization_url"])
    server.codes.clear()  # the code is no longer valid at the server
    res = client.post("/v1/mcp/acme/oauth/callback", json=redirect)
    assert res.status_code == 502 and "token_error" in res.json()["detail"]
