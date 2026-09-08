"""Guard tests for the deploy-gate database accessors — CTG-4.5 (#4502).

The suite runs against a live Postgres, so these tests assert only the property that must hold
*before* a statement is sent: a malformed identifier short-circuits and returns the empty value for
its type, rather than reaching the driver and raising. A deploy gate is called with whatever a
pipeline's environment variable happened to contain, so this is the accessor most likely to be
handed a handle that is not a UUID at all.

The SQL itself is exercised by the migration guardrails and by the store tests.
"""

from __future__ import annotations

from unittest.mock import patch

from app.database import db

_BAD = "not-a-uuid"
_UUID = "11111111-1111-4111-8111-111111111111"
_OTHER = "22222222-2222-4222-8222-222222222222"


def test_policy_reads_short_circuit_on_a_malformed_tenant():
    """A bad tenant handle is a clean "no policy saved", never a driver error."""
    assert db.get_deploy_gate_policy(_BAD) is None
    assert db.get_deploy_gate_policy(_BAD, _UUID) is None
    assert db.get_deploy_gate_policy("") is None


def test_policy_writes_short_circuit_on_a_malformed_tenant():
    """A write that cannot be addressed is refused before the statement, not after it."""
    assert (
        db.upsert_deploy_gate_policy(
            tenant_id=_BAD,
            project_id=_UUID,
            thresholds={},
            content_fingerprint="sha256:x",
        )
        is None
    )
    assert db.delete_deploy_gate_policy(_BAD) == 0
    assert db.delete_deploy_gate_policy(_BAD, _UUID) == 0


def test_a_malformed_project_falls_back_to_the_tenant_wide_scope():
    """A garbage project handle must read the tenant policy, not crash and not invent a scope."""
    with patch.object(db, "execute_query", return_value=[]) as query:
        assert db.get_deploy_gate_policy(_UUID, _BAD) is None
    sql, params = query.call_args.args
    assert "project_id IS NULL" in sql
    assert params == (_UUID,)


def test_the_scoped_read_prefers_the_project_override_in_one_query():
    """Two scopes, one round trip: the override sorts first, so no second query is needed."""
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.get_deploy_gate_policy(_UUID, _OTHER)
    sql, params = query.call_args.args
    assert "project_id = %s::uuid OR project_id IS NULL" in sql
    assert "ORDER BY project_id NULLS LAST" in sql
    assert params == (_UUID, _OTHER)


def test_report_lists_short_circuit_on_a_malformed_tenant():
    """The gate's verification fallback owes the same guarantee as every other list read."""
    assert db.list_provider_verification_reports(_BAD, artifact_id=_UUID) == []


def test_an_artifact_filtered_report_read_binds_the_resolved_coordinates():
    """The gate is anchored on a project id, so it filters on what CTG-4.3 resolved, not on the
    reference string a run happened to be requested with."""
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.list_provider_verification_reports(
            _UUID, artifact_kind="project", artifact_id=_OTHER, version_label="1.2.0", limit=1
        )
    sql, params = query.call_args.args
    assert "artifact_kind = %s" in sql
    assert "artifact_id = %s::uuid" in sql
    assert "version_label = %s" in sql
    assert params == (_UUID, "project", _OTHER, "1.2.0", 1)


def test_a_malformed_artifact_id_is_dropped_rather_than_bound():
    """A non-UUID artifact filter must not reach the driver as a uuid cast."""
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.list_provider_verification_reports(_UUID, artifact_id=_BAD, limit=5)
    sql, params = query.call_args.args
    # The column is in the SELECT list either way; what must not appear is a bound predicate.
    assert "artifact_id = %s::uuid" not in sql
    assert params == (_UUID, 5)
