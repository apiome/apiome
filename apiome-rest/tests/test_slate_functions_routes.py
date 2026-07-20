"""Function control REST surface — UXE-3.3 (private-suite#2475).

Route-level tests over :mod:`app.slate_functions_routes`, following the
``test_slate_security_routes.py`` precedent: a module-level ``TestClient``, a mock auth dict, and
store functions patched *where used*. The pure module and the store are proven separately in their
own suites; what is asserted here is the contract the surface publishes.

The claims that matter most, and which nothing below is allowed to weaken:

* **Every route names the permission it needs.** VIEW for reads, PUBLISH for writes, and VIEW for
  simulation and for audit export — "which function served this customer" is the question that
  brings an operator here during an incident, and "show me the ledger" is the auditor's whole job;
  requiring PUBLISH for either would put the answer out of reach of the person asking.
* **Refusals reach the client as sentences, character for character.** 409 with
  ``{code, message, reason}``, the shape the authoring surface's ``disabledReason`` renders, and
  the message is the server's own — never a restatement.
* **Secrets are references and cannot cross a boundary.** There is no value field on the request,
  and a reference naming another tenant or environment is refused with no acknowledgement path.
* **Deny-by-default is the absence of a grant.** A capability without a reason or without an end
  date is refused; revoking is a delete; and the catalog says what each grant opens before anybody
  makes one.
* **Personalization that would serve one reader's page to another is refused, not warned about.**
  A missing fallback, an identity-keyed cache vary and a personal classification with no consent
  basis are each a distinct named refusal.
* **A cross-tenant probe cannot confirm a lane exists.** An unknown environment answers 404, never
  403.
* **No response can claim an execution.** ``observed``, ``executed`` and ``enforced`` are literal
  pydantic defaults no handler assigns, so the honesty of the surface is a property of its types.
* **Evidence exports cannot run code and cannot lie by omission.** Formula-leading cells are
  neutralized, truncation is stated in words, and the export writes its own audit row.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
FUNCTION = "44444444-4444-4444-4444-444444444444"
RELEASE = "55555555-5555-5555-5555-555555555555"
VARIANT = "66666666-6666-6666-6666-666666666666"
INVOCATION = "77777777-7777-7777-7777-777777777777"
VERSION = "88888888-8888-8888-8888-888888888888"
EGRESS = "99999999-9999-9999-9999-999999999999"
SECRET_REF = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_TENANT = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
OTHER_ENV = "cccccccc-cccc-cccc-cccc-cccccccccccc"

AUTHOR_KEY = "user-1"
APPROVER_KEY = "user-2"

SOURCE_DIGEST = "sha256:" + "c" * 64
BODY_DIGEST = "sha256:" + "a" * 64

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
    "functions_enabled": True,
    "policy_version": 3,
    "edge_attached": False,
    "edge_provider": None,
    "default_region": "eu-west",
    "default_residency_class": "in-region-only",
    "default_cpu_ms_limit": 50,
    "default_memory_mb_limit": 128,
    "default_wall_ms_limit": 5000,
    "residency_waiver_reason": None,
    "updated_at": None,
    "updated_by_actor_name": "ken@example.com",
}


def function_request(**overrides) -> Dict[str, Any]:
    """A valid function request body, in the camelCase the wire uses."""
    base = {
        "ordinal": 0,
        "enabled": True,
        "label": "Add locale header",
        "matcherKind": "prefix",
        "matcherValue": "/guide/",
        "matcherMethods": ["GET"],
        "matcherHosts": [],
        "runtime": "js-isolate",
        "activeVersionId": VERSION,
        "rolloutMode": "simulate",
        "rolloutPercent": 10,
        "envVarNames": [],
        "declaredDestinations": [],
        "acknowledgedWarnings": [],
        "expectedPolicyVersion": 3,
        "dryRun": False,
        "reason": "test",
    }
    base.update(overrides)
    return base


def stored_function(**overrides) -> Dict[str, Any]:
    """A function row as the store returns it."""
    base = {
        "id": FUNCTION,
        "tenant_id": TENANT,
        "environment_id": ENV,
        "ordinal": 0,
        "enabled": True,
        "label": "Add locale header",
        "matcher_kind": "prefix",
        "matcher_value": "/guide/",
        "matcher_methods": ["GET"],
        "matcher_hosts": [],
        "runtime": "js-isolate",
        "active_version_id": VERSION,
        "rollout_mode": "simulate",
        "rollout_percent": 10,
        "region": None,
        "residency_class": None,
        "cpu_ms_limit": None,
        "memory_mb_limit": None,
        "wall_ms_limit": None,
        "env_var_names": [],
        "acknowledged_warnings": [],
        "body_digest": BODY_DIGEST,
        "revision": 2,
    }
    base.update(overrides)
    return base


def variant_request(**overrides) -> Dict[str, Any]:
    """A valid personalization variant request body."""
    base = {
        "functionId": FUNCTION,
        "ordinal": 0,
        "enabled": True,
        "label": "German readers",
        "audienceKind": "geo",
        "audienceMatcher": [{"kind": "country", "equals": "DE"}],
        "fallbackVariant": "default",
        "cacheKeyEffect": "vary-on-dimension",
        "varyDimension": "country",
        "analyticsDimension": "country",
        "privacyClass": "non-personal",
        "consentBasis": "not-required",
        "expectedPolicyVersion": 3,
        "dryRun": False,
        "reason": "test",
    }
    base.update(overrides)
    return base


def stored_variant(**overrides) -> Dict[str, Any]:
    """A variant row as the store returns it."""
    base = {
        "id": VARIANT,
        "function_id": FUNCTION,
        "ordinal": 0,
        "enabled": True,
        "label": "German readers",
        "audience_kind": "geo",
        "audience_matcher": [{"kind": "country", "equals": "DE"}],
        "fallback_variant": "default",
        "cache_key_effect": "vary-on-dimension",
        "analytics_dimension": "country",
        "privacy_class": "non-personal",
        "consent_basis": "not-required",
    }
    base.update(overrides)
    return base


def future(days: int = 30) -> str:
    """An ISO-8601 moment ``days`` from now."""
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_slate_authentication] = lambda: dict(_MOCK_JWT)
    yield
    app.dependency_overrides.pop(validate_slate_authentication, None)


@pytest.fixture(autouse=True)
def _permissions():
    """Allow by default; individual tests re-patch to assert the required permission."""
    with patch("app.slate_functions_routes.enforce_permission") as enforce:
        yield enforce


@pytest.fixture(autouse=True)
def _lane():
    """Resolve the environment, its policy and the lookups every route needs."""
    with (
        patch("app.slate_functions_routes.get_environment", return_value=dict(ENVIRONMENT)),
        patch("app.slate_functions_routes.ensure_policy", return_value=dict(POLICY)),
        patch("app.slate_functions_routes.list_functions", return_value=[]),
        patch("app.slate_functions_routes.list_variants", return_value=[]),
        patch("app.slate_functions_routes.list_capabilities", return_value=[]),
        patch("app.slate_functions_routes.list_egress_rules", return_value=[]),
        patch("app.slate_functions_routes.list_secret_refs", return_value=[]),
        patch("app.slate_functions_routes.list_approvals", return_value=[]),
        patch(
            "app.slate_functions_routes.function_evaluation_context",
            return_value={"simulated_at": None, "previous_rollout_percent": None},
        ),
    ):
        yield


class TestCatalog:
    """A capability is what it opens, not its name: every entry must explain its cost."""

    def test_every_runtime_states_its_sandbox_and_its_blast_radius(self) -> None:
        response = client.get("/v1/slate/functions/runtimes")
        assert response.status_code == 200
        runtimes = response.json()["runtimes"]
        assert [r["key"] for r in runtimes] == ["js-isolate", "wasm"]
        for runtime in runtimes:
            assert runtime["expectedImpact"], f"{runtime['key']} explains nothing"
            assert runtime["sandbox"]
            assert runtime["unsafeIf"]

    def test_every_capability_says_what_granting_it_costs(self) -> None:
        capabilities = client.get("/v1/slate/functions/capabilities").json()["capabilities"]
        assert {c["id"] for c in capabilities} == {
            "geo-read",
            "env-read",
            "kv-read",
            "kv-write",
            "crypto-subtle",
            "fetch-egress",
            "cookie-write",
            "secret-read",
        }
        for capability in capabilities:
            assert capability["expectedImpact"]
            assert capability["unsafeIf"]
            assert capability["privacyReach"] in ("none", "coarse", "identifying")

    def test_the_standing_privileges_are_the_ones_that_must_lapse(self) -> None:
        by_id = {c["id"]: c for c in client.get("/v1/slate/functions/capabilities").json()["capabilities"]}
        assert by_id["secret-read"]["requiresExpiry"] is True
        assert by_id["fetch-egress"]["requiresExpiry"] is True
        assert by_id["geo-read"]["requiresExpiry"] is False

    def test_every_residency_posture_states_what_it_does_not_cover(self) -> None:
        """The field most residency controls quietly omit is the one an operator needs."""
        body = client.get("/v1/slate/functions/presets").json()
        postures = {p["key"]: p for p in body["residencyClasses"]}
        assert set(postures) == {"in-region-only", "region-pinned", "unrestricted"}
        for posture in postures.values():
            assert posture["doesNotCover"]
        assert postures["unrestricted"]["permitsPersonal"] is False
        assert postures["unrestricted"]["requiresWaiverReason"] is True

    def test_the_cache_key_effects_say_which_are_safe_for_personal_data(self) -> None:
        effects = {e["key"]: e for e in client.get("/v1/slate/functions/presets").json()["cacheKeyEffects"]}
        assert effects["none"]["safeForPersonal"] is False
        assert effects["bypass-cache"]["safeForPersonal"] is True
        for effect in effects.values():
            assert effect["expectedImpact"]

    def test_reading_the_catalogs_requires_the_view_permission(self, _permissions) -> None:
        for path in ("presets", "runtimes", "capabilities"):
            _permissions.reset_mock()
            client.get(f"/v1/slate/functions/{path}")
            _, args, _ = _permissions.mock_calls[0]
            assert args[2] == "versions"
            assert args[3] == "view"


class TestPolicyRead:
    """What may run on this lane, and what it actually runs."""

    def test_the_policy_is_returned_in_camel_case(self) -> None:
        response = client.get(f"/v1/slate/environments/{ENV}/functions")
        assert response.status_code == 200
        body = response.json()
        assert body["policyVersion"] == 3
        assert body["functionsEnabled"] is True
        assert body["defaultResidencyClass"] == "in-region-only"
        assert body["defaultCpuMsLimit"] == 50
        assert body["functionsDigest"].startswith("sha256:")

    def test_the_response_states_that_nothing_executes(self) -> None:
        body = client.get(f"/v1/slate/environments/{ENV}/functions").json()
        assert body["edgeAttached"] is False
        assert body["enforcement"]["enforced"] is False
        assert "no code runs on any request" in body["enforcement"]["sentence"]

    def test_a_functions_grants_and_variants_travel_with_it(self) -> None:
        with (
            patch(
                "app.slate_functions_routes.list_functions", return_value=[stored_function()]
            ),
            patch(
                "app.slate_functions_routes.list_capabilities",
                return_value=[
                    {
                        "id": "grant-1",
                        "function_id": FUNCTION,
                        "capability": "geo-read",
                        "reason": "locale banner",
                    }
                ],
            ),
            patch("app.slate_functions_routes.list_variants", return_value=[stored_variant()]),
            patch(
                "app.slate_functions_routes.list_secret_refs",
                return_value=[
                    {
                        "id": SECRET_REF,
                        "function_id": FUNCTION,
                        "secret_name": "pricing-api-key",
                        "alias": "PRICING_KEY",
                        "scope": "function",
                    }
                ],
            ),
        ):
            body = client.get(f"/v1/slate/environments/{ENV}/functions").json()
        function = body["functions"][0]
        assert function["capabilities"][0]["capability"] == "geo-read"
        assert function["variants"][0]["cacheKeyEffect"] == "vary-on-dimension"
        assert function["secrets"][0]["alias"] == "PRICING_KEY"

    def test_a_secret_reference_carries_no_value_field_at_all(self) -> None:
        with (
            patch(
                "app.slate_functions_routes.list_functions", return_value=[stored_function()]
            ),
            patch(
                "app.slate_functions_routes.list_secret_refs",
                return_value=[
                    {
                        "id": SECRET_REF,
                        "function_id": FUNCTION,
                        "secret_name": "pricing-api-key",
                        "alias": "PRICING_KEY",
                        "scope": "function",
                    }
                ],
            ),
        ):
            body = client.get(f"/v1/slate/environments/{ENV}/functions").json()
        secret = body["functions"][0]["secrets"][0]
        assert set(secret) == {"id", "functionId", "secretName", "alias", "scope", "actorName"}
        assert "value" not in secret

    def test_an_unknown_environment_answers_404_not_403(self) -> None:
        """A cross-tenant probe must not be able to confirm the lane exists."""
        with patch("app.slate_functions_routes.get_environment", return_value=None):
            response = client.get(f"/v1/slate/environments/{ENV}/functions")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "environment_not_found"

    def test_reading_the_policy_requires_the_view_permission(self, _permissions) -> None:
        client.get(f"/v1/slate/environments/{ENV}/functions")
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "view"


class TestPolicyWrites:
    """Loosening residency is the change nobody can explain months later without a reason."""

    def test_setting_the_policy_writes_and_audits(self) -> None:
        with (
            patch(
                "app.slate_functions_routes.set_policy",
                return_value={**POLICY, "policy_version": 4, "default_residency_class": "region-pinned"},
            ) as write,
            patch("app.slate_functions_routes.append_audit") as audit,
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/functions/policy",
                json={
                    "functionsEnabled": True,
                    "defaultRegion": "eu-west",
                    "defaultResidencyClass": "region-pinned",
                    "expectedPolicyVersion": 3,
                    "reason": "EU commitment",
                },
            )
        assert response.status_code == 200
        assert response.json()["applied"] is True
        assert response.json()["policyVersion"] == 4
        assert write.called and audit.called

    def test_going_unrestricted_without_a_stated_reason_is_refused(self) -> None:
        with patch("app.slate_functions_routes.append_audit"):
            response = client.put(
                f"/v1/slate/environments/{ENV}/functions/policy",
                json={
                    "defaultResidencyClass": "unrestricted",
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "residency-violation"
        assert detail["code"] == "residency-violation"
        assert "Pin the region, or reclassify the variant." in detail["message"]

    def test_going_unrestricted_with_a_reason_is_allowed(self) -> None:
        with (
            patch(
                "app.slate_functions_routes.set_policy",
                return_value={**POLICY, "default_residency_class": "unrestricted"},
            ),
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/functions/policy",
                json={
                    "defaultResidencyClass": "unrestricted",
                    "residencyWaiverReason": "latency for APAC readers",
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 200
        assert response.json()["defaultResidencyClass"] == "unrestricted"

    def test_a_lost_update_reports_the_version_that_actually_won(self) -> None:
        from app.slate_functions_store import SlateFunctionPolicyConflictError

        with patch(
            "app.slate_functions_routes.set_policy",
            side_effect=SlateFunctionPolicyConflictError(ENV, 3, 9),
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/functions/policy",
                json={"expectedPolicyVersion": 3},
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "policy-version-conflict"
        assert detail["actualPolicyVersion"] == 9

    def test_a_dry_run_writes_nothing(self) -> None:
        with patch("app.slate_functions_routes.set_policy") as write:
            response = client.put(
                f"/v1/slate/environments/{ENV}/functions/policy",
                json={"expectedPolicyVersion": 3, "dryRun": True},
            )
        assert response.status_code == 200
        assert response.json()["applied"] is False
        assert not write.called

    def test_writing_the_policy_requires_the_publish_permission(self, _permissions) -> None:
        with (
            patch("app.slate_functions_routes.set_policy", return_value=dict(POLICY)),
            patch("app.slate_functions_routes.append_audit"),
        ):
            client.put(
                f"/v1/slate/environments/{ENV}/functions/policy",
                json={"expectedPolicyVersion": 3},
            )
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"


class TestFunctionWrites:
    """A function that cannot be evaluated, or that outgrows its lane, is refused by name."""

    def test_creating_a_function_writes_and_audits(self) -> None:
        with (
            patch(
                "app.slate_functions_routes.upsert_function",
                return_value=stored_function(),
            ) as write,
            patch("app.slate_functions_routes.append_audit") as audit,
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions", json=function_request()
            )
        assert response.status_code == 201
        body = response.json()
        assert body["applied"] is True
        assert body["bodyDigest"].startswith("sha256:")
        assert write.called and audit.called

    def test_an_uncompilable_matcher_is_refused_with_the_servers_sentence(self) -> None:
        with patch("app.slate_functions_routes.append_audit"):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions",
                json=function_request(matcherKind="regex", matcherValue="([unclosed"),
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "matcher-invalid"
        assert detail["message"] == (
            "This route matcher does not compile, so it can never be evaluated. Fix the pattern."
        )

    def test_a_limit_above_the_lane_ceiling_is_refused(self) -> None:
        with patch("app.slate_functions_routes.append_audit"):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions",
                json=function_request(cpuMsLimit=500),
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "limit-exceeds-ceiling"

    def test_a_function_more_permissive_than_its_lane_is_refused(self) -> None:
        with patch("app.slate_functions_routes.append_audit"):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions",
                json=function_request(residencyClass="unrestricted"),
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "residency-violation"

    def test_a_colliding_precedence_is_refused_because_it_breaks_reproducibility(self) -> None:
        with (
            patch(
                "app.slate_functions_routes.list_functions",
                return_value=[stored_function(id="other-id", ordinal=0)],
            ),
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions", json=function_request(ordinal=0)
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "ordinal-conflict"

    def test_a_broad_matcher_warns_without_blocking(self) -> None:
        with (
            patch("app.slate_functions_routes.upsert_function", return_value=stored_function()),
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions",
                json=function_request(matcherValue="/"),
            )
        assert response.status_code == 201
        assert "broad-matcher" in {w["code"] for w in response.json()["warnings"]}

    def test_replacing_a_function_runs_the_same_gates_as_a_create(self) -> None:
        with patch("app.slate_functions_routes.append_audit"):
            response = client.put(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}",
                json=function_request(matcherKind="regex", matcherValue="([unclosed"),
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "matcher-invalid"

    def test_removing_a_function_keeps_its_body(self) -> None:
        with (
            patch("app.slate_functions_routes.delete_function", return_value=True) as remove,
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.delete(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}?expectedPolicyVersion=3"
            )
        assert response.status_code == 200
        assert response.json()["deleted"] is True
        assert remove.called

    def test_writing_a_function_requires_the_publish_permission(self, _permissions) -> None:
        with (
            patch("app.slate_functions_routes.upsert_function", return_value=stored_function()),
            patch("app.slate_functions_routes.append_audit"),
        ):
            client.post(f"/v1/slate/environments/{ENV}/functions", json=function_request())
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "publish"


class TestRolloutAndDualControl:
    """Putting code into the request path is the change that needs a second pair of eyes."""

    def test_enforcing_with_no_active_version_is_refused(self) -> None:
        with (
            patch(
                "app.slate_functions_routes.get_function",
                return_value=stored_function(active_version_id=None),
            ),
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/rollout",
                json={
                    "rolloutMode": "enforce",
                    "rolloutPercent": 100,
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "enforce-without-version"

    def test_enforcing_without_ever_simulating_is_refused(self) -> None:
        with (
            patch("app.slate_functions_routes.get_function", return_value=stored_function()),
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/rollout",
                json={
                    "rolloutMode": "enforce",
                    "rolloutPercent": 50,
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "enforce-without-simulation"

    def test_enforcing_without_an_approval_is_refused(self) -> None:
        with (
            patch("app.slate_functions_routes.get_function", return_value=stored_function()),
            patch(
                "app.slate_functions_routes.function_evaluation_context",
                return_value={
                    "simulated_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
                    "previous_rollout_percent": 10,
                },
            ),
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/rollout",
                json={
                    "rolloutMode": "enforce",
                    "rolloutPercent": 50,
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "enforce-without-approval"

    def test_an_approval_by_the_author_is_not_an_approval(self) -> None:
        with (
            patch("app.slate_functions_routes.get_function", return_value=stored_function()),
            patch(
                "app.slate_functions_routes.function_evaluation_context",
                return_value={
                    "simulated_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
                    "previous_rollout_percent": 10,
                },
            ),
            patch(
                "app.slate_functions_routes.list_approvals",
                return_value=[{"approver_actor_key": AUTHOR_KEY, "digest": BODY_DIGEST}],
            ),
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/rollout",
                json={
                    "rolloutMode": "enforce",
                    "rolloutPercent": 50,
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "approval-self"

    def test_an_approval_of_a_different_body_is_stale_rather_than_missing(self) -> None:
        """The two need different actions, so they are different refusals."""
        with (
            patch("app.slate_functions_routes.get_function", return_value=stored_function()),
            patch(
                "app.slate_functions_routes.function_evaluation_context",
                return_value={
                    "simulated_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
                    "previous_rollout_percent": 10,
                },
            ),
            patch(
                "app.slate_functions_routes.list_approvals",
                return_value=[
                    {"approver_actor_key": APPROVER_KEY, "digest": "sha256:" + "f" * 64}
                ],
            ),
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/rollout",
                json={
                    "rolloutMode": "enforce",
                    "rolloutPercent": 50,
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "approval-stale"

    def test_a_rollout_to_a_function_that_is_not_there_answers_404(self) -> None:
        with patch("app.slate_functions_routes.get_function", return_value=None):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/rollout",
                json={
                    "rolloutMode": "simulate",
                    "rolloutPercent": 10,
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "function_not_found"

    def test_an_approver_cannot_record_their_own_approval(self) -> None:
        response = client.post(
            f"/v1/slate/environments/{ENV}/functions/approvals",
            json={
                "subjectKind": "function",
                "subjectId": FUNCTION,
                "digest": BODY_DIGEST,
                "authorActorKey": AUTHOR_KEY,
            },
        )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "approval-self"

    def test_a_second_person_can_approve(self) -> None:
        with (
            patch(
                "app.slate_functions_routes.record_approval",
                return_value={
                    "id": "approval-1",
                    "subject_kind": "function",
                    "subject_id": FUNCTION,
                    "digest": BODY_DIGEST,
                    "author_actor_name": "sam@example.com",
                    "approver_actor_name": "ken@example.com",
                },
            ) as write,
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions/approvals",
                json={
                    "subjectKind": "function",
                    "subjectId": FUNCTION,
                    "digest": BODY_DIGEST,
                    "authorActorKey": APPROVER_KEY,
                    "authorActorName": "sam@example.com",
                },
            )
        assert response.status_code == 201
        assert response.json()["approverActorName"] == "ken@example.com"
        # The approver is the authenticated caller, never a field on the request.
        assert write.call_args.kwargs["approver_actor_key"] == AUTHOR_KEY


class TestVersionsAndRevert:
    """Reverting applies a stored document rather than reconstructing intent from a sentence."""

    def test_adding_a_version_writes_and_audits(self) -> None:
        with (
            patch(
                "app.slate_functions_routes.add_version",
                return_value={
                    "id": VERSION,
                    "revision": 3,
                    "source_digest": SOURCE_DIGEST,
                    "runtime": "js-isolate",
                    "source_origin": "upload",
                    "body": {"entrypoint": "index.js"},
                },
            ) as write,
            patch("app.slate_functions_routes.append_audit") as audit,
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/versions",
                json={
                    "sourceDigest": SOURCE_DIGEST,
                    "body": {"entrypoint": "index.js"},
                    "runtime": "js-isolate",
                    "activate": True,
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 201
        body = response.json()
        assert body["activated"] is True
        assert body["version"]["sourceDigest"] == SOURCE_DIGEST
        assert write.called and audit.called

    def test_reverting_applies_the_named_revision(self) -> None:
        with (
            patch(
                "app.slate_functions_routes.revert_function",
                return_value=stored_function(rollout_percent=0),
            ) as revert,
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/revert",
                json={"revision": 1, "expectedPolicyVersion": 3},
            )
        assert response.status_code == 200
        assert response.json()["function"]["rolloutPercent"] == 0
        assert revert.call_args.kwargs["revision"] == 1

    def test_reverting_to_a_revision_that_does_not_exist_answers_404(self) -> None:
        from app.slate_functions_store import SlateFunctionStoreError

        with patch(
            "app.slate_functions_routes.revert_function",
            side_effect=SlateFunctionStoreError("revision_not_found", "no such revision"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/revert",
                json={"revision": 9, "expectedPolicyVersion": 3},
            )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "revision_not_found"

    def test_the_revision_history_returns_bodies_and_versions_together(self) -> None:
        with (
            patch(
                "app.slate_functions_routes.list_revisions",
                return_value=[
                    {
                        "id": "rev-1",
                        "revision": 1,
                        "change_kind": "created",
                        "body_digest": BODY_DIGEST,
                        "body": stored_function(),
                        "actor_name": "ken@example.com",
                    }
                ],
            ),
            patch(
                "app.slate_functions_routes.list_versions",
                return_value=[{"id": VERSION, "revision": 1, "source_digest": SOURCE_DIGEST}],
            ),
        ):
            response = client.get(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/revisions"
            )
        assert response.status_code == 200
        body = response.json()
        assert body["revisions"][0]["changeKind"] == "created"
        assert body["revisions"][0]["body"], "a revert needs the document, not a summary"
        assert body["versions"][0]["sourceDigest"] == SOURCE_DIGEST

    def test_reading_revisions_requires_the_view_permission(self, _permissions) -> None:
        with (
            patch("app.slate_functions_routes.list_revisions", return_value=[]),
            patch("app.slate_functions_routes.list_versions", return_value=[]),
        ):
            client.get(f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/revisions")
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "view"


class TestSecretReferences:
    """Secrets are references, and a reference cannot cross a boundary."""

    def test_the_request_has_no_field_by_which_to_send_a_value(self) -> None:
        from app.slate_functions_routes import SetSecretRefRequest

        assert "value" not in SetSecretRefRequest.model_fields
        assert "secret_value" not in SetSecretRefRequest.model_fields

    def test_declaring_a_reference_writes_and_audits(self) -> None:
        with (
            patch("app.slate_functions_routes.get_function", return_value=stored_function()),
            patch(
                "app.slate_functions_routes.set_secret_ref",
                return_value={
                    "id": SECRET_REF,
                    "function_id": FUNCTION,
                    "secret_name": "pricing-api-key",
                    "alias": "PRICING_KEY",
                    "scope": "function",
                },
            ) as write,
            patch("app.slate_functions_routes.append_audit") as audit,
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/secrets",
                json={
                    "secretName": "pricing-api-key",
                    "alias": "PRICING_KEY",
                    "scope": "function",
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 200
        assert response.json()["secret"]["alias"] == "PRICING_KEY"
        assert write.called and audit.called

    def test_a_reference_to_another_tenants_secret_is_refused(self) -> None:
        with (
            patch("app.slate_functions_routes.get_function", return_value=stored_function()),
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/secrets",
                json={
                    "secretName": "their-key",
                    "alias": "THEIR_KEY",
                    "ownerTenantId": OTHER_TENANT,
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "secret-cross-project"
        assert "another project or environment" in detail["message"]

    def test_a_reference_to_another_environments_secret_is_refused(self) -> None:
        with (
            patch("app.slate_functions_routes.get_function", return_value=stored_function()),
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/secrets",
                json={
                    "secretName": "staging-key",
                    "alias": "STAGING_KEY",
                    "ownerEnvironmentId": OTHER_ENV,
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "secret-cross-project"

    def test_withdrawing_a_reference_is_a_delete(self) -> None:
        with (
            patch("app.slate_functions_routes.delete_secret_ref", return_value=True) as remove,
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.delete(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/secrets/{SECRET_REF}"
                "?expectedPolicyVersion=3"
            )
        assert response.status_code == 200
        assert response.json()["deleted"] is True
        assert remove.called


class TestCapabilities:
    """Deny-by-default is the absence of a grant; a grant has to say why and when it ends."""

    def test_granting_a_capability_writes_and_audits(self) -> None:
        with (
            patch(
                "app.slate_functions_routes.grant_capability",
                return_value={
                    "id": "grant-1",
                    "function_id": FUNCTION,
                    "capability": "geo-read",
                    "reason": "locale banner",
                },
            ) as write,
            patch("app.slate_functions_routes.append_audit") as audit,
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/capabilities",
                json={
                    "capability": "geo-read",
                    "reason": "locale banner",
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 200
        assert response.json()["capability"]["capability"] == "geo-read"
        assert write.called and audit.called

    def test_a_grant_with_no_stated_reason_is_refused(self) -> None:
        with patch("app.slate_functions_routes.append_audit"):
            response = client.put(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/capabilities",
                json={"capability": "geo-read", "reason": "  ", "expectedPolicyVersion": 3},
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "capability-without-reason"
        assert "never what was granted but why" in detail["message"]

    def test_a_standing_privilege_with_no_end_date_is_refused(self) -> None:
        with patch("app.slate_functions_routes.append_audit"):
            response = client.put(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/capabilities",
                json={
                    "capability": "secret-read",
                    "reason": "vendor integration",
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "capability-unbounded"

    def test_a_standing_privilege_beyond_the_review_window_is_refused(self) -> None:
        with patch("app.slate_functions_routes.append_audit"):
            response = client.put(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/capabilities",
                json={
                    "capability": "secret-read",
                    "reason": "vendor integration",
                    "expiresAt": future(days=400),
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "capability-unbounded"

    def test_a_standing_privilege_inside_the_window_is_allowed(self) -> None:
        with (
            patch(
                "app.slate_functions_routes.grant_capability",
                return_value={"id": "grant-1", "capability": "secret-read"},
            ),
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/capabilities",
                json={
                    "capability": "secret-read",
                    "reason": "vendor integration",
                    "expiresAt": future(days=30),
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 200

    def test_revoking_a_capability_is_a_delete(self) -> None:
        with (
            patch("app.slate_functions_routes.revoke_capability", return_value=True) as revoke,
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.delete(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/capabilities/secret-read"
                "?expectedPolicyVersion=3"
            )
        assert response.status_code == 200
        assert response.json()["deleted"] is True
        assert revoke.call_args.kwargs["capability"] == "secret-read"

    def test_revoking_a_grant_that_was_never_made_answers_404(self) -> None:
        from app.slate_functions_store import SlateFunctionStoreError

        with patch(
            "app.slate_functions_routes.revoke_capability",
            side_effect=SlateFunctionStoreError("capability_not_found", "not granted"),
        ):
            response = client.delete(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/capabilities/kv-write"
                "?expectedPolicyVersion=3"
            )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "capability_not_found"


class TestEgress:
    """An egress allowlist is the difference between a function and an SSRF relay."""

    def test_allowlisting_a_destination_writes_and_audits(self) -> None:
        with (
            patch(
                "app.slate_functions_routes.set_egress_rule",
                return_value={
                    "id": EGRESS,
                    "function_id": FUNCTION,
                    "destination_kind": "exact-host",
                    "destination": "api.example.com",
                    "reason": "pricing lookup",
                },
            ) as write,
            patch("app.slate_functions_routes.append_audit") as audit,
        ):
            response = client.put(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/egress",
                json={
                    "destinationKind": "exact-host",
                    "destination": "api.example.com",
                    "reason": "pricing lookup",
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 200
        assert response.json()["egress"]["destination"] == "api.example.com"
        assert write.called and audit.called

    def test_an_unexplained_hole_in_the_allowlist_is_refused(self) -> None:
        with patch("app.slate_functions_routes.append_audit"):
            response = client.put(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/egress",
                json={
                    "destination": "api.example.com",
                    "reason": "",
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "capability-without-reason"

    def test_an_entry_that_does_not_cover_its_stated_destination_is_refused(self) -> None:
        """Better a refusal at the write than an inert allowance discovered in production."""
        with patch("app.slate_functions_routes.append_audit"):
            response = client.put(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/egress",
                json={
                    "destinationKind": "exact-host",
                    "destination": "api.example.com",
                    "reason": "pricing lookup",
                    "destinations": ["https://other.example.net/prices"],
                    "expectedPolicyVersion": 3,
                },
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "egress-unapproved"
        assert "SSRF relay" in detail["message"]

    def test_withdrawing_an_allowance_is_a_delete(self) -> None:
        with (
            patch("app.slate_functions_routes.delete_egress_rule", return_value=True) as remove,
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.delete(
                f"/v1/slate/environments/{ENV}/functions/{FUNCTION}/egress/{EGRESS}"
                "?expectedPolicyVersion=3"
            )
        assert response.status_code == 200
        assert remove.called


class TestPersonalizationVariants:
    """A variant that would serve one reader's page to another is refused, not warned about."""

    def test_creating_a_variant_writes_and_audits(self) -> None:
        with (
            patch(
                "app.slate_functions_routes.upsert_variant", return_value=stored_variant()
            ) as write,
            patch("app.slate_functions_routes.get_function", return_value=stored_function()),
            patch("app.slate_functions_routes.append_audit") as audit,
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions/variants", json=variant_request()
            )
        assert response.status_code == 201
        assert response.json()["variant"]["fallbackVariant"] == "default"
        assert write.called and audit.called

    def test_a_variant_with_no_fallback_is_refused(self) -> None:
        with (
            patch("app.slate_functions_routes.get_function", return_value=stored_function()),
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions/variants",
                json=variant_request(fallbackVariant=""),
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "variant-without-fallback"
        assert "Name what everybody else gets." in detail["message"]

    def test_varying_the_shared_cache_key_on_an_identity_credential_is_refused(self) -> None:
        with (
            patch("app.slate_functions_routes.get_function", return_value=stored_function()),
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions/variants",
                json=variant_request(varyDimension="sessionId", analyticsDimension="sessionId"),
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "variant-identity-cache-key"

    def test_personalizing_without_touching_the_cache_key_is_refused(self) -> None:
        with (
            patch("app.slate_functions_routes.get_function", return_value=stored_function()),
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions/variants",
                json=variant_request(
                    privacyClass="pseudonymous",
                    consentBasis="explicit-consent",
                    cacheKeyEffect="none",
                ),
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "variant-identity-cache-key"

    def test_personal_data_with_no_consent_basis_is_refused(self) -> None:
        with (
            patch("app.slate_functions_routes.get_function", return_value=stored_function()),
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions/variants",
                json=variant_request(privacyClass="personal", consentBasis="not-required"),
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "variant-personal-without-basis"
        assert "cannot both be true" in detail["message"]

    def test_personal_data_on_an_unrestricted_lane_is_refused(self) -> None:
        with (
            patch(
                "app.slate_functions_routes.ensure_policy",
                return_value={
                    **POLICY,
                    "default_residency_class": "unrestricted",
                    "residency_waiver_reason": "latency",
                },
            ),
            patch("app.slate_functions_routes.get_function", return_value=stored_function()),
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions/variants",
                json=variant_request(
                    privacyClass="personal", consentBasis="explicit-consent"
                ),
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "residency-violation"

    def test_a_variant_reporting_under_no_dimension_warns_without_blocking(self) -> None:
        with (
            patch("app.slate_functions_routes.upsert_variant", return_value=stored_variant()),
            patch("app.slate_functions_routes.get_function", return_value=stored_function()),
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions/variants",
                json=variant_request(analyticsDimension="", varyDimension="country"),
            )
        assert response.status_code == 201
        assert "variant-without-analytics" in {w["code"] for w in response.json()["warnings"]}

    def test_removing_a_variant_is_a_delete(self) -> None:
        with (
            patch("app.slate_functions_routes.delete_variant", return_value=True) as remove,
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.delete(
                f"/v1/slate/environments/{ENV}/functions/variants/{VARIANT}"
                "?expectedPolicyVersion=3"
            )
        assert response.status_code == 200
        assert remove.called


class TestSimulation:
    """The simulation answers the incident question, and cannot claim anything ran."""

    def test_a_matching_function_is_reported_as_would_run_never_ran(self) -> None:
        with patch(
            "app.slate_functions_routes.list_functions", return_value=[stored_function()]
        ):
            response = client.post(
                f"/v1/slate/environments/{ENV}/functions/simulate",
                json={"request": {"method": "GET", "path": "/guide/intro"}},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["outcome"] == "would-run"
        assert body["outcome"] != "ran"
        assert body["functionRef"] == FUNCTION

    def test_the_response_cannot_claim_an_execution_or_an_observation(self) -> None:
        response = client.post(
            f"/v1/slate/environments/{ENV}/functions/simulate",
            json={"request": {"path": "/guide/intro"}},
        )
        body = response.json()
        assert body["basis"] == "policy-simulation"
        assert body["observed"] is False
        assert body["executed"] is False
        assert body["enforced"] is False
        assert "not traffic that was observed" in body["sentence"]
        assert "A zero here would be a measurement" in body["runtimeSentence"]

    def test_every_function_that_lost_says_why(self) -> None:
        with patch(
            "app.slate_functions_routes.list_functions",
            return_value=[
                stored_function(),
                stored_function(id="other-id", ordinal=1, matcher_value="/api/"),
            ],
        ):
            body = client.post(
                f"/v1/slate/environments/{ENV}/functions/simulate",
                json={"request": {"path": "/guide/intro"}},
            ).json()
        considered = body["considered"]
        assert len(considered) == 2
        assert all(step["reason"] for step in considered)
        assert considered[1]["outcome"] == "skipped"

    def test_a_capability_the_function_does_not_hold_is_an_outcome_not_a_refusal(self) -> None:
        """Deny-by-default working correctly is a runtime answer, not a write-time error."""
        with patch(
            "app.slate_functions_routes.list_functions", return_value=[stored_function()]
        ):
            body = client.post(
                f"/v1/slate/environments/{ENV}/functions/simulate",
                json={
                    "request": {
                        "path": "/guide/intro",
                        "requestedCapabilities": ["secret-read"],
                    }
                },
            ).json()
        assert body["outcome"] == "capability-denied"
        assert body["capabilitiesDenied"] == ["secret-read"]
        assert "deny-by-default" in body["denialReason"]

    def test_an_unlisted_destination_is_reported_as_egress_denied(self) -> None:
        with (
            patch("app.slate_functions_routes.list_functions", return_value=[stored_function()]),
            patch(
                "app.slate_functions_routes.list_capabilities",
                return_value=[
                    {"function_id": FUNCTION, "capability": "fetch-egress", "reason": "x"}
                ],
            ),
        ):
            body = client.post(
                f"/v1/slate/environments/{ENV}/functions/simulate",
                json={
                    "request": {
                        "path": "/guide/intro",
                        "requestedCapabilities": ["fetch-egress"],
                        "requestedDestinations": ["evil.example.net"],
                    }
                },
            ).json()
        assert body["outcome"] == "egress-denied"
        assert body["egressDenied"] == ["evil.example.net"]

    def test_persisting_a_simulation_hands_raw_data_to_the_store_to_redact(self) -> None:
        with (
            patch("app.slate_functions_routes.list_functions", return_value=[stored_function()]),
            patch(
                "app.slate_functions_routes.record_invocation",
                return_value={"id": INVOCATION},
            ) as record,
        ):
            body = client.post(
                f"/v1/slate/environments/{ENV}/functions/simulate",
                json={
                    "request": {
                        "path": "/guide/intro",
                        "headers": {"cookie": "session=abc", "user-agent": "curl/8"},
                    },
                    "persist": True,
                },
            ).json()
        assert body["invocationId"] == INVOCATION
        evidence = record.call_args.kwargs["evidence"]
        assert evidence["cookie"] == "session=abc", "the route does not redact; the store does"
        assert record.call_args.kwargs["region"] == "eu-west"

    def test_the_store_actually_strips_what_the_route_hands_it(self) -> None:
        from app.slate_functions_store import redact_evidence

        assert redact_evidence({"cookie": "session=abc", "path": "/guide"}) == {"path": "/guide"}

    def test_a_what_if_overlay_is_evaluated_instead_of_the_stored_set(self) -> None:
        with patch(
            "app.slate_functions_routes.list_functions", return_value=[stored_function()]
        ) as stored:
            body = client.post(
                f"/v1/slate/environments/{ENV}/functions/simulate",
                json={
                    "request": {"path": "/guide/intro"},
                    "functions": [
                        {
                            "id": "overlay-1",
                            "label": "Overlay",
                            "matcherKind": "prefix",
                            "matcherValue": "/guide/",
                            "activeVersionId": VERSION,
                            "rolloutPercent": 100,
                            "enabled": True,
                        }
                    ],
                },
            ).json()
        assert body["functionLabel"] == "Overlay"
        assert not stored.called

    def test_simulating_requires_view_not_publish(self, _permissions) -> None:
        """The person asking which function served a customer is mid-incident, not mid-release."""
        client.post(
            f"/v1/slate/environments/{ENV}/functions/simulate",
            json={"request": {"path": "/guide/intro"}},
        )
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "view"
        assert args[3] != "publish"


class TestInvocations:
    """"Which function served this customer" is answered by a filtered read, not a guess."""

    def test_invocations_are_returned_with_their_redacted_evidence(self) -> None:
        with patch(
            "app.slate_functions_routes.list_invocations",
            return_value=[
                {
                    "id": INVOCATION,
                    "source": "policy-simulation",
                    "function_ref": FUNCTION,
                    "function_label": "Add locale header",
                    "route": "/guide/intro",
                    "method": "GET",
                    "outcome": "would-run",
                    "executed": False,
                    "edge_attached": False,
                    "evidence": {"path": "/guide/intro"},
                }
            ],
        ):
            response = client.get(f"/v1/slate/environments/{ENV}/functions/invocations")
        assert response.status_code == 200
        body = response.json()
        assert body["invocations"][0]["outcome"] == "would-run"
        assert body["invocations"][0]["executed"] is False
        assert body["observed"] is False
        assert body["invocations"][0]["cpuMs"] is None

    def test_invocations_can_be_narrowed_to_one_variant(self) -> None:
        with patch(
            "app.slate_functions_routes.list_invocations", return_value=[]
        ) as read:
            client.get(
                f"/v1/slate/environments/{ENV}/functions/invocations?variantRef={VARIANT}"
                "&outcome=capability-denied"
            )
        assert read.call_args.kwargs["variant_ref"] == VARIANT
        assert read.call_args.kwargs["outcome"] == "capability-denied"

    def test_one_invocation_can_be_read_by_id(self) -> None:
        with patch(
            "app.slate_functions_routes.get_invocation",
            return_value={"id": INVOCATION, "outcome": "skipped", "evidence": {}},
        ):
            response = client.get(
                f"/v1/slate/environments/{ENV}/functions/invocations/{INVOCATION}"
            )
        assert response.status_code == 200
        assert response.json()["id"] == INVOCATION

    def test_an_unknown_invocation_answers_404(self) -> None:
        with patch("app.slate_functions_routes.get_invocation", return_value=None):
            response = client.get(
                f"/v1/slate/environments/{ENV}/functions/invocations/{INVOCATION}"
            )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "invocation_not_found"


class TestAuditAndExport:
    """Who read the record of who let a function read secrets is part of that record."""

    def test_the_audit_trail_is_returned_newest_first(self) -> None:
        with patch(
            "app.slate_functions_routes.list_audit",
            return_value=[
                {
                    "id": "audit-1",
                    "actor_name": "ken@example.com",
                    "actor_kind": "user",
                    "subject_kind": "capability",
                    "subject_id": FUNCTION,
                    "summary": "Capability secret-read granted",
                    "detail": "vendor integration",
                }
            ],
        ):
            response = client.get(f"/v1/slate/environments/{ENV}/functions/audit")
        assert response.status_code == 200
        assert response.json()["entries"][0]["summary"] == "Capability secret-read granted"

    def test_the_export_neutralizes_a_cell_a_spreadsheet_would_execute(self) -> None:
        with (
            patch(
                "app.slate_functions_routes.list_audit",
                return_value=[
                    {
                        "id": "audit-1",
                        "actor_name": "=HYPERLINK(\"http://evil\",\"click\")",
                        "actor_kind": "user",
                        "subject_kind": "capability",
                        "subject_id": FUNCTION,
                        "summary": "+SUM(A1:A9)",
                        "detail": "@import",
                    }
                ],
            ),
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.get(f"/v1/slate/environments/{ENV}/functions/audit/export")
        assert response.status_code == 200
        text = response.text
        assert "'=HYPERLINK" in text
        assert "'+SUM" in text
        assert "'@import" in text

    def test_a_truncated_export_says_so_in_words(self) -> None:
        """An auditor reading a silently truncated ledger concludes the rest never happened."""
        rows = [
            {
                "id": f"audit-{i}",
                "actor_name": "a",
                "actor_kind": "user",
                "subject_kind": "policy",
                "subject_id": None,
                "summary": "s",
                "detail": None,
            }
            for i in range(3)
        ]
        with (
            patch("app.slate_functions_routes.list_audit", return_value=rows) as read,
            patch("app.slate_functions_routes.append_audit"),
        ):
            response = client.get(
                f"/v1/slate/environments/{ENV}/functions/audit/export?limit=2"
            )
        assert read.call_args.kwargs["limit"] == 3, "one past the cap, so truncation is a fact"
        assert "TRUNCATED" in response.text
        assert "do not read this file as the complete record" in response.text

    def test_the_export_writes_its_own_audit_row(self) -> None:
        with (
            patch("app.slate_functions_routes.list_audit", return_value=[]),
            patch("app.slate_functions_routes.append_audit") as audit,
        ):
            client.get(f"/v1/slate/environments/{ENV}/functions/audit/export")
        assert audit.call_args.kwargs["subject_kind"] == "export"
        assert audit.call_args.kwargs["summary"] == "Function audit exported"

    def test_exporting_requires_view_not_publish(self, _permissions) -> None:
        """§29.7 gives the Auditor read-only policy and exportable audit."""
        with (
            patch("app.slate_functions_routes.list_audit", return_value=[]),
            patch("app.slate_functions_routes.append_audit"),
        ):
            client.get(f"/v1/slate/environments/{ENV}/functions/audit/export")
        _, args, _ = _permissions.mock_calls[0]
        assert args[3] == "view"
        assert args[3] != "publish"
