"""Observability control REST surface — UXE-3.4 (private-suite#2476).

Route-level tests over :mod:`app.slate_insights_routes`, following the
``test_slate_functions_routes.py`` precedent: a module-level ``TestClient``, a mock auth dict, and
store functions patched *where used*. The pure module and the store are proven separately in their
own suites; what is asserted here is the contract the surface publishes.

The claims that matter most, and which nothing below is allowed to weaken:

* **No response can claim a measurement.** ``basis``, ``observed``, ``metered`` and ``billable``
  are literal pydantic defaults **no handler assigns**, so the honesty of this surface is a
  property of its types rather than of its discipline. The tests below construct the response
  models directly and assert that setting ``billable=True`` is a validation error — because a
  model that merely *happens* not to be assigned is one somebody will assign later.
* **Every policy read and every policy write says nothing is collecting.** The ``enforcement``
  block is on both, and it names the absence of a collector in words.
* **Refusals reach the client as sentences, character for character.** 409 with
  ``{code, message, reason}``, the shape the authoring surface's ``disabledReason`` renders, and
  the message is the domain module's own — never a restatement.
* **A residency promise with no stated gap is refused.** Not warned about: a claim with no stated
  gap is the version somebody quotes to a regulator.
* **A live tail is refused without a reason, above a ceiling, or outside the allowlist**, and the
  refusal is audited even on a dry run.
* **A cross-tenant probe cannot confirm a lane exists.** An unknown environment answers 404, never
  403.
* **The route table resolves literals before path parameters.** FastAPI matches in registration
  order, so ``/tail`` must precede ``/tail/{session_id}``. That is asserted against the resolved
  table rather than trusted to the reading order of the module.
* **Evidence exports cannot run code and cannot lie by omission.** Formula-leading cells are
  neutralized, truncation is stated in words, and every export writes its own audit row.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.slate_auth import validate_slate_authentication
from app.slate_insights import (
    RESIDENCY_STAGE_CATALOG,
    RESIDENCY_STAGES,
    InsightRefusal,
    InsightWarning,
    SlateInsightRefusedError,
)
from app.slate_insights_routes import (
    EnforcementBody,
    InsightPolicyBody,
    MetricPointBody,
    MetricsResponse,
    ResidencyLaneBody,
    TailSessionBody,
    UsageRecordBody,
    UsageResponse,
    UsageRollupBody,
    _default_lanes,
)
from app.slate_insights_store import (
    SlateInsightPolicyConflictError,
    SlateInsightStoreError,
)

client = TestClient(app)

TENANT = "11111111-1111-1111-1111-111111111111"
SITE = "22222222-2222-2222-2222-222222222222"
ENV = "33333333-3333-3333-3333-333333333333"
RELEASE = "44444444-4444-4444-4444-444444444444"
EXPORT = "55555555-5555-5555-5555-555555555555"
BUDGET = "66666666-6666-6666-6666-666666666666"
CHECK = "77777777-7777-7777-7777-777777777777"
SESSION = "88888888-8888-8888-8888-888888888888"
ALERT = "99999999-9999-9999-9999-999999999999"
LANE = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TRACE = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USAGE = "cccccccc-cccc-cccc-cccc-cccccccccccc"

TRACE_ID = "d" * 32
SPAN_ID = "e" * 16

_MOCK_JWT: Dict[str, Any] = {
    "tenant_id": TENANT,
    "tenant_slug": "acme",
    "user_id": "user-1",
    "email": "ken@example.com",
    "auth_type": "jwt",
}

ENVIRONMENT = {"id": ENV, "site_id": SITE, "tenant_id": TENANT, "active_release_id": RELEASE}

POLICY = {
    "id": "policy-1",
    "tenant_id": TENANT,
    "site_id": SITE,
    "environment_id": ENV,
    "telemetry_enabled": True,
    "policy_version": 3,
    "edge_attached": False,
    "edge_provider": None,
    "metric_retention_days": 90,
    "log_retention_days": 14,
    "trace_retention_days": 7,
    "default_sample_rate": Decimal("0.05000"),
    "max_tail_sample_rate": Decimal("0.01000"),
    "max_tail_events_per_sec": 100,
    "privacy_threshold": 10,
    "retention_waiver_reason": None,
    "updated_at": None,
    "updated_by_actor_name": "ken@example.com",
}


def stored_lane(stage: str, **overrides) -> Dict[str, Any]:
    """One residency lane row as the store returns it."""
    definition = next(d for d in RESIDENCY_STAGE_CATALOG if d.stage == stage)
    base = {
        "id": f"lane-{stage}",
        "tenant_id": TENANT,
        "environment_id": ENV,
        "stage": stage,
        "residency_class": "in-region-only",
        "regions": ["eu-west"],
        "uncovered_sentence": definition.default_uncovered,
        "residency_waiver_reason": None,
        "enforced": False,
        "updated_by_actor_name": "ken@example.com",
    }
    base.update(overrides)
    return base


def stored_lanes() -> List[Dict[str, Any]]:
    """All six residency lanes, in request-path order."""
    return [stored_lane(stage) for stage in RESIDENCY_STAGES]


def stored_export(**overrides) -> Dict[str, Any]:
    """An OTLP export destination row."""
    base = {
        "id": EXPORT,
        "label": "Honeycomb",
        "endpoint": "https://api.honeycomb.io",
        "protocol": "http/protobuf",
        "signals": ["logs", "metrics", "traces"],
        "header_secret_ref": "honeycomb-key",
        "enabled": True,
        "last_delivery_state": "never-attempted",
        "last_delivery_at": None,
        "last_failure_reason": None,
        "edge_attached": False,
        "updated_by_actor_name": "ken@example.com",
    }
    base.update(overrides)
    return base


def stored_budget(**overrides) -> Dict[str, Any]:
    """A budget row."""
    base = {
        "id": BUDGET,
        "label": "Monthly delivery",
        "service": "delivery",
        "period": "monthly",
        "amount": Decimal("500.000000"),
        "currency": "USD",
        "alert_thresholds": [Decimal("0.800"), Decimal("1.000")],
        "notify_channel_ref": "ops-slack",
        "enabled": True,
        "updated_by_actor_name": "ken@example.com",
    }
    base.update(overrides)
    return base


def stored_check(**overrides) -> Dict[str, Any]:
    """A synthetic check row."""
    base = {
        "id": CHECK,
        "label": "Home page",
        "target_path": "/",
        "method": "GET",
        "regions": ["eu-west", "us-east"],
        "interval_seconds": 300,
        "expected_status": 200,
        "latency_budget_ms": 1000,
        "enabled": True,
        "updated_by_actor_name": "ken@example.com",
    }
    base.update(overrides)
    return base


def stored_session(**overrides) -> Dict[str, Any]:
    """A live tail session row."""
    base = {
        "id": SESSION,
        "sample_rate": Decimal("0.00100"),
        "max_events_per_sec": 10,
        "redaction_allowlist": ["method", "path"],
        "filter_expression": None,
        "stream_state": "requested",
        "started_at": datetime(2026, 7, 20, tzinfo=timezone.utc),
        "ended_at": None,
        "events_delivered": 0,
        "opened_by_actor_name": "ken@example.com",
        "reason": "Investigating 502s on /guide",
        "edge_attached": False,
        "retain_until": datetime(2026, 8, 3, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


def stored_usage(**overrides) -> Dict[str, Any]:
    """A daily usage record row."""
    base = {
        "id": USAGE,
        "usage_date": "2026-07-19",
        "service": "delivery",
        "quantity": Decimal("1000.000000"),
        "unit": "requests",
        "amount": Decimal("12.500000"),
        "currency": "USD",
        "included_quantity": Decimal("900.000000"),
        "overage_quantity": Decimal("100.000000"),
        "cache_savings_amount": None,
        "forecast_amount": None,
        "release_id": RELEASE,
        "region": "eu-west",
        "basis": "modelled",
        "billable": False,
        "edge_attached": False,
    }
    base.update(overrides)
    return base


def stored_metric(**overrides) -> Dict[str, Any]:
    """A metric series row."""
    base = {
        "id": "metric-1",
        "environment_id": ENV,
        "release_id": RELEASE,
        "region": "eu-west",
        "metric_family": "request",
        "metric_key": "latency-p95",
        "window_start": datetime(2026, 7, 19, 10, tzinfo=timezone.utc),
        "window_end": datetime(2026, 7, 19, 11, tzinfo=timezone.utc),
        "value": Decimal("184.000000"),
        "unit": "ms",
        "sample_count": 5000,
        "suppressed": False,
        "basis": "modelled",
        "edge_attached": False,
    }
    base.update(overrides)
    return base


def export_request(**overrides) -> Dict[str, Any]:
    """A valid export destination request body, in the camelCase the wire uses."""
    base = {
        "label": "Honeycomb",
        "endpoint": "https://api.honeycomb.io",
        "protocol": "http/protobuf",
        "signals": ["metrics", "logs", "traces"],
        "headerSecretRef": "honeycomb-key",
        "enabled": True,
        "expectedPolicyVersion": 3,
        "dryRun": False,
        "reason": "test",
    }
    base.update(overrides)
    return base


def budget_request(**overrides) -> Dict[str, Any]:
    """A valid budget request body."""
    base = {
        "label": "Monthly delivery",
        "service": "delivery",
        "period": "monthly",
        "amount": 500.0,
        "currency": "USD",
        "alertThresholds": [0.8, 1.0],
        "notifyChannelRef": "ops-slack",
        "enabled": True,
        "expectedPolicyVersion": 3,
        "dryRun": False,
        "reason": "test",
    }
    base.update(overrides)
    return base


def check_request(**overrides) -> Dict[str, Any]:
    """A valid synthetic check request body."""
    base = {
        "label": "Home page",
        "targetPath": "/",
        "method": "GET",
        "regions": ["eu-west", "us-east"],
        "intervalSeconds": 300,
        "expectedStatus": 200,
        "latencyBudgetMs": 1000,
        "enabled": True,
        "expectedPolicyVersion": 3,
        "dryRun": False,
        "reason": "test",
    }
    base.update(overrides)
    return base


def policy_request(**overrides) -> Dict[str, Any]:
    """A valid observability policy request body."""
    base = {
        "telemetryEnabled": True,
        "metricRetentionDays": 90,
        "logRetentionDays": 14,
        "traceRetentionDays": 7,
        "defaultSampleRate": 0.05,
        "maxTailSampleRate": 0.01,
        "maxTailEventsPerSec": 100,
        "privacyThreshold": 10,
        "expectedPolicyVersion": 3,
        "dryRun": False,
        "reason": "test",
    }
    base.update(overrides)
    return base


def residency_request(**overrides) -> Dict[str, Any]:
    """A valid residency lane request body."""
    base = {
        "residencyClass": "in-region-only",
        "regions": ["eu-west"],
        "uncoveredSentence": "Does not cover the network path before it.",
        "expectedPolicyVersion": 3,
        "dryRun": False,
        "reason": "test",
    }
    base.update(overrides)
    return base


def tail_request(**overrides) -> Dict[str, Any]:
    """A valid live tail request body."""
    base = {
        "sampleRate": 0.001,
        "maxEventsPerSec": 10,
        "redactionAllowlist": ["method", "path"],
        "reason": "Investigating 502s on /guide",
        "dryRun": False,
    }
    base.update(overrides)
    return base


def refusal_sentence(reason: str) -> str:
    """The domain module's own sentence for a refusal reason, never a restatement."""
    return InsightRefusal.of(reason).sentence


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_slate_authentication] = lambda: dict(_MOCK_JWT)
    yield
    app.dependency_overrides.pop(validate_slate_authentication, None)


