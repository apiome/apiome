"""Component governance domain rules — DCW-3.4 (private-suite#2364).

Pure rules: stage normalization and validation, the sequential multi-stage assessment (stale
decisions, request-changes, required roles), deprecation status and notice windows, migration
guidance, bulk-upgrade planning and its confirmation token, and the audit export shape.
"""

import csv
import io
from datetime import datetime, timedelta, timezone

from app.component_governance import (
    AUDIT_EXPORT_COLUMNS,
    DEPRECATION_SCHEDULED,
    DEPRECATION_SUNSET,
    SKIP_ALREADY_ON_TARGET,
    SKIP_PUBLISHED_VERSION,
    SKIP_TARGET_ALREADY_PINNED,
    STAGE_CHANGES_REQUESTED,
    STAGE_CURRENT,
    STAGE_SATISFIED,
    STAGE_WAITING,
    STATUS_BLOCKED,
    STATUS_DISABLED,
    STATUS_SATISFIED,
    UPGRADE_ELIGIBLE,
    ComponentApprovalStage,
    ComponentGovernancePolicy,
    assess_component_approval,
    audit_export_row,
    deprecation_status,
    migration_guidance,
    normalize_approval_stages,
    normalize_deprecation_notice_days,
    plan_bulk_upgrade,
    render_audit_csv,
    upgrade_confirmation_token,
    validate_approval_stages,
    validate_sunset,
)

DIGEST = "sha256:current"
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)

TWO_STAGES = ComponentGovernancePolicy(
    stages=(
        ComponentApprovalStage("Platform review", 2),
        ComponentApprovalStage("Security", 1, "security"),
    )
)


def _decision(stage, user, decision="approve", digest=DIGEST):
    return {"stage_index": stage, "user_id": user, "decision": decision, "payload_digest": digest}


def _no_role(_user_id):
    return None


class TestStageNormalization:
    def test_stored_stages_degrade_instead_of_failing(self):
        stages = normalize_approval_stages(
            [
                {"name": " Platform ", "requiredApprovals": 2, "requiredReviewerRole": " Admin "},
                {"name": "", "requiredApprovals": 1},
                {"name": "No-op", "requiredApprovals": 0},
                "junk",
            ]
        )
        assert [s.as_payload() for s in stages] == [
            {"name": "Platform", "requiredApprovals": 2, "requiredReviewerRole": "admin"},
            {"name": "Stage 2", "requiredApprovals": 1, "requiredReviewerRole": None},
        ]

    def test_json_text_and_junk(self):
        assert len(normalize_approval_stages('[{"name": "A", "requiredApprovals": 1}]')) == 1
        assert normalize_approval_stages("not json") == []
        assert normalize_approval_stages(None) == []

    def test_caps_at_five_stages(self):
        raw = [{"name": f"S{i}", "requiredApprovals": 1} for i in range(8)]
        assert len(normalize_approval_stages(raw)) == 5

    def test_policy_from_guide_row(self):
        policy = ComponentGovernancePolicy.from_guide(
            {
                "id": "g1",
                "name": "Guide",
                "component_approval_stages": [{"name": "A", "requiredApprovals": 1}],
                "component_deprecation_notice_days": 30,
            }
        )
        assert policy.approval_active
        assert policy.as_payload() == {
            "guideId": "g1",
            "guideName": "Guide",
            "approvalStages": [
                {"name": "A", "requiredApprovals": 1, "requiredReviewerRole": None}
            ],
            "deprecationNoticeDays": 30,
        }
        assert not ComponentGovernancePolicy.from_guide(None).approval_active

    def test_notice_days_are_clamped(self):
        assert normalize_deprecation_notice_days(400) == 365
        assert normalize_deprecation_notice_days(-3) == 0
        assert normalize_deprecation_notice_days("x") == 0
        assert normalize_deprecation_notice_days(True) == 0


class TestStageValidation:
    def test_valid_stages(self):
        stages, errors = validate_approval_stages(
            [{"name": "Platform", "requiredApprovals": 2, "requiredReviewerRole": None}]
        )
        assert errors == []
        assert stages[0].required_approvals == 2

    def test_reports_every_problem(self):
        _stages, errors = validate_approval_stages(
            [
                {"name": "", "requiredApprovals": 1},
                {"name": "A", "requiredApprovals": 0},
                {"name": "B", "requiredApprovals": True},
                {"name": "C", "requiredApprovals": 1},
                {"name": "c", "requiredApprovals": 1},
            ]
        )
        assert errors == [
            "Stage 1 needs a name.",
            "Stage 2 requiredApprovals must be a whole number from 1 to 20.",
            "Stage 3 requiredApprovals must be a whole number from 1 to 20.",
            "Stage 5 repeats the name 'c'.",
        ]

    def test_too_many_stages_and_bad_role(self):
        raw = [{"name": f"S{i}", "requiredApprovals": 1} for i in range(6)]
        raw[0]["requiredReviewerRole"] = "x" * 70
        _stages, errors = validate_approval_stages(raw)
        assert "At most 5 approval stages are supported." in errors
        assert "Stage 1 requiredReviewerRole is not a valid role slug." in errors

    def test_not_a_list(self):
        assert validate_approval_stages({"name": "A"}) == (
            [],
            ["componentApprovalStages must be a list."],
        )


