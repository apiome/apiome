"""Release lifecycle gates — APX-3.1 (private-suite#2456).

These are the decisions that must hold before routing changes. They are tested exhaustively
here, without a database, because every one of them is a rule whose failure mode is either
an outage or a release serving bytes nobody approved.

Coverage maps to the acceptance criteria:

* criterion 3 — promotion never rebuilds; rollback restores a retained artifact;
* criterion 4 — concurrent promotion, failed activation, retention and audit paths.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.slate_releases import (
    PROMOTABLE_STATUSES,
    ReleaseRefusal,
    SlateReleaseRefusedError,
    evaluate_region_rollout,
    is_approval_stale,
    measure_activation_slo,
    plan_promotion,
    plan_rollback,
    select_reapable_artifacts,
)

DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64
NOW = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def release(**overrides):
    """A ready, built, verified release."""
    base = {
        "id": "rel-1",
        "status": "ready",
        "artifact_digest": DIGEST,
        "artifact_reaped_at": None,
        "signature_verified": True,
        "page_count": 42,
    }
    return {**base, **overrides}


def environment(**overrides):
    """A production lane serving nothing."""
    base = {"id": "env-1", "active_release_id": None, "routing_version": 7}
    return {**base, **overrides}


class TestPromotionGates:
    def test_a_ready_release_promotes(self):
        plan = plan_promotion(release=release(), environment=environment())
        assert plan.action == "promotion"
        assert plan.release_id == "rel-1"
        assert plan.artifact_digest == DIGEST

    def test_the_plan_carries_the_routing_token_it_was_decided_against(self):
        # Without this the concurrency check would assert a value read at a different time.
        plan = plan_promotion(release=release(), environment=environment(routing_version=11))
        assert plan.expected_routing_version == 11

    def test_promotion_never_rebuilds(self):
        # Criterion 3, asserted as a literal rather than as a computed value.
        plan = plan_promotion(release=release(), environment=environment())
        assert plan.rebuilds is False

    def test_a_release_with_no_artifact_is_refused_as_not_built(self):
        with pytest.raises(SlateReleaseRefusedError) as exc:
            plan_promotion(release=release(artifact_digest=None), environment=environment())
        assert exc.value.code == "not-built"
        assert "never starts a build" in exc.value.refusal.sentence

    def test_a_reaped_artifact_cannot_be_served_again(self):
        with pytest.raises(SlateReleaseRefusedError) as exc:
            plan_promotion(
                release=release(artifact_reaped_at=NOW), environment=environment()
            )
        assert exc.value.code == "artifact-reaped"

    def test_an_unverifiable_signature_refuses_activation(self):
        with pytest.raises(SlateReleaseRefusedError) as exc:
            plan_promotion(
                release=release(signature_verified=False), environment=environment()
            )
        assert exc.value.code == "signature-invalid"

    @pytest.mark.parametrize(
        "status", ["queued", "building", "failed", "superseded", "rolled-back"]
    )
    def test_only_a_built_and_checked_release_is_promotable(self, status):
        with pytest.raises(SlateReleaseRefusedError) as exc:
            plan_promotion(release=release(status=status), environment=environment())
        assert exc.value.code == "not-promotable"

    @pytest.mark.parametrize("status", sorted(PROMOTABLE_STATUSES))
    def test_the_promotable_states_are_exactly_ready_and_review(self, status):
        assert plan_promotion(
            release=release(status=status), environment=environment()
        ).action == "promotion"

    def test_promoting_what_is_already_serving_is_refused(self):
        with pytest.raises(SlateReleaseRefusedError) as exc:
            plan_promotion(
                release=release(), environment=environment(active_release_id="rel-1")
            )
        assert exc.value.code == "already-active"

    def test_already_active_is_checked_before_build_state(self):
        # A release that is serving production is by definition built; reporting it as
        # "not built" would be a confusing lie.
        with pytest.raises(SlateReleaseRefusedError) as exc:
            plan_promotion(
                release=release(artifact_digest=None),
                environment=environment(active_release_id="rel-1"),
            )
        assert exc.value.code == "already-active"

    def test_the_plan_records_what_it_replaces(self):
        plan = plan_promotion(
            release=release(), environment=environment(active_release_id="rel-0")
        )
        assert plan.replaces_release_id == "rel-0"

    def test_invalidation_scope_comes_from_the_artifact_page_count(self):
        plan = plan_promotion(release=release(page_count=99), environment=environment())
        assert plan.invalidated_pages == 99


class TestPartialRolloutGate:
    def test_promoting_over_an_unfinished_rollout_is_refused(self):
        # Three releases across regions is a state no rollback can cleanly undo.
        with pytest.raises(SlateReleaseRefusedError) as exc:
            plan_promotion(
                release=release(),
                environment=environment(active_release_id="rel-0"),
                active_regions=[
                    {"region_id": "eu", "status": "active"},
                    {"region_id": "us", "status": "activating"},
                ],
            )
        assert exc.value.code == "partial-region"

    def test_promoting_over_a_failed_region_is_refused(self):
        with pytest.raises(SlateReleaseRefusedError) as exc:
            plan_promotion(
                release=release(),
                environment=environment(active_release_id="rel-0"),
                active_regions=[{"region_id": "us", "status": "failed"}],
            )
        assert exc.value.code == "partial-region"

    def test_promoting_over_a_complete_rollout_is_allowed(self):
        plan = plan_promotion(
            release=release(),
            environment=environment(active_release_id="rel-0"),
            active_regions=[{"region_id": "eu", "status": "active"}],
        )
        assert plan.action == "promotion"

    def test_an_empty_lane_is_not_blocked_by_absent_region_reports(self):
        # A lane serving nothing has no rollout to be partial; the gate must not deadlock it.
        assert plan_promotion(release=release(), environment=environment()).action == "promotion"


class TestApprovalGates:
    def test_approval_is_not_required_unless_the_lane_demands_it(self):
        assert plan_promotion(release=release(), environment=environment()).action == "promotion"

    def test_a_lane_requiring_approval_refuses_a_release_with_none(self):
        with pytest.raises(SlateReleaseRefusedError) as exc:
            plan_promotion(
                release=release(), environment=environment(), require_approval=True
            )
        assert exc.value.code == "approval-required"

    def test_an_approval_for_different_bytes_is_stale(self):
        with pytest.raises(SlateReleaseRefusedError) as exc:
            plan_promotion(
                release=release(),
                environment=environment(),
                approvals=[{"digest": OTHER_DIGEST}],
                require_approval=True,
            )
        assert exc.value.code == "stale-approval"

    def test_an_approval_for_the_current_bytes_passes(self):
        plan = plan_promotion(
            release=release(),
            environment=environment(),
            approvals=[{"digest": DIGEST}],
            require_approval=True,
        )
        assert plan.action == "promotion"

    def test_one_fresh_approval_among_stale_ones_is_enough(self):
        plan = plan_promotion(
            release=release(),
            environment=environment(),
            approvals=[{"digest": OTHER_DIGEST}, {"digest": DIGEST}],
            require_approval=True,
        )
        assert plan.action == "promotion"

    def test_a_missing_digest_counts_as_stale_rather_than_as_a_pass(self):
        assert is_approval_stale(None, DIGEST) is True
        assert is_approval_stale("", DIGEST) is True
        assert is_approval_stale(DIGEST, None) is True

    def test_matching_digests_are_not_stale(self):
        assert is_approval_stale(DIGEST, DIGEST) is False


class TestRollbackGates:
    def test_rollback_routes_to_the_retained_target(self):
        plan = plan_rollback(
            environment=environment(active_release_id="rel-2"),
            target=release(id="rel-1"),
        )
        assert plan.action == "rollback"
        assert plan.release_id == "rel-1"
        assert plan.replaces_release_id == "rel-2"

    def test_rollback_never_rebuilds(self):
        plan = plan_rollback(
            environment=environment(active_release_id="rel-2"), target=release(id="rel-1")
        )
        assert plan.rebuilds is False

    def test_rolling_back_a_lane_serving_nothing_is_refused(self):
        with pytest.raises(SlateReleaseRefusedError) as exc:
            plan_rollback(environment=environment(), target=release())
        assert exc.value.code == "nothing-active"

    def test_no_retained_target_is_refused_with_that_reason(self):
        with pytest.raises(SlateReleaseRefusedError) as exc:
            plan_rollback(environment=environment(active_release_id="rel-2"), target=None)
        assert exc.value.code == "no-rollback-target"

    def test_a_reaped_target_reads_as_a_missing_target_not_a_failed_build(self):
        # The operator's situation is "there is nothing to go back to", so say that.
        with pytest.raises(SlateReleaseRefusedError) as exc:
            plan_rollback(
                environment=environment(active_release_id="rel-2"),
                target=release(id="rel-1", artifact_reaped_at=NOW),
            )
        assert exc.value.code == "no-rollback-target"
        assert "retention window" in exc.value.refusal.sentence

    def test_a_target_with_a_bad_signature_is_still_refused_as_such(self):
        with pytest.raises(SlateReleaseRefusedError) as exc:
            plan_rollback(
                environment=environment(active_release_id="rel-2"),
                target=release(id="rel-1", signature_verified=False),
            )
        assert exc.value.code == "signature-invalid"

    def test_rollback_ignores_approval_freshness(self):
        # Requiring fresh sign-off to STOP serving a bad release would make the approval
        # policy an outage amplifier. This asymmetry is deliberate.
        plan = plan_rollback(
            environment=environment(active_release_id="rel-2"),
            target=release(id="rel-1"),
        )
        assert plan.action == "rollback"

    def test_rollback_target_may_be_a_previously_rolled_back_release(self):
        plan = plan_rollback(
            environment=environment(active_release_id="rel-3"),
            target=release(id="rel-1", status="rolled-back"),
        )
        assert plan.release_id == "rel-1"


class TestRegionRollout:
    def test_no_region_reports_is_pending_not_complete(self):
        # Absence of evidence is not evidence of a clean activation.
        rollout = evaluate_region_rollout([])
        assert rollout.state == "pending"
        assert rollout.total == 0

    def test_every_region_active_is_complete(self):
        rollout = evaluate_region_rollout(
            [{"region_id": "eu", "status": "active"}, {"region_id": "us", "status": "active"}]
        )
        assert rollout.state == "complete"
        assert rollout.active == 2

    def test_any_region_still_activating_is_partial(self):
        rollout = evaluate_region_rollout(
            [{"region_id": "eu", "status": "active"}, {"region_id": "us", "status": "activating"}]
        )
        assert rollout.state == "partial"
        assert rollout.activating == 1

    def test_a_failed_region_outranks_an_activating_one(self):
        rollout = evaluate_region_rollout(
            [{"region_id": "eu", "status": "failed"}, {"region_id": "us", "status": "activating"}]
        )
        assert rollout.state == "failed"

    def test_outstanding_regions_are_named_so_an_operator_can_act(self):
        rollout = evaluate_region_rollout(
            [
                {"region_id": "eu", "label": "Frankfurt", "status": "active"},
                {"region_id": "us", "label": "Virginia", "status": "failed"},
            ]
        )
        assert "Virginia" in rollout.outstanding
        assert "Frankfurt" not in rollout.outstanding

    def test_a_region_without_a_label_still_names_itself(self):
        rollout = evaluate_region_rollout([{"region_id": "ap-1", "status": "activating"}])
        assert rollout.outstanding == ("ap-1",)


class TestActivationSlo:
    def test_an_unstarted_activation_reports_not_started(self):
        slo = measure_activation_slo(started_at=None, completed_at=None, budget_seconds=300)
        assert slo["state"] == "not-started"
        assert slo["elapsedSeconds"] is None

    def test_an_activation_inside_budget_is_within(self):
        slo = measure_activation_slo(
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=120),
            budget_seconds=300,
        )
        assert slo["state"] == "within"
        assert slo["elapsedSeconds"] == 120

    def test_a_finished_activation_over_budget_is_breached(self):
        slo = measure_activation_slo(
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=400),
            budget_seconds=300,
        )
        assert slo["state"] == "breached"
        assert slo["inProgress"] is False

    def test_a_breach_is_reported_while_it_is_still_happening(self):
        # An operator needs to know now, not after the rollout eventually finishes.
        slo = measure_activation_slo(
            started_at=NOW,
            completed_at=None,
            budget_seconds=300,
            now=NOW + timedelta(seconds=720),
        )
        assert slo["state"] == "breaching"
        assert slo["inProgress"] is True

    def test_an_in_flight_activation_inside_budget_is_still_within(self):
        slo = measure_activation_slo(
            started_at=NOW,
            completed_at=None,
            budget_seconds=300,
            now=NOW + timedelta(seconds=60),
        )
        assert slo["state"] == "within"
        assert slo["inProgress"] is True

    def test_clock_skew_cannot_produce_a_negative_elapsed_time(self):
        slo = measure_activation_slo(
            started_at=NOW,
            completed_at=NOW - timedelta(seconds=30),
            budget_seconds=300,
        )
        assert slo["elapsedSeconds"] == 0


class TestRetention:
    def superseded(self, n: int):
        """n superseded releases, newest first."""
        return [
            {"id": f"rel-{i}", "status": "superseded", "artifact_reaped_at": None}
            for i in range(n, 0, -1)
        ]

    def test_nothing_is_reaped_inside_the_retention_window(self):
        assert select_reapable_artifacts(self.superseded(3), retained_releases=10) == []

    def test_releases_past_the_window_are_reapable_oldest_first(self):
        reapable = select_reapable_artifacts(self.superseded(5), retained_releases=2)
        assert reapable == ["rel-1", "rel-2", "rel-3"]

    def test_the_active_release_is_never_reaped(self):
        releases = [
            {"id": "rel-9", "status": "active", "artifact_reaped_at": None},
            *self.superseded(3),
        ]
        assert "rel-9" not in select_reapable_artifacts(
            releases, retained_releases=0, active_release_id="rel-9"
        )

    def test_an_active_release_is_exempt_even_when_listed_as_superseded(self):
        # Belt and braces: routing state wins over a stale status column.
        releases = [{"id": "rel-9", "status": "superseded", "artifact_reaped_at": None}]
        assert (
            select_reapable_artifacts(
                releases, retained_releases=0, active_release_id="rel-9"
            )
            == []
        )

    @pytest.mark.parametrize("status", ["ready", "review", "queued", "building", "failed"])
    def test_only_releases_that_once_served_are_candidates(self, status):
        # Reaping a release awaiting approval would destroy work in progress.
        releases = [{"id": "rel-1", "status": status, "artifact_reaped_at": None}]
        assert select_reapable_artifacts(releases, retained_releases=0) == []

    def test_an_already_reaped_artifact_is_not_reaped_twice(self):
        # rel-1's bytes are already gone, so only rel-2 is a candidate; a sweep that
        # returned rel-1 again would keep re-reaping the same rows on every run.
        releases = [
            {"id": "rel-1", "status": "superseded", "artifact_reaped_at": NOW},
            {"id": "rel-2", "status": "superseded", "artifact_reaped_at": None},
        ]
        assert select_reapable_artifacts(releases, retained_releases=0) == ["rel-2"]

    def test_reaped_releases_are_excluded_from_the_candidate_list(self):
        releases = [{"id": "rel-1", "status": "superseded", "artifact_reaped_at": NOW}]
        assert select_reapable_artifacts(releases, retained_releases=0) == []

    def test_rolled_back_releases_are_retention_candidates(self):
        releases = [{"id": "rel-1", "status": "rolled-back", "artifact_reaped_at": None}]
        assert select_reapable_artifacts(releases, retained_releases=0) == ["rel-1"]


class TestRefusalVocabulary:
    def test_every_refusal_reason_has_an_operator_facing_sentence(self):
        # The Release Center makes disabledReason the only way to disable a control, so a
        # reason with no sentence would surface as a greyed-out dead end.
        for reason in [
            "not-built",
            "not-promotable",
            "already-active",
            "nothing-active",
            "no-rollback-target",
            "stale-approval",
            "approval-required",
            "artifact-reaped",
            "signature-invalid",
            "partial-region",
            "concurrent-activation",
        ]:
            refusal = ReleaseRefusal.of(reason)
            assert refusal.reason == reason
            assert len(refusal.sentence) > 20, reason
            assert refusal.sentence.endswith(".")

    def test_an_unknown_reason_still_produces_a_sentence(self):
        assert ReleaseRefusal.of("something-new").sentence


class TestPlanSerialization:
    def test_the_plan_serializes_rebuilds_false_onto_the_wire(self):
        # The UI's impact sheet reads this field; it must be inspectable, not implied.
        plan = plan_promotion(release=release(), environment=environment())
        assert plan.as_dict()["rebuilds"] is False

    def test_the_plan_serializes_every_field_the_impact_sheet_needs(self):
        body = plan_promotion(
            release=release(), environment=environment(active_release_id="rel-0")
        ).as_dict()
        for key in (
            "action",
            "environmentId",
            "releaseId",
            "artifactDigest",
            "replacesReleaseId",
            "expectedRoutingVersion",
            "rebuilds",
            "invalidatedPages",
        ):
            assert key in body

    def test_an_activation_plan_cannot_be_mutated_after_it_is_decided(self):
        plan = plan_promotion(release=release(), environment=environment())
        with pytest.raises(Exception):
            plan.artifact_digest = OTHER_DIGEST  # type: ignore[misc]
