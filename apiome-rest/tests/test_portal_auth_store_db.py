"""PCX-1.1 (#5889) against a live Postgres: the SQL repository behind reader sign-in.

The unit tests drive :mod:`app.portal_auth_store` through an in-memory fake; these run the same
flow through :class:`~app.portal_auth_store.SqlPortalAuthRepository` and apiome-db V378, so the
SQL itself — upserts, the burn-once ``UPDATE``, the session join, and the pre-hijacking guard on
``mark_user_verified`` — is exercised. Each test is one always-rolled-back transaction.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Iterator, Tuple

import psycopg2
import pytest
from fake_portal_auth_repo import RecordingMailer
from psycopg2.extras import RealDictCursor

from app import portal_auth_store as store
from app.config import settings
from app.database import Database
from app.portal_auth import CODE_SESSION_INVALID, CODE_TOKEN_USED, PortalAuthError
from tests.test_catalog_graph_db import _NoCommitConnection

pytestmark = pytest.mark.requires_db


@pytest.fixture
def repo() -> Iterator[Tuple[store.SqlPortalAuthRepository, Any, str]]:
    """The SQL repository, a raw cursor, and a fresh tenant slug, over one rolled-back transaction."""
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute("SELECT to_regclass('apiome.portal_reader_sessions') AS t")
        if not probe.fetchone()["t"]:
            conn.close()
            pytest.skip("V378 not applied")
    db = Database()
    db.connection = _NoCommitConnection(conn)
    slug = f"portal-{uuid.uuid4().hex[:10]}"
    try:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s)", ("Portal Co", slug))
            yield store.SqlPortalAuthRepository(db), cursor, slug
    finally:
        conn.rollback()
        conn.close()


def _sign_in(repo, slug, email):
    mailer = RecordingMailer()
    assert store.request_magic_link(
        repo, mailer, tenant_slug=slug, email=email, return_to="/tenant/x",
        browse_url="https://b.example", signup_rejection=lambda _e: None,
    )
    token = mailer.last_token()
    grant = store.exchange_token(repo, tenant_slug=slug, token=token, user_agent="Firefox/132.0",
                                 session_ttl=timedelta(days=1))
    return token, grant


def _user(cursor, email):
    cursor.execute("SELECT id::text AS id, verified, password FROM apiome.users WHERE email = %s", (email,))
    return cursor.fetchone()


def test_the_full_flow_creates_one_user_one_membership_and_a_live_session(repo):
    sql, cursor, slug = repo
    email = f"r-{uuid.uuid4().hex[:8]}@example.com"
    token, grant = _sign_in(sql, slug, email)
    _sign_in(sql, slug, email)

    cursor.execute("SELECT count(*) AS n FROM apiome.users WHERE email = %s", (email,))
    assert cursor.fetchone()["n"] == 1
    user = _user(cursor, email)
    assert user["verified"] is True and user["password"] == ""
    cursor.execute("SELECT status, source FROM apiome.portal_memberships WHERE user_id = %s::uuid", (user["id"],))
    assert [dict(r) for r in cursor.fetchall()] == [{"status": "active", "source": "magic_link"}]

    with pytest.raises(PortalAuthError) as exc:
        store.exchange_token(sql, tenant_slug=slug, token=token, user_agent=None, session_ttl=timedelta(days=1))
    assert exc.value.code == CODE_TOKEN_USED

    session = store.resolve_session(sql, grant.session_token)
    assert session.tenant_slug == slug and session.profile.email == email
    assert store.revoke_session(sql, grant.session_token) is True
    with pytest.raises(PortalAuthError) as exc:
        store.resolve_session(sql, grant.session_token)
    assert exc.value.code == CODE_SESSION_INVALID

    cursor.execute("SELECT action FROM apiome.access_audit WHERE target = %s ORDER BY created_at, id", (email,))
    actions = [r["action"] for r in cursor.fetchall()]
    assert actions.count("portal.reader.enrolled") == 1
    assert actions.count("portal.reader.signed_in") == 2
    assert actions.count("portal.reader.session_revoked") == 1


@pytest.mark.parametrize("where", ["users", "credential"])
def test_an_unverified_account_holding_a_password_is_never_verified(repo, where):
    """Pre-hijacking guard: a stranger's unconfirmed sign-up must stay locked."""
    sql, cursor, slug = repo
    email = f"victim-{uuid.uuid4().hex[:8]}@example.com"
    cursor.execute(
        "INSERT INTO apiome.users (name, email, password, verified) VALUES ('v', %s, %s, false) RETURNING id",
        (email, "$2b$10$attacker" if where == "users" else ""),
    )
    user_id = cursor.fetchone()["id"]
    if where == "credential":
        cursor.execute(
            """INSERT INTO apiome.account ("id", "userId", "accountId", "providerId", "password", "createdAt", "updatedAt")
               VALUES (%s, %s, %s, 'credential', '$2b$10$attacker', now(), now())""",
            (uuid.uuid4().hex, user_id, str(user_id)),
        )

    _, grant = _sign_in(sql, slug, email)
    assert grant.reader.email == email  # the real owner still reads the portal …
    assert _user(cursor, email)["verified"] is False  # … but the stranger's password stays locked
