"""Authentication and permission resolution in one cached query, against Postgres — DBP-1.3 (#7186).

What only the real schema can prove:

* the single authorization statement answers exactly what the per-table lookups it replaced
  answered — tenant access, administrator flag and every ``resource:action`` — for administrators,
  default editors, role holders, suspended and pending members, members whose role grants nothing,
  and strangers (the old lookups are kept below as the reference);
* the folded ``versions:edit`` probe agrees with the five probes it replaced;
* a JWT request with a permission check runs one authorization statement cold and none warm;
* a role or membership change made through this process applies on the next request, and one made
  elsewhere applies once the TTL runs out;
* a repeated API-key request skips bcrypt, and a key deleted, disabled, expired or regenerated
  elsewhere is refused on its next request.

Runs inside one always-rolled-back transaction. Skipped when no database is reachable.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterator, Set, Tuple
from unittest.mock import MagicMock, patch

import bcrypt
import jwt
import psycopg2
import pytest
from fastapi import HTTPException
from psycopg2.extras import RealDictCursor

from app import auth as auth_module
from app import authz_cache
from app import database as database_module
from app.config import settings
from app.database import Database
from app.permissions import ACTIONS, RESOURCES, Action, Resource, enforce_permission, has_permission
from app.statement_stats import CountingDictCursor, capture
from tests.test_usage_index_db import _NoCommitConnection

pytestmark = pytest.mark.requires_db


# ───────────────────────────── fixtures ─────────────────────────────


@pytest.fixture
def tx(monkeypatch) -> Iterator[Tuple[Database, Any]]:
    """A :class:`Database` (also behind ``app.auth``) and a raw cursor over one rolled-back transaction."""
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute("SELECT to_regclass('apiome.tenant_user_roles') AS t")
        if not probe.fetchone()["t"]:
            conn.close()
            pytest.skip("RBAC tables not applied")
    conn.cursor_factory = CountingDictCursor
    db = Database()
    db.connection = _NoCommitConnection(conn)
    monkeypatch.setattr(auth_module, "db", db)
    try:
        with conn.cursor() as cursor:
            yield db, cursor
    finally:
        conn.rollback()
        conn.close()


def _user(cursor: Any) -> str:
    email = f"{uuid.uuid4().hex[:10]}@authz.example"
    cursor.execute(
        "INSERT INTO apiome.users (name, email, password, verified, enabled) "
        "VALUES (%s, %s, '', true, true) RETURNING id::text AS id",
        (email.split("@")[0], email),
    )
    return cursor.fetchone()["id"]


def _role(cursor: Any, tenant_id: str, slug: str, grants: Tuple[Tuple[str, str], ...]) -> str:
    cursor.execute(
        "INSERT INTO apiome.roles (tenant_id, slug, name) VALUES (%s::uuid, %s, %s) RETURNING id::text AS id",
        (tenant_id, slug, slug.title()),
    )
    role_id = cursor.fetchone()["id"]
    for resource, action in grants:
        cursor.execute(
            "INSERT INTO apiome.role_permissions (role_id, resource, action) VALUES (%s::uuid, %s, %s)",
            (role_id, resource, action),
        )
    return role_id


def _role_id(cursor: Any, tenant_id: str, slug: str) -> str:
    cursor.execute(
        "SELECT id::text AS id FROM apiome.roles WHERE tenant_id = %s::uuid AND slug = %s", (tenant_id, slug)
    )
    return cursor.fetchone()["id"]


def _member(cursor: Any, tenant_id: str, user_id: str, *, status: str = "active", role_id: str | None = None) -> None:
    cursor.execute(
        "INSERT INTO apiome.tenant_users (tenant_id, user_id, status) VALUES (%s::uuid, %s::uuid, %s)",
        (tenant_id, user_id, status),
    )
    if role_id:
        cursor.execute(
            "INSERT INTO apiome.tenant_user_roles (tenant_id, user_id, role_id) VALUES (%s::uuid, %s::uuid, %s::uuid)",
            (tenant_id, user_id, role_id),
        )


@pytest.fixture
def world(tx) -> Dict[str, Any]:
    """A tenant with one user per access shape, and its built-in roles plus two custom ones."""
    db, cursor = tx
    suffix = uuid.uuid4().hex[:10]
    cursor.execute(
        "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id, slug",
        (f"authz {suffix}", f"authz-{suffix}"),
    )
    tenant = dict(cursor.fetchone())
    cursor.execute("SELECT apiome.seed_builtin_roles(%s::uuid)", (tenant["id"],))
    tid = tenant["id"]
    empty_role = _role(cursor, tid, f"empty-{suffix}", ())
    versions_role = _role(cursor, tid, f"versions-{suffix}", (("versions", "edit"), ("projects", "view")))
    users = {name: _user(cursor) for name in (
        "admin", "admin_and_viewer", "editor_default", "viewer", "suspended_with_role",
        "suspended_no_role", "pending_no_role", "empty_role", "versions_role", "stranger",
    )}
    cursor.execute(
        "INSERT INTO apiome.tenant_administrators (tenant_id, user_id) VALUES (%s::uuid, %s::uuid), (%s::uuid, %s::uuid)",
        (tid, users["admin"], tid, users["admin_and_viewer"]),
    )
    viewer = _role_id(cursor, tid, "viewer")
    editor = _role_id(cursor, tid, "editor")
    _member(cursor, tid, users["admin_and_viewer"], role_id=viewer)
    _member(cursor, tid, users["editor_default"])
    _member(cursor, tid, users["viewer"], role_id=viewer)
    _member(cursor, tid, users["suspended_with_role"], status="suspended", role_id=editor)
    _member(cursor, tid, users["suspended_no_role"], status="suspended")
    _member(cursor, tid, users["pending_no_role"], status="pending")
    _member(cursor, tid, users["empty_role"], role_id=empty_role)
    _member(cursor, tid, users["versions_role"], role_id=versions_role)
    return {"db": db, "cursor": cursor, "tenant": tenant, "users": users}


# ───────────────────────────── the lookups this ticket replaced ─────────────────────────────


def _ref_is_admin(cursor: Any, tenant_id: str, user_id: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM apiome.tenant_administrators WHERE tenant_id = %s::uuid AND user_id = %s::uuid LIMIT 1",
        (tenant_id, user_id),
    )
    return cursor.fetchone() is not None


def _ref_has_access(cursor: Any, tenant_id: str, user_id: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM apiome.tenant_users WHERE user_id = %s::uuid AND tenant_id = %s::uuid "
        "AND status <> 'suspended' LIMIT 1",
        (user_id, tenant_id),
    )
    return cursor.fetchone() is not None or _ref_is_admin(cursor, tenant_id, user_id)


def _ref_effective(cursor: Any, tenant_id: str, user_id: str) -> Set[str]:
    cursor.execute(
        "SELECT rp.resource, rp.action FROM apiome.tenant_user_roles tur "
        "JOIN apiome.role_permissions rp ON rp.role_id = tur.role_id "
        "WHERE tur.tenant_id = %s::uuid AND tur.user_id = %s::uuid",
        (tenant_id, user_id),
    )
    rows = cursor.fetchall()
    if rows:
        return {f"{r['resource']}:{r['action']}" for r in rows}
    cursor.execute(
        "SELECT 1 FROM apiome.tenant_users WHERE tenant_id = %s::uuid AND user_id = %s::uuid "
        "AND status <> 'suspended' LIMIT 1",
        (tenant_id, user_id),
    )
    if not cursor.fetchone():
        return set()
    cursor.execute(
        "SELECT rp.resource, rp.action FROM apiome.roles r JOIN apiome.role_permissions rp ON rp.role_id = r.id "
        "WHERE r.tenant_id = %s::uuid AND r.slug = 'editor'",
        (tenant_id,),
    )
    return {f"{r['resource']}:{r['action']}" for r in cursor.fetchall()}


def _ref_can_edit_versions(cursor: Any, tenant_id: str, user_id: str) -> bool:
    if _ref_is_admin(cursor, tenant_id, user_id):
        return True
    cursor.execute(
        "SELECT 1 FROM apiome.tenant_user_roles tur JOIN apiome.role_permissions rp ON rp.role_id = tur.role_id "
        "WHERE tur.tenant_id = %s::uuid AND tur.user_id = %s::uuid AND rp.resource = 'versions' "
        "AND rp.action = 'edit' LIMIT 1",
        (tenant_id, user_id),
    )
    if cursor.fetchone():
        return True
    cursor.execute(
        "SELECT 1 FROM apiome.tenant_user_roles WHERE tenant_id = %s::uuid AND user_id = %s::uuid LIMIT 1",
        (tenant_id, user_id),
    )
    if cursor.fetchone():
        return False
    cursor.execute(
        "SELECT 1 FROM apiome.tenant_users WHERE tenant_id = %s::uuid AND user_id = %s::uuid "
        "AND status <> 'suspended' LIMIT 1",
        (tenant_id, user_id),
    )
    if not cursor.fetchone():
        return False
    cursor.execute(
        "SELECT 1 FROM apiome.roles r JOIN apiome.role_permissions rp ON rp.role_id = r.id "
        "WHERE r.tenant_id = %s::uuid AND r.slug = 'editor' AND rp.resource = 'versions' AND rp.action = 'edit' LIMIT 1",
        (tenant_id,),
    )
    return cursor.fetchone() is not None


# ───────────────────────────── helpers ─────────────────────────────


def _bearer(user_id: str) -> str:
    token = jwt.encode({"user_id": user_id, "sub": user_id}, settings.effective_jwt_secret, algorithm=settings.jwt_algorithm)
    return f"Bearer {token}"


def _request(path: str = "/v1/projects/x") -> Any:
    req = MagicMock()
    req.method = "POST"
    req.url.path = path
    return req


def _authenticate(world: Dict[str, Any], user: str) -> Dict[str, Any]:
    return auth_module.validate_authentication(
        _request(), world["tenant"]["slug"], authorization=_bearer(world["users"][user])
    )


# ───────────────────────────── same answers as before ─────────────────────────────


@pytest.mark.parametrize(
    "user",
    ["admin", "admin_and_viewer", "editor_default", "viewer", "suspended_with_role", "suspended_no_role",
     "pending_no_role", "empty_role", "versions_role", "stranger"],
)
def test_the_one_statement_answers_what_the_per_table_lookups_answered(world, user) -> None:
    db, cursor, tid = world["db"], world["cursor"], world["tenant"]["id"]
    uid = world["users"][user]

    ctx = db.get_authorization_context(uid, tenant_slug=world["tenant"]["slug"])

    assert ctx is not None and ctx.tenant_id == tid
    assert ctx.is_admin is _ref_is_admin(cursor, tid, uid)
    assert ctx.has_tenant_access is _ref_has_access(cursor, tid, uid)
    assert set(ctx.permissions) == _ref_effective(cursor, tid, uid)
    assert db.get_effective_permissions(tid, uid) == _ref_effective(cursor, tid, uid)
    assert db.is_user_tenant_admin(tid, uid) is _ref_is_admin(cursor, tid, uid)
    reference = _ref_effective(cursor, tid, uid)
    for resource in sorted(RESOURCES):
        for action in sorted(ACTIONS):
            expected = _ref_is_admin(cursor, tid, uid) or f"{resource}:{action}" in reference
            assert db.user_has_permission(tid, uid, resource, action) is expected, (user, resource, action)


@pytest.mark.parametrize(
    "user",
    ["admin", "admin_and_viewer", "editor_default", "viewer", "suspended_with_role", "suspended_no_role",
     "pending_no_role", "empty_role", "versions_role", "stranger"],
)
def test_the_folded_edit_probe_agrees_with_the_five_it_replaced(world, user) -> None:
    db, cursor, tid = world["db"], world["cursor"], world["tenant"]["id"]
    uid = world["users"][user]

    with capture() as stats:
        allowed = db._cursor_actor_can_edit_versions(cursor, tid, uid)

    assert allowed is _ref_can_edit_versions(cursor, tid, uid)
    assert stats.count == 1


def test_the_edit_probe_refuses_a_missing_or_malformed_actor_without_a_statement(world) -> None:
    db, cursor, tid = world["db"], world["cursor"], world["tenant"]["id"]
    with capture() as stats:
        assert db._cursor_actor_can_edit_versions(cursor, tid, None) is False
        assert db._cursor_actor_can_edit_versions(cursor, tid, "not-a-uuid") is False
    assert stats.count == 0


def test_a_deleted_tenant_is_not_found_by_slug_but_its_administrators_still_resolve_by_id(world) -> None:
    db, cursor, tenant = world["db"], world["cursor"], world["tenant"]
    cursor.execute("UPDATE apiome.tenants SET deleted_at = now() WHERE id = %s::uuid", (tenant["id"],))
    admin = world["users"]["admin"]

    by_id = db.get_authorization_context(admin, tenant_id=tenant["id"])
    assert by_id is not None and by_id.tenant_active is False and by_id.is_admin
    # Cached under the id only, so the slug still misses — as get_active_tenant_auth_row did.
    assert db.get_authorization_context(admin, tenant_slug=tenant["slug"]) is None
    assert db.is_user_tenant_admin(tenant["id"], admin) is True
    with pytest.raises(HTTPException) as exc:
        _authenticate(world, "admin")
    assert exc.value.status_code == 404


def test_authentication_keeps_its_404_and_403(world) -> None:
    with pytest.raises(HTTPException) as missing:
        auth_module.validate_authentication(
            _request(), "no-such-tenant", authorization=_bearer(world["users"]["admin"])
        )
    assert missing.value.status_code == 404
    for refused in ("stranger", "suspended_no_role", "suspended_with_role"):
        with pytest.raises(HTTPException) as exc:
            _authenticate(world, refused)
        assert exc.value.status_code == 403, refused
    for allowed in ("admin", "editor_default", "pending_no_role", "viewer"):
        assert _authenticate(world, allowed)["tenant_id"] == world["tenant"]["id"]


# ───────────────────────────── statement counts ─────────────────────────────


def test_a_jwt_request_with_a_permission_check_runs_one_statement_cold_and_none_warm(world) -> None:
    db = world["db"]
    with capture() as cold:
        auth = _authenticate(world, "editor_default")
        enforce_permission(db, auth, Resource.PROJECTS, Action.CREATE)
        has_permission(db, auth, Resource.MEMBERS, Action.EDIT)
        db.is_user_tenant_admin(auth["tenant_id"], auth["user_id"])
    assert cold.count == 1, cold.statements

    with capture() as warm:
        auth = _authenticate(world, "editor_default")
        enforce_permission(db, auth, Resource.PROJECTS, Action.CREATE)
    assert warm.count == 0


def test_with_the_process_cache_off_a_request_still_resolves_once(world, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_cache_ttl_seconds", 0)
    db = world["db"]
    for _ in range(2):
        memo, token = authz_cache.begin_request()
        try:
            with capture() as stats:
                auth = _authenticate(world, "viewer")
                assert has_permission(db, auth, Resource.PROJECTS, Action.VIEW)
                assert not has_permission(db, auth, Resource.PROJECTS, Action.CREATE)
            assert stats.count == 1
        finally:
            authz_cache.end_request(memo, token)


# ───────────────────────────── changes take effect ─────────────────────────────


def test_a_change_made_through_this_process_applies_on_the_next_request(world) -> None:
    db, tid = world["db"], world["tenant"]["id"]
    uid = world["users"]["editor_default"]
    auth = _authenticate(world, "editor_default")
    assert has_permission(db, auth, Resource.PROJECTS, Action.CREATE)

    db.assign_member_role(tid, uid, _role_id(world["cursor"], tid, "viewer"))
    assert not has_permission(db, _authenticate(world, "editor_default"), Resource.PROJECTS, Action.CREATE)

    db.set_member_status(tid, uid, "suspended")
    with pytest.raises(HTTPException) as exc:
        _authenticate(world, "editor_default")
    assert exc.value.status_code == 403

    db.set_member_status(tid, uid, "active")
    assert _authenticate(world, "editor_default")["tenant_id"] == tid

    db.remove_member(tid, uid)
    with pytest.raises(HTTPException):
        _authenticate(world, "editor_default")


def test_a_role_grid_change_applies_to_every_holder(world) -> None:
    db, cursor, tid = world["db"], world["cursor"], world["tenant"]["id"]
    auth = _authenticate(world, "viewer")
    assert not has_permission(db, auth, Resource.PROJECTS, Action.CREATE)

    db.set_role_permissions(_role_id(cursor, tid, "viewer"), [("projects", "view"), ("projects", "create")])

    assert has_permission(db, _authenticate(world, "viewer"), Resource.PROJECTS, Action.CREATE)


def test_a_change_made_elsewhere_applies_once_the_ttl_runs_out(world, monkeypatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(authz_cache._authz, "_clock", lambda: clock[0])
    monkeypatch.setattr(settings, "auth_cache_ttl_seconds", 30)
    cursor, tid = world["cursor"], world["tenant"]["id"]
    _authenticate(world, "editor_default")

    # The web app suspends the member directly in the database: this process is not told.
    cursor.execute(
        "UPDATE apiome.tenant_users SET status = 'suspended' WHERE tenant_id = %s::uuid AND user_id = %s::uuid",
        (tid, world["users"]["editor_default"]),
    )
    clock[0] += 29
    assert _authenticate(world, "editor_default")["tenant_id"] == tid
    clock[0] += 2
    with pytest.raises(HTTPException) as exc:
        _authenticate(world, "editor_default")
    assert exc.value.status_code == 403


# ───────────────────────────── API keys ─────────────────────────────


@pytest.fixture
def api_key(world) -> Dict[str, Any]:
    """A workspace key on the world's tenant, hashed at bcrypt's cheapest cost to keep the test fast."""
    cursor = world["cursor"]
    secret = "sk_" + uuid.uuid4().hex + uuid.uuid4().hex
    key_hash = bcrypt.hashpw(secret.encode(), bcrypt.gensalt(rounds=4)).decode()
    cursor.execute(
        """
        INSERT INTO apiome.api_keys (tenant_id, name, key_hash, key_prefix, created_by_user_id)
        VALUES (%s::uuid, %s, %s, %s, %s::uuid) RETURNING id::text AS id
        """,
        (world["tenant"]["id"], f"k-{uuid.uuid4().hex[:8]}", key_hash, secret[:12] + "...", world["users"]["admin"]),
    )
    return {"secret": secret, "id": cursor.fetchone()["id"], "world": world}


def test_a_repeated_api_key_request_skips_bcrypt_and_the_last_used_write(api_key) -> None:
    db = api_key["world"]["db"]
    with patch.object(database_module.bcrypt, "checkpw", wraps=bcrypt.checkpw) as checkpw:
        first = db.validate_api_key(api_key["secret"])
        with capture() as warm:
            second = db.validate_api_key(api_key["secret"])
    assert checkpw.call_count == 1
    assert first["id"] == second["id"] and second["tenant_slug"] == api_key["world"]["tenant"]["slug"]
    assert second["scopes"] == ["*"]
    # The cached path re-reads the key's row by id and nothing else.
    assert warm.count == 1


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE apiome.api_keys SET deleted_at = now() WHERE id = %(id)s::uuid",
        "UPDATE apiome.api_keys SET enabled = false WHERE id = %(id)s::uuid",
        "UPDATE apiome.api_keys SET expires_at = now() - interval '1 second' WHERE id = %(id)s::uuid",
        "UPDATE apiome.api_keys SET key_hash = 'regenerated-' || id::text WHERE id = %(id)s::uuid",
        "UPDATE apiome.tenants SET enabled = false WHERE id = (SELECT tenant_id FROM apiome.api_keys WHERE id = %(id)s::uuid)",
    ],
    ids=["deleted", "disabled", "expired", "regenerated", "tenant-disabled"],
)
def test_a_key_revoked_elsewhere_is_refused_on_its_next_request(api_key, change) -> None:
    db, cursor = api_key["world"]["db"], api_key["world"]["cursor"]
    assert db.validate_api_key(api_key["secret"]) is not None

    cursor.execute(change, {"id": api_key["id"]})

    assert db.validate_api_key(api_key["secret"]) is None
    assert authz_cache.get_api_key(api_key["secret"]) is None


def test_a_wrong_secret_with_the_same_prefix_is_never_served_from_the_cache(api_key) -> None:
    db = api_key["world"]["db"]
    assert db.validate_api_key(api_key["secret"]) is not None
    forged = api_key["secret"][:12] + "0" * (len(api_key["secret"]) - 12)
    assert db.validate_api_key(forged) is None


def test_with_the_key_cache_off_every_request_verifies(api_key, monkeypatch) -> None:
    monkeypatch.setattr(settings, "api_key_cache_ttl_seconds", 0)
    db = api_key["world"]["db"]
    with patch.object(database_module.bcrypt, "checkpw", wraps=bcrypt.checkpw) as checkpw:
        db.validate_api_key(api_key["secret"])
        db.validate_api_key(api_key["secret"])
    assert checkpw.call_count == 2


def test_an_mcp_key_skips_bcrypt_when_repeated_and_is_refused_once_revoked(world) -> None:
    db, cursor, tid = world["db"], world["cursor"], world["tenant"]["id"]
    _meta, secret = db.create_mcp_api_key(tid, label="registry reader")
    with patch.object(database_module.bcrypt, "checkpw", wraps=bcrypt.checkpw) as checkpw:
        assert db.resolve_mcp_api_key_tenant_id(secret) == tid
        assert db.resolve_mcp_api_key_tenant_id(secret) == tid
    assert checkpw.call_count == 1

    # Revoked straight in the database (another instance): refused on the next call.
    cursor.execute("UPDATE apiome.mcp_api_keys SET revoked_at = now() WHERE tenant_id = %s::uuid", (tid,))
    assert db.resolve_mcp_api_key_tenant_id(secret) is None
