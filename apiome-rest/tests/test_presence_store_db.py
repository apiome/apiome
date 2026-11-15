"""Presence and soft locks against a live Postgres — COL-4.1 (#4525).

Runs in one always-rolled-back transaction. ``now()`` is frozen inside it, so lapses and the
takeover grace period are produced by back-dating the rows, never by sleeping.

Asserted: avatars appear on heartbeat and vanish on leave or lapse; a lock is advisory-exclusive and
its takeover flow (request → too early → force after the grace period → previous holder's ``lost``
notice) works; locks expire on disconnect (lapse) so nothing sticks.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterator, Tuple

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

from app import presence_store
from app.config import settings
from app.database import Database
from app.presence import (
    CODE_LOCK_HELD,
    CODE_LOCK_NOT_FOUND,
    CODE_TAKEOVER_TOO_EARLY,
    PresenceValidationError,
)
from tests.test_catalog_graph_db import _NoCommitConnection

pytestmark = pytest.mark.requires_db

KEY = "class:3f2a6c1e-0000-4000-8000-000000000001"
A, B = "tab-alice-0001", "tab-bob-00001"


@pytest.fixture
def world(monkeypatch) -> Iterator[Tuple[Dict[str, Any], Any]]:
    """A tenant, project, and two users inside a rolled-back transaction."""
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute("SELECT to_regclass('apiome.element_locks') AS t")
        if not probe.fetchone()["t"]:
            conn.close()
            pytest.skip("V375 not applied")
    db = Database()
    db.connection = _NoCommitConnection(conn)
    monkeypatch.setattr(presence_store, "db", db)
    try:
        with conn.cursor() as cur:
            suffix = uuid.uuid4().hex[:10]
            ids = {}
            for who in ("alice", "bob"):
                cur.execute(
                    "INSERT INTO apiome.users (name, email, password) VALUES (%s, %s, 'x') RETURNING id::text AS id",
                    (who.title(), f"{who}-{suffix}@example.com"),
                )
                ids[who] = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
                (f"presence {suffix}", f"presence-{suffix}"),
            )
            ids["tenant"] = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO apiome.projects (tenant_id, creator_id, name, slug) "
                "VALUES (%s, %s, 'P', %s) RETURNING id::text AS id",
                (ids["tenant"], ids["alice"], f"p-{suffix}"),
            )
            ids["project"] = cur.fetchone()["id"]
            yield ids, cur
    finally:
        conn.rollback()
        conn.close()


def _beat(w, who, session, held=()):
    return presence_store.heartbeat(w["project"], w["tenant"], w[who], session, "studio", held)


def test_avatars_appear_and_disappear(world):
    w, _ = world
    assert [v.name for v in _beat(w, "alice", A).viewers] == ["Alice"]
    snap = _beat(w, "bob", B)
    assert [v.name for v in snap.viewers] == ["Alice", "Bob"]
    assert snap.viewers[1].views == ["studio"]
    presence_store.leave(w["project"], B)
    assert [v.name for v in presence_store.snapshot(w["project"]).viewers] == ["Alice"]


def test_two_tabs_of_one_person_are_one_avatar(world):
    w, _ = world
    _beat(w, "alice", A)
    snap = _beat(w, "alice", "tab-alice-0002")
    assert len(snap.viewers) == 1 and snap.viewers[0].sessions == 2


def test_a_silent_tab_lapses(world):
    w, cur = world
    _beat(w, "alice", A)
    cur.execute("UPDATE apiome.project_presence SET last_seen_at = now() - interval '2 minutes'")
    assert presence_store.snapshot(w["project"]).viewers == []


def test_lock_is_visible_to_others_and_held_exclusively(world):
    w, _ = world
    _beat(w, "alice", A)
    snap = presence_store.acquire_lock(w["project"], w["tenant"], w["alice"], A, KEY)
    assert [(lk.element_key, lk.holder_name) for lk in snap.locks] == [(KEY, "Alice")]
    with pytest.raises(PresenceValidationError) as err:
        presence_store.acquire_lock(w["project"], w["tenant"], w["bob"], B, KEY)
    assert err.value.code == CODE_LOCK_HELD
    # Re-taking your own lock is fine and keeps the original acquired_at.
    presence_store.acquire_lock(w["project"], w["tenant"], w["alice"], A, KEY)


def test_takeover_flow_notifies_the_previous_holder(world):
    w, cur = world
    _beat(w, "alice", A)
    presence_store.acquire_lock(w["project"], w["tenant"], w["alice"], A, KEY)
    snap = presence_store.request_takeover(w["project"], w["bob"], B, KEY)
    assert snap.locks[0].takeover.name == "Bob"
    # The holder sees the request on their next heartbeat.
    assert _beat(w, "alice", A, [KEY]).locks[0].takeover.user_id == w["bob"]
    with pytest.raises(PresenceValidationError) as early:
        presence_store.take_over(w["project"], w["tenant"], w["bob"], B, KEY)
    assert early.value.code == CODE_TAKEOVER_TOO_EARLY
    cur.execute("UPDATE apiome.element_locks SET takeover_requested_at = now() - interval '30 seconds'")
    stolen = presence_store.take_over(w["project"], w["tenant"], w["bob"], B, KEY)
    assert stolen.locks[0].holder_name == "Bob" and stolen.locks[0].takeover is None
    # Alice's next heartbeat tells her she lost it, and she cannot revive it by heartbeating.
    assert _beat(w, "alice", A, [KEY]).lost == [KEY]
    assert presence_store.snapshot(w["project"]).locks[0].holder_name == "Bob"


def test_release_lets_the_requester_take_over_immediately(world):
    w, _ = world
    presence_store.acquire_lock(w["project"], w["tenant"], w["alice"], A, KEY)
    presence_store.request_takeover(w["project"], w["bob"], B, KEY)
    presence_store.release_lock(w["project"], A, KEY)
    snap = presence_store.take_over(w["project"], w["tenant"], w["bob"], B, KEY)
    assert snap.locks[0].holder_name == "Bob"


def test_locks_expire_on_disconnect(world):
    w, cur = world
    _beat(w, "alice", A)
    presence_store.acquire_lock(w["project"], w["tenant"], w["alice"], A, KEY)
    cur.execute("UPDATE apiome.element_locks SET expires_at = now() - interval '1 second'")
    assert presence_store.snapshot(w["project"]).locks == []
    # Bob can simply take the lapsed lock.
    snap = presence_store.acquire_lock(w["project"], w["tenant"], w["bob"], B, KEY)
    assert snap.locks[0].holder_name == "Bob"


def test_leave_releases_every_lock(world):
    w, _ = world
    _beat(w, "alice", A)
    presence_store.acquire_lock(w["project"], w["tenant"], w["alice"], A, KEY)
    presence_store.leave(w["project"], A)
    assert presence_store.snapshot(w["project"]).locks == []


def test_requesting_a_free_element_says_so(world):
    w, _ = world
    with pytest.raises(PresenceValidationError) as err:
        presence_store.request_takeover(w["project"], w["bob"], B, KEY)
    assert err.value.code == CODE_LOCK_NOT_FOUND


def test_heartbeat_rejects_malformed_keys(world):
    w, _ = world
    with pytest.raises(PresenceValidationError):
        _beat(w, "alice", A, ["not a key"])
