"""Probe consent persistence and the audited run gate — ASP-4.1 (#5939).

The database is faked here (the ``_db`` tests cover the real SQL); what is asserted is the store's
own contract:

* a grant is validated before anything is written — ownership must be declared, the expiry must be in
  the future and timezone-aware, profiles must be known, and an identity must be a credential
  *reference* (a pasted token is rejected by the same rules V211 applies to targets);
* every grant, revocation and refused run writes an ``access_audit`` row, and an audit failure never
  turns a refusal into an allowed run;
* the gate reads the kill switch, the caps and the hosted-mock origin from settings;
* a report can never carry a finding above its proof ceiling.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app import probe_consent as pc
from app import probe_consent_store as store
from app.verification_target import TargetAuthReference, VerificationPolicy, VerificationTargetRecord

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
TENANT = "11111111-1111-4111-8111-111111111111"
TARGET = "22222222-2222-4222-8222-222222222222"
USER = "33333333-3333-4333-8333-333333333333"
CONSENT = "44444444-4444-4444-8444-444444444444"
ACTOR = store.TargetActor(user_id=USER, label="ops@example.com")


def _target(**overrides: Any) -> VerificationTargetRecord:
    """A stored target."""
    payload: Dict[str, Any] = {
        "id": TARGET,
        "tenant_id": TENANT,
        "slug": "staging",
        "name": "Staging",
        "environment": "staging",
        "base_url": "https://staging.example.com/api",
        "network_class": "public",
        "auth": TargetAuthReference(),
        "policy": VerificationPolicy(),
        "enabled": True,
    }
    payload.update(overrides)
    return VerificationTargetRecord(**payload)


def _grant(**overrides: Any) -> store.ProbeConsentGrant:
    """A valid grant body."""
    body: Dict[str, Any] = {
        "ownership_declared": True,
        "expires_at": (NOW + timedelta(days=7)).isoformat(),
        "profiles_allowed": ["safe-active", "passive"],
    }
    body.update(overrides)
    return store.ProbeConsentGrant(**body)


def _consent_row(**overrides: Any) -> Dict[str, Any]:
    """A consent row as the database returns it."""
    row: Dict[str, Any] = {
        "id": CONSENT,
        "tenant_id": TENANT,
        "target_id": TARGET,
        "ownership_declared": True,
        "approved_by": USER,
        "approved_at": NOW - timedelta(days=1),
        "expires_at": NOW + timedelta(days=6),
        "profiles_allowed": ["passive", "safe-active"],
        "identity_a_kind": "env",
        "identity_a_scheme": "bearer",
        "identity_a_ref": "PROBE_TOKEN_A",
        "identity_a_header_name": None,
        "identity_b_kind": None,
        "identity_b_scheme": None,
        "identity_b_ref": None,
        "identity_b_header_name": None,
        "revoked_at": None,
        "revoked_by": None,
        "created_at": NOW - timedelta(days=1),
    }
    row.update(overrides)
    return row


class _Cursor:
    """A cursor that records statements and returns scripted rows."""

    def __init__(self, owner: "_FakeDb") -> None:
        self._owner = owner
        self._last: List[Dict[str, Any]] = []

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self._owner.statements.append((sql, params))
        self._last = self._owner.next_rows()

    def fetchall(self) -> List[Dict[str, Any]]:
        return self._last

    def fetchone(self) -> Any:
        return self._last[0] if self._last else None


class _Conn:
    def __init__(self, owner: "_FakeDb") -> None:
        self._owner = owner
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> _Cursor:
        return _Cursor(self._owner)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class _FakeDb:
    """Scripted ``execute_query``/``connect`` plus a captured ``write_access_audit``."""

    def __init__(self, *responses: List[Dict[str, Any]], audit_fails: bool = False) -> None:
        self._responses = list(responses)
        self.statements: List[Any] = []
        self.audits: List[Dict[str, Any]] = []
        self.conn = _Conn(self)
        self._audit_fails = audit_fails

    def next_rows(self) -> List[Dict[str, Any]]:
        return self._responses.pop(0) if self._responses else []

    def execute_query(self, sql: str, params: Any = None) -> List[Dict[str, Any]]:
        self.statements.append((sql, params))
        return self.next_rows()

    def connect(self) -> _Conn:
        return self.conn

    def write_access_audit(self, **entry: Any) -> None:
        if self._audit_fails:
            raise RuntimeError("ledger down")
        self.audits.append(entry)


# ===========================================================================
# Grant body validation
# ===========================================================================


def test_a_grant_must_declare_ownership() -> None:
    with pytest.raises(ValidationError, match="ownership_declared must be true"):
        _grant(ownership_declared=False)


def test_a_grant_needs_a_timezone_aware_expiry() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        _grant(expires_at="2026-12-01T00:00:00")


def test_a_grant_rejects_unknown_and_empty_profiles_and_orders_the_rest() -> None:
    with pytest.raises(ValidationError, match="unknown probe profile"):
        _grant(profiles_allowed=["passive", "fuzz"])
    with pytest.raises(ValidationError):
        _grant(profiles_allowed=[])
    assert _grant(profiles_allowed=["payload", "passive", "passive"]).profiles_allowed == [
        "passive",
        "payload",
    ]


@pytest.mark.parametrize(
    "identity",
    [
        {"kind": "env", "scheme": "bearer", "ref": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig"},
        {"kind": "env", "scheme": "bearer", "ref": "sk_live_abc123"},
        {"kind": "stored", "scheme": "bearer", "ref": "not-a-uuid-but-a-token"},
        {"kind": "none"},
    ],
)
def test_a_pasted_token_or_an_empty_reference_cannot_be_an_identity(identity: Dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _grant(identity_a=identity)
    with pytest.raises(ValidationError):
        _grant(identity_b=identity)


def test_identities_accept_references() -> None:
    grant = _grant(
        identity_a={"kind": "env", "scheme": "bearer", "ref": "PROBE_TOKEN_A"},
        identity_b={"kind": "stored", "scheme": "basic", "ref": CONSENT},
    )
    assert grant.identity_a.ref == "PROBE_TOKEN_A"
    assert grant.identity_b.kind == "stored"


def test_a_grant_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _grant(token="hunter2")


# ===========================================================================
# Grant / read / revoke
# ===========================================================================


def test_granting_revokes_the_previous_consent_inserts_and_audits() -> None:
    fake = _FakeDb([{"id": "old-consent"}], [_consent_row()])
    with patch.object(store, "db", fake):
        record = store.grant_consent(TENANT, _target(), _grant(), actor=ACTOR, now=NOW)
    assert record.id == CONSENT
    assert record.status == "active"
    assert record.identity_a.ref == "PROBE_TOKEN_A"
    update_sql, insert_sql = fake.statements[0][0], fake.statements[1][0]
    assert "UPDATE apiome.verification_target_probe_consents" in update_sql
    assert "revoked_at IS NULL" in update_sql
    assert "INSERT INTO apiome.verification_target_probe_consents" in insert_sql
    assert fake.conn.committed
    insert_params = fake.statements[1][1]
    assert insert_params[2] is True  # ownership_declared
    assert insert_params[6] == ["passive", "safe-active"]
    assert len(fake.audits) == 1
    audit = fake.audits[0]
    assert audit["action"] == store.AUDIT_CONSENT_GRANT
    assert audit["actor_id"] == USER
    assert audit["target"] == TARGET
    assert audit["detail"]["replaced_consent_ids"] == ["old-consent"]
    assert audit["detail"]["identities"] == ["identity_a"]
    assert "PROBE_TOKEN_A" not in str(audit["detail"])  # names which identities, not their refs


def test_a_grant_with_a_past_expiry_is_refused_before_any_write() -> None:
    fake = _FakeDb()
    with patch.object(store, "db", fake), pytest.raises(store.ProbeConsentStoreError) as excinfo:
        store.grant_consent(
            TENANT, _target(), _grant(expires_at=(NOW - timedelta(hours=1)).isoformat()),
            actor=ACTOR, now=NOW,
        )
    assert excinfo.value.code == "probe-consent-invalid"
    assert fake.statements == [] and fake.audits == []


def test_a_grant_needs_an_identified_approver() -> None:
    fake = _FakeDb()
    with patch.object(store, "db", fake), pytest.raises(store.ProbeConsentStoreError):
        store.grant_consent(
            TENANT, _target(), _grant(), actor=store.TargetActor(user_id=None), now=NOW
        )
    assert fake.statements == []


def test_a_failed_insert_rolls_back_and_writes_no_audit() -> None:
    class _Boom(_FakeDb):
        def next_rows(self):
            if len(self.statements) == 2:
                raise RuntimeError("unique violation")
            return []

    fake = _Boom()
    with patch.object(store, "db", fake), pytest.raises(RuntimeError):
        store.grant_consent(TENANT, _target(), _grant(), actor=ACTOR, now=NOW)
    assert fake.conn.rolled_back and not fake.conn.committed
    assert fake.audits == []


def test_an_audit_failure_does_not_fail_the_grant() -> None:
    fake = _FakeDb([], [_consent_row()], audit_fails=True)
    with patch.object(store, "db", fake):
        record = store.grant_consent(TENANT, _target(), _grant(), actor=ACTOR, now=NOW)
    assert record.id == CONSENT


def test_reading_a_live_consent_reports_its_status() -> None:
    fake = _FakeDb([_consent_row(expires_at=NOW - timedelta(minutes=1))])
    with patch.object(store, "db", fake):
        record = store.get_live_consent(TENANT, TARGET, now=NOW)
    assert record.status == "expired"


def test_no_consent_and_malformed_ids_read_as_none() -> None:
    fake = _FakeDb([])
    with patch.object(store, "db", fake):
        assert store.get_live_consent(TENANT, TARGET) is None
        assert store.get_live_consent("t1", TARGET) is None
    assert len(fake.statements) == 1


def test_revoking_audits_and_returns_the_revoked_row() -> None:
    fake = _FakeDb([_consent_row(revoked_at=NOW, revoked_by=USER)])
    with patch.object(store, "db", fake):
        record = store.revoke_consent(TENANT, _target(), actor=ACTOR, now=NOW)
    assert record.status == "revoked"
    assert fake.audits[0]["action"] == store.AUDIT_CONSENT_REVOKE
    assert fake.audits[0]["detail"]["consent_id"] == CONSENT


def test_revoking_nothing_is_not_found() -> None:
    fake = _FakeDb([])
    with patch.object(store, "db", fake), pytest.raises(store.ProbeConsentStoreError) as excinfo:
        store.revoke_consent(TENANT, _target(), actor=ACTOR, now=NOW)
    assert excinfo.value.code == store.CODE_CONSENT_NOT_FOUND
    assert fake.audits == []


# ===========================================================================
# The audited run gate
# ===========================================================================


@pytest.fixture
def _switch_on():
    with patch.object(store.settings, "security_probe_enabled", True):
        yield


def test_policy_and_limits_come_from_settings() -> None:
    with patch.multiple(
        store.settings,
        security_probe_enabled=True,
        security_probe_max_concurrent_per_tenant=3,
        security_probe_max_runs_per_hour_per_tenant=7,
        security_probe_max_requests_per_run=9,
    ):
        policy = store.governor_policy()
        limits = store.run_limits()
    assert policy.enabled and policy.subject_kind == pc.SUBJECT_VERIFICATION_TARGET
    assert (policy.max_concurrent_per_tenant, policy.max_runs_per_hour_per_tenant) == (3, 7)
    assert limits.max_requests == 9


def test_the_kill_switch_defaults_off() -> None:
    from app.config import Settings

    assert Settings.model_fields["security_probe_enabled"].default is False


def test_tenant_usage_counts_the_trailing_hour() -> None:
    fake = _FakeDb([{"n": 4}])
    with patch.object(store, "db", fake):
        usage = store.tenant_usage(TENANT, now=NOW, active_runs=1)
    assert (usage.active_runs, usage.runs_last_hour) == (1, 4)
    assert fake.statements[0][1] == (TENANT, NOW - timedelta(hours=1))


def test_an_authorized_run_carries_the_consent_and_writes_no_refusal(_switch_on) -> None:
    fake = _FakeDb([_consent_row()], [{"n": 0}])
    with patch.object(store, "db", fake):
        auth = store.authorize_probe_run(
            TENANT, _target(), profile_id="safe-active", explicit_approval=False, actor=ACTOR, now=NOW
        )
    assert auth.consent_id == CONSENT
    assert auth.proof_ceiling == "exploited-in-test"
    assert fake.audits == []


def test_a_staging_run_without_consent_is_refused_and_audited(_switch_on) -> None:
    fake = _FakeDb([], [{"n": 0}])
    with patch.object(store, "db", fake), pytest.raises(pc.ProbeRefusalError) as excinfo:
        store.authorize_probe_run(
            TENANT, _target(), profile_id="passive", explicit_approval=False, actor=ACTOR, now=NOW
        )
    assert excinfo.value.code == pc.CODE_CONSENT_MISSING
    (audit,) = fake.audits
    assert audit["action"] == store.AUDIT_RUN_REFUSED
    assert audit["detail"]["code"] == pc.CODE_CONSENT_MISSING
    assert audit["detail"]["explicit_approval"] is False


def test_an_expired_consent_refuses_and_audits_the_consent_id(_switch_on) -> None:
    fake = _FakeDb([_consent_row(expires_at=NOW - timedelta(seconds=1))], [{"n": 0}])
    with patch.object(store, "db", fake), pytest.raises(pc.ProbeRefusalError) as excinfo:
        store.authorize_probe_run(
            TENANT, _target(), profile_id="passive", explicit_approval=False, actor=ACTOR, now=NOW
        )
    assert excinfo.value.code == pc.CODE_CONSENT_EXPIRED
    assert fake.audits[0]["detail"]["consent_id"] == CONSENT


def test_the_kill_switch_off_refuses_a_consented_target_and_audits_it() -> None:
    fake = _FakeDb([_consent_row()], [{"n": 0}])
    with patch.object(store.settings, "security_probe_enabled", False), patch.object(
        store, "db", fake
    ), pytest.raises(pc.ProbeRefusalError) as excinfo:
        store.authorize_probe_run(
            TENANT, _target(), profile_id="passive", explicit_approval=False, actor=ACTOR, now=NOW
        )
    assert excinfo.value.code == pc.CODE_KILL_SWITCH_OFF
    assert fake.audits[0]["detail"]["code"] == pc.CODE_KILL_SWITCH_OFF


def test_the_hosted_mock_runs_with_the_switch_off_and_no_consent() -> None:
    mock_target = _target(environment="mock", base_url="http://localhost:8775/m/acme/petstore")
    fake = _FakeDb([], [{"n": 0}])
    with patch.object(store.settings, "security_probe_enabled", False), patch.object(
        store.settings, "mock_public_base_url", "http://localhost:8775"
    ), patch.object(store, "db", fake):
        auth = store.authorize_probe_run(
            TENANT, mock_target, profile_id=None, explicit_approval=False, actor=ACTOR, now=NOW
        )
    assert auth.hosted_mock is True and auth.proof_ceiling == "observed"
    assert fake.audits == []


def test_an_audit_failure_never_turns_a_refusal_into_a_run(_switch_on) -> None:
    fake = _FakeDb([], [{"n": 0}], audit_fails=True)
    with patch.object(store, "db", fake), pytest.raises(pc.ProbeRefusalError):
        store.authorize_probe_run(
            TENANT, _target(), profile_id="passive", explicit_approval=False, actor=ACTOR, now=NOW
        )


# ===========================================================================
# Reports
# ===========================================================================


def _authorization(**overrides: Any) -> pc.ProbeAuthorization:
    base: Dict[str, Any] = dict(
        target_id=TARGET,
        profile_id="passive",
        hosted_mock=False,
        consent_id=CONSENT,
        proof_ceiling="exploited-in-test",
        explicit_approval=False,
        limits=pc.DEFAULT_LIMITS,
    )
    base.update(overrides)
    return pc.ProbeAuthorization(**base)


def _report_row(**overrides: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "id": "55555555-5555-4555-8555-555555555555",
        "tenant_id": TENANT,
        "target_id": TARGET,
        "target_slug": "staging",
        "target_environment": "staging",
        "target_network_class": "public",
        "target_base_url": "https://staging.example.com/api",
        "profile": "passive",
        "consent_id": CONSENT,
        "hosted_mock": False,
        "explicit_approval": False,
        "proof_ceiling": "exploited-in-test",
        "limits": pc.DEFAULT_LIMITS.as_dict(),
        "count_suspected": 0,
        "count_observed": 1,
        "count_exploited_in_test": 1,
        "evidence_run_id": None,
        "created_at": NOW,
        "created_by": USER,
        "actor_label": "ops@example.com",
        "actor_kind": "user",
        "report": {"findings": []},
    }
    row.update(overrides)
    return row


def test_saving_a_report_writes_the_snapshot_and_counts() -> None:
    fake = _FakeDb([_report_row()])
    with patch.object(store, "db", fake):
        record = store.save_report(
            TENANT, _target(), _authorization(),
            counts={"observed": 1, "exploited-in-test": 1}, report={"findings": []}, actor=ACTOR,
        )
    assert record.count_exploited_in_test == 1
    assert record.report == {"findings": []}
    params = fake.statements[0][1]
    assert params[2:6] == ("staging", "staging", "public", "https://staging.example.com/api")
    assert params[12:15] == (0, 1, 1)


def test_a_mock_report_cannot_claim_an_exploit() -> None:
    fake = _FakeDb()
    with patch.object(store, "db", fake), pytest.raises(store.ProbeConsentStoreError) as excinfo:
        store.save_report(
            TENANT, _target(), _authorization(hosted_mock=True, consent_id=None, proof_ceiling="observed"),
            counts={"exploited-in-test": 1}, report={}, actor=ACTOR,
        )
    assert excinfo.value.code == store.CODE_REPORT_INVALID
    assert fake.statements == []


def test_negative_counts_are_refused() -> None:
    with patch.object(store, "db", _FakeDb()), pytest.raises(store.ProbeConsentStoreError):
        store.save_report(
            TENANT, _target(), _authorization(), counts={"observed": -1}, report={}, actor=ACTOR
        )


def test_listing_reports_filters_and_bounds() -> None:
    row = _report_row()
    row.pop("report")
    fake = _FakeDb([row])
    with patch.object(store, "db", fake):
        reports = store.list_reports(TENANT, target_id=TARGET, limit=10_000)
    assert reports[0].target_slug == "staging"
    sql, params = fake.statements[0]
    assert "target_id = %s::uuid" in sql
    assert params == (TENANT, TARGET, store.MAX_LIST_LIMIT)


def test_listing_with_malformed_ids_is_empty_without_a_query() -> None:
    fake = _FakeDb()
    with patch.object(store, "db", fake):
        assert store.list_reports("t1") == []
        assert store.list_reports(TENANT, target_id="staging") == []
    assert fake.statements == []


def test_reading_a_missing_report_is_not_found() -> None:
    with patch.object(store, "db", _FakeDb([])), pytest.raises(store.ProbeConsentStoreError) as excinfo:
        store.get_report(TENANT, "55555555-5555-4555-8555-555555555555")
    assert excinfo.value.code == store.CODE_REPORT_NOT_FOUND
