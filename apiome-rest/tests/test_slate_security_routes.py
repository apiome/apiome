"""Security control REST surface — UXE-3.2 (private-suite#2474).

Route-level tests over :mod:`app.slate_security_routes`, following the
``test_slate_cache_routes.py`` precedent: a module-level ``TestClient``, a mock auth dict, and
store functions patched *where used*. The pure module and the store are proven separately in their
own suites; what is asserted here is the contract the surface publishes.

The claims that matter most, and which nothing below is allowed to weaken:

* **Every route names the permission it needs.** VIEW for reads including simulation — "which
  rule blocked this customer" is the question that brings an operator here during an incident,
  and requiring PUBLISH would put the answer out of reach of the person asking.
* **Refusals reach the client as sentences.** 409 with ``{code, message, reason}``, the shape the
  authoring surface's ``disabledReason`` renders.
* **Dual control is real.** An enforcing block rule needs an approval of *this* body by somebody
  *other* than its author, and each of the three ways that can fail is a distinct named refusal.
* **Redaction happens.** The route hands raw request data to the store and the store strips it;
  a cookie does not survive and an address becomes a network.
* **No response can claim an enforcement.** ``observed``, ``enforced`` and ``mitigated`` are
  literal defaults, so the honesty of the surface is a property of its types.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.slate_auth import validate_slate_authentication
from app.slate_security import body_digest
from app.slate_security_store import redact_evidence

client = TestClient(app)

TENANT = "11111111-1111-1111-1111-111111111111"
SITE = "22222222-2222-2222-2222-222222222222"
ENV = "33333333-3333-3333-3333-333333333333"
RULE = "44444444-4444-4444-4444-444444444444"
RELEASE = "55555555-5555-5555-5555-555555555555"
EXCEPTION = "66666666-6666-6666-6666-666666666666"
EVENT = "77777777-7777-7777-7777-777777777777"

AUTHOR_KEY = "user-1"
APPROVER_KEY = "user-2"

_MOCK_JWT: Dict[str, Any] = {
    "tenant_id": TENANT,
    "tenant_slug": "acme",
    "user_id": AUTHOR_KEY,
    "email": "ken@example.com",
    "auth_type": "jwt",
}

ENVIRONMENT = {"id": ENV, "site_id": SITE, "tenant_id": TENANT, "active_release_id": RELEASE}

POLICY = {
    "id": "policy-1",
    "tenant_id": TENANT,
    "site_id": SITE,
    "environment_id": ENV,
    "managed_ruleset": "core",
    "bot_preset": "balanced",
    "rate_preset": "standard",
    "challenge_mode": "managed",
    "preset_overrides": {},
    "managed_off_reason": None,
    "policy_version": 3,
    "edge_attached": False,
    "edge_provider": None,
    "updated_at": None,
    "updated_by_actor_name": "ken@example.com",
}


def rule_body(**overrides) -> Dict[str, Any]:
    """A valid custom-rule request body, in the camelCase the wire uses."""
    base = {
        "ordinal": 0,
        "enabled": True,
        "label": "Block admin probes",
        "matcherKind": "prefix",
        "matcherValue": "/admin",
        "matcherMethods": ["GET"],
        "matcherHosts": [],
        "conditions": [],
        "action": "log",
        "rolloutMode": "simulate",
        "rolloutPercent": 10,
        "acknowledgedWarnings": [],
        "expectedPolicyVersion": 3,
        "dryRun": False,
        "reason": "test",
    }
    base.update(overrides)
    return base


def snake_body(**overrides) -> Dict[str, Any]:
    """The same body in the snake_case ``model_dump`` produces, for computing its digest."""
    camel = rule_body(**overrides)
    mapping = {
        "matcherKind": "matcher_kind",
        "matcherValue": "matcher_value",
        "matcherMethods": "matcher_methods",
        "matcherHosts": "matcher_hosts",
        "rolloutMode": "rollout_mode",
        "rolloutPercent": "rollout_percent",
        "acknowledgedWarnings": "acknowledged_warnings",
    }
    return {mapping.get(key, key): value for key, value in camel.items()}


def approval(digest: str, approver_key: str = APPROVER_KEY) -> Dict[str, Any]:
    """An approval row as the store returns it."""
    return {
        "id": "approval-1",
        "subject_kind": "rule",
        "subject_id": RULE,
        "digest": digest,
        "author_actor_key": AUTHOR_KEY,
        "author_actor_name": "ken@example.com",
        "approver_actor_key": approver_key,
        "approver_actor_name": "sam@example.com",
    }


def stored_rule(**overrides) -> Dict[str, Any]:
    """A rule row as the store returns it."""
    base = {
        "id": RULE,
        "ordinal": 0,
        "enabled": True,
        "label": "Block admin probes",
        "matcher_kind": "prefix",
        "matcher_value": "/admin",
        "matcher_methods": ["GET"],
        "matcher_hosts": [],
        "conditions": [],
        "action": "block",
        "rate_requests": None,
        "rate_window_seconds": None,
        "rollout_mode": "simulate",
        "rollout_percent": 10,
        "expires_at": None,
        "acknowledged_warnings": [],
        "body_digest": "sha256:" + "a" * 64,
        "revision": 2,
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_slate_authentication] = lambda: dict(_MOCK_JWT)
    yield
    app.dependency_overrides.pop(validate_slate_authentication, None)


@pytest.fixture(autouse=True)
def _permissions():
    """Allow by default; individual tests re-patch to assert the required permission."""
    with patch("app.slate_security_routes.enforce_permission") as enforce:
        yield enforce


@pytest.fixture(autouse=True)
def _lane():
    """Resolve the environment, its policy and the lookups every route needs."""
    with (
        patch("app.slate_security_routes.get_environment", return_value=dict(ENVIRONMENT)),
        patch("app.slate_security_routes.ensure_policy", return_value=dict(POLICY)),
        patch("app.slate_security_routes.list_rules", return_value=[]),
        patch("app.slate_security_routes.list_managed_groups", return_value=[]),
        patch("app.slate_security_routes.list_exceptions", return_value=[]),
        patch("app.slate_security_routes.list_approvals", return_value=[]),
        patch(
            "app.slate_security_routes.rule_evaluation_context",
            return_value={"simulated_at": None, "previous_rollout_percent": None},
        ),
    ):
        yield


class TestCatalog:
    """A preset is its fields, not its name: every one must explain its expected impact."""

    def test_every_managed_tier_and_preset_is_returned_with_its_impact(self) -> None:
        response = client.get("/v1/slate/security/presets")
        assert response.status_code == 200
        body = response.json()
        assert [t["key"] for t in body["managedRulesets"]] == ["off", "core", "strict"]
        assert [p["key"] for p in body["botPresets"]] == [
            "off",
            "monitor",
            "balanced",
            "aggressive",
        ]
        assert [p["key"] for p in body["ratePresets"]] == [
            "off",
            "generous",
            "standard",
            "strict",
        ]
        for family in ("managedRulesets", "botPresets", "ratePresets"):
            for entry in body[family]:
                assert entry["expectedImpact"], f"{family} {entry['key']} explains nothing"

    def test_rate_budgets_travel_as_numbers_rather_than_adjectives(self) -> None:
        presets = {p["key"]: p for p in client.get("/v1/slate/security/presets").json()["ratePresets"]}
        assert presets["standard"]["requests"] == 300
        assert presets["standard"]["windowSeconds"] == 60

    def test_only_turning_the_ruleset_off_requires_a_reason(self) -> None:
        tiers = {t["key"]: t for t in client.get("/v1/slate/security/presets").json()["managedRulesets"]}
        assert tiers["off"]["requiresReason"] is True
        assert tiers["core"]["requiresReason"] is False

    def test_the_group_catalog_names_its_false_positive_risk(self) -> None:
        groups = client.get("/v1/slate/security/managed-groups").json()["groups"]
        assert {g["id"] for g in groups} >= {
            "sql-injection",
            "xss",
            "path-traversal",
            "remote-code-execution",
            "scanner-detection",
            "protocol-anomaly",
        }
        for group in groups:
            assert group["falsePositiveRisk"] in ("low", "medium", "high")
            assert group["expectedImpact"]

    def test_reading_presets_requires_the_view_permission(self, _permissions) -> None:
        client.get("/v1/slate/security/presets")
        _, args, _ = _permissions.mock_calls[0]
        assert args[2] == "versions"
        assert args[3] == "view"

    def test_reading_the_group_catalog_requires_the_view_permission(self, _permissions) -> None:
        client.get("/v1/slate/security/managed-groups")
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "view"


class TestPolicyRead:
    """What the lane is protected by, and what it actually enforces."""

    def test_the_policy_is_returned_in_camel_case(self) -> None:
        response = client.get(f"/v1/slate/environments/{ENV}/security")
        assert response.status_code == 200
        body = response.json()
        assert body["policyVersion"] == 3
        assert body["managedRuleset"] == "core"
        assert body["botPreset"] == "balanced"
        assert body["groups"], "the catalog travels with the policy"
        assert body["rulesDigest"].startswith("sha256:")

    def test_the_response_states_that_nothing_is_enforced(self) -> None:
        body = client.get(f"/v1/slate/environments/{ENV}/security").json()
        assert body["edgeAttached"] is False
        assert body["enforcement"]["enforced"] is False
        assert "nothing is challenged and nothing is blocked" in body["enforcement"]["sentence"]

    def test_ddos_status_is_unavailable_rather_than_a_protection_state(self) -> None:
        """A green badge here would be a false statement, not merely an inert setting."""
        body = client.get(f"/v1/slate/environments/{ENV}/security").json()
        assert body["ddos"]["status"] == "unavailable"
        assert body["ddos"]["status"] not in ("protected", "off")
        assert "absence of anything able to report" in body["ddos"]["sentence"]

    def test_an_unknown_environment_answers_404_not_403(self) -> None:
        """A cross-tenant probe must not be able to confirm the lane exists."""
        with patch("app.slate_security_routes.get_environment", return_value=None):
            response = client.get(f"/v1/slate/environments/{ENV}/security")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "environment_not_found"

    def test_reading_the_policy_requires_the_view_permission(self, _permissions) -> None:
        client.get(f"/v1/slate/environments/{ENV}/security")
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "view"


class TestPresetWrites:
    """Disabling the WAF is the change nobody can explain months later without a reason."""

    def test_setting_presets_writes_and_audits(self) -> None:
        with (
            patch(
                "app.slate_security_routes.set_presets",
                return_value={**POLICY, "managed_ruleset": "strict", "policy_version": 4},
            ) as write,
            patch("app.slate_security_routes.append_audit") as audit,
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/security/presets",
                json={
                    "managedRuleset": "strict",
                    "botPreset": "aggressive",
                    "ratePreset": "strict",
                    "challengeMode": "managed",
                    "expectedPolicyVersion": 3,
                    "reason": "under attack",
                },
            )
        assert response.status_code == 200
        assert response.json()["applied"] is True
        assert response.json()["policyVersion"] == 4
        assert write.called and audit.called

    def test_turning_the_managed_ruleset_off_without_a_reason_is_refused(self) -> None:
        with patch("app.slate_security_routes.append_audit"):
            response = client.put(
                f"/v1/slate/environments/{ENV}/security/presets",
                json={"managedRuleset": "off", "expectedPolicyVersion": 3},
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "managed-off-without-reason"
        assert detail["code"] == "managed-off-without-reason"
        assert "the part that survives the incident" in detail["message"]

    def test_turning_it_off_with_a_reason_is_allowed(self) -> None:
        with (
            patch("app.slate_security_routes.set_presets", return_value=dict(POLICY)),
            patch("app.slate_security_routes.append_audit"),
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/security/presets",
                json={
                    "managedRuleset": "off",
                    "managedOffReason": "ruling out the WAF during incident 42",
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 200

    def test_a_dry_run_validates_without_writing_or_auditing(self) -> None:
        with (
            patch("app.slate_security_routes.set_presets") as write,
            patch("app.slate_security_routes.append_audit") as audit,
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/security/presets",
                json={"managedRuleset": "strict", "expectedPolicyVersion": 3, "dryRun": True},
            )
        assert response.status_code == 200
        assert response.json()["applied"] is False
        assert not write.called and not audit.called

    def test_a_refused_dry_run_writes_no_audit(self) -> None:
        """A rejected preview is not an event."""
        with patch("app.slate_security_routes.append_audit") as audit:
            response = client.put(
                f"/v1/slate/environments/{ENV}/security/presets",
                json={"managedRuleset": "off", "expectedPolicyVersion": 3, "dryRun": True},
            )
        assert response.status_code == 409
        assert not audit.called

    def test_a_refused_real_write_does_write_audit(self) -> None:
        with patch("app.slate_security_routes.append_audit") as audit:
            client.put(
                f"/v1/slate/environments/{ENV}/security/presets",
                json={"managedRuleset": "off", "expectedPolicyVersion": 3},
            )
        assert audit.called
        assert "refused" in audit.call_args.kwargs["summary"].lower()
        assert "managed-off-without-reason" in audit.call_args.kwargs["detail"]

    def test_a_stale_policy_version_is_a_named_conflict(self) -> None:
        from app.slate_security_store import SlateSecurityPolicyConflictError

        with (
            patch(
                "app.slate_security_routes.set_presets",
                side_effect=SlateSecurityPolicyConflictError(ENV, 3, 9),
            ),
            patch("app.slate_security_routes.append_audit"),
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/security/presets",
                json={"managedRuleset": "core", "expectedPolicyVersion": 3},
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "policy-version-conflict"
        assert detail["actualPolicyVersion"] == 9

    def test_changing_presets_requires_the_publish_permission(self, _permissions) -> None:
        with (
            patch("app.slate_security_routes.set_presets", return_value=dict(POLICY)),
            patch("app.slate_security_routes.append_audit"),
        ):
            client.put(
                f"/v1/slate/environments/{ENV}/security/presets",
                json={"managedRuleset": "core", "expectedPolicyVersion": 3},
            )
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"


class TestManagedGroupWrites:
    """off and log are the directions that remove protection, so both need a reason."""

    def test_weakening_a_group_without_a_reason_is_refused(self) -> None:
        with patch("app.slate_security_routes.append_audit"):
            response = client.put(
                f"/v1/slate/environments/{ENV}/security/managed-groups/xss",
                json={"mode": "off", "expectedPolicyVersion": 3},
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "managed-off-without-reason"

    def test_strengthening_a_group_needs_no_reason(self) -> None:
        with (
            patch(
                "app.slate_security_routes.set_managed_group",
                return_value={"group_id": "xss", "mode": "block", "reason": None},
            ),
            patch("app.slate_security_routes.append_audit"),
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/security/managed-groups/xss",
                json={"mode": "block", "expectedPolicyVersion": 3},
            )
        assert response.status_code == 200
        assert response.json()["group"]["mode"] == "block"

    def test_an_unknown_group_answers_404(self) -> None:
        response = client.put(
            f"/v1/slate/environments/{ENV}/security/managed-groups/not-a-group",
            json={"mode": "block", "expectedPolicyVersion": 3},
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "group_not_found"

    def test_changing_a_group_requires_the_publish_permission(self, _permissions) -> None:
        with (
            patch(
                "app.slate_security_routes.set_managed_group",
                return_value={"group_id": "xss", "mode": "block"},
            ),
            patch("app.slate_security_routes.append_audit"),
        ):
            client.put(
                f"/v1/slate/environments/{ENV}/security/managed-groups/xss",
                json={"mode": "block", "expectedPolicyVersion": 3},
            )
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"


class TestRuleWrites:
    """The server is the authority on what is unsafe, and it says so in sentences."""

    def test_a_safe_rule_is_created(self) -> None:
        with (
            patch("app.slate_security_routes.upsert_rule", return_value=stored_rule()) as write,
            patch("app.slate_security_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/rules", json=rule_body()
            )
        assert response.status_code == 201
        assert response.json()["applied"] is True
        assert response.json()["bodyDigest"].startswith("sha256:")
        assert write.called

    def test_a_rule_blocking_the_entire_site_is_refused_with_its_sentence(self) -> None:
        with (
            patch("app.slate_security_routes.upsert_rule") as write,
            patch("app.slate_security_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/rules",
                json=rule_body(action="block", matcherKind="prefix", matcherValue="/"),
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "blocks-entire-site"
        assert "including the one an operator would use to remove it" in detail["message"]
        assert not write.called, "an unsafe rule must never reach the store"

    def test_a_hard_refusal_cannot_be_acknowledged_past(self) -> None:
        with patch("app.slate_security_routes.append_audit"):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/rules",
                json=rule_body(
                    action="block",
                    matcherValue="/",
                    acknowledgedWarnings=["blocks-entire-site"],
                ),
            )
        assert response.status_code == 409

    def test_a_broad_acting_rule_is_written_but_carries_its_warning(self) -> None:
        with (
            patch("app.slate_security_routes.upsert_rule", return_value=stored_rule()),
            patch("app.slate_security_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/rules",
                json=rule_body(action="challenge", matcherValue="/guide"),
            )
        assert response.status_code == 201
        codes = [w["code"] for w in response.json()["warnings"]]
        assert "broad-matcher" in codes

    def test_a_duplicate_precedence_is_refused_by_name(self) -> None:
        existing = [stored_rule(id="other", ordinal=0)]
        with (
            patch("app.slate_security_routes.list_rules", return_value=existing),
            patch("app.slate_security_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/rules", json=rule_body(ordinal=0)
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "ordinal-conflict"

    def test_a_dry_run_validates_without_writing(self) -> None:
        with (
            patch("app.slate_security_routes.upsert_rule") as write,
            patch("app.slate_security_routes.append_audit") as audit,
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/rules", json=rule_body(dryRun=True)
            )
        assert response.status_code == 201
        assert response.json()["applied"] is False
        assert not write.called and not audit.called

    def test_replacing_a_rule_that_is_not_on_the_lane_answers_404(self) -> None:
        from app.slate_security_store import SlateSecurityStoreError

        with (
            patch(
                "app.slate_security_routes.upsert_rule",
                side_effect=SlateSecurityStoreError("rule_not_found", "no"),
            ),
            patch("app.slate_security_routes.append_audit"),
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/security/rules/{RULE}",
                json=rule_body(ordinal=7),
            )
        assert response.status_code == 404

    def test_deleting_a_rule_audits(self) -> None:
        with (
            patch("app.slate_security_routes.delete_rule", return_value=True),
            patch("app.slate_security_routes.append_audit") as audit,
        ):
            response = client.delete(
                f"/v1/slate/environments/{ENV}/security/rules/{RULE}?expectedPolicyVersion=3"
            )
        assert response.status_code == 200
        assert response.json()["deleted"] is True
        assert audit.called

    def test_writing_a_rule_requires_the_publish_permission(self, _permissions) -> None:
        with (
            patch("app.slate_security_routes.upsert_rule", return_value=stored_rule()),
            patch("app.slate_security_routes.append_audit"),
        ):
            client.post(f"/v1/slate/environments/{ENV}/security/rules", json=rule_body())
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"

    def test_deleting_a_rule_requires_the_publish_permission(self, _permissions) -> None:
        with (
            patch("app.slate_security_routes.delete_rule", return_value=True),
            patch("app.slate_security_routes.append_audit"),
        ):
            client.delete(
                f"/v1/slate/environments/{ENV}/security/rules/{RULE}?expectedPolicyVersion=3"
            )
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"


class TestDualControl:
    """Blocking traffic is the one change where a second pair of eyes is worth the delay."""

    def _enforcing_block(self, **overrides) -> Dict[str, Any]:
        return rule_body(
            action="block",
            matcherValue="/admin",
            rolloutMode="enforce",
            rolloutPercent=100,
            **overrides,
        )

    def test_a_rule_that_never_simulated_cannot_begin_enforcing(self) -> None:
        with patch("app.slate_security_routes.append_audit"):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/rules", json=self._enforcing_block()
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "enforce-without-simulation"
        assert "Simulate first" in detail["message"]

    def test_an_enforcing_block_with_no_approval_is_refused(self) -> None:
        with (
            patch(
                "app.slate_security_routes.rule_evaluation_context",
                return_value={
                    "simulated_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
                    "previous_rollout_percent": 10,
                },
            ),
            patch("app.slate_security_routes.list_approvals", return_value=[]),
            patch("app.slate_security_routes.upsert_rule") as write,
            patch("app.slate_security_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/rules", json=self._enforcing_block()
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "enforce-without-approval"
        assert "somebody other than its author" in detail["message"]
        assert not write.called

    def test_an_author_cannot_approve_their_own_enforcing_block(self) -> None:
        digest = body_digest(
            {**snake_body(action="block", rollout_mode="enforce", rollout_percent=100), "id": ""}
        )
        with (
            patch(
                "app.slate_security_routes.rule_evaluation_context",
                return_value={
                    "simulated_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
                    "previous_rollout_percent": 10,
                },
            ),
            patch(
                "app.slate_security_routes.list_approvals",
                return_value=[approval(digest, approver_key=AUTHOR_KEY)],
            ),
            patch("app.slate_security_routes.upsert_rule") as write,
            patch("app.slate_security_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/rules", json=self._enforcing_block()
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "approval-self"
        assert not write.called

    def test_an_approval_of_a_different_body_is_stale_rather_than_missing(self) -> None:
        """The two need different actions: re-review, versus get somebody else to look."""
        with (
            patch(
                "app.slate_security_routes.rule_evaluation_context",
                return_value={
                    "simulated_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
                    "previous_rollout_percent": 10,
                },
            ),
            patch(
                "app.slate_security_routes.list_approvals",
                return_value=[approval("sha256:" + "c" * 64)],
            ),
            patch("app.slate_security_routes.upsert_rule") as write,
            patch("app.slate_security_routes.append_audit"),
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/security/rules/{RULE}",
                json=self._enforcing_block(),
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "approval-stale"
        assert not write.called

    def test_a_distinct_approval_of_this_exact_body_lets_it_enforce(self) -> None:
        digest = body_digest(
            {**snake_body(action="block", rollout_mode="enforce", rollout_percent=100), "id": ""}
        )
        with (
            patch(
                "app.slate_security_routes.rule_evaluation_context",
                return_value={
                    "simulated_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
                    "previous_rollout_percent": 10,
                },
            ),
            patch("app.slate_security_routes.list_approvals", return_value=[approval(digest)]),
            patch("app.slate_security_routes.upsert_rule", return_value=stored_rule()) as write,
            patch("app.slate_security_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/rules", json=self._enforcing_block()
            )
        assert response.status_code == 201, response.json()
        assert write.called
        assert response.json()["bodyDigest"] == digest

    def test_the_rollout_route_runs_the_same_gate_as_a_body_edit(self) -> None:
        """A different verb must not be a weaker path to the same state."""
        with (
            patch("app.slate_security_routes.get_rule", return_value=stored_rule()),
            patch("app.slate_security_routes.set_rollout") as write,
            patch("app.slate_security_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/rules/{RULE}/rollout",
                json={"rolloutMode": "enforce", "rolloutPercent": 100,
                      "expectedPolicyVersion": 3},
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "enforce-without-simulation"
        assert not write.called

    def test_a_rollout_on_a_rule_that_does_not_exist_answers_404(self) -> None:
        with patch("app.slate_security_routes.get_rule", return_value=None):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/rules/{RULE}/rollout",
                json={"rolloutMode": "simulate", "rolloutPercent": 50,
                      "expectedPolicyVersion": 3},
            )
        assert response.status_code == 404

    def test_a_zero_to_hundred_jump_is_warned_about_rather_than_refused(self) -> None:
        with (
            patch(
                "app.slate_security_routes.get_rule",
                return_value=stored_rule(action="challenge", rollout_percent=0),
            ),
            patch(
                "app.slate_security_routes.rule_evaluation_context",
                return_value={
                    "simulated_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
                    "previous_rollout_percent": 0,
                },
            ),
            patch(
                "app.slate_security_routes.set_rollout",
                return_value=stored_rule(rollout_percent=100),
            ),
            patch("app.slate_security_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/rules/{RULE}/rollout",
                json={"rolloutMode": "simulate", "rolloutPercent": 100,
                      "expectedPolicyVersion": 3},
            )
        assert response.status_code == 200
        assert "rollout-jump" in [w["code"] for w in response.json()["warnings"]]

    def test_approving_ones_own_change_is_refused_at_the_approval_route(self) -> None:
        with patch("app.slate_security_routes.record_approval") as write:
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/approvals",
                json={
                    "subjectKind": "rule",
                    "subjectId": RULE,
                    "digest": "sha256:" + "a" * 64,
                    "authorActorKey": AUTHOR_KEY,
                },
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "approval-self"
        assert not write.called

    def test_a_distinct_approver_is_recorded(self) -> None:
        with (
            patch(
                "app.slate_security_routes.record_approval",
                return_value={"id": "approval-1", "digest": "sha256:" + "a" * 64},
            ) as write,
            patch("app.slate_security_routes.append_audit") as audit,
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/approvals",
                json={
                    "subjectKind": "rule",
                    "subjectId": RULE,
                    "digest": "sha256:" + "a" * 64,
                    "authorActorKey": "someone-else",
                },
            )
        assert response.status_code == 201
        assert write.call_args.kwargs["approver_actor_key"] == AUTHOR_KEY
        assert write.call_args.kwargs["author_actor_key"] == "someone-else"
        assert audit.called

    def test_recording_an_approval_requires_the_publish_permission(self, _permissions) -> None:
        with (
            patch("app.slate_security_routes.record_approval", return_value={"id": "a"}),
            patch("app.slate_security_routes.append_audit"),
        ):
            client.post(
                f"/v1/slate/environments/{ENV}/security/approvals",
                json={
                    "subjectKind": "rule",
                    "subjectId": RULE,
                    "digest": "sha256:" + "a" * 64,
                    "authorActorKey": "someone-else",
                },
            )
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"


class TestRevisionsAndRevert:
    """Reverting applies a stored document rather than reconstructing intent from a sentence."""

    def test_a_rules_revisions_are_returned_newest_first(self) -> None:
        rows = [
            {
                "id": "rev-2",
                "revision": 2,
                "change_kind": "rollout-changed",
                "body_digest": "sha256:" + "a" * 64,
                "at": None,
                "actor_name": "ken@example.com",
                "body": {"rollout_percent": 10},
            }
        ]
        with patch("app.slate_security_routes.list_revisions", return_value=rows):
            body = client.get(
                f"/v1/slate/environments/{ENV}/security/rules/{RULE}/revisions"
            ).json()
        assert body["revisions"][0]["changeKind"] == "rollout-changed"
        assert body["revisions"][0]["body"] == {"rollout_percent": 10}

    def test_reading_revisions_requires_only_the_view_permission(self, _permissions) -> None:
        with patch("app.slate_security_routes.list_revisions", return_value=[]):
            client.get(f"/v1/slate/environments/{ENV}/security/rules/{RULE}/revisions")
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "view"

    def test_a_revert_applies_and_audits(self) -> None:
        with (
            patch(
                "app.slate_security_routes.revert_rule",
                return_value=stored_rule(rollout_percent=0),
            ) as write,
            patch("app.slate_security_routes.append_audit") as audit,
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/rules/{RULE}/revert",
                json={"revision": 1, "expectedPolicyVersion": 3},
            )
        assert response.status_code == 200
        assert response.json()["rule"]["rolloutPercent"] == 0
        assert write.called
        assert audit.call_args.kwargs["subject_kind"] == "revert"

    def test_reverting_to_a_revision_that_does_not_exist_answers_404(self) -> None:
        from app.slate_security_store import SlateSecurityStoreError

        with (
            patch(
                "app.slate_security_routes.revert_rule",
                side_effect=SlateSecurityStoreError("revision_not_found", "no"),
            ),
            patch("app.slate_security_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/rules/{RULE}/revert",
                json={"revision": 9, "expectedPolicyVersion": 3},
            )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "revision_not_found"

    def test_reverting_requires_the_publish_permission(self, _permissions) -> None:
        with (
            patch("app.slate_security_routes.revert_rule", return_value=stored_rule()),
            patch("app.slate_security_routes.append_audit"),
        ):
            client.post(
                f"/v1/slate/environments/{ENV}/security/rules/{RULE}/revert",
                json={"revision": 1, "expectedPolicyVersion": 3},
            )
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"


class TestExceptions:
    """An exception that cannot lapse has stopped being an exception and become the policy."""

    def _expires(self, days: int) -> str:
        return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

    def test_a_scoped_bounded_carve_out_is_created(self) -> None:
        with (
            patch(
                "app.slate_security_routes.create_exception",
                return_value={"id": EXCEPTION, "subject_kind": "managed-group",
                              "matcher_value": "/search"},
            ) as write,
            patch("app.slate_security_routes.append_audit") as audit,
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/exceptions",
                json={
                    "subjectKind": "managed-group",
                    "subjectRef": "sql-injection",
                    "matcherKind": "prefix",
                    "matcherValue": "/search",
                    "expiresAt": self._expires(7),
                    "reason": "the SQL guide's search reflects reader input",
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 201
        assert write.called and audit.called

    def test_a_carve_out_covering_every_route_is_refused(self) -> None:
        with (
            patch("app.slate_security_routes.create_exception") as write,
            patch("app.slate_security_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/exceptions",
                json={
                    "subjectKind": "policy",
                    "matcherKind": "prefix",
                    "matcherValue": "/",
                    "expiresAt": self._expires(7),
                    "reason": "incident",
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "exception-unbounded"
        assert not write.called

    def test_a_carve_out_outliving_the_maximum_window_is_refused(self) -> None:
        with patch("app.slate_security_routes.append_audit"):
            response = client.post(
                f"/v1/slate/environments/{ENV}/security/exceptions",
                json={
                    "subjectKind": "rule",
                    "subjectRef": RULE,
                    "matcherKind": "prefix",
                    "matcherValue": "/search",
                    "expiresAt": self._expires(400),
                    "reason": "vendor fix pending",
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "exception-outlives-limit"

    def test_closing_a_carve_out_early_audits(self) -> None:
        with (
            patch("app.slate_security_routes.delete_exception", return_value=True),
            patch("app.slate_security_routes.append_audit") as audit,
        ):
            response = client.delete(
                f"/v1/slate/environments/{ENV}/security/exceptions/{EXCEPTION}"
                "?expectedPolicyVersion=3"
            )
        assert response.status_code == 200
        assert response.json()["deleted"] is True
        assert audit.called

    def test_opening_a_carve_out_requires_the_publish_permission(self, _permissions) -> None:
        with (
            patch("app.slate_security_routes.create_exception", return_value={"id": EXCEPTION}),
            patch("app.slate_security_routes.append_audit"),
        ):
            client.post(
                f"/v1/slate/environments/{ENV}/security/exceptions",
                json={
                    "subjectKind": "rule",
                    "subjectRef": RULE,
                    "matcherKind": "prefix",
                    "matcherValue": "/search",
                    "expiresAt": self._expires(7),
                    "reason": "x",
                    "expectedPolicyVersion": 3,
                },
            )
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"

    def test_closing_a_carve_out_requires_the_publish_permission(self, _permissions) -> None:
        with (
            patch("app.slate_security_routes.delete_exception", return_value=True),
            patch("app.slate_security_routes.append_audit"),
        ):
            client.delete(
                f"/v1/slate/environments/{ENV}/security/exceptions/{EXCEPTION}"
                "?expectedPolicyVersion=3"
            )
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"


class TestSimulation:
    """The honesty boundary, as a property of the response type rather than of the handler."""

    def test_a_simulation_answers_every_clause(self) -> None:
        response = client.post(
            f"/v1/slate/environments/{ENV}/security/simulate",
            json={"request": {"path": "/docs", "method": "GET"}},
        )
        assert response.status_code == 200
        body = response.json()
        for field in (
            "action",
            "actionReason",
            "winningRuleKind",
            "winningRuleLabel",
            "considered",
            "rulesDigest",
            "policyVersion",
        ):
            assert field in body, f"the simulation does not answer {field}"

    def test_a_simulation_can_never_claim_to_have_been_observed_or_enforced(self) -> None:
        body = client.post(
            f"/v1/slate/environments/{ENV}/security/simulate",
            json={"request": {"path": "/docs"}},
        ).json()
        assert body["basis"] == "policy-simulation"
        assert body["observed"] is False
        assert body["enforced"] is False
        assert body["mitigated"] is False
        assert "not traffic that was observed" in body["sentence"]

    def test_a_simulated_enforcing_block_reports_would_block_and_never_blocked(self) -> None:
        overlay = [
            {
                "id": RULE,
                "ordinal": 0,
                "label": "Block admin probes",
                "matcherKind": "prefix",
                "matcherValue": "/admin",
                "action": "block",
                "rolloutMode": "simulate",
                "rolloutPercent": 100,
            }
        ]
        body = client.post(
            f"/v1/slate/environments/{ENV}/security/simulate",
            json={"request": {"path": "/admin/panel"}, "rules": overlay},
        ).json()
        assert body["action"] == "would-block"
        assert body["mitigated"] is False

    def test_every_rule_that_lost_says_why(self) -> None:
        overlay = [
            {
                "id": RULE,
                "ordinal": 0,
                "label": "Disabled rule",
                "enabled": False,
                "matcherKind": "prefix",
                "matcherValue": "/admin",
                "action": "block",
            }
        ]
        body = client.post(
            f"/v1/slate/environments/{ENV}/security/simulate",
            json={"request": {"path": "/admin"}, "rules": overlay},
        ).json()
        steps = {step["label"]: step for step in body["considered"]}
        assert steps["Disabled rule"]["outcome"] == "skipped"
        assert steps["Disabled rule"]["reason"]

    def test_a_what_if_ruleset_overrides_the_stored_rules(self) -> None:
        with patch("app.slate_security_routes.list_rules") as stored:
            client.post(
                f"/v1/slate/environments/{ENV}/security/simulate",
                json={"request": {"path": "/docs"}, "rules": []},
            )
        assert not stored.called

    def test_a_simulation_is_not_recorded_unless_asked(self) -> None:
        with patch("app.slate_security_routes.record_event") as record:
            client.post(
                f"/v1/slate/environments/{ENV}/security/simulate",
                json={"request": {"path": "/docs"}},
            )
        assert not record.called

    def test_a_persisted_simulation_hands_raw_data_to_the_store_which_redacts_it(self) -> None:
        """The route must not pre-redact: a redaction the caller can skip will be skipped."""
        with patch(
            "app.slate_security_routes.record_event", return_value={"id": EVENT}
        ) as record:
            body = client.post(
                f"/v1/slate/environments/{ENV}/security/simulate",
                json={
                    "request": {
                        "path": "/admin",
                        "headers": {
                            "cookie": "session=super-secret",
                            "user-agent": "u" * 900,
                            "clientIpPrefix": "203.0.113.42",
                        },
                    },
                    "persist": True,
                },
            ).json()
        assert body["eventId"] == EVENT

        raw = record.call_args.kwargs["evidence"]
        assert raw["cookie"] == "session=super-secret", "the route passes what it saw"

        redacted = redact_evidence(raw)
        assert "cookie" not in redacted
        assert "super-secret" not in str(redacted)
        assert redacted["clientIpPrefix"] == "203.0.113.0/24"
        assert len(redacted["userAgent"]) == 256

    def test_simulating_requires_only_the_view_permission(self, _permissions) -> None:
        client.post(
            f"/v1/slate/environments/{ENV}/security/simulate",
            json={"request": {"path": "/docs"}},
        )
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "view"


class TestEvents:
    """An event stream that looked like observed traffic would be the most dangerous lie here."""

    def _row(self, **overrides) -> Dict[str, Any]:
        base = {
            "id": EVENT,
            "at": None,
            "source": "policy-simulation",
            "rule_kind": "rule",
            "rule_ref": RULE,
            "rule_label": "Block admin probes",
            "route": "/admin",
            "method": "GET",
            "release_id": None,
            "region": None,
            "action": "would-block",
            "mitigated": False,
            "edge_attached": False,
            "evidence": {"path": "/admin", "clientIpPrefix": "203.0.113.0/24"},
            "retain_until": None,
        }
        base.update(overrides)
        return base

    def test_events_are_returned_with_their_redacted_evidence(self) -> None:
        with patch("app.slate_security_routes.list_events", return_value=[self._row()]):
            body = client.get(f"/v1/slate/environments/{ENV}/security/events").json()
        event = body["events"][0]
        assert event["action"] == "would-block"
        assert event["evidence"]["clientIpPrefix"] == "203.0.113.0/24"
        assert "cookie" not in event["evidence"]

    def test_no_event_claims_a_mitigation(self) -> None:
        with patch("app.slate_security_routes.list_events", return_value=[self._row()]):
            body = client.get(f"/v1/slate/environments/{ENV}/security/events").json()
        assert body["events"][0]["mitigated"] is False
        assert body["events"][0]["edgeAttached"] is False
        assert body["observed"] is False
        assert "No request path exists to observe" in body["sentence"]

    def test_events_can_be_filtered_on_the_designer_dimension_names(self) -> None:
        with patch("app.slate_security_routes.list_events", return_value=[]) as query:
            client.get(
                f"/v1/slate/environments/{ENV}/security/events"
                f"?limit=10&ruleRef={RULE}&action=would-block&route=/admin"
                f"&releaseId={RELEASE}&region=eu-west&source=policy-simulation"
            )
        kwargs = query.call_args.kwargs
        assert kwargs["limit"] == 10
        assert kwargs["rule_ref"] == RULE
        assert kwargs["action"] == "would-block"
        assert kwargs["route"] == "/admin"
        assert kwargs["release_id"] == RELEASE
        assert kwargs["region"] == "eu-west"
        assert kwargs["source"] == "policy-simulation"

    def test_one_event_can_be_read(self) -> None:
        with patch("app.slate_security_routes.get_event", return_value=self._row()):
            response = client.get(f"/v1/slate/environments/{ENV}/security/events/{EVENT}")
        assert response.status_code == 200
        assert response.json()["ruleLabel"] == "Block admin probes"

    def test_an_unknown_event_answers_404(self) -> None:
        with patch("app.slate_security_routes.get_event", return_value=None):
            response = client.get(f"/v1/slate/environments/{ENV}/security/events/{EVENT}")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "event_not_found"

    def test_reading_events_requires_only_the_view_permission(self, _permissions) -> None:
        with patch("app.slate_security_routes.list_events", return_value=[]):
            client.get(f"/v1/slate/environments/{ENV}/security/events")
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "view"


class TestAuditAndExport:
    """Compliance evidence that executes on open, or that stops early in silence, is not evidence."""

    def _entry(self, **overrides) -> Dict[str, Any]:
        base = {
            "id": "audit-1",
            "at": None,
            "actor_name": "ken@example.com",
            "actor_kind": "user",
            "subject_kind": "policy",
            "subject_id": None,
            "summary": "Managed ruleset disabled",
            "detail": "incident 42",
        }
        base.update(overrides)
        return base

    def test_the_audit_trail_is_returned(self) -> None:
        with patch("app.slate_security_routes.list_audit", return_value=[self._entry()]):
            body = client.get(f"/v1/slate/environments/{ENV}/security/audit").json()
        assert body["entries"][0]["summary"] == "Managed ruleset disabled"
        assert body["entries"][0]["subjectKind"] == "policy"

    def test_the_export_is_csv(self) -> None:
        with (
            patch("app.slate_security_routes.list_audit", return_value=[self._entry()]),
            patch("app.slate_security_routes.append_audit"),
        ):
            response = client.get(f"/v1/slate/environments/{ENV}/security/audit/export")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "when,actor,actorKind" in response.text
        assert "Managed ruleset disabled" in response.text

    def test_a_formula_in_an_actor_name_is_neutralized(self) -> None:
        """An actor display name is attacker-influenced text; opening the export must not run it."""
        rows = [
            self._entry(actor_name='=cmd|\' /C calc\'!A0', summary="+SUM(1)", detail="-2+3"),
            self._entry(id="audit-2", actor_name="@import", summary="\ttabbed"),
        ]
        with (
            patch("app.slate_security_routes.list_audit", return_value=rows),
            patch("app.slate_security_routes.append_audit"),
        ):
            text = client.get(
                f"/v1/slate/environments/{ENV}/security/audit/export"
            ).text
        assert "'=cmd" in text
        assert "'+SUM(1)" in text
        assert "'-2+3" in text
        assert "'@import" in text
        for line in text.splitlines()[1:]:
            for cell in line.split(","):
                stripped = cell.strip('"')
                assert not stripped.startswith(("=", "+", "@")), cell

    def test_an_export_that_hit_its_cap_says_so_rather_than_stopping_in_silence(self) -> None:
        """Silent truncation in compliance evidence reads as 'these entries never happened'."""
        rows = [self._entry(id=f"audit-{i}") for i in range(3)]
        with (
            patch("app.slate_security_routes.list_audit", return_value=rows) as query,
            patch("app.slate_security_routes.append_audit"),
        ):
            text = client.get(
                f"/v1/slate/environments/{ENV}/security/audit/export?limit=2"
            ).text
        assert query.call_args.kwargs["limit"] == 3, "one row past the cap, so 'more' is a fact"
        assert "TRUNCATED" in text
        assert "do not read this file as the complete record" in text

    def test_an_export_within_its_cap_carries_no_truncation_row(self) -> None:
        with (
            patch("app.slate_security_routes.list_audit", return_value=[self._entry()]),
            patch("app.slate_security_routes.append_audit"),
        ):
            text = client.get(f"/v1/slate/environments/{ENV}/security/audit/export").text
        assert "TRUNCATED" not in text

    def test_exporting_the_evidence_is_itself_audited(self) -> None:
        with (
            patch("app.slate_security_routes.list_audit", return_value=[self._entry()]),
            patch("app.slate_security_routes.append_audit") as audit,
        ):
            client.get(f"/v1/slate/environments/{ENV}/security/audit/export")
        assert audit.called
        assert audit.call_args.kwargs["subject_kind"] == "export"
        assert audit.call_args.kwargs["actor_name"] == "ken@example.com"

    def test_reading_the_audit_trail_requires_only_the_view_permission(self, _permissions) -> None:
        with patch("app.slate_security_routes.list_audit", return_value=[]):
            client.get(f"/v1/slate/environments/{ENV}/security/audit")
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "view"

    def test_exporting_requires_only_the_view_permission(self, _permissions) -> None:
        with (
            patch("app.slate_security_routes.list_audit", return_value=[]),
            patch("app.slate_security_routes.append_audit"),
        ):
            client.get(f"/v1/slate/environments/{ENV}/security/audit/export")
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "view"
