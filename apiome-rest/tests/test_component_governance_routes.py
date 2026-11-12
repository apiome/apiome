"""Component governance API — DCW-3.4 (private-suite#2364).

The publish approval gate, stage-bound decisions, scheduled deprecation with affected projects
and guidance, the bulk-upgrade preview (compatibility via the CTG classifier) and its explicit
confirmation, and the admin-only audit export. One ``db`` mock is patched into every module the
routes read through, so a test scripts one storage plane.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.component_governance import plan_bulk_upgrade, upgrade_confirmation_token
from app.database import ComponentLibraryConflictError
from app.main import app

client = TestClient(app)

_MOCK_JWT = {"tenant_id": "t1", "user_id": "user-a", "auth_method": "jwt"}
COMPONENT_ID = "11111111-1111-4111-8111-111111111111"
REVISION_ID = "22222222-2222-4222-8222-222222222222"
TARGET_ID = "33333333-3333-4333-8333-333333333333"
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)

_BASE = "/v1/component-library/tn"
_COMPONENT = f"{_BASE}/components/{COMPONENT_ID}"
_REVISION = f"{_COMPONENT}/revisions/{REVISION_ID}"

_COMPONENT_ROW = {"id": COMPONENT_ID, "name": "PageParam", "kind": "parameter"}
_DRAFT = {
    "id": REVISION_ID,
    "revision": "1.1.0",
    "state": "draft",
    "payload_digest": "sha256:draft",
    "canonical_payload": {"name": "page", "in": "query"},
}
_PUBLISHED = dict(_DRAFT, revision="1.0.0", state="published", payload_digest="sha256:old")
_TARGET = dict(
    _DRAFT,
    id=TARGET_ID,
    revision="2.0.0",
    state="published",
    payload_digest="sha256:new",
    canonical_payload={"name": "pageNumber", "in": "query"},
)
_GUIDE = {
    "id": "g1",
    "name": "Governed",
    "component_approval_stages": [
        {"name": "Platform", "requiredApprovals": 1},
        {"name": "Security", "requiredApprovals": 1, "requiredReviewerRole": "security"},
    ],
    "component_deprecation_notice_days": 30,
}
_CONSUMERS = [
    {
        "pin_id": "p1",
        "local_name": None,
        "version_id": "v1",
        "version_label": "1.0",
        "published": False,
        "project_id": "proj1",
        "project_name": "Orders",
        "revision_id": REVISION_ID,
        "revision": "1.0.0",
    },
    {
        "pin_id": "p2",
        "local_name": None,
        "version_id": "v2",
        "version_label": "2.0",
        "published": True,
        "project_id": "proj2",
        "project_name": "Billing",
        "revision_id": REVISION_ID,
        "revision": "1.0.0",
    },
]


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: dict(_MOCK_JWT)
    yield
    app.dependency_overrides.pop(validate_authentication, None)


@contextmanager
def storage(*, guide=_GUIDE, revisions=(_DRAFT,), decisions=(), allowed=True, admin=True):
    """Patch one scripted ``db`` into every module the governance routes read through."""
    mdb = MagicMock()
    mdb.user_has_permission.return_value = allowed
    mdb.is_user_tenant_admin.return_value = admin
    mdb.get_assigned_style_guide.return_value = guide
    mdb.get_operational_component.return_value = _COMPONENT_ROW
    mdb.get_component_revisions.return_value = [dict(r) for r in revisions]
    mdb.list_component_revision_approvals.return_value = [dict(d) for d in decisions]
    mdb.get_effective_role_slug.side_effect = lambda _t, user: (
        "security" if user == "sec" else "editor"
    )
    with patch("app.component_governance_routes.db", mdb), patch(
        "app.component_governance_service.db", mdb
    ), patch("app.component_library_routes.db", mdb), patch(
        "app.component_governance_routes._now", return_value=NOW
    ):
        yield mdb


def _decision(stage, user, digest="sha256:draft", decision="approve"):
    return {
        "id": f"{stage}-{user}",
        "stage_index": stage,
        "stage_name": "Platform" if stage == 0 else "Security",
        "user_id": user,
        "user_email": f"{user}@example.com",
        "decision": decision,
        "note": None,
        "payload_digest": digest,
        "created_at": NOW,
    }


class TestPolicy:
    def test_reads_the_component_policy_from_the_governing_guide(self):
        with storage() as mdb:
            body = client.get(f"{_BASE}/governance/policy").json()
        assert body["guideName"] == "Governed"
        assert [s["name"] for s in body["approvalStages"]] == ["Platform", "Security"]
        assert body["deprecationNoticeDays"] == 30
        mdb.get_assigned_style_guide.assert_called_with("t1", None)


class TestPublishGate:
    def test_unsatisfied_policy_blocks_publish(self):
        with storage(decisions=[_decision(0, "u1")]) as mdb:
            r = client.post(f"{_REVISION}/publish")
        assert r.status_code == 409
        detail = r.json()["detail"]
        assert detail["code"] == "APPROVAL_REQUIRED"
        assert detail["approval"]["currentStage"] == 1
        assert detail["message"] == "'Security' has 0 of 1 required approval(s)."
        mdb.publish_component_revision.assert_not_called()

    def test_satisfied_policy_publishes_with_the_judged_digest(self):
        with storage(decisions=[_decision(0, "u1"), _decision(1, "sec")]) as mdb:
            mdb.publish_component_revision.return_value = {
                "published": True,
                "alreadyPublished": False,
                "revision": "1.1.0",
            }
            r = client.post(f"{_REVISION}/publish")
        assert r.status_code == 200
        kwargs = mdb.publish_component_revision.call_args.kwargs
        assert kwargs["expected_digest"] == "sha256:draft"
        assert kwargs["approval"]["status"] == "satisfied"

    def test_no_policy_publishes_as_before(self):
        with storage(guide=None) as mdb:
            mdb.publish_component_revision.return_value = {"published": True, "revision": "1.1.0"}
            r = client.post(f"{_REVISION}/publish")
        assert r.status_code == 200
        kwargs = mdb.publish_component_revision.call_args.kwargs
        assert kwargs["expected_digest"] is None and kwargs["approval"] is None
        mdb.list_component_revision_approvals.assert_not_called()

    def test_republish_stays_idempotent(self):
        with storage(revisions=[_PUBLISHED]) as mdb:
            mdb.publish_component_revision.return_value = {
                "published": True,
                "alreadyPublished": True,
                "revision": "1.0.0",
            }
            r = client.post(f"{_REVISION}/publish")
        assert r.status_code == 200
        assert r.json()["alreadyPublished"] is True

    def test_stale_payload_answers_409(self):
        with storage(decisions=[_decision(0, "u1"), _decision(1, "sec")]) as mdb:
            mdb.publish_component_revision.side_effect = ComponentLibraryConflictError(
                "approval_stale", {"payloadDigest": "sha256:edited"}
            )
            r = client.post(f"{_REVISION}/publish")
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "APPROVAL_STALE"

    def test_policy_read_failure_fails_closed(self):
        failing = TestClient(app, raise_server_exceptions=False)
        with storage() as mdb:
            mdb.get_assigned_style_guide.side_effect = RuntimeError("db down")
            r = failing.post(f"{_REVISION}/publish")
        assert r.status_code == 500
        mdb.publish_component_revision.assert_not_called()


class TestApprovals:
    def test_assessment_and_history_mark_stale_decisions(self):
        with storage(decisions=[_decision(0, "u1", digest="sha256:before")]):
            body = client.get(f"{_REVISION}/approval").json()
        assert body["assessment"]["staleDecisions"] == 1
        assert body["assessment"]["currentStage"] == 0
        assert body["decisions"][0]["stale"] is True
        assert body["decisions"][0]["userEmail"] == "u1@example.com"

    def test_records_on_the_current_stage(self):
        with storage() as mdb:
            r = client.post(f"{_REVISION}/approval", json={"decision": "approve", "note": " ok "})
        assert r.status_code == 200
        kwargs = mdb.record_component_revision_approval.call_args.kwargs
        assert kwargs["stage_index"] == 0
        assert kwargs["stage_name"] == "Platform"
        assert kwargs["note"] == "ok"
        assert kwargs["expected_digest"] == "sha256:draft"
        assert kwargs["actor_id"] == "user-a"

    def test_refuses_a_stage_that_is_not_current(self):
        with storage() as mdb:
            r = client.post(f"{_REVISION}/approval", json={"decision": "approve", "stage": 1})
        assert r.status_code == 409
        assert r.json()["detail"] == {
            "code": "STAGE_NOT_CURRENT",
            "message": "Decisions are recorded on the current approval stage only.",
            "currentStage": 0,
        }
        mdb.record_component_revision_approval.assert_not_called()

    def test_no_policy_means_nothing_to_approve(self):
        with storage(guide=None) as mdb:
            r = client.post(f"{_REVISION}/approval", json={"decision": "approve"})
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "APPROVAL_NOT_REQUIRED"
        mdb.record_component_revision_approval.assert_not_called()

    def test_published_revisions_take_no_decisions(self):
        with storage(revisions=[_PUBLISHED]) as mdb:
            r = client.post(f"{_REVISION}/approval", json={"decision": "approve"})
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "PUBLISHED_IMMUTABLE"
        mdb.record_component_revision_approval.assert_not_called()

    def test_requires_types_edit(self):
        with storage(allowed=False) as mdb:
            r = client.post(f"{_REVISION}/approval", json={"decision": "approve"})
        assert r.status_code == 403
        mdb.record_component_revision_approval.assert_not_called()

    def test_rejects_unknown_decisions(self):
        with storage():
            r = client.post(f"{_REVISION}/approval", json={"decision": "pending"})
        assert r.status_code == 422

    def test_other_tenant_revision_is_404(self):
        with storage(revisions=()):
            r = client.get(f"{_REVISION}/approval")
        assert r.status_code == 404


class TestDeprecation:
    def _schedule(self, mdb, days=45):
        mdb.schedule_component_deprecation.return_value = {
            "deprecationId": "dep-1",
            "revision": "1.0.0",
            "replacementRevision": "2.0.0",
            "componentName": "PageParam",
            "affected": _CONSUMERS,
        }
        return client.post(
            f"{_REVISION}/deprecation",
            json={
                "sunsetAt": (NOW + timedelta(days=days)).isoformat(),
                "replacementRevisionId": TARGET_ID,
                "migrationGuide": "Rename page to pageNumber.",
            },
        )

    def test_schedule_returns_affected_projects_and_guidance(self):
        with storage(revisions=[_PUBLISHED, _TARGET]) as mdb:
            r = self._schedule(mdb)
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "scheduled"
        assert [p["projectName"] for p in body["affectedProjects"]] == ["Orders", "Billing"]
        assert body["guidance"]["draftVersions"] == 1
        assert body["guidance"]["publishedVersions"] == 1
        assert "PageParam@2.0.0" in body["guidance"]["summary"]
        kwargs = mdb.schedule_component_deprecation.call_args.kwargs
        assert kwargs["policy"]["noticeDays"] == 30

    def test_notice_window_is_enforced(self):
        with storage() as mdb:
            r = self._schedule(mdb, days=10)
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "SUNSET_INVALID"
        assert r.json()["detail"]["noticeDays"] == 30
        mdb.schedule_component_deprecation.assert_not_called()

    def test_requires_types_publish(self):
        with storage(allowed=False) as mdb:
            r = self._schedule(mdb)
        assert r.status_code == 403
        mdb.schedule_component_deprecation.assert_not_called()

    def test_conflicts_pass_through(self):
        with storage() as mdb:
            mdb.schedule_component_deprecation.side_effect = ComponentLibraryConflictError(
                "deprecation_exists"
            )
            r = client.post(
                f"{_REVISION}/deprecation",
                json={"sunsetAt": (NOW + timedelta(days=60)).isoformat()},
            )
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "DEPRECATION_EXISTS"

    def test_list_reports_sunset_status(self):
        with storage() as mdb:
            mdb.list_component_deprecations.return_value = [
                {
                    "id": "dep-1",
                    "component_id": COMPONENT_ID,
                    "component_name": "PageParam",
                    "kind": "parameter",
                    "revision_id": REVISION_ID,
                    "revision": "1.0.0",
                    "replacement_revision_id": None,
                    "replacement_revision": None,
                    "sunset_at": NOW - timedelta(days=1),
                    "migration_guide": None,
                }
            ]
            mdb.get_component_consumers.return_value = _CONSUMERS[:1]
            body = client.get(f"{_BASE}/deprecations").json()
        entry = body["deprecations"][0]
        assert entry["status"] == "sunset"
        assert entry["affectedProjects"][0]["version"] == "1.0"

    def test_cancel(self):
        with storage() as mdb:
            r = client.delete(f"{_COMPONENT}/deprecations/dep-1")
        assert r.status_code == 200
        assert mdb.cancel_component_deprecation.call_args.args[:3] == ("t1", COMPONENT_ID, "dep-1")

    def test_sunset_pin_answers_409(self):
        with storage() as mdb:
            mdb.get_version_by_id.return_value = {"id": "v1", "project_id": "proj"}
            mdb.create_version_component_pin.side_effect = ComponentLibraryConflictError(
                "revision_sunset", {"revision": "1.0.0"}
            )
            r = client.post(
                f"{_BASE}/projects/proj/versions/v1/pins",
                json={"componentRevisionId": REVISION_ID},
            )
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "REVISION_SUNSET"


class TestUpgradePreview:
    def test_preview_classifies_eligible_versions_and_skips_published(self):
        classified = MagicMock()
        classified.changes = [MagicMock(model_dump=lambda **_: {"pointer": "/x"})]
        classified.counts = {"breaking": 1, "total": 1}
        classified.max_severity = "breaking"
        with storage(revisions=[_PUBLISHED, _TARGET]) as mdb, patch(
            "app.component_governance_routes.openapi_for_revision", return_value={}
        ) as build, patch(
            "app.component_governance_routes.classify_openapi_changes", return_value=classified
        ):
            mdb.get_component_consumers.return_value = _CONSUMERS
            mdb.get_version_by_id.return_value = {"id": "v1", "project_id": "proj1"}
            mdb.get_materializable_pins_for_version.return_value = [
                {"revision_id": REVISION_ID, "payload": {"name": "page"}, "revision": "1.0.0"}
            ]
            r = client.post(f"{_COMPONENT}/upgrades/preview", json={"targetRevisionId": TARGET_ID})
        assert r.status_code == 200
        body = r.json()
        assert body["eligible"] == 1 and body["skipped"] == 1 and body["breaking"] == 1
        assert [e["status"] for e in body["entries"]] == ["eligible", "published-version"]
        assert body["entries"][0]["compatibility"]["maxSeverity"] == "breaking"
        assert body["entries"][1]["compatibility"] == {"status": "not-applicable"}
        assert body["confirmationToken"] == upgrade_confirmation_token(
            COMPONENT_ID, TARGET_ID, plan_bulk_upgrade(_CONSUMERS, TARGET_ID)
        )
        head_rows = build.call_args_list[1].kwargs["component_pin_rows"]
        assert head_rows[0]["payload"] == {"name": "pageNumber", "in": "query"}
        assert head_rows[0]["revision_id"] == TARGET_ID
        mdb.execute_component_bulk_upgrade.assert_not_called()

    def test_identical_payload_is_no_changes_without_building_documents(self):
        same = dict(_TARGET, payload_digest="sha256:old")
        with storage(revisions=[_PUBLISHED, same]) as mdb, patch(
            "app.component_governance_routes.openapi_for_revision"
        ) as build:
            mdb.get_component_consumers.return_value = _CONSUMERS[:1]
            body = client.post(
                f"{_COMPONENT}/upgrades/preview", json={"targetRevisionId": TARGET_ID}
            ).json()
        assert body["entries"][0]["compatibility"]["status"] == "no-changes"
        build.assert_not_called()

    def test_document_failure_is_unavailable_not_safe(self):
        with storage(revisions=[_PUBLISHED, _TARGET]) as mdb, patch(
            "app.component_governance_routes.openapi_for_revision", side_effect=RuntimeError()
        ):
            mdb.get_component_consumers.return_value = _CONSUMERS[:1]
            mdb.get_version_by_id.return_value = {"id": "v1"}
            body = client.post(
                f"{_COMPONENT}/upgrades/preview", json={"targetRevisionId": TARGET_ID}
            ).json()
        assert body["entries"][0]["compatibility"]["status"] == "unavailable"

    def test_target_must_be_published(self):
        with storage(revisions=[_DRAFT]):
            r = client.post(
                f"{_COMPONENT}/upgrades/preview", json={"targetRevisionId": REVISION_ID}
            )
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "REVISION_NOT_PUBLISHED"


class TestUpgradeExecute:
    def _body(self, **overrides):
        body = {
            "targetRevisionId": TARGET_ID,
            "pinIds": ["p1", "p1"],
            "confirmationToken": "sha256:tok",
            "confirm": True,
        }
        body.update(overrides)
        return body

    def test_requires_explicit_confirmation(self):
        with storage(revisions=[_TARGET]) as mdb:
            r = client.post(f"{_COMPONENT}/upgrades", json=self._body(confirm=False))
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "CONFIRMATION_REQUIRED"
        mdb.execute_component_bulk_upgrade.assert_not_called()

    def test_runs_the_previewed_plan(self):
        with storage(revisions=[_TARGET]) as mdb:
            mdb.execute_component_bulk_upgrade.return_value = {
                "targetRevision": "2.0.0",
                "upgraded": [{"pinId": "p1", "newPinId": "n1"}],
                "affected": [
                    {"projectId": "proj1", "projectName": "Orders", "versionId": "v1",
                     "version": "1.0", "published": False, "revision": "1.0.0"}
                ],
            }
            r = client.post(f"{_COMPONENT}/upgrades", json=self._body())
        assert r.status_code == 200
        assert r.json()["affectedProjects"][0]["projectName"] == "Orders"
        args = mdb.execute_component_bulk_upgrade.call_args
        assert args.args[3] == ["p1"]  # de-duplicated
        assert args.kwargs["confirmation_token"] == "sha256:tok"

    def test_stale_plan_answers_409(self):
        with storage(revisions=[_TARGET]) as mdb:
            mdb.execute_component_bulk_upgrade.side_effect = ComponentLibraryConflictError(
                "upgrade_plan_stale"
            )
            r = client.post(f"{_COMPONENT}/upgrades", json=self._body())
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "UPGRADE_PLAN_STALE"

    def test_requires_versions_edit_and_pins(self):
        with storage(allowed=False, revisions=[_TARGET]) as mdb:
            assert client.post(f"{_COMPONENT}/upgrades", json=self._body()).status_code == 403
        with storage(revisions=[_TARGET]):
            assert client.post(
                f"{_COMPONENT}/upgrades", json=self._body(pinIds=[])
            ).status_code == 422
        mdb.execute_component_bulk_upgrade.assert_not_called()


class TestAuditExport:
    _ROW = {
        "created_at": NOW,
        "action": "pin.upgrade",
        "outcome": "success",
        "actor_id": "user-a",
        "actor_email": "a@example.com",
        "component_id": COMPONENT_ID,
        "component_name": "PageParam",
        "detail": {
            "policy": {"approvalStages": []},
            "oldRevision": "1.0.0",
            "newRevision": "2.0.0",
            "affectedProjects": [{"projectId": "proj1"}],
        },
    }

    def test_json_export_has_every_audit_field(self):
        with storage() as mdb:
            mdb.list_component_library_audit.return_value = [self._ROW]
            body = client.get(f"{_BASE}/audit/export").json()
        row = body["rows"][0]
        for key in ("actorId", "policy", "oldRevision", "newRevision", "affectedProjects",
                    "decision", "timestamp"):
            assert key in row
        assert row["decision"] == "upgraded"
        assert body["truncated"] is False

    def test_csv_export(self):
        with storage() as mdb:
            mdb.list_component_library_audit.return_value = [self._ROW]
            r = client.get(f"{_BASE}/audit/export?format=csv&componentId={COMPONENT_ID}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert "attachment" in r.headers["content-disposition"]
        assert r.text.splitlines()[0].startswith("timestamp,action,decision,actorId")
        assert mdb.list_component_library_audit.call_args.kwargs["component_id"] == COMPONENT_ID

    def test_truncation_is_reported(self):
        with storage() as mdb, patch(
            "app.component_governance_routes.MAX_AUDIT_EXPORT_ROWS", 1
        ):
            mdb.list_component_library_audit.return_value = [self._ROW, self._ROW]
            body = client.get(f"{_BASE}/audit/export").json()
        assert body["truncated"] is True and len(body["rows"]) == 1

    def test_tenant_admins_only(self):
        with storage(admin=False) as mdb:
            r = client.get(f"{_BASE}/audit/export")
        assert r.status_code == 403
        mdb.list_component_library_audit.assert_not_called()