class TestAssessment:
    def test_no_stages_is_disabled(self):
        result = assess_component_approval(ComponentGovernancePolicy(), [], DIGEST, _no_role)
        assert result.status == STATUS_DISABLED
        assert not result.blocked

    def test_first_stage_is_current_and_later_stages_wait(self):
        result = assess_component_approval(TWO_STAGES, [_decision(0, "u1")], DIGEST, _no_role)
        assert result.status == STATUS_BLOCKED
        assert result.current_stage == 0
        assert [s["status"] for s in result.stages] == [STAGE_CURRENT, STAGE_WAITING]
        assert result.message() == "'Platform review' has 1 of 2 required approval(s)."

    def test_stages_are_sequential(self):
        decisions = [_decision(0, "u1"), _decision(0, "u2"), _decision(1, "sec")]
        result = assess_component_approval(
            TWO_STAGES, decisions, DIGEST, lambda user: "security" if user == "sec" else None
        )
        assert result.status == STATUS_SATISFIED
        assert [s["status"] for s in result.stages] == [STAGE_SATISFIED, STAGE_SATISFIED]
        assert result.stages[1]["roleApprovals"] == 1

    def test_required_role_must_be_present(self):
        decisions = [_decision(0, "u1"), _decision(0, "u2"), _decision(1, "u3")]
        result = assess_component_approval(TWO_STAGES, decisions, DIGEST, _no_role)
        assert result.current_stage == 1
        assert result.stages[1]["approvals"] == 1
        assert result.message() == "'Security' needs an approval from a reviewer with the 'security' role."

    def test_request_changes_blocks_the_stage(self):
        decisions = [_decision(0, "u1"), _decision(0, "u2"), _decision(0, "u3", "request_changes")]
        result = assess_component_approval(TWO_STAGES, decisions, DIGEST, _no_role)
        assert result.stages[0]["status"] == STAGE_CHANGES_REQUESTED
        assert result.current_stage == 0
        assert "requested changes" in result.message()

    def test_decisions_on_an_earlier_payload_are_stale(self):
        decisions = [_decision(0, "u1", digest="sha256:old"), _decision(0, "u2", digest="sha256:old")]
        result = assess_component_approval(TWO_STAGES, decisions, DIGEST, _no_role)
        assert result.stale_decisions == 2
        assert result.stages[0]["approvals"] == 0
        assert result.blocked

    def test_role_lookup_only_when_a_stage_requires_one(self):
        calls = []

        def role_of(user):
            calls.append(user)
            return None

        policy = ComponentGovernancePolicy(stages=(ComponentApprovalStage("A", 1),))
        assess_component_approval(policy, [_decision(0, "u1")], DIGEST, role_of)
        assert calls == []

    def test_payload_shape(self):
        payload = assess_component_approval(TWO_STAGES, [], DIGEST, _no_role).as_payload()
        assert payload["blocked"] is True
        assert payload["currentStage"] == 0
        assert payload["policy"]["approvalStages"][1]["requiredReviewerRole"] == "security"


class TestDeprecation:
    def test_status(self):
        assert deprecation_status(NOW + timedelta(days=1), NOW) == DEPRECATION_SCHEDULED
        assert deprecation_status(NOW, NOW) == DEPRECATION_SUNSET
        assert deprecation_status(datetime(2026, 1, 1), NOW) == DEPRECATION_SUNSET

    def test_sunset_must_be_future_and_respect_notice(self):
        assert validate_sunset(NOW - timedelta(minutes=1), NOW, 0) == (
            "The sunset date must be in the future."
        )
        assert validate_sunset(NOW + timedelta(days=10), NOW, 30) == (
            "The deprecation policy requires 30 day(s) of notice; the earliest sunset is "
            "2026-12-11."
        )
        assert validate_sunset(NOW + timedelta(days=31), NOW, 30) is None
        assert validate_sunset(NOW + timedelta(hours=1), NOW, 0) is None

    def test_guidance_names_drafts_and_published_versions(self):
        guidance = migration_guidance(
            component_name="PageParam",
            revision="1.0.0",
            sunset_at=NOW + timedelta(days=30),
            replacement_revision="2.0.0",
            guide="Rename `page` to `pageNumber`.",
            affected=[{"published": False}, {"published": False}, {"published": True}],
        )
        assert guidance["summary"] == (
            "PageParam@1.0.0 is deprecated and reaches its sunset on 2026-12-11. "
            "Move to PageParam@2.0.0."
        )
        assert guidance["draftVersions"] == 2
        assert guidance["publishedVersions"] == 1
        assert guidance["steps"][0].startswith("Upgrade the 2 draft version(s)")
        assert "published versions never change" in guidance["steps"][1]
        assert guidance["steps"][-1].startswith("After 2026-12-11, new pins")

    def test_guidance_without_replacement_or_consumers(self):
        guidance = migration_guidance(
            component_name="X",
            revision="1.0.0",
            sunset_at=NOW,
            replacement_revision=None,
            guide=None,
            affected=[],
        )
        assert guidance["replacementRevision"] is None
        assert guidance["guide"] is None
        assert len(guidance["steps"]) == 1


