"""Managed Slate hosting REST surface — APX-3.1 (private-suite#2456).

The deployment API the Release Center consumes: authorization posture (reads view,
recording edit, routing publish), 404-not-403 on scope misses, signature verification at
record time, the named-refusal contract, the dry-run plan, the concurrency 409, and the
rule that a refused action still leaves an audit entry.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.slate_auth import validate_slate_authentication
from app.config import settings
from app.main import app
from app.slate_artifacts import (
    ArtifactDigests,
    compute_config_digest,
    compute_content_digest,
    compute_source_digest,
    sign_digests,
)
from app.slate_deployment_store import SlateActivationConflictError

client = TestClient(app)

_MOCK_JWT = {
    "tenant_id": "t1",
    "user_id": "user-a",
    "email": "dana@example.com",
    "auth_method": "jwt",
}

SITE = "site-1"
ENV = "env-1"
NOW = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)

DIGESTS = ArtifactDigests(
    content=compute_content_digest({"index.html": b"<html/>"}),
    source=compute_source_digest({"catalogRevision": "rev-1"}),
    config=compute_config_digest({"theme": "default"}),
)


def signature() -> str:
    """A signature that verifies under the configured development key."""
    return sign_digests(
        DIGESTS,
        key=settings.effective_slate_artifact_signing_key,
        key_id=settings.slate_artifact_signing_key_id,
    )


def environment_row(**overrides):
    base = {
        "id": ENV,
        "site_id": SITE,
        "kind": "production",
        "name": "production",
        "active_release_id": None,
        "routing_version": 3,
        "robots_excluded": False,
        "access_policy": "public",
        "expires_at": None,
        "retained_releases": 10,
        "activation_slo_seconds": 300,
    }
    return {**base, **overrides}


def release_row(**overrides):
    base = {
        "id": "rel-1",
        "release_ref": "r-4821",
        "environment_id": ENV,
        "status": "ready",
        "source_commit": "a" * 40,
        "source_ref": "main",
        "source_message": "Document invoices",
        "actor_id": "user-a",
        "actor_name": "Dana",
        "actor_kind": "user",
        "impact": {"invalidatedPages": 12},
        "created_at": NOW,
        "activated_at": None,
        "activation_completed_at": None,
        "deactivated_at": None,
        "traffic_percent": None,
        "traffic_requests_per_min": None,
        "artifact_digest": DIGESTS.content,
        "source_digest": DIGESTS.source,
        "config_digest": DIGESTS.config,
        "signature": signature(),
        "signature_key_id": settings.slate_artifact_signing_key_id,
        "page_count": 12,
        "size_bytes": 4096,
        "storage_uri": "s3://artifacts/rel-1",
        "built_at": NOW,
        "artifact_reaped_at": None,
        "manifest": {},
    }
    return {**base, **overrides}


ACTIVATED = {"activationId": "act-1", "routingVersion": 4, "activatedAt": NOW}

EMPTY_EVIDENCE = {
    "checks": [],
    "phases": [],
    "logs": [],
    "approvals": [],
    "changed_pages": [],
    "audit": [],
    "regions": [],
}


@pytest.fixture(autouse=True)
def _auth():
    # Overriding the dependency substitutes the signature under test, so this fixture cannot
    # see the tenant_slug binding defect it once hid. That is covered by
    # tests/test_slate_tenant_auth.py, which deliberately overrides nothing.
    app.dependency_overrides[validate_slate_authentication] = lambda: dict(_MOCK_JWT)
    yield
    app.dependency_overrides.pop(validate_slate_authentication, None)


@pytest.fixture(autouse=True)
def _permissions():
    """Allow by default; individual tests re-patch to assert the required permission."""
    with patch("app.slate_routes.enforce_permission") as enforce:
        yield enforce


class TestAuthorization:
    def test_listing_releases_requires_the_view_permission(self, _permissions):
        with patch("app.slate_routes.list_releases", return_value=[]):
            client.get(f"/v1/slate/sites/{SITE}/releases")
        _, args, _ = _permissions.mock_calls[0]
        assert args[2] == "versions"
        assert args[3] == "view"

    def test_recording_a_release_requires_the_edit_permission(self, _permissions):
        with patch("app.slate_routes.get_environment", return_value=environment_row()), \
             patch("app.slate_routes.record_artifact", return_value={"id": "art-1"}), \
             patch("app.slate_routes.store_create_release", return_value=release_row()), \
             patch("app.slate_routes.get_release", return_value=release_row()):
            client.post(f"/v1/slate/sites/{SITE}/releases", json=create_payload())
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "edit"

    def test_promotion_requires_the_publish_permission(self, _permissions):
        with patch("app.slate_routes.get_environment", return_value=environment_row()), \
             patch("app.slate_routes.get_release", return_value=release_row()), \
             patch("app.slate_routes._release_evidence", return_value=EMPTY_EVIDENCE), \
             patch("app.slate_routes._region_rows", return_value=[]), \
             patch("app.slate_routes.activate", return_value=ACTIVATED):
            client.post(f"/v1/slate/environments/{ENV}/promote", json={"releaseId": "rel-1"})
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"

    def test_rollback_requires_the_publish_permission(self, _permissions):
        with patch("app.slate_routes.get_environment", return_value=environment_row(active_release_id="rel-2")), \
             patch("app.slate_routes.find_rollback_target", return_value=release_row(status="superseded")), \
             patch("app.slate_routes.activate", return_value=ACTIVATED):
            client.post(f"/v1/slate/environments/{ENV}/rollback", json={})
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"

    def test_retention_requires_the_publish_permission(self, _permissions):
        with patch("app.slate_routes.get_environment", return_value=environment_row()), \
             patch("app.slate_routes.list_releases", return_value=[]), \
             patch("app.slate_routes.reap_artifacts", return_value=0):
            client.post(f"/v1/slate/sites/{SITE}/retention?environmentId={ENV}")
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"


class TestScopeMisses:
    def test_an_unknown_environment_answers_404_not_403(self):
        # A cross-tenant probe must not be able to confirm the lane exists.
        with patch("app.slate_routes.get_environment", return_value=None):
            response = client.post(
                f"/v1/slate/environments/{ENV}/promote", json={"releaseId": "rel-1"}
            )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "environment_not_found"

    def test_an_unknown_release_answers_404(self):
        with patch("app.slate_routes.get_release", return_value=None):
            response = client.get("/v1/slate/releases/rel-missing")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "release_not_found"

    def test_promoting_an_unknown_release_answers_404(self):
        with patch("app.slate_routes.get_environment", return_value=environment_row()), \
             patch("app.slate_routes.get_release", return_value=None):
            response = client.post(
                f"/v1/slate/environments/{ENV}/promote", json={"releaseId": "nope"}
            )
        assert response.status_code == 404


class TestReleaseTimeline:
    def test_the_timeline_returns_camelcase_release_rows(self):
        with patch("app.slate_routes.list_releases", return_value=[release_row()]):
            response = client.get(f"/v1/slate/sites/{SITE}/releases")
        assert response.status_code == 200
        release = response.json()["releases"][0]
        assert release["releaseRef"] == "r-4821"
        assert release["artifact"]["digest"] == DIGESTS.content

    def test_every_row_exposes_the_nine_facts_the_blueprint_requires(self):
        with patch("app.slate_routes.list_releases", return_value=[release_row()]):
            release = client.get(f"/v1/slate/sites/{SITE}/releases").json()["releases"][0]
        for key in (
            "status",
            "environmentId",
            "source",
            "artifact",
            "actor",
            "checks",
            "createdAt",
            "domains",
            "traffic",
        ):
            assert key in release

    def test_a_signed_artifact_reports_its_signature_as_verified(self):
        with patch("app.slate_routes.list_releases", return_value=[release_row()]):
            release = client.get(f"/v1/slate/sites/{SITE}/releases").json()["releases"][0]
        assert release["artifact"]["signatureVerified"] is True

    def test_a_tampered_artifact_reports_its_signature_as_unverified(self):
        tampered = release_row(artifact_digest=compute_content_digest({"index.html": b"evil"}))
        with patch("app.slate_routes.list_releases", return_value=[tampered]):
            release = client.get(f"/v1/slate/sites/{SITE}/releases").json()["releases"][0]
        assert release["artifact"]["signatureVerified"] is False

    def test_a_reaped_artifact_is_reported_as_not_retained(self):
        with patch("app.slate_routes.list_releases", return_value=[release_row(artifact_reaped_at=NOW)]):
            release = client.get(f"/v1/slate/sites/{SITE}/releases").json()["releases"][0]
        assert release["artifact"]["retained"] is False

    def test_the_timeline_can_be_scoped_to_one_environment(self):
        with patch("app.slate_routes.list_releases", return_value=[]) as listed:
            client.get(f"/v1/slate/sites/{SITE}/releases?environmentId={ENV}")
        assert listed.call_args.kwargs["environment_id"] == ENV

    def test_traffic_is_absent_when_the_release_serves_none(self):
        with patch("app.slate_routes.list_releases", return_value=[release_row()]):
            release = client.get(f"/v1/slate/sites/{SITE}/releases").json()["releases"][0]
        assert release["traffic"] is None

    def test_traffic_is_present_when_the_release_serves(self):
        serving = release_row(status="active", traffic_percent=100, traffic_requests_per_min=250)
        with patch("app.slate_routes.list_releases", return_value=[serving]):
            release = client.get(f"/v1/slate/sites/{SITE}/releases").json()["releases"][0]
        assert release["traffic"]["percent"] == 100
        assert release["traffic"]["requestsPerMinute"] == 250


def create_payload(**overrides):
    base = {
        "environmentId": ENV,
        "releaseRef": "r-4821",
        "source": {"commit": "a" * 40, "ref": "main", "message": "Document invoices"},
        "contentDigest": DIGESTS.content,
        "sourceDigest": DIGESTS.source,
        "configDigest": DIGESTS.config,
        "signature": signature(),
        "signatureKeyId": settings.slate_artifact_signing_key_id,
        "storageUri": "s3://artifacts/rel-1",
        "manifest": {},
        "pageCount": 12,
        "sizeBytes": 4096,
    }
    return {**base, **overrides}


class TestRecordingAReleaseVerifiesSignatures:
    def test_a_correctly_signed_release_is_recorded(self):
        with patch("app.slate_routes.get_environment", return_value=environment_row()), \
             patch("app.slate_routes.record_artifact", return_value={"id": "art-1"}), \
             patch("app.slate_routes.store_create_release", return_value=release_row()), \
             patch("app.slate_routes.get_release", return_value=release_row()):
            response = client.post(f"/v1/slate/sites/{SITE}/releases", json=create_payload())
        assert response.status_code == 201

    def test_an_unverifiable_signature_is_refused_at_record_time(self):
        # Discovering this during an incident promotion would be the worst possible moment.
        with patch("app.slate_routes.get_environment", return_value=environment_row()), \
             patch("app.slate_routes.record_artifact") as recorded:
            response = client.post(
                f"/v1/slate/sites/{SITE}/releases",
                json=create_payload(signature="00" * 32),
            )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "signature_invalid"
        recorded.assert_not_called()

    def test_a_malformed_digest_is_refused_with_422(self):
        with patch("app.slate_routes.get_environment", return_value=environment_row()):
            response = client.post(
                f"/v1/slate/sites/{SITE}/releases",
                json=create_payload(contentDigest="not-a-digest"),
            )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "malformed_digest"

    def test_a_release_signed_for_other_bytes_is_refused(self):
        other = compute_content_digest({"index.html": b"different"})
        with patch("app.slate_routes.get_environment", return_value=environment_row()), \
             patch("app.slate_routes.record_artifact") as recorded:
            response = client.post(
                f"/v1/slate/sites/{SITE}/releases", json=create_payload(contentDigest=other)
            )
        assert response.status_code == 422
        recorded.assert_not_called()


class TestPromotion:
    def promote(self, body=None, **patches):
        defaults = {
            "app.slate_routes.get_environment": environment_row(),
            "app.slate_routes.get_release": release_row(),
            "app.slate_routes._release_evidence": EMPTY_EVIDENCE,
            "app.slate_routes._region_rows": [],
        }
        defaults.update(patches)
        stack = [patch(target, return_value=value) for target, value in defaults.items()]
        for item in stack:
            item.start()
        try:
            return client.post(
                f"/v1/slate/environments/{ENV}/promote",
                # `body or {...}` would swallow an intentionally empty body, which is
                # exactly what the missing-releaseId test needs to send.
                json={"releaseId": "rel-1"} if body is None else body,
            )
        finally:
            for item in reversed(stack):
                item.stop()

    def test_a_promotion_routes_without_rebuilding(self):
        with patch("app.slate_routes.activate", return_value=ACTIVATED):
            response = self.promote()
        assert response.status_code == 200
        body = response.json()
        assert body["applied"] is True
        assert body["plan"]["rebuilds"] is False

    def test_the_plan_names_the_digest_it_routes_to(self):
        with patch("app.slate_routes.activate", return_value=ACTIVATED):
            body = self.promote().json()
        assert body["plan"]["artifactDigest"] == DIGESTS.content

    def test_a_dry_run_returns_the_plan_without_changing_routing(self):
        with patch("app.slate_routes.activate") as activated:
            response = self.promote(body={"releaseId": "rel-1", "dryRun": True})
        assert response.status_code == 200
        assert response.json()["applied"] is False
        assert response.json()["dryRun"] is True
        activated.assert_not_called()

    def test_a_dry_run_still_runs_every_gate(self):
        # A plan that has not been validated would make the impact sheet a guess.
        with patch("app.slate_routes.activate"):
            response = self.promote(
                body={"releaseId": "rel-1", "dryRun": True},
                **{"app.slate_routes.get_release": release_row(status="failed")},
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "not-promotable"

    def test_promoting_without_a_release_id_is_a_422(self):
        response = self.promote(body={})
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "release_required"

    def test_a_refusal_is_a_409_naming_its_reason(self):
        with patch("app.slate_routes.append_audit"):
            response = self.promote(
                **{"app.slate_routes.get_release": release_row(artifact_digest=None)}
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "not-built"
        assert "never starts a build" in detail["message"]

    def test_a_refused_promotion_still_records_an_audit_entry(self):
        with patch("app.slate_routes.append_audit") as audited:
            self.promote(**{"app.slate_routes.get_release": release_row(status="failed")})
        audited.assert_called_once()
        assert audited.call_args.kwargs["summary"] == "Promotion refused"
        assert "not-promotable" in audited.call_args.kwargs["detail"]

    def test_a_refused_dry_run_does_not_record_an_audit_entry(self):
        # A review that nobody confirmed is not an event worth recording.
        with patch("app.slate_routes.append_audit") as audited:
            self.promote(
                body={"releaseId": "rel-1", "dryRun": True},
                **{"app.slate_routes.get_release": release_row(status="failed")},
            )
        audited.assert_not_called()

    def test_a_concurrent_promotion_answers_409_with_both_versions(self):
        conflict = SlateActivationConflictError(ENV, 3, 5)
        with patch("app.slate_routes.activate", side_effect=conflict):
            response = self.promote()
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "concurrent-activation"
        assert detail["expectedRoutingVersion"] == 3
        assert detail["actualRoutingVersion"] == 5

    def test_promoting_what_is_already_active_is_refused(self):
        with patch("app.slate_routes.append_audit"):
            response = self.promote(
                **{"app.slate_routes.get_environment": environment_row(active_release_id="rel-1")}
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "already-active"

    def test_promotion_over_a_partial_rollout_is_refused(self):
        with patch("app.slate_routes.append_audit"):
            response = self.promote(
                **{
                    "app.slate_routes.get_environment": environment_row(active_release_id="rel-0"),
                    "app.slate_routes._region_rows": [
                        {"region_id": "us", "status": "activating"}
                    ],
                }
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "partial-region"


class TestRollback:
    def test_a_rollback_routes_to_the_retained_target(self):
        with patch("app.slate_routes.get_environment", return_value=environment_row(active_release_id="rel-2")), \
             patch("app.slate_routes.find_rollback_target", return_value=release_row(status="superseded")), \
             patch("app.slate_routes.activate", return_value=ACTIVATED):
            response = client.post(f"/v1/slate/environments/{ENV}/rollback", json={})
        assert response.status_code == 200
        assert response.json()["plan"]["action"] == "rollback"
        assert response.json()["plan"]["rebuilds"] is False

    def test_no_retained_target_is_a_409(self):
        with patch("app.slate_routes.get_environment", return_value=environment_row(active_release_id="rel-2")), \
             patch("app.slate_routes.find_rollback_target", return_value=None), \
             patch("app.slate_routes.append_audit"):
            response = client.post(f"/v1/slate/environments/{ENV}/rollback", json={})
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "no-rollback-target"

    def test_rolling_back_a_lane_serving_nothing_is_a_409(self):
        with patch("app.slate_routes.get_environment", return_value=environment_row()), \
             patch("app.slate_routes.find_rollback_target", return_value=None):
            response = client.post(f"/v1/slate/environments/{ENV}/rollback", json={})
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "nothing-active"

    def test_a_rollback_dry_run_changes_nothing(self):
        with patch("app.slate_routes.get_environment", return_value=environment_row(active_release_id="rel-2")), \
             patch("app.slate_routes.find_rollback_target", return_value=release_row(status="superseded")), \
             patch("app.slate_routes.activate") as activated:
            response = client.post(
                f"/v1/slate/environments/{ENV}/rollback", json={"dryRun": True}
            )
        assert response.json()["applied"] is False
        activated.assert_not_called()

    def test_a_refused_rollback_records_an_audit_entry_against_the_active_release(self):
        with patch("app.slate_routes.get_environment", return_value=environment_row(active_release_id="rel-2")), \
             patch("app.slate_routes.find_rollback_target", return_value=None), \
             patch("app.slate_routes.append_audit") as audited:
            client.post(f"/v1/slate/environments/{ENV}/rollback", json={})
        audited.assert_called_once()
        assert audited.call_args.kwargs["release_id"] == "rel-2"
        assert audited.call_args.kwargs["summary"] == "Rollback refused"


class TestEnvironmentState:
    def test_the_lane_reports_its_routing_version(self):
        with patch("app.slate_routes.get_environment", return_value=environment_row()), \
             patch("app.slate_routes._region_rows", return_value=[]), \
             patch("app.slate_routes._environment_domains", return_value=[]):
            body = client.get(f"/v1/slate/environments/{ENV}").json()
        assert body["routingVersion"] == 3

    def test_a_lane_with_no_region_reports_is_pending_not_complete(self):
        with patch("app.slate_routes.get_environment", return_value=environment_row(active_release_id="rel-1")), \
             patch("app.slate_routes._region_rows", return_value=[]), \
             patch("app.slate_routes.get_release", return_value=release_row(status="active", activated_at=NOW)), \
             patch("app.slate_routes._environment_domains", return_value=[]):
            body = client.get(f"/v1/slate/environments/{ENV}").json()
        assert body["rollout"]["state"] == "pending"

    def test_a_partial_rollout_names_its_outstanding_regions(self):
        with patch("app.slate_routes.get_environment", return_value=environment_row(active_release_id="rel-1")), \
             patch("app.slate_routes._region_rows", return_value=[
                 {"region_id": "eu", "label": "Frankfurt", "status": "active"},
                 {"region_id": "us", "label": "Virginia", "status": "activating"},
             ]), \
             patch("app.slate_routes.get_release", return_value=release_row(status="active", activated_at=NOW)), \
             patch("app.slate_routes._environment_domains", return_value=[]):
            body = client.get(f"/v1/slate/environments/{ENV}").json()
        assert body["rollout"]["state"] == "partial"
        assert body["rollout"]["outstanding"] == ["Virginia"]

    def test_an_idle_lane_reports_the_slo_as_not_started(self):
        with patch("app.slate_routes.get_environment", return_value=environment_row()), \
             patch("app.slate_routes._region_rows", return_value=[]), \
             patch("app.slate_routes._environment_domains", return_value=[]):
            body = client.get(f"/v1/slate/environments/{ENV}").json()
        assert body["activationSlo"]["state"] == "not-started"

    def test_the_domain_inventory_is_reported_with_tls_state(self):
        domains = [{"host": "docs.example.com", "is_primary": True, "tls_status": "active"}]
        with patch("app.slate_routes.get_environment", return_value=environment_row()), \
             patch("app.slate_routes._region_rows", return_value=[]), \
             patch("app.slate_routes._environment_domains", return_value=domains):
            body = client.get(f"/v1/slate/environments/{ENV}").json()
        assert body["domains"][0]["host"] == "docs.example.com"


class TestRetentionEndpoint:
    def test_the_sweep_reports_what_it_reaped(self):
        releases = [
            {"id": f"rel-{i}", "status": "superseded", "artifact_reaped_at": None}
            for i in range(5, 0, -1)
        ]
        with patch("app.slate_routes.get_environment", return_value=environment_row(retained_releases=2)), \
             patch("app.slate_routes.list_releases", return_value=releases), \
             patch("app.slate_routes.reap_artifacts", return_value=3) as reaped:
            body = client.post(
                f"/v1/slate/sites/{SITE}/retention?environmentId={ENV}"
            ).json()
        assert body["reaped"] == 3
        assert body["retainedReleases"] == 2
        assert reaped.call_args.kwargs["release_ids"] == ["rel-1", "rel-2", "rel-3"]

    def test_the_active_release_is_excluded_from_the_sweep(self):
        releases = [{"id": "rel-1", "status": "superseded", "artifact_reaped_at": None}]
        with patch("app.slate_routes.get_environment",
                   return_value=environment_row(retained_releases=0, active_release_id="rel-1")), \
             patch("app.slate_routes.list_releases", return_value=releases), \
             patch("app.slate_routes.reap_artifacts", return_value=0) as reaped:
            client.post(f"/v1/slate/sites/{SITE}/retention?environmentId={ENV}")
        assert reaped.call_args.kwargs["release_ids"] == []


class TestSiteInventory:
    def test_sites_are_listed_with_their_lanes(self):
        site = {
            "id": SITE,
            "project_id": "proj-1",
            "name": "Payments docs",
            "slug": "payments-docs",
            "retained_releases": 10,
            "activation_slo_seconds": 300,
            "environments": [
                {
                    "id": ENV,
                    "kind": "production",
                    "name": "production",
                    "active_release_id": "rel-1",
                    "routing_version": 4,
                    "robots_excluded": False,
                    "access_policy": "public",
                    "expires_at": None,
                }
            ],
        }
        with patch("app.slate_routes.list_sites", return_value=[site]):
            body = client.get("/v1/slate/sites").json()

        assert body["sites"][0]["slug"] == "payments-docs"
        assert body["sites"][0]["environments"][0]["kind"] == "production"
        assert body["sites"][0]["environments"][0]["routingVersion"] == 4

    def test_sites_can_be_filtered_by_project(self):
        with patch("app.slate_routes.list_sites", return_value=[]) as listed:
            client.get("/v1/slate/sites?projectId=proj-1")
        assert listed.call_args.kwargs["project_id"] == "proj-1"

    def test_a_project_with_no_hosted_site_returns_an_empty_list(self):
        # "Not hosted" is a legitimate answer, not an error.
        with patch("app.slate_routes.list_sites", return_value=[]):
            response = client.get("/v1/slate/sites?projectId=proj-9")
        assert response.status_code == 200
        assert response.json()["sites"] == []

    def test_listing_sites_requires_the_view_permission(self, _permissions):
        with patch("app.slate_routes.list_sites", return_value=[]):
            client.get("/v1/slate/sites")
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "view"

    def test_a_lane_serving_nothing_reports_a_null_active_release(self):
        site = {
            "id": SITE,
            "project_id": "proj-1",
            "name": "Docs",
            "slug": "docs",
            "retained_releases": 10,
            "activation_slo_seconds": 300,
            "environments": [
                {"id": ENV, "kind": "preview", "name": "preview", "active_release_id": None,
                 "routing_version": 0, "robots_excluded": True, "access_policy": "tenant",
                 "expires_at": None}
            ],
        }
        with patch("app.slate_routes.list_sites", return_value=[site]):
            lane = client.get("/v1/slate/sites").json()["sites"][0]["environments"][0]
        assert lane["activeReleaseId"] is None
        assert lane["robotsExcluded"] is True
