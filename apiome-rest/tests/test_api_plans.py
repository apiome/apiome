"""Pure rules for API plans — APX-1.2 (#6099).

:mod:`app.api_plans` holds what needs no database:

* **limits validate** — every count positive, every window once, stored shortest window first;
* the auth config carries only the strategy's own settings (a header name for ``key_auth``, an IdP
  config and scopes for ``oauth2_client_credentials``);
* a plan is **declared only** with no environment or with one whose connector cannot provision —
  every connector today, until APX-4.1 — and says so in a notice;
* a member whose security schemes cannot carry the strategy is a warning, not a refusal;
* the ``x-apiome-plans`` entry never carries ``billing_ref``, and the fidelity item keeps the plans
  for OpenAPI and drops them for every other target.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app import api_plans
from app.api_plans import (
    CODE_INVALID,
    NOTICE_DECLARED_ONLY,
    PLANS_EXTRAS_KEY,
    WARNING_AUTH_MISMATCH,
    ApiPlanInput,
    ApiPlanRecord,
    ApiPlanValidationError,
    PlanAuthConfig,
    PlanEnvironment,
    PlanLimit,
    auth_mismatch_warnings,
    connector_can_provision,
    declared_only_notice,
    is_declared_only,
    normalize_auth_config,
    normalize_limits,
    normalize_plan_name,
    normalize_terms_url,
    plan_extension_entry,
    plans_loss_item,
    resolve_plan_slug,
    scheme_satisfies,
)


def _env(slug: str = "kong-prod-cp", *, kind: str = "kong-admin", can: bool = False, missing: bool = False):
    return PlanEnvironment(id=f"id-{slug}", slug=None if missing else slug, connector_kind=kind,
                           can_provision=can, missing=missing)


# -- limits -------------------------------------------------------------------------------------


def test_limits_are_stored_shortest_window_first() -> None:
    limits = [PlanLimit(window="day", requests=50_000), PlanLimit(window="minute", requests=100)]
    assert normalize_limits(limits) == [
        {"window": "minute", "requests": 100},
        {"window": "day", "requests": 50_000},
    ]


def test_a_window_may_be_limited_once() -> None:
    with pytest.raises(ApiPlanValidationError) as caught:
        normalize_limits([PlanLimit(window="minute", requests=100), PlanLimit(window="minute", requests=10)])
    assert caught.value.code == CODE_INVALID
    assert "minute window is limited twice" in str(caught.value)


@pytest.mark.parametrize("requests", [0, -5])
def test_a_limit_must_allow_at_least_one_request(requests: int) -> None:
    with pytest.raises(ValidationError):
        PlanLimit(window="second", requests=requests)


def test_a_limit_window_is_one_of_the_five() -> None:
    with pytest.raises(ValidationError):
        PlanLimit(window="week", requests=10)


def test_concurrency_and_key_age_are_positive() -> None:
    with pytest.raises(ValidationError):
        ApiPlanInput(name="Standard", concurrency=0)
    with pytest.raises(ValidationError):
        ApiPlanInput(name="Standard", credential_ttl_days=0)


# -- fields -------------------------------------------------------------------------------------


def test_the_slug_is_derived_from_the_name_or_refused() -> None:
    assert resolve_plan_slug(None, "Partner Tier") == "partner-tier"
    assert resolve_plan_slug("Sandbox", "x") == "sandbox"
    with pytest.raises(ApiPlanValidationError) as caught:
        resolve_plan_slug("-bad-", "x")
    assert caught.value.code == CODE_INVALID and "plan slug" in str(caught.value)


def test_a_plan_needs_a_name() -> None:
    assert normalize_plan_name("  Standard ") == "Standard"
    with pytest.raises(ApiPlanValidationError):
        normalize_plan_name("   ")


def test_key_auth_keeps_only_a_header_name() -> None:
    assert normalize_auth_config("key_auth", PlanAuthConfig(header_name=" X-API-Key ")) == {"header_name": "X-API-Key"}
    assert normalize_auth_config("key_auth", None) == {}
    with pytest.raises(ApiPlanValidationError):
        normalize_auth_config("key_auth", PlanAuthConfig(scopes=["payments:read"]))
    with pytest.raises(ApiPlanValidationError):
        normalize_auth_config("key_auth", PlanAuthConfig(header_name="X API Key"))


def test_oauth2_keeps_its_idp_and_unique_scopes() -> None:
    config = PlanAuthConfig(idp_config_id="okta-main", scopes=["payments:read", " payments:read", "refunds:write", ""])
    assert normalize_auth_config("oauth2_client_credentials", config) == {
        "idp_config_id": "okta-main",
        "scopes": ["payments:read", "refunds:write"],
    }
    with pytest.raises(ApiPlanValidationError):
        normalize_auth_config("oauth2_client_credentials", PlanAuthConfig(header_name="apikey"))
    with pytest.raises(ApiPlanValidationError):
        normalize_auth_config("oauth2_client_credentials", PlanAuthConfig(scopes=['bad"scope']))


def test_mtls_and_none_take_no_settings() -> None:
    assert normalize_auth_config("mtls", PlanAuthConfig()) == {}
    with pytest.raises(ApiPlanValidationError):
        normalize_auth_config("none", PlanAuthConfig(idp_config_id="okta"))


def test_the_terms_url_is_absolute_http() -> None:
    assert normalize_terms_url(" https://example.com/terms ") == "https://example.com/terms"
    assert normalize_terms_url("") is None
    for bad in ("ftp://example.com", "example.com/terms", "https://exa mple.com", "javascript:alert(1)"):
        with pytest.raises(ApiPlanValidationError):
            normalize_terms_url(bad)


# -- declared only ------------------------------------------------------------------------------


def test_no_connector_can_provision_until_apx_4_1() -> None:
    assert api_plans.PROVISIONING_CONNECTOR_KINDS == frozenset()
    assert not connector_can_provision("kong-admin")
    assert not connector_can_provision(None)


def test_a_plan_with_no_environment_is_declared_only() -> None:
    assert is_declared_only([])
    notice = declared_only_notice([])
    assert notice is not None and notice.code == NOTICE_DECLARED_ONLY
    assert "names no gateway environment" in notice.message


def test_an_environment_without_provisioning_makes_the_plan_declared_only() -> None:
    envs = [_env("kong-prod-cp"), _env("kong-staging-cp", can=True)]
    assert is_declared_only(envs)
    notice = declared_only_notice(envs)
    assert notice is not None
    assert "kong-prod-cp cannot be provisioned yet" in notice.message
    assert "kong-staging-cp" not in notice.message


def test_a_deleted_environment_cannot_be_provisioned() -> None:
    assert is_declared_only([_env("gone", can=True, missing=True)])


def test_a_plan_is_provisioned_when_every_environment_can_be(monkeypatch) -> None:
    monkeypatch.setattr(api_plans, "PROVISIONING_CONNECTOR_KINDS", frozenset({"kong-admin"}))
    assert connector_can_provision("kong-admin")
    envs = [_env("kong-prod-cp", can=True)]
    assert not is_declared_only(envs)
    assert declared_only_notice(envs) is None


# -- auth vs security schemes -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("strategy", "scheme_type", "fits"),
    [
        ("key_auth", "apiKey", True),
        ("key_auth", "http", False),
        ("oauth2_client_credentials", "oauth2", True),
        ("oauth2_client_credentials", "openIdConnect", True),
        ("oauth2_client_credentials", "apiKey", False),
        ("mtls", "mutualTLS", True),
        ("mtls", "http", False),
        ("none", "anything", True),
    ],
)
def test_a_scheme_fits_its_strategy(strategy: str, scheme_type: str, fits: bool) -> None:
    assert scheme_satisfies(strategy, {"scheme_type": scheme_type}) is fits
    assert scheme_satisfies(strategy, {"type": scheme_type}) is fits


def test_a_member_without_a_matching_scheme_is_a_warning() -> None:
    members = [
        {"kind": "project_latest", "ref": "r-1", "name": "Payments API", "schemes": [{"scheme_type": "apiKey"}]},
        {"kind": "project_version", "ref": "r-2", "name": "Refunds API", "schemes": [{"scheme_type": "oauth2"}]},
        {"kind": "catalog_item", "ref": "r-3", "name": "Ledger spec", "schemes": []},
    ]
    warnings = auth_mismatch_warnings("key_auth", members)
    assert [w.member["name"] for w in warnings] == ["Refunds API", "Ledger spec"]
    assert all(w.code == WARNING_AUTH_MISMATCH for w in warnings)
    assert warnings[0].message == "Refunds API declares no API key scheme, so this plan's auth does not match it."
    assert auth_mismatch_warnings("none", members) == []


# -- export -------------------------------------------------------------------------------------


def _plan(**overrides) -> ApiPlanRecord:
    body = {
        "id": "pl-1", "product": "payments", "slug": "standard", "name": "Standard",
        "auth_strategy": "key_auth", "auth_config": PlanAuthConfig(header_name="X-API-Key"),
        "limits": [PlanLimit(window="minute", requests=100)], "approval": "manual",
        "environments": [_env("kong-prod-cp"), _env("gone", missing=True)], "declared_only": True,
        "billing_ref": "stripe_price_123", "pricing_note": "$49 / month", "state": "published",
    }
    body.update(overrides)
    return ApiPlanRecord(**body)


def test_the_extension_entry_carries_what_a_consumer_needs_and_no_billing_ref() -> None:
    entry = plan_extension_entry("payments", "Payments", _plan())
    assert entry == {
        "product": "payments",
        "product_name": "Payments",
        "plan": "standard",
        "name": "Standard",
        "state": "published",
        "auth": {"strategy": "key_auth", "header_name": "X-API-Key"},
        "limits": [{"window": "minute", "requests": 100}],
        "approval": "manual",
        "declared_only": True,
        "pricing_note": "$49 / month",
        "environments": ["kong-prod-cp"],
    }
    assert "billing_ref" not in entry


def test_the_extension_entry_leaves_out_the_idp_config_id() -> None:
    plan = _plan(auth_strategy="oauth2_client_credentials",
                 auth_config=PlanAuthConfig(idp_config_id="okta-main", scopes=["payments:read"]))
    assert plan_extension_entry("payments", "Payments", plan)["auth"] == {
        "strategy": "oauth2_client_credentials", "scopes": ["payments:read"],
    }


def test_the_fidelity_item_keeps_plans_for_openapi_and_drops_them_elsewhere() -> None:
    extras = {PLANS_EXTRAS_KEY: [{"plan": "standard"}, {"plan": "partner"}]}
    kept = plans_loss_item(extras, "openapi", "OpenAPI 3.1")
    assert kept is not None and kept["kind"] == "ok" and kept["target_mapping"] == "root x-apiome-plans"
    dropped = plans_loss_item(extras, "protobuf", "Protobuf")
    assert dropped is not None and dropped["kind"] == "drop" and dropped["severity"] == "info"
    assert dropped["message"] == "2 API product plans (x-apiome-plans) dropped: Protobuf has no equivalent."
    assert plans_loss_item({}, "protobuf", "Protobuf") is None
