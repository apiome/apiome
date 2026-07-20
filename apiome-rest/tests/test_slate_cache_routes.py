"""Cache control REST surface — UXE-3.1 (private-suite#2473).

Route-level tests over :mod:`app.slate_cache_routes`, following the ``test_slate_routes.py``
precedent: a module-level ``TestClient``, a mock auth dict, and store functions patched *where
used*. The planner and the store are proven separately in their own suites; what is asserted
here is the contract the surface publishes.

The claims that matter most, and which nothing below is allowed to weaken:

* **Refusals reach the client as sentences.** 409 with ``{code, message, reason}``, the shape
  the authoring surface's ``disabledReason`` renders. A refusal that arrived as a bare status
  would leave the operator with a greyed-out control and no explanation.
* **A dry run runs every gate and writes nothing.** Including audit: a rejected preview is not
  an event.
* **A refused action that is *not* a dry run still writes audit.** Refusing to purge during an
  incident is exactly the event that has to be in the timeline afterwards.
* **No response ever claims a flush.** There is no delivery tier, so ``dispatched`` is false
  everywhere and every purge response says why in words.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.slate_auth import validate_slate_authentication

client = TestClient(app)

TENANT = "11111111-1111-1111-1111-111111111111"
SITE = "22222222-2222-2222-2222-222222222222"
ENV = "33333333-3333-3333-3333-333333333333"
RULE = "44444444-4444-4444-4444-444444444444"
RELEASE = "55555555-5555-5555-5555-555555555555"

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
    "preset": "standard",
    "preset_expires_at": None,
    "preset_overrides": {},
    "policy_version": 3,
    "edge_attached": False,
    "edge_provider": None,
    "updated_at": None,
    "updated_by_actor_name": "ken@example.com",
}


def rule_body(**overrides) -> Dict[str, Any]:
    """A valid expert-rule request body."""
    base = {
        "ordinal": 0,
        "enabled": True,
        "label": "Docs HTML",
        "matcherKind": "prefix",
        "matcherValue": "/docs",
        "matcherMethods": ["GET"],
        "matcherHosts": [],
        "eligibility": "cacheable",
        "browserTtlSeconds": 0,
        "edgeTtlSeconds": 60,
        "staleWhileRevalidateSeconds": 0,
        "staleIfErrorSeconds": 0,
        "cacheKeyBase": "host-url",
        "varyQueryMode": "none",
        "varyQueryKeys": [],
        "varyHeaders": [],
        "varyCookies": [],
        "bypassConditions": [],
        "tags": [],
        "acknowledgedWarnings": [],
        "expectedPolicyVersion": 3,
        "dryRun": False,
        "reason": "test",
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
    with patch("app.slate_cache_routes.enforce_permission") as enforce:
        yield enforce


@pytest.fixture(autouse=True)
def _lane():
    """Resolve the environment and its policy for every route that needs one."""
    with (
        patch("app.slate_cache_routes.get_environment", return_value=dict(ENVIRONMENT)),
        patch("app.slate_cache_routes.ensure_policy", return_value=dict(POLICY)),
    ):
        yield


class TestPresets:
    """Criterion 1: presets travel as data, so the UI holds no second copy of the numbers."""

    def test_every_preset_is_returned_with_its_full_rule_set(self) -> None:
        response = client.get("/v1/slate/cache/presets")
        assert response.status_code == 200
        presets = response.json()["presets"]
        assert [p["key"] for p in presets] == [
            "standard",
            "aggressive",
            "bypass",
            "personalized",
        ]
        for preset in presets:
            assert preset["rationale"]
            assert preset["unsafeIf"]
            for rule in preset["rules"]:
                assert "edgeTtlSeconds" in rule
                assert "staleIfErrorSeconds" in rule

    def test_only_bypass_declares_that_it_requires_an_expiry(self) -> None:
        presets = {p["key"]: p for p in client.get("/v1/slate/cache/presets").json()["presets"]}
        assert presets["bypass"]["requiresExpiry"] is True
        assert presets["standard"]["requiresExpiry"] is False

    def test_reading_presets_requires_the_view_permission(self, _permissions) -> None:
        client.get("/v1/slate/cache/presets")
        _, args, _ = _permissions.mock_calls[0]
        assert args[2] == "versions"
        assert args[3] == "view"


class TestPolicyRead:
    """What the lane is doing, and what it actually enforces."""

    def test_the_policy_is_returned_with_its_rules_in_camel_case(self) -> None:
        with patch("app.slate_cache_routes.list_rules", return_value=[]):
            response = client.get(f"/v1/slate/environments/{ENV}/cache")
        assert response.status_code == 200
        body = response.json()
        assert body["policyVersion"] == 3
        assert body["preset"] == "standard"
        assert body["presetRules"], "the preset's own rules decide where no expert rule matches"

    def test_the_response_states_that_nothing_is_enforced_yet(self) -> None:
        with patch("app.slate_cache_routes.list_rules", return_value=[]):
            body = client.get(f"/v1/slate/environments/{ENV}/cache").json()
        assert body["edgeAttached"] is False
        assert body["enforcement"]["enforced"] is False
        assert "do not yet shape response headers" in body["enforcement"]["sentence"]

    def test_an_unknown_environment_answers_404_not_403(self) -> None:
        """A cross-tenant probe must not be able to confirm the lane exists."""
        with patch("app.slate_cache_routes.get_environment", return_value=None):
            response = client.get(f"/v1/slate/environments/{ENV}/cache")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "environment_not_found"


class TestPresetWrites:
    """Bypass without an expiry is refused here, and again by V187."""

    def test_setting_a_preset_writes_and_audits(self) -> None:
        with (
            patch(
                "app.slate_cache_routes.set_preset",
                return_value={**POLICY, "preset": "aggressive", "policy_version": 4},
            ) as write,
            patch("app.slate_cache_routes.append_audit") as audit,
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/cache/preset",
                json={"preset": "aggressive", "expectedPolicyVersion": 3, "reason": "docs site"},
            )
        assert response.status_code == 200
        assert response.json() == {
            **response.json(),
            "applied": True,
            "dryRun": False,
            "preset": "aggressive",
            "policyVersion": 4,
        }
        assert write.called
        assert audit.called

    def test_bypass_without_an_expiry_is_refused_with_its_sentence(self) -> None:
        with patch("app.slate_cache_routes.append_audit"):
            response = client.put(
                f"/v1/slate/environments/{ENV}/cache/preset",
                json={"preset": "bypass", "expectedPolicyVersion": 3},
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "bypass-without-expiry"
        assert detail["code"] == "bypass-without-expiry"
        assert "becomes the configuration" in detail["message"]

    def test_bypass_with_an_expiry_is_allowed(self) -> None:
        with (
            patch(
                "app.slate_cache_routes.set_preset",
                return_value={**POLICY, "preset": "bypass", "policy_version": 4},
            ),
            patch("app.slate_cache_routes.append_audit"),
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/cache/preset",
                json={
                    "preset": "bypass",
                    "presetExpiresAt": "2026-07-20T00:00:00+00:00",
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 200

    def test_an_unknown_preset_is_refused(self) -> None:
        with patch("app.slate_cache_routes.append_audit"):
            response = client.put(
                f"/v1/slate/environments/{ENV}/cache/preset",
                json={"preset": "turbo", "expectedPolicyVersion": 3},
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "preset-unknown"

    def test_a_dry_run_validates_without_writing_or_auditing(self) -> None:
        with (
            patch("app.slate_cache_routes.set_preset") as write,
            patch("app.slate_cache_routes.append_audit") as audit,
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/cache/preset",
                json={"preset": "aggressive", "expectedPolicyVersion": 3, "dryRun": True},
            )
        assert response.status_code == 200
        assert response.json()["applied"] is False
        assert response.json()["resolvedRules"], "a dry run still shows what would happen"
        assert not write.called
        assert not audit.called

    def test_a_refused_dry_run_writes_no_audit(self) -> None:
        """A rejected preview is not an event."""
        with patch("app.slate_cache_routes.append_audit") as audit:
            response = client.put(
                f"/v1/slate/environments/{ENV}/cache/preset",
                json={"preset": "bypass", "expectedPolicyVersion": 3, "dryRun": True},
            )
        assert response.status_code == 409
        assert not audit.called

    def test_a_refused_real_write_does_write_audit(self) -> None:
        with patch("app.slate_cache_routes.append_audit") as audit:
            client.put(
                f"/v1/slate/environments/{ENV}/cache/preset",
                json={"preset": "bypass", "expectedPolicyVersion": 3},
            )
        assert audit.called
        assert "refused" in audit.call_args.kwargs["summary"].lower()
        assert "bypass-without-expiry" in audit.call_args.kwargs["detail"]

    def test_a_stale_policy_version_is_a_named_conflict(self) -> None:
        from app.slate_cache_store import SlateCachePolicyConflictError

        with (
            patch(
                "app.slate_cache_routes.set_preset",
                side_effect=SlateCachePolicyConflictError(ENV, 3, 9),
            ),
            patch("app.slate_cache_routes.append_audit"),
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/cache/preset",
                json={"preset": "aggressive", "expectedPolicyVersion": 3},
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "policy-version-conflict"
        assert detail["actualPolicyVersion"] == 9

    def test_changing_a_preset_requires_the_publish_permission(self, _permissions) -> None:
        with (
            patch("app.slate_cache_routes.set_preset", return_value=dict(POLICY)),
            patch("app.slate_cache_routes.append_audit"),
        ):
            client.put(
                f"/v1/slate/environments/{ENV}/cache/preset",
                json={"preset": "standard", "expectedPolicyVersion": 3},
            )
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"


class TestRuleWrites:
    """Criterion 4: the server is the authority on what is unsafe."""

    def test_a_safe_rule_is_created(self) -> None:
        with (
            patch("app.slate_cache_routes.list_rules", return_value=[]),
            patch(
                "app.slate_cache_routes.upsert_rule",
                return_value={"id": RULE, **{"label": "Docs HTML", "ordinal": 0}},
            ),
            patch("app.slate_cache_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/cache/rules", json=rule_body()
            )
        assert response.status_code == 201
        assert response.json()["applied"] is True

    def test_an_identity_cookie_in_a_shared_key_is_refused_with_its_sentence(self) -> None:
        with (
            patch("app.slate_cache_routes.list_rules", return_value=[]),
            patch("app.slate_cache_routes.upsert_rule") as write,
            patch("app.slate_cache_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/cache/rules",
                json=rule_body(varyCookies=["session"]),
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "identity-in-cache-key"
        assert "another reader can reach" in detail["message"]
        assert not write.called, "an unsafe rule must never reach the store"

    def test_an_unsafe_rule_cannot_be_acknowledged_past(self) -> None:
        """Hard refusals have no acknowledgement path, by design."""
        with (
            patch("app.slate_cache_routes.list_rules", return_value=[]),
            patch("app.slate_cache_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/cache/rules",
                json=rule_body(
                    varyCookies=["session"], acknowledgedWarnings=["identity-in-cache-key"]
                ),
            )
        assert response.status_code == 409

    def test_a_costly_rule_is_written_but_carries_its_warning(self) -> None:
        with (
            patch("app.slate_cache_routes.list_rules", return_value=[]),
            patch("app.slate_cache_routes.upsert_rule", return_value={"id": RULE, "ordinal": 0}),
            patch("app.slate_cache_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/cache/rules",
                json=rule_body(varyQueryMode="all"),
            )
        assert response.status_code == 201
        codes = [w["code"] for w in response.json()["warnings"]]
        assert "vary-query-all" in codes

    def test_a_duplicate_precedence_is_refused_by_name(self) -> None:
        existing = [{"id": "other", "ordinal": 0, "enabled": True, "matcher_value": "/x"}]
        with (
            patch("app.slate_cache_routes.list_rules", return_value=existing),
            patch("app.slate_cache_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/cache/rules", json=rule_body(ordinal=0)
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "ordinal-conflict"

    def test_replacing_a_rule_does_not_conflict_with_itself(self) -> None:
        existing = [{"id": RULE, "ordinal": 0, "enabled": True, "matcher_value": "/docs"}]
        with (
            patch("app.slate_cache_routes.list_rules", return_value=existing),
            patch("app.slate_cache_routes.upsert_rule", return_value={"id": RULE, "ordinal": 0}),
            patch("app.slate_cache_routes.append_audit"),
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/cache/rules/{RULE}", json=rule_body(ordinal=0)
            )
        assert response.status_code == 200

    def test_a_rule_dry_run_validates_without_writing(self) -> None:
        with (
            patch("app.slate_cache_routes.list_rules", return_value=[]),
            patch("app.slate_cache_routes.upsert_rule") as write,
            patch("app.slate_cache_routes.append_audit") as audit,
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/cache/rules", json=rule_body(dryRun=True)
            )
        assert response.status_code == 201
        assert response.json()["applied"] is False
        assert not write.called
        assert not audit.called

    def test_replacing_a_rule_that_is_not_on_the_lane_answers_404(self) -> None:
        from app.slate_cache_store import SlateCacheStoreError

        with (
            patch("app.slate_cache_routes.list_rules", return_value=[]),
            patch(
                "app.slate_cache_routes.upsert_rule",
                side_effect=SlateCacheStoreError("rule_not_found", "no"),
            ),
            patch("app.slate_cache_routes.append_audit"),
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/cache/rules/{RULE}", json=rule_body(ordinal=7)
            )
        assert response.status_code == 404

    def test_deleting_a_rule_audits(self) -> None:
        with (
            patch("app.slate_cache_routes.delete_rule", return_value=True),
            patch("app.slate_cache_routes.append_audit") as audit,
        ):
            response = client.delete(
                f"/v1/slate/environments/{ENV}/cache/rules/{RULE}?expectedPolicyVersion=3"
            )
        assert response.status_code == 200
        assert response.json()["deleted"] is True
        assert audit.called

    def test_writing_a_rule_requires_the_publish_permission(self, _permissions) -> None:
        with (
            patch("app.slate_cache_routes.list_rules", return_value=[]),
            patch("app.slate_cache_routes.upsert_rule", return_value={"id": RULE, "ordinal": 0}),
            patch("app.slate_cache_routes.append_audit"),
        ):
            client.post(f"/v1/slate/environments/{ENV}/cache/rules", json=rule_body())
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"


class TestTrace:
    """Criterion 2, at the surface. The evaluation itself is proven in its own suite."""

    def test_a_trace_answers_every_clause(self) -> None:
        with patch("app.slate_cache_routes.list_rules", return_value=[]):
            response = client.post(
                f"/v1/slate/environments/{ENV}/cache/trace",
                json={"request": {"method": "GET", "host": "docs.example.com", "path": "/docs"}},
            )
        assert response.status_code == 200
        body = response.json()
        for field in (
            "eligibility",
            "cacheKey",
            "edgeTtlSeconds",
            "bypassed",
            "winningRuleLabel",
            "considered",
            "rulesDigest",
        ):
            assert field in body, f"the trace does not answer {field}"

    def test_a_trace_states_that_it_is_policy_evaluation_not_an_observed_hit(self) -> None:
        with patch("app.slate_cache_routes.list_rules", return_value=[]):
            body = client.post(
                f"/v1/slate/environments/{ENV}/cache/trace",
                json={"request": {"path": "/docs"}},
            ).json()
        assert body["basis"] == "policy-evaluation"
        assert body["observed"] is False

    def test_a_what_if_ruleset_overrides_the_stored_rules(self) -> None:
        with patch("app.slate_cache_routes.list_rules") as stored:
            body = client.post(
                f"/v1/slate/environments/{ENV}/cache/trace",
                json={
                    "request": {"path": "/docs/intro"},
                    "rules": [
                        {
                            "ordinal": 0,
                            "label": "What if",
                            "matcherKind": "prefix",
                            "matcherValue": "/docs",
                            "matcherMethods": ["GET"],
                            "edgeTtlSeconds": 999,
                        }
                    ],
                },
            ).json()
        assert body["edgeTtlSeconds"] == 999
        assert body["winningRuleLabel"] == "What if"
        assert not stored.called

    def test_a_trace_is_not_recorded_unless_asked(self) -> None:
        with (
            patch("app.slate_cache_routes.list_rules", return_value=[]),
            patch("app.slate_cache_routes.record_trace") as record,
        ):
            client.post(
                f"/v1/slate/environments/{ENV}/cache/trace", json={"request": {"path": "/docs"}}
            )
        assert not record.called

    def test_a_persisted_trace_returns_its_id(self) -> None:
        with (
            patch("app.slate_cache_routes.list_rules", return_value=[]),
            patch("app.slate_cache_routes.record_trace", return_value={"id": "trace-1"}),
        ):
            body = client.post(
                f"/v1/slate/environments/{ENV}/cache/trace",
                json={"request": {"path": "/docs"}, "persist": True},
            ).json()
        assert body["traceId"] == "trace-1"

    def test_tracing_requires_only_the_view_permission(self, _permissions) -> None:
        """A trace is a read; requiring publish would put it out of reach during an incident."""
        with patch("app.slate_cache_routes.list_rules", return_value=[]):
            client.post(
                f"/v1/slate/environments/{ENV}/cache/trace", json={"request": {"path": "/docs"}}
            )
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "view"


class TestPurge:
    """Criterion 3, and the honesty rules."""

    def test_a_prefix_purge_estimates_its_scope_and_names_the_basis(self) -> None:
        with (
            patch(
                "app.slate_cache_routes.routes_for_release",
                return_value=["/docs/a", "/docs/b", "/blog/c"],
            ),
            patch("app.slate_cache_routes.record_purge", return_value={"id": "purge-1"}),
            patch("app.slate_cache_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/cache/purge",
                json={"scopeKind": "prefix", "scopeValue": "/docs", "reason": "stale nav"},
            )
        assert response.status_code == 200
        estimate = response.json()["estimate"]
        assert estimate["estimatedObjects"] == 2
        assert estimate["estimateBasis"] == "changed-pages"
        assert estimate["sampleRoutes"] == ["/docs/a", "/docs/b"]
        assert "Unchanged pages" in estimate["coverage"]

    def test_no_purge_response_ever_claims_a_flush(self) -> None:
        with (
            patch("app.slate_cache_routes.routes_for_release", return_value=["/docs/a"]),
            patch("app.slate_cache_routes.record_purge", return_value={"id": "purge-1"}),
            patch("app.slate_cache_routes.append_audit"),
        ):
            body = client.post(
                f"/v1/slate/environments/{ENV}/cache/purge",
                json={"scopeKind": "prefix", "scopeValue": "/docs", "reason": "x"},
            ).json()
        assert body["outcome"] == "recorded"
        assert body["outcome"] != "dispatched"
        assert body["edgeAttached"] is False
        assert body["delivery"]["dispatched"] is False
        assert "nothing was evicted" in body["delivery"]["sentence"]

    def test_a_dry_run_estimates_without_auditing(self) -> None:
        with (
            patch("app.slate_cache_routes.routes_for_release", return_value=["/docs/a"]),
            patch("app.slate_cache_routes.record_purge", return_value={"id": "purge-1"}),
            patch("app.slate_cache_routes.append_audit") as audit,
        ):
            body = client.post(
                f"/v1/slate/environments/{ENV}/cache/purge",
                json={
                    "scopeKind": "prefix",
                    "scopeValue": "/docs",
                    "reason": "x",
                    "dryRun": True,
                },
            ).json()
        assert body["outcome"] == "estimated"
        assert not audit.called

    def test_an_empty_scope_is_refused_and_recorded(self) -> None:
        with (
            patch("app.slate_cache_routes.routes_for_release", return_value=["/blog/a"]),
            patch("app.slate_cache_routes.record_purge", return_value={"id": "purge-2"}) as record,
            patch("app.slate_cache_routes.append_audit") as audit,
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/cache/purge",
                json={"scopeKind": "prefix", "scopeValue": "/docs", "reason": "x"},
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "purge-scope-empty"
        assert record.call_args.kwargs["outcome"] == "refused"
        assert record.call_args.kwargs["refusal_reason"] == "purge-scope-empty"
        assert audit.called, "a refusal during an incident belongs in the timeline"

    def test_a_refused_dry_run_records_nothing(self) -> None:
        with (
            patch("app.slate_cache_routes.routes_for_release", return_value=["/blog/a"]),
            patch("app.slate_cache_routes.record_purge") as record,
            patch("app.slate_cache_routes.append_audit") as audit,
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/cache/purge",
                json={
                    "scopeKind": "prefix",
                    "scopeValue": "/docs",
                    "reason": "x",
                    "dryRun": True,
                },
            )
        assert response.status_code == 409
        assert not record.called
        assert not audit.called

    def test_a_confirmed_estimate_that_changed_is_refused(self) -> None:
        """The operator approved a different blast radius than the one now in front of them."""
        with (
            patch(
                "app.slate_cache_routes.routes_for_release",
                return_value=["/docs/a", "/docs/b", "/docs/c"],
            ),
            patch("app.slate_cache_routes.record_purge", return_value={"id": "p"}),
            patch("app.slate_cache_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/cache/purge",
                json={
                    "scopeKind": "prefix",
                    "scopeValue": "/docs",
                    "reason": "x",
                    "confirmEstimatedObjects": 2,
                },
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "purge-estimate-changed"

    def test_a_matching_confirmed_estimate_proceeds(self) -> None:
        with (
            patch("app.slate_cache_routes.routes_for_release", return_value=["/docs/a", "/docs/b"]),
            patch("app.slate_cache_routes.record_purge", return_value={"id": "p"}),
            patch("app.slate_cache_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/cache/purge",
                json={
                    "scopeKind": "prefix",
                    "scopeValue": "/docs",
                    "reason": "x",
                    "confirmEstimatedObjects": 2,
                },
            )
        assert response.status_code == 200

    def test_a_release_scope_that_names_no_pages_is_refused(self) -> None:
        with (
            patch("app.slate_cache_routes.routes_for_release", return_value=[]),
            patch("app.slate_cache_routes.record_purge", return_value={"id": "p"}),
            patch("app.slate_cache_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/cache/purge",
                json={"scopeKind": "release", "scopeValue": RELEASE, "reason": "x"},
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "purge-release-not-found"

    def test_a_host_scope_uses_the_domain_inventory_as_its_basis(self) -> None:
        with (
            patch("app.slate_cache_routes.routes_for_host", return_value=["/a", "/b"]),
            patch("app.slate_cache_routes.record_purge", return_value={"id": "p"}),
            patch("app.slate_cache_routes.append_audit"),
        ):
            body = client.post(
                f"/v1/slate/environments/{ENV}/cache/purge",
                json={"scopeKind": "host", "scopeValue": "docs.example.com", "reason": "x"},
            ).json()
        assert body["estimate"]["estimateBasis"] == "domain-inventory"

    def test_a_tag_scope_resolves_through_the_rules_carrying_it(self) -> None:
        tagged = [{"id": "r", "ordinal": 0, "enabled": True, "matcher_kind": "prefix",
                   "matcher_value": "/docs", "matcher_methods": ["GET"]}]
        with (
            patch("app.slate_cache_routes.rules_for_tag", return_value=tagged),
            patch(
                "app.slate_cache_routes.routes_for_release",
                return_value=["/docs/a", "/blog/b"],
            ),
            patch("app.slate_cache_routes.record_purge", return_value={"id": "p"}),
            patch("app.slate_cache_routes.append_audit"),
        ):
            body = client.post(
                f"/v1/slate/environments/{ENV}/cache/purge",
                json={"scopeKind": "tag", "scopeValue": "nav", "reason": "x"},
            ).json()
        assert body["estimate"]["estimateBasis"] == "rule-tags"
        assert body["estimate"]["sampleRoutes"] == ["/docs/a"]

    def test_an_unknown_scope_kind_is_rejected_by_the_schema(self) -> None:
        response = client.post(
            f"/v1/slate/environments/{ENV}/cache/purge",
            json={"scopeKind": "everything", "scopeValue": "x", "reason": "x"},
        )
        assert response.status_code == 422

    def test_a_purge_requires_a_reason(self) -> None:
        response = client.post(
            f"/v1/slate/environments/{ENV}/cache/purge",
            json={"scopeKind": "prefix", "scopeValue": "/docs"},
        )
        assert response.status_code == 422

    def test_purging_requires_the_publish_permission(self, _permissions) -> None:
        with (
            patch("app.slate_cache_routes.routes_for_release", return_value=["/docs/a"]),
            patch("app.slate_cache_routes.record_purge", return_value={"id": "p"}),
            patch("app.slate_cache_routes.append_audit"),
        ):
            client.post(
                f"/v1/slate/environments/{ENV}/cache/purge",
                json={"scopeKind": "prefix", "scopeValue": "/docs", "reason": "x"},
            )
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"


class TestHistoryAndAudit:
    """The evidence half of criterion 3."""

    def test_purge_history_is_returned_with_its_estimates_and_basis(self) -> None:
        rows = [
            {
                "id": "purge-1",
                "at": None,
                "actor_name": "ken@example.com",
                "scope_kind": "prefix",
                "scope_value": "/docs",
                "reason": "stale nav",
                "estimated_objects": 12,
                "estimate_basis": "changed-pages",
                "sample_routes": ["/docs/a"],
                "dry_run": False,
                "outcome": "recorded",
                "refusal_reason": None,
                "edge_attached": False,
            }
        ]
        with patch("app.slate_cache_routes.list_purges", return_value=rows):
            body = client.get(f"/v1/slate/environments/{ENV}/cache/purges").json()
        purge = body["purges"][0]
        assert purge["estimatedObjects"] == 12
        assert purge["estimateBasis"] == "changed-pages"
        assert purge["actorName"] == "ken@example.com"
        assert purge["edgeAttached"] is False

    def test_purge_history_can_be_filtered(self) -> None:
        with patch("app.slate_cache_routes.list_purges", return_value=[]) as query:
            client.get(f"/v1/slate/environments/{ENV}/cache/purges?scopeKind=host&limit=5")
        assert query.call_args.kwargs["scope_kind"] == "host"
        assert query.call_args.kwargs["limit"] == 5

    def test_the_audit_trail_is_returned(self) -> None:
        rows = [
            {
                "id": "audit-1",
                "at": None,
                "actor_name": "ken@example.com",
                "actor_kind": "user",
                "subject_kind": "purge",
                "subject_id": None,
                "summary": "Purged by prefix",
                "detail": "12 objects",
            }
        ]
        with patch("app.slate_cache_routes.list_audit", return_value=rows):
            body = client.get(f"/v1/slate/environments/{ENV}/cache/audit").json()
        assert body["entries"][0]["summary"] == "Purged by prefix"
        assert body["entries"][0]["subjectKind"] == "purge"

    def test_reading_history_requires_only_the_view_permission(self, _permissions) -> None:
        with patch("app.slate_cache_routes.list_purges", return_value=[]):
            client.get(f"/v1/slate/environments/{ENV}/cache/purges")
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "view"