@pytest.fixture(autouse=True)
def _permissions():
    """Allow by default; individual tests re-patch to assert the required permission."""
    with patch("app.slate_insights_routes.enforce_permission") as enforce:
        yield enforce


@pytest.fixture(autouse=True)
def _lane():
    """Resolve the environment, its policy and the lookups every route needs."""
    with (
        patch("app.slate_insights_routes.get_environment", return_value=dict(ENVIRONMENT)),
        patch("app.slate_insights_routes.ensure_policy", return_value=dict(POLICY)),
        patch("app.slate_insights_routes.ensure_residency_lanes", return_value=stored_lanes()),
        patch("app.slate_insights_routes.list_residency_lanes", return_value=stored_lanes()),
        patch("app.slate_insights_routes.list_exports", return_value=[]),
        patch("app.slate_insights_routes.list_budgets", return_value=[]),
        patch("app.slate_insights_routes.list_synthetic_checks", return_value=[]),
        patch("app.slate_insights_routes.list_usage", return_value=[]),
        patch("app.slate_insights_routes.bump_policy_version", return_value=4),
        patch("app.slate_insights_routes.append_audit"),
    ):
        yield


# ─── Catalogs ────────────────────────────────────────────────────────────────


class TestCatalogs:
    """A metric is what it cannot tell you as much as what it can."""

    def test_every_metric_family_states_the_question_it_cannot_answer(self) -> None:
        response = client.get("/v1/slate/insights/metric-families")
        assert response.status_code == 200
        families = response.json()["families"]
        assert [f["family"] for f in families] == [
            "request",
            "cache",
            "origin",
            "function",
            "security",
            "cost",
        ]
        for family in families:
            assert family["answers"], f"{family['family']} says nothing"
            assert family["doesNotAnswer"], f"{family['family']} claims to answer everything"

    def test_the_cost_family_says_a_modelled_cost_is_not_an_invoice(self) -> None:
        families = {
            f["family"]: f
            for f in client.get("/v1/slate/insights/metric-families").json()["families"]
        }
        assert "metered" in families["cost"]["doesNotAnswer"]

    def test_every_service_names_what_drives_its_number(self) -> None:
        body = client.get("/v1/slate/insights/services").json()
        assert {s["service"] for s in body["services"]} == {
            "delivery",
            "build",
            "function",
            "log",
            "ai",
        }
        for service in body["services"]:
            assert service["unit"]
            assert service["driver"]

    def test_the_service_catalog_says_nothing_meters_or_bills(self) -> None:
        body = client.get("/v1/slate/insights/services").json()
        assert body["metered"] is False
        assert body["billable"] is False
        assert "may not be invoiced" in body["sentence"]

    def test_all_six_residency_stages_state_what_they_do_not_cover(self) -> None:
        """The field most residency controls quietly omit is the one a regulator asks about."""
        body = client.get("/v1/slate/insights/residency-stages").json()
        assert [s["stage"] for s in body["stages"]] == list(RESIDENCY_STAGES)
        for stage in body["stages"]:
            assert stage["covers"]
            assert stage["defaultUncovered"]

    def test_the_log_storage_stage_names_exported_copies_as_its_gap(self) -> None:
        stages = {
            s["stage"]: s
            for s in client.get("/v1/slate/insights/residency-stages").json()["stages"]
        }
        assert "exported copies" in stages["log-data-storage"]["defaultUncovered"]

    def test_the_residency_classes_share_the_edge_surfaces_vocabulary(self) -> None:
        body = client.get("/v1/slate/insights/residency-stages").json()
        assert [c["key"] for c in body["residencyClasses"]] == [
            "in-region-only",
            "region-pinned",
            "unrestricted",
        ]
        for posture in body["residencyClasses"]:
            assert posture["description"]

    def test_reading_the_catalogs_requires_the_view_permission(self, _permissions) -> None:
        for path in ("metric-families", "services", "residency-stages"):
            _permissions.reset_mock()
            client.get(f"/v1/slate/insights/{path}")
            _, args, _ = _permissions.mock_calls[0]
            assert args[2] == "versions"
            assert args[3] == "view"


# ─── The lane ────────────────────────────────────────────────────────────────


class TestLaneRead:
    """Retention, residency and destinations are read together or they drift on screen."""

    def test_the_lane_is_returned_in_camel_case(self) -> None:
        response = client.get(f"/v1/slate/environments/{ENV}/insights")
        assert response.status_code == 200
        body = response.json()
        assert body["policyVersion"] == 3
        assert body["policy"]["logRetentionDays"] == 14
        assert body["policy"]["privacyThreshold"] == 10
        assert body["signalsDigest"].startswith("sha256:")

    def test_the_lane_returns_all_six_residency_stages(self) -> None:
        """Five stages is not a promise, it is a promise with the sixth unwritten."""
        body = client.get(f"/v1/slate/environments/{ENV}/insights").json()
        assert [lane["stage"] for lane in body["residencyLanes"]] == list(RESIDENCY_STAGES)
        assert body["residencyComplete"] is True
        for lane in body["residencyLanes"]:
            assert lane["uncoveredSentence"]
            assert lane["label"]

    def test_an_incomplete_residency_set_reports_no_effective_promise(self) -> None:
        """A read must show the gap, not hand the operator a 409 they cannot act on."""
        with patch(
            "app.slate_insights_routes.ensure_residency_lanes",
            return_value=[stored_lane("ingress")],
        ):
            body = client.get(f"/v1/slate/environments/{ENV}/insights").json()
        assert body["residencyComplete"] is False
        assert body["effectiveResidencyClass"] is None

    def test_the_lane_reports_the_weakest_promise_any_stage_makes(self) -> None:
        lanes = stored_lanes()
        lanes[-1] = stored_lane(
            "log-data-storage",
            residency_class="unrestricted",
            regions=[],
            residency_waiver_reason="Provider has no EU log region.",
        )
        with patch("app.slate_insights_routes.ensure_residency_lanes", return_value=lanes):
            body = client.get(f"/v1/slate/environments/{ENV}/insights").json()
        assert body["effectiveResidencyClass"] == "unrestricted"
        assert any(w["code"] == "residency-partially-unrestricted" for w in body["warnings"])

    def test_a_never_configured_lane_is_unrestricted_not_a_promise_nobody_made(self) -> None:
        """The tempting default is the strictest class. It is wrong, and this pins why.

        ``in-region-only`` is not a safe default but a compliance claim, and creating six of them
        for a lane nobody has configured asserts a promise nobody made — the exact overstatement
        ``uncovered_sentence`` is NOT NULL to prevent. It would also have to name a region to
        satisfy V190, and the only placeholder available is ``auto``, so the row would claim
        confinement to something that is not a region.
        """
        lanes = _default_lanes()
        assert len(lanes) == 6
        for lane in lanes:
            assert lane["residency_class"] == "unrestricted"
            # V190 accepts the loosening only when it is explained, and the explanation is the
            # honest one: nothing has been promised yet.
            assert lane["residency_waiver_reason"]
            assert "no residency promise has been made" in lane["residency_waiver_reason"]
            # The gap sentence is still mandatory, and still the stage's own.
            assert lane["uncovered_sentence"]

    def test_the_default_lane_set_would_satisfy_every_v190_residency_constraint(self) -> None:
        """The previous default tripped ``confined_needs_regions`` on first read. This pins that
        the replacement satisfies both residency CHECKs rather than trading one break for another.
        """
        for lane in _default_lanes():
            unrestricted = lane["residency_class"] == "unrestricted"
            # slate_residency_lanes_unrestricted_needs_reason
            assert not unrestricted or lane["residency_waiver_reason"] is not None
            # slate_residency_lanes_confined_needs_regions
            assert unrestricted or len(lane["regions"]) > 0

    def test_the_response_states_that_nothing_is_collecting(self) -> None:
        body = client.get(f"/v1/slate/environments/{ENV}/insights").json()
        assert body["enforcement"]["enforced"] is False
        assert body["enforcement"]["observed"] is False
        assert "No collector is attached" in body["enforcement"]["sentence"]
        assert body["policy"]["edgeAttached"] is False

    def test_exports_budgets_and_checks_travel_with_the_lane(self) -> None:
        with (
            patch("app.slate_insights_routes.list_exports", return_value=[stored_export()]),
            patch("app.slate_insights_routes.list_budgets", return_value=[stored_budget()]),
            patch(
                "app.slate_insights_routes.list_synthetic_checks", return_value=[stored_check()]
            ),
        ):
            body = client.get(f"/v1/slate/environments/{ENV}/insights").json()
        assert body["exports"][0]["label"] == "Honeycomb"
        assert body["budgets"][0]["amount"] == 500.0
        assert body["syntheticChecks"][0]["targetPath"] == "/"

    def test_an_export_carries_a_secret_reference_and_no_header_value(self) -> None:
        with patch("app.slate_insights_routes.list_exports", return_value=[stored_export()]):
            body = client.get(f"/v1/slate/environments/{ENV}/insights").json()
        export = body["exports"][0]
        assert export["headerSecretRef"] == "honeycomb-key"
        assert "headers" not in export
        assert "headerValue" not in export

    def test_an_export_cannot_report_that_anything_was_delivered(self) -> None:
        with patch("app.slate_insights_routes.list_exports", return_value=[stored_export()]):
            body = client.get(f"/v1/slate/environments/{ENV}/insights").json()
        assert body["exports"][0]["edgeAttached"] is False
        assert body["exports"][0]["lastDeliveryState"] == "never-attempted"

    def test_a_budget_amount_survives_the_trip_from_numeric(self) -> None:
        """A Decimal that coerced to zero would make the digest and the budget disagree."""
        with patch("app.slate_insights_routes.list_budgets", return_value=[stored_budget()]):
            body = client.get(f"/v1/slate/environments/{ENV}/insights").json()
        assert body["budgets"][0]["amount"] == 500.0
        assert body["budgets"][0]["alertThresholds"] == [0.8, 1.0]

    def test_the_digest_changes_when_the_configuration_does(self) -> None:
        first = client.get(f"/v1/slate/environments/{ENV}/insights").json()["signalsDigest"]
        with patch("app.slate_insights_routes.list_budgets", return_value=[stored_budget()]):
            second = client.get(f"/v1/slate/environments/{ENV}/insights").json()["signalsDigest"]
        assert first != second

    def test_an_unknown_environment_answers_404_not_403(self) -> None:
        """A cross-tenant probe must not be able to confirm the lane exists."""
        with patch("app.slate_insights_routes.get_environment", return_value=None):
            response = client.get(f"/v1/slate/environments/{ENV}/insights")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "environment_not_found"

    def test_reading_the_lane_requires_the_view_permission(self, _permissions) -> None:
        client.get(f"/v1/slate/environments/{ENV}/insights")
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "view"


