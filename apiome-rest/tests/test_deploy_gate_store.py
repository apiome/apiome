"""Deploy-gate policy persistence — CTG-4.5 (#4502).

The database handle is patched, so these tests assert what the *store* promises rather than what
Postgres does: the two-scope resolution, and the two ways a policy can be unreadable without the
gate losing its ability to answer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.deploy_gate import (
    DEFAULT_THRESHOLDS,
    POLICY_SOURCE_DEFAULT,
    POLICY_SOURCE_PROJECT,
    POLICY_SOURCE_TENANT,
    GateThresholdError,
    canonical_thresholds_body,
    thresholds_content_fingerprint,
    thresholds_from_body,
)
from app.deploy_gate_store import (
    audit_detail,
    clear_policy,
    default_policy,
    load_policy,
    policy_from_row,
    save_policy,
)

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_POLICY_ID = "33333333-3333-4333-8333-333333333333"
_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _row(**overrides):
    """A stored ``deploy_gate_policy`` row."""
    thresholds = thresholds_from_body({"lint": {"failBelowGrade": "C"}})
    row = {
        "id": _POLICY_ID,
        "tenant_id": _TENANT,
        "project_id": None,
        "thresholds": canonical_thresholds_body(thresholds),
        "content_fingerprint": thresholds_content_fingerprint(thresholds),
        "created_by": None,
        "updated_by": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    row.update(overrides)
    return row


def test_no_saved_row_reads_as_the_documented_default():
    """An upgrade must change no behaviour for a tenant that configured nothing."""
    with patch("app.deploy_gate_store.db.get_deploy_gate_policy", return_value=None):
        policy = load_policy(_TENANT, _PROJECT)
    assert policy.source == POLICY_SOURCE_DEFAULT
    assert policy.thresholds == DEFAULT_THRESHOLDS
    assert policy.degraded is False
    assert policy.content_fingerprint.startswith("sha256:")


def test_a_project_row_reports_project_scope_and_a_tenant_row_reports_tenant_scope():
    """`source` is what makes a verdict explicable: it names where the bar came from."""
    assert policy_from_row(_row()).source == POLICY_SOURCE_TENANT
    assert policy_from_row(_row(project_id=_PROJECT)).source == POLICY_SOURCE_PROJECT


def test_resolution_is_one_query_that_prefers_the_override():
    """The gate is on a pipeline's hot path; finding the bar must not cost two round trips."""
    with patch(
        "app.deploy_gate_store.db.get_deploy_gate_policy", return_value=_row(project_id=_PROJECT)
    ) as get:
        policy = load_policy(_TENANT, _PROJECT)
    get.assert_called_once_with(_TENANT, _PROJECT)
    assert policy.source == POLICY_SOURCE_PROJECT


def test_an_unreadable_store_degrades_to_the_default_rather_than_failing_the_gate():
    """Every pipeline in the tenant reads this; an infrastructure fault must not stop them all."""
    with patch(
        "app.deploy_gate_store.db.get_deploy_gate_policy", side_effect=RuntimeError("down")
    ):
        policy = load_policy(_TENANT, _PROJECT)
    assert policy.source == POLICY_SOURCE_DEFAULT
    assert policy.degraded is True


def test_a_body_this_release_cannot_parse_degrades_but_keeps_its_provenance():
    """A row written by a newer release still says which scope it came from and when."""
    policy = policy_from_row(_row(thresholds={"lint": {"failBelowGrade": "Z"}}))
    assert policy.degraded is True
    assert policy.source == POLICY_SOURCE_TENANT
    assert policy.policy_id == _POLICY_ID
    assert policy.thresholds == DEFAULT_THRESHOLDS


def test_degraded_is_false_on_an_ordinary_read_so_the_flag_means_something():
    """The flag exists to distinguish "unset" from "unreadable"; it must not cry wolf."""
    assert default_policy().degraded is False
    assert policy_from_row(_row()).degraded is False


def test_saving_validates_before_it_writes():
    """A refused policy must not reach the database at all."""
    with patch("app.deploy_gate_store.db.upsert_deploy_gate_policy") as upsert:
        with pytest.raises(GateThresholdError):
            save_policy(_TENANT, project_id=None, body={"lint": {"failBelowGrade": "Z"}})
    upsert.assert_not_called()


def test_saving_stores_the_full_canonical_body_not_the_submitted_fragment():
    """A policy naming one threshold must still pin the other seven against a future default."""
    with patch(
        "app.deploy_gate_store.db.upsert_deploy_gate_policy", return_value=_row()
    ) as upsert:
        save_policy(
            _TENANT,
            project_id=_PROJECT,
            body={"lint": {"failBelowGrade": "C"}},
            actor_id="u",
        )
    stored = upsert.call_args.kwargs["thresholds"]
    assert set(stored) == {"schemaVersion", "lint", "breaking", "consumers", "verification"}
    assert stored["verification"]["warnAfterSeconds"] == 86_400
    assert upsert.call_args.kwargs["content_fingerprint"].startswith("sha256:")


def test_clearing_reports_whether_anything_was_actually_saved():
    """A caller that cleared nothing should not be told it cleared something."""
    with patch("app.deploy_gate_store.db.delete_deploy_gate_policy", return_value=1):
        assert clear_policy(_TENANT, project_id=_PROJECT) is True
    with patch("app.deploy_gate_store.db.delete_deploy_gate_policy", return_value=0):
        assert clear_policy(_TENANT, project_id=_PROJECT) is False


def test_the_audit_payload_carries_the_bar_that_was_set():
    """A row that says only "the policy changed" cannot answer "changed to what?"."""
    detail = audit_detail(policy_from_row(_row(project_id=_PROJECT)))
    assert detail["source"] == POLICY_SOURCE_PROJECT
    assert detail["thresholds"]["lint"]["failBelowGrade"] == "C"
    assert detail["contentFingerprint"].startswith("sha256:")