class TestBulkUpgrade:
    PINS = [
        {"pin_id": "p1", "version_id": "v1", "revision_id": "r1", "published": False},
        {"pin_id": "p2", "version_id": "v2", "revision_id": "r1", "published": True},
        {"pin_id": "p3", "version_id": "v3", "revision_id": "r2", "published": False},
        {"pin_id": "p4", "version_id": "v4", "revision_id": "r1", "published": False},
        {"pin_id": "p5", "version_id": "v4", "revision_id": "r2", "published": False},
    ]

    def test_plan_statuses(self):
        plan = plan_bulk_upgrade(self.PINS, "r2")
        assert [entry["status"] for entry in plan] == [
            UPGRADE_ELIGIBLE,
            SKIP_PUBLISHED_VERSION,
            SKIP_ALREADY_ON_TARGET,
            SKIP_TARGET_ALREADY_PINNED,
            SKIP_ALREADY_ON_TARGET,
        ]

    def test_token_binds_the_eligible_plan(self):
        plan = plan_bulk_upgrade(self.PINS, "r2")
        token = upgrade_confirmation_token("c1", "r2", plan)
        assert token.startswith("sha256:")
        assert token == upgrade_confirmation_token("c1", "r2", list(reversed(plan)))
        # A version published since the preview drops out of the eligible set.
        changed = [dict(p, published=True) if p["pin_id"] == "p1" else p for p in self.PINS]
        assert token != upgrade_confirmation_token("c1", "r2", plan_bulk_upgrade(changed, "r2"))
        assert token != upgrade_confirmation_token("c1", "r3", plan)


class TestAuditExport:
    def test_governance_row(self):
        row = audit_export_row(
            {
                "created_at": NOW,
                "action": "upgrade.bulk",
                "actor_id": "u1",
                "actor_email": "admin@example.com",
                "component_id": "c1",
                "component_name": "PageParam",
                "outcome": "success",
                "detail": {
                    "policy": {"approvalStages": []},
                    "oldRevision": ["1.0.0"],
                    "newRevision": "2.0.0",
                    "affectedProjects": [{"projectId": "p1"}, "junk"],
                },
            }
        )
        assert row == {
            "timestamp": "2026-11-11T12:00:00+00:00",
            "action": "upgrade.bulk",
            "decision": "upgraded",
            "actorId": "u1",
            "actorEmail": "admin@example.com",
            "componentId": "c1",
            "componentName": "PageParam",
            "policy": {"approvalStages": []},
            "oldRevision": ["1.0.0"],
            "newRevision": "2.0.0",
            "affectedProjects": [{"projectId": "p1"}],
            "outcome": "success",
        }

    def test_dcw_3_1_publish_rows_map_their_revision_keys(self):
        row = audit_export_row(
            {"action": "revision.publish", "detail": {"revision": "1.1.0", "previousHead": "1.0.0"}}
        )
        assert row["oldRevision"] == "1.0.0"
        assert row["newRevision"] == "1.1.0"
        assert row["decision"] == "published"
        assert row["affectedProjects"] == []

    def test_explicit_decision_wins(self):
        row = audit_export_row({"action": "revision.approval", "detail": {"decision": "approve"}})
        assert row["decision"] == "approve"

    def test_csv_has_header_json_cells_and_formula_guard(self):
        rows = [
            audit_export_row(
                {
                    "action": "pin.upgrade",
                    "actor_email": "=HYPERLINK(1)",
                    "detail": {"affectedProjects": [{"projectId": "p1"}], "newRevision": "2.0.0"},
                }
            )
        ]
        parsed = list(csv.reader(io.StringIO(render_audit_csv(rows))))
        assert tuple(parsed[0]) == AUDIT_EXPORT_COLUMNS
        record = dict(zip(parsed[0], parsed[1]))
        assert record["actorEmail"] == "'=HYPERLINK(1)"
        assert record["affectedProjects"] == '[{"projectId":"p1"}]'
        assert record["newRevision"] == "2.0.0"