# ─── Policy writes ───────────────────────────────────────────────────────────


class TestPolicyWrites:
    """The evidence a later investigation wants is what somebody shortened retention on first."""

    def test_setting_the_policy_writes_bumps_and_audits(self) -> None:
        with (
            patch(
                "app.slate_insights_routes.update_policy",
                return_value={**POLICY, "policy_version": 4, "log_retention_days": 30},
            ) as write,
            patch("app.slate_insights_routes.append_audit") as audit,
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/insights/policy",
                json=policy_request(logRetentionDays=30),
            )
        assert response.status_code == 200
        body = response.json()
        assert body["applied"] is True
        assert body["policyVersion"] == 4
        assert body["policy"]["logRetentionDays"] == 30
        assert write.called and audit.called

    def test_the_write_response_carries_the_enforcement_block(self) -> None:
        with patch(
            "app.slate_insights_routes.update_policy",
            return_value={**POLICY, "policy_version": 4},
        ):
            body = client.put(
                f"/v1/slate/environments/{ENV}/insights/policy", json=policy_request()
            ).json()
        assert body["enforcement"]["enforced"] is False
        assert body["enforcement"]["observed"] is False
        assert "No collector is attached" in body["enforcement"]["sentence"]

    def test_shortening_retention_below_the_floor_without_a_reason_is_refused(self) -> None:
        response = client.put(
            f"/v1/slate/environments/{ENV}/insights/policy",
            json=policy_request(logRetentionDays=3),
        )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "retention-below-floor"
        assert detail["reason"] == "retention-below-floor"
        assert detail["message"] == refusal_sentence("retention-below-floor")

    def test_shortening_retention_with_a_stated_reason_is_allowed(self) -> None:
        with patch(
            "app.slate_insights_routes.update_policy",
            return_value={**POLICY, "policy_version": 4, "log_retention_days": 3},
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/insights/policy",
                json=policy_request(
                    logRetentionDays=3, retentionWaiverReason="Regulator ordered deletion."
                ),
            )
        assert response.status_code == 200
        assert response.json()["applied"] is True

    def test_a_privacy_threshold_below_the_identifiability_floor_is_refused(self) -> None:
        response = client.put(
            f"/v1/slate/environments/{ENV}/insights/policy",
            json=policy_request(privacyThreshold=2),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "privacy-threshold-below-floor"
        assert response.json()["detail"]["message"] == refusal_sentence(
            "privacy-threshold-below-floor"
        )

    def test_a_refused_policy_change_is_audited(self) -> None:
        with patch("app.slate_insights_routes.append_audit") as audit:
            client.put(
                f"/v1/slate/environments/{ENV}/insights/policy",
                json=policy_request(privacyThreshold=1),
            )
        assert audit.called
        assert audit.call_args.kwargs["summary"] == "Observability policy change refused"

    def test_shortening_retention_warns_without_blocking(self) -> None:
        with patch(
            "app.slate_insights_routes.update_policy",
            return_value={**POLICY, "policy_version": 4},
        ):
            body = client.put(
                f"/v1/slate/environments/{ENV}/insights/policy",
                json=policy_request(metricRetentionDays=30),
            ).json()
        assert body["applied"] is True
        assert any(w["code"] == "retention-shortened" for w in body["warnings"])

    def test_a_sparse_sample_rate_warns_without_blocking(self) -> None:
        with patch(
            "app.slate_insights_routes.update_policy",
            return_value={**POLICY, "policy_version": 4},
        ):
            body = client.put(
                f"/v1/slate/environments/{ENV}/insights/policy",
                json=policy_request(defaultSampleRate=0.0001),
            ).json()
        assert any(w["code"] == "sampling-sparse" for w in body["warnings"])

    def test_a_dry_run_writes_nothing_and_reports_applied_false(self) -> None:
        with (
            patch("app.slate_insights_routes.update_policy") as write,
            patch("app.slate_insights_routes.bump_policy_version") as bump,
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/insights/policy",
                json=policy_request(dryRun=True, logRetentionDays=30),
            )
        assert response.status_code == 200
        body = response.json()
        assert body["applied"] is False
        assert body["dryRun"] is True
        assert body["policy"]["logRetentionDays"] == 30
        assert not write.called and not bump.called

    def test_a_lost_update_reports_the_version_that_actually_won(self) -> None:
        with patch(
            "app.slate_insights_routes.bump_policy_version",
            side_effect=SlateInsightPolicyConflictError(ENV, 3, 7),
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/insights/policy", json=policy_request()
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "policy-version-conflict"
        assert detail["message"] == refusal_sentence("policy-version-conflict")
        assert detail["actualPolicyVersion"] == 7

    def test_a_missing_policy_row_answers_404(self) -> None:
        with patch(
            "app.slate_insights_routes.update_policy",
            side_effect=SlateInsightStoreError("policy_not_found", "gone"),
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/insights/policy", json=policy_request()
            )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "policy_not_found"

    def test_writing_the_policy_requires_the_publish_permission(self, _permissions) -> None:
        with patch("app.slate_insights_routes.update_policy", return_value=dict(POLICY)):
            client.put(f"/v1/slate/environments/{ENV}/insights/policy", json=policy_request())
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"


# ─── Residency writes ────────────────────────────────────────────────────────


class TestResidencyWrites:
    """A claim with no stated gap is the version somebody quotes to a regulator."""

    def test_writing_a_stage_writes_and_audits(self) -> None:
        with (
            patch(
                "app.slate_insights_routes.upsert_residency_lane",
                return_value=stored_lane("ingress"),
            ) as write,
            patch("app.slate_insights_routes.append_audit") as audit,
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/insights/residency/ingress",
                json=residency_request(),
            )
        assert response.status_code == 200
        body = response.json()
        assert body["applied"] is True
        assert body["policyVersion"] == 4
        assert body["lane"]["stage"] == "ingress"
        assert write.called and audit.called

    def test_the_written_stage_carries_its_catalog_prose(self) -> None:
        with patch(
            "app.slate_insights_routes.upsert_residency_lane",
            return_value=stored_lane("cache-storage"),
        ):
            body = client.put(
                f"/v1/slate/environments/{ENV}/insights/residency/cache-storage",
                json=residency_request(),
            ).json()
        assert body["lane"]["label"] == "Cache storage"
        assert body["lane"]["covers"]

    def test_a_blank_gap_sentence_becomes_the_catalog_sentence_rather_than_a_blank(self) -> None:
        """``residency-gap-unstated`` is unreachable here, and that is the stronger guarantee.

        Whitespace reads exactly like a stated gap on screen, so normalization treats it as absent
        and substitutes the stage's catalog sentence. The refusal remains in the domain module for
        a caller that reaches the store by another route; through this surface a lane cannot be
        written with no stated gap at all.
        """
        for blank in ("", "   "):
            with patch(
                "app.slate_insights_routes.upsert_residency_lane",
                return_value=stored_lane("ingress"),
            ) as write:
                response = client.put(
                    f"/v1/slate/environments/{ENV}/insights/residency/ingress",
                    json=residency_request(uncoveredSentence=blank),
                )
            assert response.status_code == 200
            written = write.call_args.kwargs["lane"]["uncovered_sentence"]
            assert written.strip()
            assert written == next(
                d.default_uncovered for d in RESIDENCY_STAGE_CATALOG if d.stage == "ingress"
            )

    def test_going_unrestricted_without_a_stated_reason_is_refused(self) -> None:
        response = client.put(
            f"/v1/slate/environments/{ENV}/insights/residency/function-execution",
            json=residency_request(residencyClass="unrestricted", regions=[]),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "residency-violation"
        assert response.json()["detail"]["message"] == refusal_sentence("residency-violation")

    def test_a_confined_stage_naming_no_region_is_refused(self) -> None:
        """The strictest-sounding setting that means nothing."""
        response = client.put(
            f"/v1/slate/environments/{ENV}/insights/residency/ingress",
            json=residency_request(residencyClass="in-region-only", regions=[]),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "residency-violation"

    def test_going_unrestricted_with_a_reason_is_allowed(self) -> None:
        with patch(
            "app.slate_insights_routes.upsert_residency_lane",
            return_value=stored_lane("log-data-storage", residency_class="unrestricted"),
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/insights/residency/log-data-storage",
                json=residency_request(
                    residencyClass="unrestricted",
                    regions=[],
                    residencyWaiverReason="Provider has no EU log region.",
                ),
            )
        assert response.status_code == 200
        assert response.json()["applied"] is True

    def test_a_stage_that_is_not_one_of_the_six_answers_404(self) -> None:
        response = client.put(
            f"/v1/slate/environments/{ENV}/insights/residency/invented-stage",
            json=residency_request(),
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "residency_stage_not_found"

    def test_a_residency_dry_run_writes_nothing(self) -> None:
        with (
            patch("app.slate_insights_routes.upsert_residency_lane") as write,
            patch("app.slate_insights_routes.bump_policy_version") as bump,
        ):
            body = client.put(
                f"/v1/slate/environments/{ENV}/insights/residency/ingress",
                json=residency_request(dryRun=True),
            ).json()
        assert body["applied"] is False
        assert body["dryRun"] is True
        assert not write.called and not bump.called

    def test_the_write_reports_the_promise_the_lane_as_a_whole_now_makes(self) -> None:
        with patch(
            "app.slate_insights_routes.upsert_residency_lane",
            return_value=stored_lane("ingress"),
        ):
            body = client.put(
                f"/v1/slate/environments/{ENV}/insights/residency/ingress",
                json=residency_request(),
            ).json()
        assert body["effectiveResidencyClass"] == "in-region-only"

    def test_a_refused_residency_change_is_audited(self) -> None:
        with patch("app.slate_insights_routes.append_audit") as audit:
            client.put(
                f"/v1/slate/environments/{ENV}/insights/residency/ingress",
                json=residency_request(residencyClass="unrestricted", regions=[]),
            )
        assert audit.call_args.kwargs["subject_kind"] == "residency"
        assert audit.call_args.kwargs["summary"] == "Residency change refused for ingress"

    def test_writing_residency_requires_the_publish_permission(self, _permissions) -> None:
        with patch(
            "app.slate_insights_routes.upsert_residency_lane",
            return_value=stored_lane("ingress"),
        ):
            client.put(
                f"/v1/slate/environments/{ENV}/insights/residency/ingress",
                json=residency_request(),
            )
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"


# ─── Export destinations ─────────────────────────────────────────────────────


class TestExports:
    """A destination is a reference and an endpoint, and never a bearer token."""

    def test_creating_an_export_writes_and_audits(self) -> None:
        with (
            patch(
                "app.slate_insights_routes.upsert_export", return_value=stored_export()
            ) as write,
            patch("app.slate_insights_routes.append_audit") as audit,
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/insights/exports", json=export_request()
            )
        assert response.status_code == 201
        body = response.json()
        assert body["applied"] is True
        assert body["export"]["label"] == "Honeycomb"
        assert body["policyVersion"] == 4
        assert write.called and audit.called

    def test_an_inline_header_value_is_refused_rather_than_dropped(self) -> None:
        """Silently accepting a pasted bearer token would teach the operator it was stored."""
        response = client.post(
            f"/v1/slate/environments/{ENV}/insights/exports",
            json=export_request(headers={"authorization": "Bearer hunter2"}),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "export-header-inline"
        assert response.json()["detail"]["message"] == refusal_sentence("export-header-inline")

    def test_a_bare_header_value_is_refused_too(self) -> None:
        response = client.post(
            f"/v1/slate/environments/{ENV}/insights/exports",
            json=export_request(headerValue="Bearer hunter2"),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "export-header-inline"

    def test_a_plaintext_endpoint_is_refused(self) -> None:
        response = client.post(
            f"/v1/slate/environments/{ENV}/insights/exports",
            json=export_request(endpoint="http://collector.internal:4318"),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "export-endpoint-insecure"
        assert response.json()["detail"]["message"] == refusal_sentence(
            "export-endpoint-insecure"
        )

    def test_a_partial_signal_set_warns_without_blocking(self) -> None:
        with patch(
            "app.slate_insights_routes.upsert_export",
            return_value=stored_export(signals=["traces"]),
        ):
            body = client.post(
                f"/v1/slate/environments/{ENV}/insights/exports",
                json=export_request(signals=["traces"]),
            ).json()
        assert body["applied"] is True
        assert any(w["code"] == "export-partial-signals" for w in body["warnings"])

    def test_an_unrecognized_signal_set_falls_back_rather_than_being_silently_empty(self) -> None:
        """A destination configured, enabled and silent is the one nobody notices."""
        with patch(
            "app.slate_insights_routes.upsert_export", return_value=stored_export()
        ) as write:
            client.post(
                f"/v1/slate/environments/{ENV}/insights/exports",
                json=export_request(signals=["profiles"]),
            )
        assert write.call_args.kwargs["export"]["signals"] == ["metrics", "traces"]

    def test_replacing_an_export_runs_the_same_gates_as_a_create(self) -> None:
        response = client.put(
            f"/v1/slate/environments/{ENV}/insights/exports/{EXPORT}",
            json=export_request(endpoint="http://collector.internal:4318"),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "export-endpoint-insecure"

    def test_an_export_dry_run_writes_nothing(self) -> None:
        with (
            patch("app.slate_insights_routes.upsert_export") as write,
            patch("app.slate_insights_routes.bump_policy_version") as bump,
        ):
            body = client.post(
                f"/v1/slate/environments/{ENV}/insights/exports",
                json=export_request(dryRun=True),
            ).json()
        assert body["applied"] is False
        assert body["dryRun"] is True
        assert not write.called and not bump.called

    def test_removing_an_export_bumps_and_audits(self) -> None:
        with (
            patch(
                "app.slate_insights_routes.delete_export", return_value=stored_export()
            ) as delete,
            patch("app.slate_insights_routes.append_audit") as audit,
        ):
            response = client.delete(
                f"/v1/slate/environments/{ENV}/insights/exports/{EXPORT}"
                "?expectedPolicyVersion=3"
            )
        assert response.status_code == 200
        assert response.json()["deleted"] is True
        assert response.json()["policyVersion"] == 4
        assert delete.called and audit.called

    def test_removing_an_export_that_was_never_there_answers_404(self) -> None:
        with patch(
            "app.slate_insights_routes.delete_export",
            side_effect=SlateInsightStoreError("export_not_found", "no such destination"),
        ):
            response = client.delete(
                f"/v1/slate/environments/{ENV}/insights/exports/{EXPORT}"
                "?expectedPolicyVersion=3"
            )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "export_not_found"

    def test_writing_an_export_requires_the_publish_permission(self, _permissions) -> None:
        with patch("app.slate_insights_routes.upsert_export", return_value=stored_export()):
            client.post(
                f"/v1/slate/environments/{ENV}/insights/exports", json=export_request()
            )
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"


# ─── Budgets ─────────────────────────────────────────────────────────────────


class TestBudgets:
    """Money reconciles or it is not money."""

    def test_creating_a_budget_writes_and_audits(self) -> None:
        with (
            patch(
                "app.slate_insights_routes.upsert_budget", return_value=stored_budget()
            ) as write,
            patch("app.slate_insights_routes.append_audit") as audit,
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/insights/budgets", json=budget_request()
            )
        assert response.status_code == 201
        assert response.json()["applied"] is True
        assert response.json()["budget"]["amount"] == 500.0
        assert write.called and audit.called

    def test_a_zero_budget_is_refused(self) -> None:
        response = client.post(
            f"/v1/slate/environments/{ENV}/insights/budgets", json=budget_request(amount=0)
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "budget-not-positive"
        assert response.json()["detail"]["message"] == refusal_sentence("budget-not-positive")

    def test_a_budget_in_another_currency_from_the_usage_is_refused(self) -> None:
        """Converting at a rate this system invented would put the threshold on an unreviewed rate."""
        with patch("app.slate_insights_routes.list_usage", return_value=[stored_usage()]):
            response = client.post(
                f"/v1/slate/environments/{ENV}/insights/budgets",
                json=budget_request(currency="EUR"),
            )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "currency-mismatch"
        assert response.json()["detail"]["message"] == refusal_sentence("currency-mismatch")

    def test_the_usage_currency_is_read_rather_than_asserted_by_the_caller(self) -> None:
        """A client able to declare agreement could make the mismatch refusal unreachable."""
        with patch("app.slate_insights_routes.list_usage", return_value=[stored_usage()]) as read:
            client.post(
                f"/v1/slate/environments/{ENV}/insights/budgets",
                json=budget_request(currency="EUR"),
            )
        assert read.called
        assert read.call_args.kwargs["environment_id"] == ENV

    def test_a_budget_already_nearly_exhausted_warns_without_blocking(self) -> None:
        with (
            patch(
                "app.slate_insights_routes.list_usage",
                return_value=[stored_usage(amount=Decimal("480.000000"))],
            ),
            patch("app.slate_insights_routes.upsert_budget", return_value=stored_budget()),
        ):
            body = client.post(
                f"/v1/slate/environments/{ENV}/insights/budgets", json=budget_request()
            ).json()
        assert body["applied"] is True
        assert any(w["code"] == "budget-near-exhausted" for w in body["warnings"])

    def test_omitted_thresholds_fall_back_rather_than_producing_a_budget_that_never_alerts(
        self,
    ) -> None:
        with patch(
            "app.slate_insights_routes.upsert_budget", return_value=stored_budget()
        ) as write:
            client.post(
                f"/v1/slate/environments/{ENV}/insights/budgets",
                json=budget_request(alertThresholds=[]),
            )
        assert write.call_args.kwargs["budget"]["alert_thresholds"] == [0.8, 1.0]

    def test_replacing_a_budget_runs_the_same_gates_as_a_create(self) -> None:
        response = client.put(
            f"/v1/slate/environments/{ENV}/insights/budgets/{BUDGET}",
            json=budget_request(amount=-5),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "budget-not-positive"

    def test_a_budget_dry_run_writes_nothing(self) -> None:
        with (
            patch("app.slate_insights_routes.upsert_budget") as write,
            patch("app.slate_insights_routes.bump_policy_version") as bump,
        ):
            body = client.post(
                f"/v1/slate/environments/{ENV}/insights/budgets",
                json=budget_request(dryRun=True),
            ).json()
        assert body["applied"] is False
        assert body["dryRun"] is True
        assert not write.called and not bump.called

    def test_removing_a_budget_bumps_and_audits(self) -> None:
        with (
            patch(
                "app.slate_insights_routes.delete_budget", return_value=stored_budget()
            ) as delete,
            patch("app.slate_insights_routes.append_audit") as audit,
        ):
            response = client.delete(
                f"/v1/slate/environments/{ENV}/insights/budgets/{BUDGET}"
                "?expectedPolicyVersion=3"
            )
        assert response.status_code == 200
        assert response.json()["deleted"] is True
        assert delete.called and audit.called

    def test_removing_a_budget_that_was_never_there_answers_404(self) -> None:
        with patch(
            "app.slate_insights_routes.delete_budget",
            side_effect=SlateInsightStoreError("budget_not_found", "no such budget"),
        ):
            response = client.delete(
                f"/v1/slate/environments/{ENV}/insights/budgets/{BUDGET}"
                "?expectedPolicyVersion=3"
            )
        assert response.status_code == 404

    def test_writing_a_budget_requires_the_publish_permission(self, _permissions) -> None:
        with patch("app.slate_insights_routes.upsert_budget", return_value=stored_budget()):
            client.post(
                f"/v1/slate/environments/{ENV}/insights/budgets", json=budget_request()
            )
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"


# ─── Synthetic checks ────────────────────────────────────────────────────────


class TestSyntheticChecks:
    """A probe that reports one region's health is not reporting the lane's."""

    def test_creating_a_check_writes_and_audits(self) -> None:
        with (
            patch(
                "app.slate_insights_routes.upsert_synthetic_check", return_value=stored_check()
            ) as write,
            patch("app.slate_insights_routes.append_audit") as audit,
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/insights/checks", json=check_request()
            )
        assert response.status_code == 201
        assert response.json()["applied"] is True
        assert response.json()["check"]["label"] == "Home page"
        assert write.called and audit.called

    def test_a_single_region_check_warns_without_blocking(self) -> None:
        with patch(
            "app.slate_insights_routes.upsert_synthetic_check",
            return_value=stored_check(regions=["eu-west"]),
        ):
            body = client.post(
                f"/v1/slate/environments/{ENV}/insights/checks",
                json=check_request(regions=["eu-west"]),
            ).json()
        assert body["applied"] is True
        assert any(w["code"] == "synthetic-single-region" for w in body["warnings"])

    def test_a_disabled_single_region_check_does_not_warn(self) -> None:
        with patch(
            "app.slate_insights_routes.upsert_synthetic_check", return_value=stored_check()
        ):
            body = client.post(
                f"/v1/slate/environments/{ENV}/insights/checks",
                json=check_request(regions=["eu-west"], enabled=False),
            ).json()
        assert body["warnings"] == []

    def test_replacing_a_check_writes(self) -> None:
        with patch(
            "app.slate_insights_routes.upsert_synthetic_check", return_value=stored_check()
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/insights/checks/{CHECK}", json=check_request()
            )
        assert response.status_code == 200
        assert response.json()["applied"] is True

    def test_a_check_dry_run_writes_nothing(self) -> None:
        with (
            patch("app.slate_insights_routes.upsert_synthetic_check") as write,
            patch("app.slate_insights_routes.bump_policy_version") as bump,
        ):
            body = client.post(
                f"/v1/slate/environments/{ENV}/insights/checks",
                json=check_request(dryRun=True),
            ).json()
        assert body["applied"] is False
        assert not write.called and not bump.called

    def test_removing_a_check_bumps_and_audits(self) -> None:
        with (
            patch(
                "app.slate_insights_routes.delete_synthetic_check", return_value=stored_check()
            ),
            patch("app.slate_insights_routes.append_audit") as audit,
        ):
            response = client.delete(
                f"/v1/slate/environments/{ENV}/insights/checks/{CHECK}?expectedPolicyVersion=3"
            )
        assert response.status_code == 200
        assert response.json()["deleted"] is True
        assert audit.called

    def test_removing_a_check_that_was_never_there_answers_404(self) -> None:
        with patch(
            "app.slate_insights_routes.delete_synthetic_check",
            side_effect=SlateInsightStoreError("check_not_found", "no such check"),
        ):
            response = client.delete(
                f"/v1/slate/environments/{ENV}/insights/checks/{CHECK}?expectedPolicyVersion=3"
            )
        assert response.status_code == 404


# ─── Live tail ───────────────────────────────────────────────────────────────


class TestLiveTail:
    """A tail is a capture of live reader traffic in front of a person."""

    def test_opening_a_tail_records_and_audits(self) -> None:
        with (
            patch(
                "app.slate_insights_routes.open_tail_session", return_value=stored_session()
            ) as write,
            patch("app.slate_insights_routes.append_audit") as audit,
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/insights/tail", json=tail_request()
            )
        assert response.status_code == 201
        body = response.json()
        assert body["applied"] is True
        assert body["session"]["streamState"] == "requested"
        assert write.called and audit.called

    def test_a_session_cannot_report_that_anything_was_delivered(self) -> None:
        with patch(
            "app.slate_insights_routes.open_tail_session",
            return_value=stored_session(events_delivered=42, edge_attached=True),
        ):
            body = client.post(
                f"/v1/slate/environments/{ENV}/insights/tail", json=tail_request()
            ).json()
        assert body["session"]["eventsDelivered"] == 0
        assert body["session"]["edgeAttached"] is False

    def test_a_tail_with_no_stated_reason_is_refused(self) -> None:
        response = client.post(
            f"/v1/slate/environments/{ENV}/insights/tail", json=tail_request(reason="  ")
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "tail-without-reason"
        assert response.json()["detail"]["message"] == refusal_sentence("tail-without-reason")

    def test_a_tail_above_the_lane_sampling_ceiling_is_refused(self) -> None:
        response = client.post(
            f"/v1/slate/environments/{ENV}/insights/tail", json=tail_request(sampleRate=0.5)
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "tail-exceeds-ceiling"
        assert response.json()["detail"]["message"] == refusal_sentence("tail-exceeds-ceiling")

    def test_a_tail_above_the_lane_event_ceiling_is_refused(self) -> None:
        response = client.post(
            f"/v1/slate/environments/{ENV}/insights/tail",
            json=tail_request(maxEventsPerSec=100000),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "tail-exceeds-ceiling"

    def test_a_tail_asking_for_a_field_outside_the_allowlist_is_refused(self) -> None:
        """A session that could add an authorization header is a credential capture."""
        response = client.post(
            f"/v1/slate/environments/{ENV}/insights/tail",
            json=tail_request(redactionAllowlist=["method", "authorization"]),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "tail-redaction-removed"
        assert response.json()["detail"]["message"] == refusal_sentence("tail-redaction-removed")

    def test_a_refused_tail_is_audited_even_on_a_dry_run(self) -> None:
        """A preview flag set by the caller must not keep an attempted capture out of the record."""
        with patch("app.slate_insights_routes.append_audit") as audit:
            client.post(
                f"/v1/slate/environments/{ENV}/insights/tail",
                json=tail_request(reason="", dryRun=True),
            )
        assert audit.called
        assert audit.call_args.kwargs["subject_kind"] == "live-tail"
        assert audit.call_args.kwargs["summary"] == "Live tail refused"

    def test_a_tail_dry_run_records_nothing(self) -> None:
        with patch("app.slate_insights_routes.open_tail_session") as write:
            body = client.post(
                f"/v1/slate/environments/{ENV}/insights/tail", json=tail_request(dryRun=True)
            ).json()
        assert body["applied"] is False
        assert body["dryRun"] is True
        assert not write.called

    def test_the_allowlist_actually_in_force_is_stored_on_the_session(self) -> None:
        with patch(
            "app.slate_insights_routes.open_tail_session", return_value=stored_session()
        ) as write:
            client.post(
                f"/v1/slate/environments/{ENV}/insights/tail",
                json=tail_request(redactionAllowlist=["method", "path", "statusCode"]),
            )
        assert write.call_args.kwargs["session"]["redaction_allowlist"] == [
            "method",
            "path",
            "statusCode",
        ]

    def test_listing_sessions_returns_them_newest_first(self) -> None:
        with patch(
            "app.slate_insights_routes.list_tail_sessions", return_value=[stored_session()]
        ):
            response = client.get(f"/v1/slate/environments/{ENV}/insights/tail")
        assert response.status_code == 200
        assert response.json()["sessions"][0]["reason"].startswith("Investigating")

    def test_closing_a_session_audits(self) -> None:
        with (
            patch(
                "app.slate_insights_routes.close_tail_session",
                return_value=stored_session(stream_state="closed"),
            ),
            patch("app.slate_insights_routes.append_audit") as audit,
        ):
            response = client.delete(
                f"/v1/slate/environments/{ENV}/insights/tail/{SESSION}"
            )
        assert response.status_code == 200
        assert response.json()["closed"] is True
        assert response.json()["session"]["streamState"] == "closed"
        assert audit.call_args.kwargs["summary"] == "Live tail closed"

    def test_closing_a_session_that_does_not_exist_answers_404(self) -> None:
        with patch(
            "app.slate_insights_routes.close_tail_session",
            side_effect=SlateInsightStoreError("session_not_found", "no such session"),
        ):
            response = client.delete(
                f"/v1/slate/environments/{ENV}/insights/tail/{SESSION}"
            )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "session_not_found"

    def test_opening_a_tail_requires_the_publish_permission(self, _permissions) -> None:
        with patch(
            "app.slate_insights_routes.open_tail_session", return_value=stored_session()
        ):
            client.post(f"/v1/slate/environments/{ENV}/insights/tail", json=tail_request())
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"

    def test_listing_sessions_requires_only_view(self, _permissions) -> None:
        with patch("app.slate_insights_routes.list_tail_sessions", return_value=[]):
            client.get(f"/v1/slate/environments/{ENV}/insights/tail")
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "view"


# ─── Metrics, logs and traces ────────────────────────────────────────────────


class TestSignals:
    """A point a drill-down cannot land on is worse than a gap in the chart."""

    def test_metrics_are_returned_correlated_on_release_and_region(self) -> None:
        with patch(
            "app.slate_insights_routes.list_metric_series", return_value=[stored_metric()]
        ):
            response = client.get(f"/v1/slate/environments/{ENV}/insights/metrics")
        assert response.status_code == 200
        point = response.json()["points"][0]
        assert point["releaseId"] == RELEASE
        assert point["region"] == "eu-west"
        assert point["value"] == 184.0
        assert point["metricKey"] == "latency-p95"

    def test_the_metric_response_cannot_claim_an_observation(self) -> None:
        with patch("app.slate_insights_routes.list_metric_series", return_value=[]):
            body = client.get(f"/v1/slate/environments/{ENV}/insights/metrics").json()
        assert body["basis"] == "policy-modelled"
        assert body["observed"] is False
        assert body["enforcement"]["enforced"] is False
        assert "modelled" in body["sentence"]

    def test_an_uncorrelatable_point_is_dropped_and_reported_rather_than_emitted(self) -> None:
        with patch(
            "app.slate_insights_routes.list_metric_series",
            return_value=[stored_metric(id="orphan", environment_id="")],
        ):
            body = client.get(f"/v1/slate/environments/{ENV}/insights/metrics").json()
        assert body["points"] == []
        assert body["dropped"][0]["id"] == "orphan"
        assert "cannot be attributed" in body["dropped"][0]["reason"]

    def test_a_point_below_the_privacy_threshold_is_suppressed_not_shown(self) -> None:
        with patch(
            "app.slate_insights_routes.list_metric_series",
            return_value=[stored_metric(sample_count=3)],
        ):
            body = client.get(f"/v1/slate/environments/{ENV}/insights/metrics").json()
        assert body["points"][0]["suppressed"] is True
        assert body["points"][0]["value"] is None
        assert body["suppressedCount"] == 1
        assert body["privacyThreshold"] == 10

    def test_logs_are_returned_with_their_redacted_evidence(self) -> None:
        with patch(
            "app.slate_insights_routes.list_logs",
            return_value=[
                {
                    "id": "log-1",
                    "at": datetime(2026, 7, 19, tzinfo=timezone.utc),
                    "level": "error",
                    "source": "origin",
                    "message": "upstream timeout",
                    "release_id": RELEASE,
                    "region": "eu-west",
                    "trace_ref": TRACE,
                    "evidence": {"method": "GET", "path": "/guide"},
                    "retain_until": datetime(2026, 8, 2, tzinfo=timezone.utc),
                }
            ],
        ):
            response = client.get(f"/v1/slate/environments/{ENV}/insights/logs")
        assert response.status_code == 200
        body = response.json()
        assert body["logs"][0]["evidence"] == {"method": "GET", "path": "/guide"}
        assert body["logs"][0]["observed"] is False
        assert body["observed"] is False

    def test_logs_can_be_narrowed_to_one_trace(self) -> None:
        with patch("app.slate_insights_routes.list_logs", return_value=[]) as read:
            client.get(f"/v1/slate/environments/{ENV}/insights/logs?traceRef={TRACE}")
        assert read.call_args.kwargs["trace_ref"] == TRACE

    def test_traces_can_be_narrowed_to_the_slow_ones(self) -> None:
        with patch("app.slate_insights_routes.list_traces", return_value=[]) as read:
            client.get(f"/v1/slate/environments/{ENV}/insights/traces?minDurationMs=500")
        assert read.call_args.kwargs["min_duration_ms"] == 500

    def test_a_trace_is_returned_with_its_spans_as_a_waterfall(self) -> None:
        with patch(
            "app.slate_insights_routes.get_trace",
            return_value={
                "trace": {
                    "id": TRACE,
                    "trace_id": TRACE_ID,
                    "started_at": datetime(2026, 7, 19, tzinfo=timezone.utc),
                    "duration_ms": 184,
                    "route": "/guide/{slug}",
                    "method": "GET",
                    "status_code": 200,
                    "sample_rate": Decimal("1.00000"),
                    "release_id": RELEASE,
                    "region": "eu-west",
                },
                "spans": [
                    {
                        "id": "span-1",
                        "span_id": SPAN_ID,
                        "name": "origin fetch",
                        "component": "origin",
                        "start_offset_ms": 10,
                        "duration_ms": 150,
                        "status": "ok",
                        "attributes": {"route": "/guide/{slug}"},
                    }
                ],
            },
        ):
            response = client.get(
                f"/v1/slate/environments/{ENV}/insights/traces/{TRACE_ID}"
            )
        assert response.status_code == 200
        body = response.json()
        assert body["trace"]["traceId"] == TRACE_ID
        assert body["trace"]["observed"] is False
        assert body["spans"][0]["component"] == "origin"
        assert body["spans"][0]["startOffsetMs"] == 10

    def test_an_unknown_trace_answers_404(self) -> None:
        with patch(
            "app.slate_insights_routes.get_trace",
            side_effect=SlateInsightStoreError("trace_not_found", "no such trace"),
        ):
            response = client.get(
                f"/v1/slate/environments/{ENV}/insights/traces/{TRACE_ID}"
            )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "trace_not_found"

    def test_synthetic_results_can_be_narrowed_to_the_annotated_ones(self) -> None:
        with patch(
            "app.slate_insights_routes.list_synthetic_results",
            return_value=[
                {
                    "id": "result-1",
                    "check_id": CHECK,
                    "at": datetime(2026, 7, 19, tzinfo=timezone.utc),
                    "outcome": "degraded",
                    "region": "eu-west",
                    "status_code": 200,
                    "latency_ms": 2400,
                    "release_id": RELEASE,
                    "annotation_kind": "post-promotion-regression",
                    "annotation_note": "p95 doubled after promotion",
                }
            ],
        ) as read:
            response = client.get(
                f"/v1/slate/environments/{ENV}/insights/synthetic-results?annotatedOnly=true"
            )
        assert read.call_args.kwargs["annotated_only"] is True
        body = response.json()
        assert body["results"][0]["annotationKind"] == "post-promotion-regression"
        assert body["results"][0]["observed"] is False
        assert body["observed"] is False

    def test_reading_signals_requires_only_view(self, _permissions) -> None:
        for path in ("metrics", "logs", "traces", "synthetic-results"):
            _permissions.reset_mock()
            with (
                patch("app.slate_insights_routes.list_metric_series", return_value=[]),
                patch("app.slate_insights_routes.list_logs", return_value=[]),
                patch("app.slate_insights_routes.list_traces", return_value=[]),
                patch("app.slate_insights_routes.list_synthetic_results", return_value=[]),
            ):
                client.get(f"/v1/slate/environments/{ENV}/insights/{path}")
            _, args, _ = _permissions.mock_calls[0]
            assert args[3] == "view"


# ─── Usage and budget alerts ─────────────────────────────────────────────────


class TestUsageAndAlerts:
    """A modelled cost presented as a charge is not an estimate but an invented invoice."""

    def test_usage_is_rolled_up_per_service(self) -> None:
        with patch(
            "app.slate_insights_routes.list_usage",
            return_value=[
                stored_usage(),
                stored_usage(id="usage-2", usage_date="2026-07-20", amount=Decimal("7.500000")),
            ],
        ):
            response = client.get(f"/v1/slate/environments/{ENV}/insights/usage")
        assert response.status_code == 200
        body = response.json()
        rollup = body["rollups"][0]
        assert rollup["service"] == "delivery"
        assert rollup["label"] == "Delivery"
        assert rollup["amount"] == 20.0
        assert rollup["days"] == 2

    def test_no_response_carrying_money_can_claim_to_be_billable(self) -> None:
        with patch("app.slate_insights_routes.list_usage", return_value=[stored_usage()]):
            body = client.get(f"/v1/slate/environments/{ENV}/insights/usage").json()
        assert body["basis"] == "modelled"
        assert body["metered"] is False
        assert body["billable"] is False
        assert body["rollups"][0]["billable"] is False
        assert body["rollups"][0]["metered"] is False
        assert body["records"][0]["billable"] is False
        assert "may not be invoiced" in body["sentence"]

    def test_a_forecast_is_carried_separately_and_never_summed_into_the_total(self) -> None:
        with patch(
            "app.slate_insights_routes.list_usage",
            return_value=[stored_usage(), stored_usage(id="usage-2", usage_date="2026-07-20")],
        ):
            body = client.get(
                f"/v1/slate/environments/{ENV}/insights/usage?daysRemaining=10"
            ).json()
        assert body["rollups"][0]["amount"] == 25.0
        assert body["forecastAmount"] == 125.0
        assert body["forecastDaysRemaining"] == 10
        assert "never summed into a total" in body["forecastSentence"]

    def test_a_thin_history_warns_that_the_forecast_is_wide(self) -> None:
        with patch("app.slate_insights_routes.list_usage", return_value=[stored_usage()]):
            body = client.get(
                f"/v1/slate/environments/{ENV}/insights/usage?daysRemaining=20"
            ).json()
        assert any(w["code"] == "forecast-wide" for w in body["warnings"])

    def test_no_forecast_is_produced_when_none_was_asked_for(self) -> None:
        with patch("app.slate_insights_routes.list_usage", return_value=[stored_usage()]):
            body = client.get(f"/v1/slate/environments/{ENV}/insights/usage").json()
        assert body["forecastAmount"] is None

    def test_cache_savings_stay_absent_on_a_modelled_rollup(self) -> None:
        """A saving computed from a model is a discount nobody gave."""
        with patch(
            "app.slate_insights_routes.list_usage",
            return_value=[stored_usage(cache_savings_amount=Decimal("3.000000"))],
        ):
            body = client.get(f"/v1/slate/environments/{ENV}/insights/usage").json()
        assert body["rollups"][0]["cacheSavingsAmount"] is None

    def test_usage_in_two_currencies_is_refused_rather_than_converted(self) -> None:
        with patch(
            "app.slate_insights_routes.list_usage",
            return_value=[stored_usage(), stored_usage(id="usage-2", currency="EUR")],
        ):
            response = client.get(f"/v1/slate/environments/{ENV}/insights/usage")
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "currency-mismatch"
        assert response.json()["detail"]["message"] == refusal_sentence("currency-mismatch")

    def test_alerts_show_the_arithmetic_they_fired_on(self) -> None:
        with patch(
            "app.slate_insights_routes.list_budget_alerts",
            return_value=[
                {
                    "id": ALERT,
                    "budget_id": BUDGET,
                    "at": datetime(2026, 7, 19, tzinfo=timezone.utc),
                    "threshold": Decimal("0.800"),
                    "observed_amount": Decimal("410.000000"),
                    "budget_amount": Decimal("500.000000"),
                    "currency": "USD",
                    "period_start": "2026-07-01",
                    "period_end": "2026-07-31",
                    "delivery_state": "not-dispatched",
                    "acknowledged_at": None,
                    "acknowledged_by_actor_name": None,
                }
            ],
        ):
            response = client.get(f"/v1/slate/environments/{ENV}/insights/alerts")
        assert response.status_code == 200
        body = response.json()
        alert = body["alerts"][0]
        assert alert["threshold"] == 0.8
        assert alert["observedAmount"] == 410.0
        assert alert["budgetAmount"] == 500.0
        assert alert["basis"] == "modelled"
        assert alert["dispatched"] is False
        assert body["dispatched"] is False

    def test_alerts_can_be_narrowed_to_the_unacknowledged_ones(self) -> None:
        with patch("app.slate_insights_routes.list_budget_alerts", return_value=[]) as read:
            client.get(
                f"/v1/slate/environments/{ENV}/insights/alerts?unacknowledgedOnly=true"
            )
        assert read.call_args.kwargs["unacknowledged_only"] is True

    def test_acknowledging_an_alert_writes_and_audits(self) -> None:
        with (
            patch(
                "app.slate_insights_routes.acknowledge_budget_alert",
                return_value={
                    "id": ALERT,
                    "budget_id": BUDGET,
                    "threshold": Decimal("0.800"),
                    "observed_amount": Decimal("410.000000"),
                    "budget_amount": Decimal("500.000000"),
                    "currency": "USD",
                    "acknowledged_at": datetime(2026, 7, 20, tzinfo=timezone.utc),
                    "acknowledged_by_actor_name": "ken@example.com",
                },
            ) as write,
            patch("app.slate_insights_routes.append_audit") as audit,
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/insights/alerts/{ALERT}/acknowledge",
                json={"note": "Expected, campaign traffic."},
            )
        assert response.status_code == 200
        assert response.json()["acknowledged"] is True
        assert response.json()["alert"]["acknowledgedBy"] == "ken@example.com"
        assert write.called and audit.called

    def test_acknowledging_consumes_no_policy_version(self) -> None:
        """Invalidating every open editor to dismiss a notice is the wrong incident-time trade."""
        with (
            patch(
                "app.slate_insights_routes.acknowledge_budget_alert",
                return_value={"id": ALERT, "budget_id": BUDGET},
            ),
            patch("app.slate_insights_routes.bump_policy_version") as bump,
        ):
            client.post(
                f"/v1/slate/environments/{ENV}/insights/alerts/{ALERT}/acknowledge", json={}
            )
        assert not bump.called

    def test_acknowledging_an_alert_that_does_not_exist_answers_404(self) -> None:
        with patch(
            "app.slate_insights_routes.acknowledge_budget_alert",
            side_effect=SlateInsightStoreError("alert_not_found", "no such alert"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/insights/alerts/{ALERT}/acknowledge", json={}
            )
        assert response.status_code == 404

    def test_an_acknowledge_dry_run_writes_nothing(self) -> None:
        with patch("app.slate_insights_routes.acknowledge_budget_alert") as write:
            body = client.post(
                f"/v1/slate/environments/{ENV}/insights/alerts/{ALERT}/acknowledge",
                json={"dryRun": True},
            ).json()
        assert body["acknowledged"] is False
        assert body["dryRun"] is True
        assert not write.called

    def test_reading_usage_requires_only_view(self, _permissions) -> None:
        client.get(f"/v1/slate/environments/{ENV}/insights/usage")
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "view"


# ─── Audit and exports ───────────────────────────────────────────────────────


class TestAuditAndExport:
    """Who read the record of who opened a live tail is part of that record."""

    def test_the_audit_trail_is_returned_newest_first(self) -> None:
        with patch(
            "app.slate_insights_routes.list_audit",
            return_value=[
                {
                    "id": "audit-1",
                    "at": datetime(2026, 7, 19, tzinfo=timezone.utc),
                    "actor_name": "ken@example.com",
                    "actor_kind": "user",
                    "subject_kind": "live-tail",
                    "subject_id": SESSION,
                    "summary": "Live tail opened at 0.001 sampling",
                    "detail": {"reason": "Investigating 502s"},
                }
            ],
        ):
            response = client.get(f"/v1/slate/environments/{ENV}/insights/audit")
        assert response.status_code == 200
        entry = response.json()["entries"][0]
        assert entry["summary"] == "Live tail opened at 0.001 sampling"
        assert entry["detail"] == {"reason": "Investigating 502s"}

    def test_the_audit_trail_can_be_narrowed_to_one_subject_kind(self) -> None:
        with patch("app.slate_insights_routes.list_audit", return_value=[]) as read:
            client.get(f"/v1/slate/environments/{ENV}/insights/audit?subjectKind=live-tail")
        assert read.call_args.kwargs["subject_kind"] == "live-tail"

    def test_the_audit_export_neutralizes_a_cell_a_spreadsheet_would_execute(self) -> None:
        with patch(
            "app.slate_insights_routes.list_audit",
            return_value=[
                {
                    "id": "audit-1",
                    "at": None,
                    "actor_name": '=HYPERLINK("http://evil","click")',
                    "actor_kind": "user",
                    "subject_kind": "budget",
                    "subject_id": BUDGET,
                    "summary": "+SUM(A1:A9)",
                    "detail": "@import",
                }
            ],
        ):
            response = client.get(
                f"/v1/slate/environments/{ENV}/insights/audit/export"
            )
        assert response.status_code == 200
        text = response.text
        assert "'=HYPERLINK" in text
        assert "'+SUM" in text
        assert "'@import" in text

    def test_a_truncated_audit_export_says_so_in_words(self) -> None:
        """An auditor reading a silently truncated ledger concludes the rest never happened."""
        rows = [
            {
                "id": f"audit-{i}",
                "at": None,
                "actor_name": "a",
                "actor_kind": "user",
                "subject_kind": "policy",
                "subject_id": None,
                "summary": "s",
                "detail": None,
            }
            for i in range(3)
        ]
        with patch("app.slate_insights_routes.list_audit", return_value=rows) as read:
            response = client.get(
                f"/v1/slate/environments/{ENV}/insights/audit/export?limit=2"
            )
        assert read.call_args.kwargs["limit"] == 3, "one past the cap, so truncation is a fact"
        assert "TRUNCATED" in response.text
        assert "do not read this file as the complete record" in response.text

    def test_the_audit_export_writes_its_own_audit_row(self) -> None:
        with (
            patch("app.slate_insights_routes.list_audit", return_value=[]),
            patch("app.slate_insights_routes.append_audit") as audit,
        ):
            client.get(f"/v1/slate/environments/{ENV}/insights/audit/export")
        assert audit.call_args.kwargs["subject_kind"] == "export"
        assert audit.call_args.kwargs["summary"] == "Observability audit exported"

    def test_the_usage_export_states_basis_metered_and_billable_on_every_row(self) -> None:
        """A forwarded spreadsheet has to say what it is without the page around it."""
        with patch("app.slate_insights_routes.list_usage", return_value=[stored_usage()]):
            response = client.get(f"/v1/slate/environments/{ENV}/insights/usage/export")
        assert response.status_code == 200
        lines = [line for line in response.text.splitlines() if line]
        assert lines[0].endswith("basis,metered,billable")
        assert lines[1].endswith("modelled,false,false")

    def test_the_usage_export_neutralizes_a_cell_a_spreadsheet_would_execute(self) -> None:
        with patch(
            "app.slate_insights_routes.list_usage",
            return_value=[stored_usage(service="=cmd|' /c calc'!A0", region="@evil")],
        ):
            response = client.get(f"/v1/slate/environments/{ENV}/insights/usage/export")
        assert "'=cmd" in response.text
        assert "'@evil" in response.text

    def test_a_truncated_usage_export_says_so_in_words(self) -> None:
        rows = [stored_usage(id=f"usage-{i}") for i in range(3)]
        with patch("app.slate_insights_routes.list_usage", return_value=rows) as read:
            response = client.get(
                f"/v1/slate/environments/{ENV}/insights/usage/export?limit=2"
            )
        assert read.call_args.kwargs["limit"] == 3
        assert "TRUNCATED" in response.text
        assert "do not read this file as the complete record" in response.text

    def test_the_usage_export_writes_its_own_audit_row(self) -> None:
        with (
            patch("app.slate_insights_routes.list_usage", return_value=[]),
            patch("app.slate_insights_routes.append_audit") as audit,
        ):
            client.get(f"/v1/slate/environments/{ENV}/insights/usage/export")
        assert audit.call_args.kwargs["subject_kind"] == "export"
        assert audit.call_args.kwargs["summary"] == "Usage exported"

    def test_exporting_requires_view_not_publish(self, _permissions) -> None:
        """§29.7 gives the Auditor read-only policy and exportable evidence."""
        for path in ("audit/export", "usage/export"):
            _permissions.reset_mock()
            with (
                patch("app.slate_insights_routes.list_audit", return_value=[]),
                patch("app.slate_insights_routes.list_usage", return_value=[]),
            ):
                client.get(f"/v1/slate/environments/{ENV}/insights/{path}")
            _, args, _ = _permissions.mock_calls[0]
            assert args[3] == "view"
            assert args[3] != "publish"


# ─── Honesty is a property of the types ──────────────────────────────────────


class TestHonestyIsStructural:
    """A field that merely happens not to be assigned is one somebody will assign later.

    These tests construct the response models directly rather than driving a route, because the
    claim under test is about the type and not about any particular handler's discipline.
    """

    def test_a_usage_rollup_cannot_be_marked_billable(self) -> None:
        with pytest.raises(ValidationError):
            UsageRollupBody(service="delivery", billable=True)

    def test_a_usage_rollup_cannot_be_marked_metered(self) -> None:
        with pytest.raises(ValidationError):
            UsageRollupBody(service="delivery", metered=True)

    def test_a_usage_rollup_cannot_claim_a_metered_basis(self) -> None:
        with pytest.raises(ValidationError):
            UsageRollupBody(service="delivery", basis="metered")

    def test_a_usage_record_cannot_be_marked_billable(self) -> None:
        with pytest.raises(ValidationError):
            UsageRecordBody(id="usage-1", billable=True)

    def test_a_usage_response_cannot_be_marked_billable(self) -> None:
        with pytest.raises(ValidationError):
            UsageResponse(records=[], rollups=[], billable=True)

    def test_a_metric_point_cannot_claim_to_have_been_observed(self) -> None:
        with pytest.raises(ValidationError):
            MetricPointBody(observed=True)

    def test_a_metric_point_cannot_claim_an_edge_observed_basis(self) -> None:
        with pytest.raises(ValidationError):
            MetricPointBody(basis="edge-observed")

    def test_a_metrics_response_cannot_claim_to_have_been_observed(self) -> None:
        with pytest.raises(ValidationError):
            MetricsResponse(points=[], observed=True)

    def test_an_enforcement_block_cannot_claim_to_be_enforced(self) -> None:
        with pytest.raises(ValidationError):
            EnforcementBody(enforced=True)

    def test_a_policy_body_cannot_claim_an_edge_is_attached(self) -> None:
        with pytest.raises(ValidationError):
            InsightPolicyBody(edge_attached=True)

    def test_a_residency_lane_cannot_claim_to_be_enforced(self) -> None:
        with pytest.raises(ValidationError):
            ResidencyLaneBody(stage="ingress", enforced=True)

    def test_a_tail_session_cannot_claim_to_have_delivered_events(self) -> None:
        with pytest.raises(ValidationError):
            TailSessionBody(events_delivered=1)

    def test_a_tail_session_cannot_claim_an_edge_is_attached(self) -> None:
        with pytest.raises(ValidationError):
            TailSessionBody(edge_attached=True)

    def test_the_honest_defaults_are_what_a_bare_model_reports(self) -> None:
        rollup = UsageRollupBody(service="delivery")
        assert rollup.basis == "modelled"
        assert rollup.metered is False
        assert rollup.billable is False
        assert EnforcementBody().enforced is False
        assert TailSessionBody().events_delivered == 0


# ─── Route resolution ────────────────────────────────────────────────────────


class TestRouteResolution:
    """FastAPI matches in registration order, so the order is part of the contract."""

    @staticmethod
    def _paths() -> List[str]:
        return [getattr(route, "path", "") for route in app.routes]

    def test_the_tail_list_is_registered_before_the_tail_session_parameter(self) -> None:
        """A list arriving at the close handler would try to close a session named nothing."""
        paths = self._paths()
        base = "/v1/slate/environments/{environment_id}/insights/tail"
        assert paths.index(base) < paths.index(f"{base}/{{session_id}}")

    def test_the_trace_list_is_registered_before_the_trace_parameter(self) -> None:
        paths = self._paths()
        base = "/v1/slate/environments/{environment_id}/insights/traces"
        assert paths.index(base) < paths.index(f"{base}/{{trace_id}}")

    def test_every_literal_segment_precedes_its_own_sibling_parameter(self) -> None:
        """Within each resource group the collection is registered before the member."""
        paths = self._paths()
        prefix = "/v1/slate/environments/{environment_id}/insights"
        for literal, parameterized in (
            (f"{prefix}/exports", f"{prefix}/exports/{{export_id}}"),
            (f"{prefix}/budgets", f"{prefix}/budgets/{{budget_id}}"),
            (f"{prefix}/checks", f"{prefix}/checks/{{check_id}}"),
            (f"{prefix}/tail", f"{prefix}/tail/{{session_id}}"),
            (f"{prefix}/alerts", f"{prefix}/alerts/{{alert_id}}/acknowledge"),
            (f"{prefix}/traces", f"{prefix}/traces/{{trace_id}}"),
        ):
            assert paths.index(literal) < paths.index(parameterized), literal

    def test_the_lane_root_precedes_every_segment_beneath_it(self) -> None:
        paths = self._paths()
        prefix = "/v1/slate/environments/{environment_id}/insights"
        root = paths.index(prefix)
        for path in paths:
            if path.startswith(f"{prefix}/"):
                assert root < paths.index(path), path

    def test_the_resolved_table_is_exactly_the_published_contract(self) -> None:
        """The authoring surface is written against this list; a silent rename breaks it."""
        prefix = "/v1/slate/environments/{environment_id}/insights"
        resolved = {
            (path, method)
            for route in app.routes
            for path in [getattr(route, "path", "")]
            for method in getattr(route, "methods", set()) or set()
            if "/insights" in path
        }
        for expected in {
            ("/v1/slate/insights/metric-families", "GET"),
            ("/v1/slate/insights/services", "GET"),
            ("/v1/slate/insights/residency-stages", "GET"),
            (prefix, "GET"),
            (f"{prefix}/policy", "PUT"),
            (f"{prefix}/residency/{{stage}}", "PUT"),
            (f"{prefix}/exports", "POST"),
            (f"{prefix}/exports/{{export_id}}", "PUT"),
            (f"{prefix}/exports/{{export_id}}", "DELETE"),
            (f"{prefix}/budgets", "POST"),
            (f"{prefix}/budgets/{{budget_id}}", "PUT"),
            (f"{prefix}/budgets/{{budget_id}}", "DELETE"),
            (f"{prefix}/checks", "POST"),
            (f"{prefix}/checks/{{check_id}}", "PUT"),
            (f"{prefix}/checks/{{check_id}}", "DELETE"),
            (f"{prefix}/tail", "POST"),
            (f"{prefix}/tail", "GET"),
            (f"{prefix}/tail/{{session_id}}", "DELETE"),
            (f"{prefix}/alerts", "GET"),
            (f"{prefix}/alerts/{{alert_id}}/acknowledge", "POST"),
            (f"{prefix}/metrics", "GET"),
            (f"{prefix}/logs", "GET"),
            (f"{prefix}/traces", "GET"),
            (f"{prefix}/traces/{{trace_id}}", "GET"),
            (f"{prefix}/usage", "GET"),
            (f"{prefix}/usage/export", "GET"),
            (f"{prefix}/synthetic-results", "GET"),
            (f"{prefix}/audit", "GET"),
            (f"{prefix}/audit/export", "GET"),
        }:
            assert expected in resolved, expected


# ─── Refusal vocabulary ──────────────────────────────────────────────────────


class TestRefusalMapping:
    """The message is the domain module's own, character for character."""

    @pytest.mark.parametrize(
        "reason",
        [
            "retention-below-floor",
            "privacy-threshold-below-floor",
            "residency-gap-unstated",
            "residency-violation",
            "currency-mismatch",
            "tail-without-reason",
            "tail-exceeds-ceiling",
            "tail-redaction-removed",
            "export-header-inline",
            "export-endpoint-insecure",
            "budget-not-positive",
            "policy-version-conflict",
        ],
    )
    def test_every_reachable_refusal_maps_to_409_with_its_own_sentence(self, reason: str) -> None:
        """Asserted through the shared mapper, so a new refusal cannot arrive as a 500."""
        from app.slate_insights_routes import _refusal_http

        error = SlateInsightRefusedError(InsightRefusal.of(reason))
        mapped = _refusal_http(error)
        assert mapped.status_code == 409
        assert mapped.detail == {
            "code": reason,
            "message": refusal_sentence(reason),
            "reason": reason,
        }
        assert mapped.detail["message"] is not reason

    def test_a_warning_reaches_the_client_with_its_sentence_intact(self) -> None:
        from app.slate_insights_routes import _warning_bodies

        bodies = _warning_bodies([InsightWarning.of("forecast-wide", "forecast_amount")])
        assert bodies[0].code == "forecast-wide"
        assert bodies[0].field == "forecast_amount"
        assert bodies[0].message == InsightWarning.of("forecast-wide").message
        assert bodies[0].severity == "warn"

    def test_every_write_route_answers_404_for_an_unknown_environment(self) -> None:
        """A cross-tenant probe must not be able to confirm the lane exists, on any verb."""
        with patch("app.slate_insights_routes.get_environment", return_value=None):
            assert (
                client.put(
                    f"/v1/slate/environments/{ENV}/insights/policy", json=policy_request()
                ).status_code
                == 404
            )
            assert (
                client.post(
                    f"/v1/slate/environments/{ENV}/insights/exports", json=export_request()
                ).status_code
                == 404
            )
            assert (
                client.post(
                    f"/v1/slate/environments/{ENV}/insights/budgets", json=budget_request()
                ).status_code
                == 404
            )
            assert (
                client.post(
                    f"/v1/slate/environments/{ENV}/insights/tail", json=tail_request()
                ).status_code
                == 404
            )
            assert (
                client.get(f"/v1/slate/environments/{ENV}/insights/usage").status_code == 404
            )
