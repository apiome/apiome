"""`$ref` hygiene — COA-2.8 (#7051).

* :mod:`app.openapi_ref_hygiene`: external references grouped by URL with every location; cycle
  groups with a path round each loop (self-recursion, two-node loops, nested pointers, literal
  ``example`` data ignored); the JSON Pointer diff;
* :mod:`app.project_references`: a fetch classified as ok / changed / unreachable / blocked,
  compared with the pin when pinned, else with the previous snapshot;
* the routes over an in-memory store and a stubbed fetcher: list, refresh (acceptance: a changed
  remote reference is detected and reported as a diff), pin / unpin, the tenant policy gate and the
  kill switch, the admin-only policy route.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app import project_references_routes as routes
from app.auth import validate_authentication
from app.config import settings
from app.database import db
from app.main import app
from app.openapi_ref_hygiene import MAX_DIFF_CHANGES, external_ref_groups, find_ref_cycles, json_value_diff
from app.project_references import classify_fetch, reference_view, summarize
from app.remote_ref_resolver import REASON_BLOCKED, REASON_FETCH_FAILED, FetchedDocument

_TENANT = "550e8400-e29b-41d4-a716-446655440000"
_ACTOR = "33333333-3333-3333-3333-333333333333"
_PROJECT = "11111111-1111-1111-1111-111111111111"
_REVISION = "22222222-2222-2222-2222-222222222222"
_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt", "email": "a@x.io"}
_BASE = f"/v1/projects/acme/{_PROJECT}/references"
_POLICY = "/v1/tenants/acme/governance/external-ref-policy"

_MONEY = "https://schemas.example.com/common.json"
_ERRORS = "https://errors.example.org/problem.json"

_DOC: Dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Node"}}},
                    },
                    "default": {"$ref": f"{_ERRORS}#/Problem"},
                }
            }
        }
    },
    "components": {
        "schemas": {
            "Node": {
                "type": "object",
                "properties": {
                    "price": {"$ref": f"{_MONEY}#/Money"},
                    "children": {"type": "array", "items": {"$ref": "#/components/schemas/Node"}},
                    "edge": {"$ref": "#/components/schemas/Edge"},
                },
                "example": {"$ref": "#/components/schemas/NotARef"},
            },
            "Edge": {"type": "object", "properties": {"to": {"$ref": "#/components/schemas/Node"}}},
            "Tax": {"$ref": f"{_MONEY}#/Tax"},
            "Leaf": {"type": "string"},
        }
    },
}


# ---------------------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------------------


def test_external_refs_are_grouped_by_url_with_every_location() -> None:
    groups = external_ref_groups(_DOC)
    assert [group["url"] for group in groups] == [_ERRORS, _MONEY]
    money = groups[1]
    assert sorted(loc["ref"] for loc in money["locations"]) == [f"{_MONEY}#/Money", f"{_MONEY}#/Tax"]
    assert all(loc["location"].startswith("#/components/schemas/") for loc in money["locations"])


def test_cycles_report_each_loop_once_with_a_path() -> None:
    result = find_ref_cycles(_DOC)
    assert result["total"] == 1 and result["truncated"] is False
    (cycle,) = result["cycles"]
    assert cycle["refs"] == ["#/components/schemas/Edge", "#/components/schemas/Node"]
    assert cycle["path"][0] == cycle["path"][-1] == "#/components/schemas/Edge"
    assert "#/components/schemas/Node" in cycle["path"]


def test_a_self_recursive_schema_is_a_cycle_of_one() -> None:
    doc = {
        "components": {"schemas": {"Tree": {"items": {"$ref": "#/components/schemas/Tree"}}}},
        "x": {"$ref": "#/components/schemas/Tree"},
    }
    (cycle,) = find_ref_cycles(doc)["cycles"]
    assert cycle == {"refs": ["#/components/schemas/Tree"], "path": ["#/components/schemas/Tree"] * 2}


def test_no_cycles_and_dangling_refs_are_fine() -> None:
    doc = {
        "a": {"$ref": "#/components/schemas/Missing"},
        "b": {"$ref": "#/components/schemas/Leaf"},
        "components": {"schemas": {"Leaf": {"type": "string"}}},
    }
    assert find_ref_cycles(doc) == {"cycles": [], "total": 0, "truncated": False}


def test_a_cycle_through_a_nested_pointer_is_found() -> None:
    doc = {
        "components": {
            "schemas": {
                "A": {"properties": {"b": {"$ref": "#/components/schemas/B/properties/back"}}},
                "B": {"properties": {"back": {"$ref": "#/components/schemas/A"}}},
            }
        },
        "root": {"$ref": "#/components/schemas/A"},
    }
    (cycle,) = find_ref_cycles(doc)["cycles"]
    assert cycle["refs"] == ["#/components/schemas/A", "#/components/schemas/B/properties/back"]


def test_a_long_chain_does_not_overflow() -> None:
    schemas = {f"S{i}": {"$ref": f"#/components/schemas/S{i + 1}"} for i in range(3000)}
    schemas["S3000"] = {"$ref": "#/components/schemas/S0"}
    doc = {"components": {"schemas": schemas}, "root": {"$ref": "#/components/schemas/S0"}}
    (cycle,) = find_ref_cycles(doc)["cycles"]
    assert len(cycle["refs"]) == 3001


def test_diff_reports_added_removed_and_changed_pointers() -> None:
    before = {
        "Money": {"type": "object", "required": ["amount"], "properties": {"amount": {"type": "number"}}},
        "Old": {"type": "string"},
        "list": [1, 2, 3],
    }
    after = {
        "Money": {
            "type": "object",
            "required": ["amount", "currency"],
            "properties": {"amount": {"type": "string"}, "currency": {"type": "string"}},
        },
        "list": [1, 2],
    }
    diff = json_value_diff(before, after)
    rows = {(row["pointer"], row["kind"]) for row in diff["changes"]}
    assert rows == {
        ("/Money/required/1", "added"),
        ("/Money/properties/amount/type", "changed"),
        ("/Money/properties/currency", "added"),
        ("/Old", "removed"),
        ("/list/2", "removed"),
    }
    assert diff["total"] == 5 and diff["truncated"] is False
    assert json_value_diff({"a": 1}, {"a": 1})["changes"] == []
    assert json_value_diff({"a": 1}, {"a": 1.0})["changes"][0]["kind"] == "changed"


def test_diff_is_capped_but_counts_everything() -> None:
    diff = json_value_diff({}, {f"k{i}": i for i in range(MAX_DIFF_CHANGES + 5)})
    assert len(diff["changes"]) == MAX_DIFF_CHANGES and diff["total"] == MAX_DIFF_CHANGES + 5
    assert diff["truncated"] is True


# ---------------------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------------------


def _fetched(document: Any, digest: str) -> FetchedDocument:
    return FetchedDocument(url=_MONEY, document=document, digest=digest)


def test_first_fetch_is_ok_without_a_diff() -> None:
    outcome = classify_fetch(_fetched({"a": 1}, "d1"), None)
    assert (outcome.status, outcome.digest, outcome.diff) == ("ok", "d1", None)


def test_a_new_digest_is_a_change_against_the_previous_snapshot() -> None:
    outcome = classify_fetch(_fetched({"a": 2}, "d2"), {"content_digest": "d1", "document": {"a": 1}})
    assert outcome.status == "changed"
    assert outcome.diff["against"] == "previous" and outcome.diff["from_digest"] == "d1"
    assert outcome.diff["changes"] == [{"pointer": "/a", "kind": "changed", "before": 1, "after": 2}]


def test_a_pinned_reference_is_compared_with_its_pin() -> None:
    row = {"content_digest": "d2", "document": {"a": 2}, "pinned_digest": "d1", "pinned_document": {"a": 1}}
    outcome = classify_fetch(_fetched({"a": 2}, "d2"), row)
    assert outcome.status == "changed" and outcome.diff["against"] == "pin"
    assert classify_fetch(_fetched({"a": 1}, "d1"), row).status == "ok"


def test_refusals_are_blocked_and_failures_unreachable() -> None:
    blocked = classify_fetch(FetchedDocument(url=_MONEY, reason="blocked-by-tenant-policy", detail="no"), None)
    assert (blocked.status, blocked.reason) == ("blocked", "blocked-by-tenant-policy")
    assert classify_fetch(FetchedDocument(url=_MONEY, reason=REASON_BLOCKED), None).status == "blocked"
    assert classify_fetch(FetchedDocument(url=_MONEY, reason=REASON_FETCH_FAILED), None).status == "unreachable"


def test_reference_view_and_summary() -> None:
    group = {"url": _MONEY, "locations": [{"location": "#/x", "ref": f"{_MONEY}#/Money"}]}
    fresh = reference_view(group, None)
    assert fresh["status"] == "not-fetched" and fresh["host"] == "schemas.example.com" and fresh["pinned"] is None
    pinned = reference_view(group, {"status": "ok", "content_digest": "d", "pinned_digest": "d"})
    assert pinned["pinned"] == {"digest": "d", "at": None}
    assert summarize([fresh, pinned, pinned]) == {"not-fetched": 1, "ok": 2}


# ---------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------


class _Store:
    """In-memory stand-in for :mod:`app.project_external_ref_store`."""

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}

    def list_refs(self, tenant_id, project_id):
        return {url: dict(row) for url, row in self.rows.items()}

    def record_check(
        self,
        *,
        tenant_id,
        project_id,
        url,
        status,
        actor_id,
        reason=None,
        detail=None,
        digest=None,
        document=None,
        diff=None,
    ):
        row = self.rows.setdefault(url, {"url": url})
        row.update(status=status, reason=reason, detail=detail, diff=diff, checked_by=actor_id)
        if digest is not None:
            row.update(content_digest=digest, document=document)
        return dict(row)

    def set_pin(self, *, tenant_id, project_id, url, actor_id):
        row = self.rows.get(url)
        if not row or not row.get("content_digest"):
            return None
        row.update(pinned_digest=row["content_digest"], pinned_document=row["document"])
        if row["status"] == "changed":
            row.update(status="ok", diff=None)
        return dict(row)

    def clear_pin(self, *, tenant_id, project_id, url):
        row = self.rows.get(url)
        if not row:
            return None
        row.update(pinned_digest=None, pinned_document=None)
        return dict(row)


class _Remote:
    """What each URL serves; a URL missing here fails to fetch."""

    def __init__(self) -> None:
        self.served: Dict[str, Any] = {_MONEY: {"Money": {"type": "number"}}, _ERRORS: {"Problem": {}}}
        self.fetches: List[str] = []

    def __call__(self, url: str, *, max_bytes: int, timeout: float) -> bytes:
        from app.remote_ref_resolver import _FetchError

        self.fetches.append(url)
        if url not in self.served:
            raise _FetchError(REASON_FETCH_FAILED, "connection refused")
        return json.dumps(self.served[url]).encode()


@pytest.fixture
def env(monkeypatch):
    fake = _Store()
    remote = _Remote()
    policy: Dict[str, Any] = {"repository_external_ref_policy": "inline", "repository_external_ref_allowlist": []}
    audits: List[Dict[str, Any]] = []
    admin = {"value": True}
    for name in ("list_refs", "record_check", "set_pin", "clear_pin"):
        monkeypatch.setattr(f"app.project_external_ref_store.{name}", getattr(fake, name))
    monkeypatch.setattr(routes, "enforce_permission", lambda *a, **k: _ACTOR)
    monkeypatch.setattr(
        routes,
        "load_version_source",
        lambda tenant, project, version: (
            json.loads(json.dumps(_DOC)),
            {"version_record_id": _REVISION, "version_label": "1.0.0"},
        ),
    )
    monkeypatch.setattr("app.remote_ref_resolver._http_fetch", remote)
    monkeypatch.setattr(db, "get_tenant_external_ref_policy", lambda tenant: dict(policy))

    def _set_policy(tenant, *, policy: str, allowlist=None):
        stored.update(repository_external_ref_policy=policy, repository_external_ref_allowlist=allowlist or [])
        return True

    stored = policy
    monkeypatch.setattr(db, "set_tenant_external_ref_policy", _set_policy)
    monkeypatch.setattr(db, "is_user_tenant_admin", lambda tenant, user: admin["value"])
    monkeypatch.setattr(
        db,
        "insert_workflow_audit",
        lambda t, p, v, action, outcome, actor, detail=None: audits.append({"action": action, "detail": detail}),
    )
    monkeypatch.setattr(
        db, "write_access_audit", lambda **kw: audits.append({"action": kw["action"], "detail": kw["detail"]})
    )
    monkeypatch.setattr(settings, "remote_ref_resolution_allowed", True)
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield {"store": fake, "remote": remote, "policy": policy, "audits": audits, "admin": admin}
    app.dependency_overrides.clear()


client = TestClient(app)


def _by_url(body: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {ref["url"]: ref for ref in body["references"]}


def test_list_shows_refs_cycles_and_policy_before_any_refresh(env) -> None:
    body = client.get(_BASE).json()
    refs = _by_url(body)
    assert set(refs) == {_MONEY, _ERRORS}
    assert refs[_MONEY]["status"] == "not-fetched" and len(refs[_MONEY]["locations"]) == 2
    assert body["summary"] == {"not-fetched": 2}
    assert body["cycle_total"] == 1 and body["cycles"][0]["refs"][0] == "#/components/schemas/Edge"
    assert body["policy"] == {
        "mode": "inline",
        "allowlist": [],
        "resolution_allowed": True,
        "fetches": True,
        "can_edit": True,
    }
    assert body["version_label"] == "1.0.0" and body["refreshed"] is None
    assert env["remote"].fetches == []


def test_acceptance_a_changed_remote_ref_is_reported_as_a_diff(env) -> None:
    first = client.post(f"{_BASE}/refresh", json={}).json()
    assert first["refreshed"] == 2 and _by_url(first)[_MONEY]["status"] == "ok"

    env["remote"].served[_MONEY] = {"Money": {"type": "string", "pattern": "^[0-9]+$"}}
    second = client.post(f"{_BASE}/refresh", json={}).json()
    money = _by_url(second)[_MONEY]
    assert money["status"] == "changed"
    assert money["diff"]["against"] == "previous"
    assert {(c["pointer"], c["kind"]) for c in money["diff"]["changes"]} == {
        ("/Money/type", "changed"),
        ("/Money/pattern", "added"),
    }
    assert _by_url(second)[_ERRORS]["status"] == "ok"
    changed = [a for a in env["audits"] if a["action"] == "project.external_ref.changed"]
    assert changed and changed[0]["detail"]["url"] == _MONEY and changed[0]["detail"]["changes"] == 2

    # Unpinned, the next refresh compares with the new snapshot: no change.
    assert _by_url(client.post(f"{_BASE}/refresh", json={}).json())[_MONEY]["status"] == "ok"


def test_a_pin_keeps_a_change_reported_until_re_pinned(env) -> None:
    client.post(f"{_BASE}/refresh", json={})
    pinned = client.put(f"{_BASE}/pin", json={"url": _MONEY})
    assert pinned.status_code == 200 and pinned.json()["pinned"]["digest"]

    env["remote"].served[_MONEY] = {"Money": {"type": "integer"}}
    for _ in range(2):
        money = _by_url(client.post(f"{_BASE}/refresh", json={}).json())[_MONEY]
        assert money["status"] == "changed" and money["diff"]["against"] == "pin"

    repinned = client.put(f"{_BASE}/pin", json={"url": _MONEY}).json()
    assert repinned["status"] == "ok" and repinned["diff"] is None
    unpinned = client.delete(f"{_BASE}/pin", params={"url": _MONEY})
    assert unpinned.status_code == 200 and unpinned.json()["pinned"] is None


def test_pin_refusals(env) -> None:
    never = client.put(f"{_BASE}/pin", json={"url": _MONEY})
    assert never.status_code == 409 and never.json()["detail"]["code"] == "ref-not-fetched"
    gone = client.delete(f"{_BASE}/pin", params={"url": _MONEY})
    assert gone.status_code == 404 and gone.json()["detail"]["code"] == "ref-not-found"


def test_refresh_one_url_and_refuse_an_unknown_one(env) -> None:
    body = client.post(f"{_BASE}/refresh", json={"urls": [_ERRORS]}).json()
    assert body["refreshed"] == 1 and env["remote"].fetches == [_ERRORS]
    assert _by_url(body)[_MONEY]["status"] == "not-fetched"
    unknown = client.post(f"{_BASE}/refresh", json={"urls": ["https://other.example.com/x.json"]})
    assert unknown.status_code == 422 and unknown.json()["detail"]["code"] == "unknown-reference"


def test_the_tenant_policy_and_the_kill_switch_block_fetches(env, monkeypatch) -> None:
    env["policy"].update(repository_external_ref_policy="block")
    refs = _by_url(client.post(f"{_BASE}/refresh", json={}).json())
    assert refs[_MONEY]["status"] == "blocked" and refs[_MONEY]["reason"] == "blocked-by-tenant-policy"
    assert env["remote"].fetches == []

    env["policy"].update(
        repository_external_ref_policy="proxy-fetch", repository_external_ref_allowlist=["*.example.com"]
    )
    refs = _by_url(client.post(f"{_BASE}/refresh", json={}).json())
    assert refs[_MONEY]["status"] == "ok"
    assert refs[_ERRORS]["status"] == "blocked" and refs[_ERRORS]["reason"] == "host-not-allowlisted"

    monkeypatch.setattr(settings, "remote_ref_resolution_allowed", False)
    body = client.post(f"{_BASE}/refresh", json={}).json()
    assert _by_url(body)[_MONEY]["reason"] == "resolution-disabled"
    assert body["policy"]["fetches"] is False


def test_a_failed_fetch_is_unreachable_and_keeps_the_last_snapshot(env) -> None:
    client.post(f"{_BASE}/refresh", json={})
    digest = env["store"].rows[_MONEY]["content_digest"]
    del env["remote"].served[_MONEY]
    money = _by_url(client.post(f"{_BASE}/refresh", json={}).json())[_MONEY]
    assert money["status"] == "unreachable" and money["digest"] == digest


def test_refresh_bypasses_the_shared_cache(env) -> None:
    client.post(f"{_BASE}/refresh", json={})
    client.post(f"{_BASE}/refresh", json={})
    assert env["remote"].fetches.count(_MONEY) == 2


def test_policy_get_and_admin_put(env) -> None:
    assert client.get(_POLICY).json()["mode"] == "inline"
    saved = client.put(
        _POLICY, json={"mode": "proxy-fetch", "allowlist": ["https://Schemas.Example.com/v1", "*.acme.com"]}
    )
    assert saved.status_code == 200
    assert saved.json()["allowlist"] == ["schemas.example.com", "*.acme.com"]
    audit = next(a for a in env["audits"] if a["action"] == "governance.external_ref_policy.update")
    assert audit["detail"]["before"]["mode"] == "inline" and audit["detail"]["after"]["mode"] == "proxy-fetch"


@pytest.mark.parametrize(
    "body,code",
    [
        ({"mode": "proxy-fetch", "allowlist": []}, "allowlist-required"),
        ({"mode": "inline", "allowlist": ["bad host!"]}, "invalid-allowlist"),
    ],
)
def test_policy_put_refusals(env, body, code) -> None:
    reply = client.put(_POLICY, json=body)
    assert reply.status_code == 422 and reply.json()["detail"]["code"] == code


def test_policy_put_is_admin_only(env) -> None:
    env["admin"]["value"] = False
    assert client.put(_POLICY, json={"mode": "inline", "allowlist": []}).status_code == 403
    assert client.get(_POLICY).json()["can_edit"] is False
    assert env["policy"]["repository_external_ref_policy"] == "inline"


def test_policy_rejects_an_unknown_mode(env) -> None:
    assert client.put(_POLICY, json={"mode": "everything"}).status_code == 422


def test_store_rejects_an_unknown_status() -> None:
    from app.project_external_ref_store import record_check

    with pytest.raises(ValueError):
        record_check(tenant_id=_TENANT, project_id=_PROJECT, url=_MONEY, status="weird", actor_id=None)


def test_unpinned_optional_fields_round_trip(env) -> None:
    """The stored row's optional fields reach the wire model unchanged."""
    env["store"].rows[_MONEY] = {
        "url": _MONEY,
        "status": "blocked",
        "reason": "allowlist-empty",
        "detail": "no hosts",
        "content_digest": None,
    }
    money: Optional[Dict[str, Any]] = _by_url(client.get(_BASE).json())[_MONEY]
    assert money["status"] == "blocked" and money["detail"] == "no hosts"
