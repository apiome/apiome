"""Consumer-tagged mock capture against a live Postgres — PFX-9.1 (#7319).

What only the real schema (apiome-db V461) and the real SQL prove:

* retention defaults to 7 days, saves per workspace with an audit row, and the database refuses a
  value outside 1–30;
* sessions and calls are read back per workspace only: another tenant's session is a 404 and never
  listed, and a call is checked against its tenant as well as its session;
* an expired session or call is never shown, even before the sweeper deletes it;
* deleting a session deletes its calls and is audited;
* a capture URL stores only its token's digest, names a version of the caller's own workspace, lists
  as live / revoked / expired, and is revoked once (audited) — never across workspaces;
* the HTTP routes answer the same, and refuse a bad consumer name with a reason.

Runs inside one always-rolled-back transaction. Skipped when no database is reachable or V461 is
not applied.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Iterator
from unittest.mock import patch

import psycopg2
import pytest

from app.consumer_contract_store import ConsumerActor
from app.pact_capture import link_token_hash
from app.pact_capture_store import (
    CaptureNotFoundError,
    create_link,
    delete_session,
    list_calls,
    list_links,
    list_sessions,
    read_session,
    read_settings,
    revoke_link,
    save_retention,
)
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack

pytestmark = pytest.mark.requires_db

ACTOR = ConsumerActor(user_id=None, label="ada@example.com")


@pytest.fixture
def env(stack: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    stack["cursor"].execute("SELECT to_regclass('apiome.mock_consumer_capture_session') AS t")
    if not stack["cursor"].fetchone()["t"]:
        pytest.skip("V461 not applied")
    for which in ("seed", "other"):
        stack[which]["version"] = _version(stack, which)
        stack["cursor"].execute(
            "SELECT p.slug AS project, t.slug AS tenant FROM apiome.projects p "
            "JOIN apiome.tenants t ON t.id = p.tenant_id WHERE p.id = %s::uuid",
            (stack[which]["project"],),
        )
        stack[which].update({f"{key}_slug": value for key, value in stack["cursor"].fetchone().items()})
    with (
        patch("app.pact_capture_routes.db", stack["db"]),
        patch("app.pact_capture_routes.enforce_permission", return_value=None),
        patch("app.pact_capture_routes.has_permission", return_value=True),
    ):
        yield stack


def _version(env: Dict[str, Any], which: str) -> str:
    cursor = env["cursor"]
    cursor.execute("SELECT id::text AS id FROM apiome.users LIMIT 1")
    user = cursor.fetchone()["id"]
    cursor.execute(
        """INSERT INTO apiome.versions (project_id, creator_id, version_id)
           VALUES (%s::uuid, %s::uuid, '2.7.0') RETURNING id::text AS id""",
        (env[which]["project"], user),
    )
    return cursor.fetchone()["id"]


def _session(env: Dict[str, Any], which: str = "seed", *, consumer: str = "orders-ui", expired: bool = False) -> str:
    """A session the way the mock runtime writes one."""
    cursor = env["cursor"]
    expires = "now() - interval '1 minute'" if expired else "now() + interval '7 days'"
    cursor.execute(
        f"""INSERT INTO apiome.mock_consumer_capture_session
              (tenant_id, version_id, project_slug, version_label, consumer, consumer_version,
               first_call_at, last_call_at, call_count, refused_count, refused, expires_at)
            VALUES (%s::uuid, %s::uuid, %s, '2.7.0', %s, '3.4.0', now(), now(), 2, 1,
                    '{{"session-full": 1}}'::jsonb, {expires})
            RETURNING id::text AS id""",
        (env[which]["tenant"], env[which]["version"], env[which]["project_slug"], consumer),
    )
    return cursor.fetchone()["id"]


def _call(
    env: Dict[str, Any], session: str, which: str = "seed", *, expired: bool = False, path: str = "/invoices/42"
) -> None:
    expires = "now() - interval '1 minute'" if expired else "now() + interval '7 days'"
    env["cursor"].execute(
        f"""INSERT INTO apiome.mock_consumer_capture_call
              (session_id, tenant_id, captured_at, via, method, path, path_template, operation_key,
               status, origin, request, response, redactions, redaction_count, expires_at)
            VALUES (%s::uuid, %s::uuid, now(), 'header', 'GET', %s, '/invoices/{{id}}',
                    'GET /invoices/{{id}}', 200, 'spec', %s::jsonb, %s::jsonb, '[]'::jsonb, 0, {expires})""",
        (
            session,
            env[which]["tenant"],
            path,
            json.dumps({"method": "GET", "path": path, "query": [], "headers": {}, "body": None}),
            json.dumps({"status": 200, "headers": {}, "body": {"id": 42}}),
        ),
    )


def _audits(env: Dict[str, Any], action: str) -> int:
    env["cursor"].execute(
        "SELECT count(*) AS n FROM apiome.access_audit WHERE tenant_id = %s::uuid AND action = %s",
        (env["seed"]["tenant"], action),
    )
    return int(env["cursor"].fetchone()["n"])


# ---------------------------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------------------------


def test_retention_defaults_saves_per_workspace_and_is_audited(env: Dict[str, Any]) -> None:
    db, seed, other = env["db"], env["seed"]["tenant"], env["other"]["tenant"]
    assert read_settings(db.execute_query, seed)["retention_days"] == 7
    assert read_settings(db.execute_query, seed)["configured"] is False
    saved = save_retention(db, seed, 14, actor=ACTOR)
    assert saved["retention_days"] == 14 and saved["configured"] is True
    assert saved["updated_by_label"] == "ada@example.com"
    assert read_settings(db.execute_query, other)["retention_days"] == 7
    assert _audits(env, "pacts.capture.settings") == 1


def test_the_database_refuses_retention_outside_its_bounds(env: Dict[str, Any]) -> None:
    cursor = env["cursor"]
    cursor.execute("SAVEPOINT bounds")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cursor.execute(
            "INSERT INTO apiome.mock_consumer_capture_settings (tenant_id, retention_days) VALUES (%s::uuid, 31)",
            (env["seed"]["tenant"],),
        )
    cursor.execute("ROLLBACK TO SAVEPOINT bounds")


# ---------------------------------------------------------------------------------------------
# Sessions and calls
# ---------------------------------------------------------------------------------------------


def test_sessions_and_calls_are_read_per_workspace(env: Dict[str, Any]) -> None:
    db, seed, other = env["db"], env["seed"]["tenant"], env["other"]["tenant"]
    mine = _session(env)
    _call(env, mine, path="/invoices/42")
    _call(env, mine, path="/invoices/43")
    theirs = _session(env, "other")
    _call(env, theirs, "other")

    listed = list_sessions(db.execute_query, seed, limit=10)
    assert [row["id"] for row in listed] == [mine]
    assert listed[0]["refused"] == {"session-full": 1}
    assert listed[0]["project"] == env["seed"]["project_slug"]
    assert [row["path"] for row in list_calls(db.execute_query, seed, mine, limit=10)] == [
        "/invoices/42",
        "/invoices/43",
    ]

    with pytest.raises(CaptureNotFoundError) as refused:
        read_session(db.execute_query, seed, theirs)
    assert refused.value.code == "capture-session-not-found"
    # A call is checked against its tenant too, not only its session.
    assert list_calls(db.execute_query, seed, theirs, limit=10) == []
    assert [row["id"] for row in list_sessions(db.execute_query, other, limit=10)] == [theirs]


def test_filters_and_paging(env: Dict[str, Any]) -> None:
    db, seed = env["db"], env["seed"]["tenant"]
    a = _session(env, consumer="a")
    b = _session(env, consumer="b")
    assert [row["id"] for row in list_sessions(db.execute_query, seed, consumer="b", limit=10)] == [b]
    assert list_sessions(db.execute_query, seed, project="nope", limit=10) == []
    first = list_sessions(db.execute_query, seed, limit=1)
    assert len(first) == 1
    from app.pact_capture_store import SESSIONS_ORDER

    rest = list_sessions(
        db.execute_query, seed, limit=10, cursor=SESSIONS_ORDER.decode(SESSIONS_ORDER.cursor_of(first[0]))
    )
    assert {first[0]["id"], *(row["id"] for row in rest)} == {a, b}


def test_expired_captures_are_never_shown(env: Dict[str, Any]) -> None:
    db, seed = env["db"], env["seed"]["tenant"]
    gone = _session(env, consumer="old", expired=True)
    live = _session(env)
    _call(env, live, path="/kept")
    _call(env, live, expired=True, path="/expired")
    assert [row["id"] for row in list_sessions(db.execute_query, seed, limit=10)] == [live]
    with pytest.raises(CaptureNotFoundError) as refused:
        read_session(db.execute_query, seed, gone)
    assert "kept 7 days" in str(refused.value)
    assert [row["path"] for row in list_calls(db.execute_query, seed, live, limit=10)] == ["/kept"]


def test_deleting_a_session_deletes_its_calls_and_is_audited(env: Dict[str, Any]) -> None:
    db, cursor, seed = env["db"], env["cursor"], env["seed"]["tenant"]
    session = _session(env)
    _call(env, session)
    theirs = _session(env, "other")
    delete_session(db, seed, session, actor=ACTOR)
    cursor.execute(
        "SELECT count(*) AS n FROM apiome.mock_consumer_capture_call WHERE session_id = %s::uuid", (session,)
    )
    assert cursor.fetchone()["n"] == 0
    assert _audits(env, "pacts.capture.session.delete") == 1
    with pytest.raises(CaptureNotFoundError):
        delete_session(db, seed, theirs, actor=ACTOR)
    cursor.execute("SELECT count(*) AS n FROM apiome.mock_consumer_capture_session WHERE id = %s::uuid", (theirs,))
    assert cursor.fetchone()["n"] == 1


# ---------------------------------------------------------------------------------------------
# Capture URLs
# ---------------------------------------------------------------------------------------------


def test_a_link_stores_only_its_digest_and_is_revoked_once(env: Dict[str, Any]) -> None:
    db, cursor, seed = env["db"], env["cursor"], env["seed"]["tenant"]
    created = create_link(
        db,
        seed,
        project=env["seed"]["project_slug"],
        version="2.7.0",
        consumer="Orders UI",
        consumer_version="3.4.0",
        expires_in_days=7,
        actor=ACTOR,
    )
    token = created["token"]
    assert created["state"] == "live"
    assert created["path"] == f"/{env['seed']['tenant_slug']}/{env['seed']['project_slug']}/2.7.0/~capture/{token}"
    assert created["url"].endswith(created["path"])
    cursor.execute("SELECT * FROM apiome.mock_consumer_capture_link WHERE id = %s::uuid", (created["id"],))
    row = cursor.fetchone()
    assert row["token_hash"] == link_token_hash(token)
    assert token not in json.dumps({k: str(v) for k, v in row.items()})
    assert _audits(env, "pacts.capture.link.create") == 1
    cursor.execute(
        "SELECT detail::text AS d FROM apiome.access_audit "
        "WHERE tenant_id = %s::uuid AND action = 'pacts.capture.link.create'",
        (seed,),
    )
    assert token not in cursor.fetchone()["d"]

    listed = list_links(db.execute_query, seed, limit=10)
    assert [(link["id"], link["state"]) for link in listed] == [(created["id"], "live")]
    assert "token" not in listed[0]
    assert list_links(db.execute_query, env["other"]["tenant"], limit=10) == []

    with pytest.raises(CaptureNotFoundError):
        revoke_link(db, env["other"]["tenant"], created["id"], actor=ACTOR)
    assert revoke_link(db, seed, created["id"], actor=ACTOR)["state"] == "revoked"
    assert revoke_link(db, seed, created["id"], actor=ACTOR)["state"] == "revoked"
    assert _audits(env, "pacts.capture.link.revoke") == 1


def test_a_link_names_a_version_of_the_callers_own_workspace(env: Dict[str, Any]) -> None:
    with pytest.raises(CaptureNotFoundError) as refused:
        create_link(
            env["db"],
            env["seed"]["tenant"],
            project=env["other"]["project_slug"],
            version="2.7.0",
            consumer="Orders UI",
            consumer_version="3.4.0",
            expires_in_days=7,
            actor=ACTOR,
        )
    assert refused.value.code == "capture-version-not-found"


def test_an_expired_link_lists_as_expired(env: Dict[str, Any]) -> None:
    db, cursor, seed = env["db"], env["cursor"], env["seed"]["tenant"]
    cursor.execute(
        """INSERT INTO apiome.mock_consumer_capture_link
             (tenant_id, version_id, consumer, consumer_version, token_hash, token_prefix, expires_at)
           VALUES (%s::uuid, %s::uuid, 'Orders UI', '3.4.0', %s, 'mcap_abcd', now() - interval '1 day')""",
        (seed, env["seed"]["version"], uuid.uuid4().hex * 2),
    )
    assert [link["state"] for link in list_links(db.execute_query, seed, limit=10)] == ["expired"]


# ---------------------------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------------------------


def test_the_routes_read_and_refuse_as_the_store_does(env: Dict[str, Any]) -> None:
    client = env["client"]
    session = _session(env)
    _call(env, session)
    base = "/v1/tenants/t/pact-captures"

    listed = client.get(f"{base}/sessions")
    assert listed.status_code == 200, listed.text
    assert [s["id"] for s in listed.json()["sessions"]] == [session]
    assert listed.json()["retention_days"] == 7

    detail = client.get(f"{base}/sessions/{session}")
    assert detail.status_code == 200, detail.text
    call = detail.json()["calls"][0]
    assert call["origin"] == "spec" and call["path_template"] == "/invoices/{id}"
    assert call["response"]["body"] == {"id": 42}

    missing = client.get(f"{base}/sessions/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "capture-session-not-found"
    assert client.get(f"{base}/sessions?cursor=nope").status_code == 400

    bad = client.post(
        f"{base}/links",
        json={
            "project": env["seed"]["project_slug"],
            "version": "2.7.0",
            "consumer": " Orders",
            "consumer_version": "1",
        },
    )
    assert bad.status_code == 422 and "leading or trailing spaces" in bad.text
    assert (
        client.post(
            f"{base}/links", json={"project": "p", "version": "v", "consumer": "a", "consumer_version": "1", "x": 1}
        ).status_code
        == 422
    )
    created = client.post(
        f"{base}/links",
        json={
            "project": env["seed"]["project_slug"],
            "version": "2.7.0",
            "consumer": "Orders UI",
            "consumer_version": "3.4.0",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["token"].startswith("mcap_")
    assert client.get(f"{base}/links").json()["links"][0]["token_prefix"] == created.json()["token_prefix"]

    assert client.put(f"{base}/settings", json={"retention_days": 0}).status_code == 422
    saved = client.put(f"{base}/settings", json={"retention_days": 30})
    assert saved.status_code == 200 and saved.json()["retention_days"] == 30
    assert saved.json()["limits"]["max_calls_per_session"] == 5000

    assert client.delete(f"{base}/sessions/{session}").status_code == 204
    assert client.get(f"{base}/sessions/{session}").status_code == 404
