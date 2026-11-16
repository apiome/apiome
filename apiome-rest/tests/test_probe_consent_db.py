"""Probe consent and security probe reports against a live Postgres — ASP-4.1 (#5939).

Runs the real store SQL over V386 in one always-rolled-back transaction (the ``tx`` fixture of
``test_catalog_graph_db``):

* a grant is stored, read back with its identity reference, and replaces the previous live consent;
* the database refuses a pasted token as an identity even when the API model is bypassed;
* revocation keeps the row; a revoked row cannot be revoked again or edited;
* the gate refuses a staging target without consent, refuses after revocation, and a hosted-mock run
  needs no consent and is capped at ``observed``;
* a report is written once and counted toward the hourly cap; an UPDATE is rejected.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Tuple
from unittest.mock import patch

import psycopg2
import pytest

from app import probe_consent as pc
from app import probe_consent_store as store
from app.verification_target import record_from_row
from tests.test_catalog_graph_db import tx  # noqa: F401 - the fixture

pytestmark = pytest.mark.requires_db


def _seed(
    cursor: Any, environment: str = "staging", base_url: str = "https://staging.example.com"
) -> Tuple[str, Any, str]:
    """A tenant with one verification target; returns (tenant id, target record, user id)."""
    cursor.execute("SELECT id::text AS id FROM apiome.users LIMIT 1")
    user = cursor.fetchone()["id"]
    suffix = uuid.uuid4().hex[:10]
    cursor.execute(
        "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
        (f"probe {suffix}", f"probe-{suffix}"),
    )
    tenant = cursor.fetchone()["id"]
    cursor.execute(
        """INSERT INTO apiome.verification_target (tenant_id, slug, name, environment, base_url)
           VALUES (%s, %s, 'Target', %s, %s) RETURNING *""",
        (tenant, f"t-{suffix}", environment, base_url),
    )
    target = record_from_row(cursor.fetchone())
    return tenant, target, user


def _grant(**overrides: Any) -> store.ProbeConsentGrant:
    body: Dict[str, Any] = {
        "ownership_declared": True,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "profiles_allowed": ["passive", "safe-active"],
        "identity_a": {"kind": "env", "scheme": "bearer", "ref": "PROBE_TOKEN_A"},
    }
    body.update(overrides)
    return store.ProbeConsentGrant(**body)


def test_grant_read_replace_and_revoke(tx) -> None:  # noqa: F811 - the fixture
    db, cursor = tx
    tenant, target, user = _seed(cursor)
    actor = store.TargetActor(user_id=user, label="ops@example.com")
    with patch.object(store, "db", db), patch.object(store.settings, "security_probe_enabled", True):
        first = store.grant_consent(tenant, target, _grant(), actor=actor)
        assert store.get_live_consent(tenant, target.id).id == first.id
        assert first.identity_a.ref == "PROBE_TOKEN_A"

        auth = store.authorize_probe_run(
            tenant, target, profile_id="safe-active", explicit_approval=False, actor=actor
        )
        assert auth.consent_id == first.id and auth.identities == ("identity_a",)

        second = store.grant_consent(tenant, target, _grant(profiles_allowed=["passive"]), actor=actor)
        assert second.id != first.id
        assert store.get_live_consent(tenant, target.id).id == second.id
        cursor.execute(
            "SELECT revoked_at FROM apiome.verification_target_probe_consents WHERE id = %s",
            (first.id,),
        )
        assert cursor.fetchone()["revoked_at"] is not None

        revoked = store.revoke_consent(tenant, target, actor=actor)
        assert revoked.status == "revoked"
        assert store.get_live_consent(tenant, target.id) is None
        with pytest.raises(store.ProbeConsentStoreError):
            store.revoke_consent(tenant, target, actor=actor)

        with pytest.raises(pc.ProbeRefusalError) as excinfo:
            store.authorize_probe_run(
                tenant, target, profile_id="passive", explicit_approval=False, actor=actor
            )
        assert excinfo.value.code == pc.CODE_CONSENT_MISSING

    cursor.execute(
        "SELECT action FROM apiome.access_audit WHERE tenant_id = %s ORDER BY created_at, id",
        (tenant,),
    )
    actions = sorted(row["action"] for row in cursor.fetchall())
    assert actions == sorted(
        [
            store.AUDIT_CONSENT_GRANT,
            store.AUDIT_CONSENT_GRANT,
            store.AUDIT_CONSENT_REVOKE,
            store.AUDIT_RUN_REFUSED,
        ]
    )


def test_the_database_refuses_a_token_as_an_identity(tx) -> None:  # noqa: F811
    _db, cursor = tx
    tenant, target, user = _seed(cursor)
    cursor.execute("SAVEPOINT s")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cursor.execute(
            """INSERT INTO apiome.verification_target_probe_consents
               (tenant_id, target_id, ownership_declared, approved_by, expires_at, profiles_allowed,
                identity_a_kind, identity_a_scheme, identity_a_ref)
               VALUES (%s, %s, true, %s, now() + interval '1 day', ARRAY['passive'],
                       'env', 'bearer', 'eyJhbGciOi.eyJzdWIi.sig')""",
            (tenant, target.id, user),
        )
    cursor.execute("ROLLBACK TO SAVEPOINT s")


def test_a_consent_cannot_be_edited(tx) -> None:  # noqa: F811
    db, cursor = tx
    tenant, target, user = _seed(cursor)
    with patch.object(store, "db", db):
        record = store.grant_consent(tenant, target, _grant(), actor=store.TargetActor(user_id=user))
    cursor.execute("SAVEPOINT s")
    with pytest.raises(psycopg2.errors.CheckViolation, match="only be revoked"):
        cursor.execute(
            "UPDATE apiome.verification_target_probe_consents SET profiles_allowed = ARRAY['payload'] WHERE id = %s",
            (record.id,),
        )
    cursor.execute("ROLLBACK TO SAVEPOINT s")


def test_the_hosted_mock_runs_without_consent_and_its_report_is_write_once(tx) -> None:  # noqa: F811
    db, cursor = tx
    tenant, target, user = _seed(cursor, environment="mock", base_url="http://localhost:8775/m/acme")
    actor = store.TargetActor(user_id=user)
    with patch.object(store, "db", db), patch.object(
        store.settings, "security_probe_enabled", False
    ), patch.object(store.settings, "mock_public_base_url", "http://localhost:8775"):
        assert store.tenant_usage(tenant).runs_last_hour == 0
        auth = store.authorize_probe_run(
            tenant, target, profile_id="passive", explicit_approval=False, actor=actor
        )
        assert auth.hosted_mock and auth.proof_ceiling == "observed"
        report = store.save_report(
            tenant, target, auth, counts={"observed": 2},
            report={"ceiling_reason": pc.MOCK_CEILING_REASON}, actor=actor,
        )
        assert report.consent_id is None and report.count_observed == 2
        assert store.get_report(tenant, report.id).report["ceiling_reason"] == pc.MOCK_CEILING_REASON
        assert [r.id for r in store.list_reports(tenant, target_id=target.id)] == [report.id]
        assert store.tenant_usage(tenant).runs_last_hour == 1

    cursor.execute("SAVEPOINT s")
    with pytest.raises(psycopg2.Error, match="immutable"):
        cursor.execute(
            "UPDATE apiome.security_probe_reports SET count_observed = 0 WHERE id = %s", (report.id,)
        )
    cursor.execute("ROLLBACK TO SAVEPOINT s")
