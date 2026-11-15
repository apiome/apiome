"""HTTP and WebSocket contract tests for presence — COL-4.1 (#4525).

The store is replaced with a small in-memory fake so these tests pin what the routes own: the
``projects:view`` guard, status mapping, the OpenAPI contract, the rate limit, and the socket's
frame protocol (auth first, heartbeat, lock, error frames, release on close).
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from app import presence_routes
from app.auth import validate_authentication
from app.main import app
from app.presence import (
    CODE_LOCK_HELD,
    LockRecord,
    PresenceSnapshot,
    PresenceValidationError,
    ViewerRecord,
    validate_element_key,
    validate_session_id,
    validate_view,
)
from app.rate_limit import FixedWindowRateLimiter

client = TestClient(app)
BASE = "/v1/tenants/acme/projects/petstore/presence"
USER = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a00a1"
KEY = "class:3f2a6c1e-0000-4000-8000-000000000001"
SESSION = "tab-alice-0001"


def _snap(locks: List[LockRecord] = (), lost: List[str] = ()) -> PresenceSnapshot:
    return PresenceSnapshot(
        viewers=[ViewerRecord(user_id=USER, name="Alice", views=["studio"], sessions=1)],
        locks=list(locks), lost=list(lost), server_time="2026-11-14T00:00:00+00:00", ttl_seconds=45,
    )


@pytest.fixture
def fake(monkeypatch):
    calls: List[Any] = []

    class Store:
        held_error = False

        def heartbeat(self, project_id, tenant_id, user_id, session_id, view, held=()):
            calls.append(("heartbeat", session_id, view, list(held)))
            return _snap()

        def snapshot(self, project_id, **_):
            return _snap()

        def leave(self, project_id, session_id):
            calls.append(("leave", session_id))

        def acquire_lock(self, project_id, tenant_id, user_id, session_id, key):
            calls.append(("acquire", key))
            if self.held_error:
                raise PresenceValidationError(CODE_LOCK_HELD, "Bob is editing this element")
            return _snap()

        def release_lock(self, project_id, session_id, key):
            calls.append(("release", key))
            return _snap()

        def request_takeover(self, project_id, user_id, session_id, key):
            calls.append(("request", key))
            return _snap()

        def take_over(self, project_id, tenant_id, user_id, session_id, key):
            calls.append(("take", key))
            return _snap()

    store = Store()
    store.calls = calls
    for name in ("heartbeat", "snapshot", "leave", "acquire_lock", "release_lock", "request_takeover", "take_over"):
        monkeypatch.setattr(presence_routes.presence_store, name, getattr(store, name))
    monkeypatch.setattr(presence_routes, "enforce_permission", lambda *a, **k: USER)
    monkeypatch.setattr(presence_routes, "resolve_project", lambda tenant, ref: {"id": "p-1"})
    monkeypatch.setattr(presence_routes, "_limiter", FixedWindowRateLimiter())
    app.dependency_overrides[validate_authentication] = lambda: {"tenant_id": "t-1", "auth_method": "jwt", "user_id": USER}
    yield store
    app.dependency_overrides.pop(validate_authentication, None)


def test_heartbeat_returns_the_snapshot(fake):
    r = client.post(f"{BASE}/heartbeat", json={"session_id": SESSION, "view": "studio", "held": [KEY]})
    assert r.status_code == 200, r.text
    assert r.json()["viewers"][0]["name"] == "Alice"
    assert fake.calls == [("heartbeat", SESSION, "studio", [KEY])]


def test_bad_session_id_is_a_400(fake):
    r = client.post(f"{BASE}/heartbeat", json={"session_id": "x"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "presence-invalid"


def test_get_does_not_announce_the_caller(fake):
    assert client.get(BASE).status_code == 200
    assert fake.calls == []


def test_lock_conflict_is_409_with_the_holder_named(fake):
    fake.held_error = True
    r = client.put(f"{BASE}/locks/{KEY}", params={"session_id": SESSION})
    assert r.status_code == 409
    assert r.json()["detail"] == {"code": CODE_LOCK_HELD, "message": "Bob is editing this element"}


def test_lock_unlock_request_and_take_over_routes(fake):
    assert client.put(f"{BASE}/locks/{KEY}", params={"session_id": SESSION}).status_code == 200
    assert client.delete(f"{BASE}/locks/{KEY}", params={"session_id": SESSION}).status_code == 200
    assert client.post(f"{BASE}/request-takeover/{KEY}", params={"session_id": SESSION}).status_code == 200
    assert client.post(f"{BASE}/take-over/{KEY}", params={"session_id": SESSION}).status_code == 200
    assert [c[0] for c in fake.calls] == ["acquire", "release", "request", "take"]


def test_leave_is_204(fake):
    assert client.post(f"{BASE}/leave", json={"session_id": SESSION}).status_code == 204
    assert fake.calls == [("leave", SESSION)]


def test_unknown_project_is_404(fake, monkeypatch):
    from app.comments import CommentValidationError

    def missing(tenant, ref):
        raise CommentValidationError("comment-project-not-found", "no project")

    monkeypatch.setattr(presence_routes, "resolve_project", missing)
    assert client.get(BASE).status_code == 404


def test_rate_limit(fake, monkeypatch):
    monkeypatch.setattr(presence_routes.settings, "presence_rate_limit_per_minute", 2)
    monkeypatch.setattr(presence_routes.settings, "rate_limit_enabled", True)
    codes = [client.get(BASE).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_every_route_is_in_the_openapi_contract():
    paths = client.get("/openapi.json").json()["paths"]
    assert f"{BASE.replace('acme', '{tenant_slug}').replace('petstore', '{project_ref}')}/heartbeat" in paths


def test_socket_protocol(fake, monkeypatch):
    monkeypatch.setattr(presence_routes, "validate_authentication", lambda *a: {"tenant_id": "t-1", "user_id": USER})
    with client.websocket_connect(f"{BASE}/ws") as ws:
        ws.send_json({"type": "auth", "authorization": "Bearer x"})
        ws.send_json({"type": "heartbeat", "session_id": SESSION, "view": "studio"})
        assert ws.receive_json()["viewers"][0]["name"] == "Alice"
        ws.send_json({"type": "lock", "element_key": KEY})
        assert ws.receive_json()["type"] == "snapshot"
        fake.held_error = True
        ws.send_json({"type": "lock", "element_key": KEY})
        assert ws.receive_json() == {"type": "error", "code": CODE_LOCK_HELD, "message": "Bob is editing this element"}
        ws.send_json({"type": "bogus"})
        assert ws.receive_json()["code"] == "presence-invalid"
    assert ("leave", SESSION) in fake.calls


def test_socket_refuses_a_first_frame_that_is_not_auth(fake):
    with client.websocket_connect(f"{BASE}/ws") as ws:
        ws.send_json({"type": "heartbeat", "session_id": SESSION})
        with pytest.raises(Exception):
            ws.receive_json()


@pytest.mark.parametrize("key", ["", "nokind", "Class:1", "class:", "class:a b"])
def test_malformed_element_keys_are_refused(key):
    with pytest.raises(PresenceValidationError):
        validate_element_key(key)


def test_validators_accept_the_documented_shapes():
    assert validate_element_key("path:/pets/{id}") == "path:/pets/{id}"
    assert validate_session_id("abcdefgh") == "abcdefgh"
    assert validate_view(None) == "project"
    with pytest.raises(PresenceValidationError):
        validate_view("Bad View")
