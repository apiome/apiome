"""HTTP contract tests for the API change check suite — GNC-3.1 (#4740).

``/v1/tenants/{tenant_slug}/…/check-suite`` and the suite policy. Storage is the in-memory
:class:`tests.fake_suite_db.FakeSuiteDb`, the evidence readers and the provider are doubles;
everything above them is real — the RBAC guard, the store's rules, GNC-2.2's recording and the
status adapter. Asserted here:

* **The acceptance criteria, over HTTP.** A run answers pending / pass / fail / skipped; a re-run of
  unchanged inputs is a ``200`` replay of the same evaluation; the drill-down names the evidence and
  the policy; and a tenant administrator can make the suite required before publish.
* The rules around them: which permission each verb needs, who may change a policy, the refusal
  codes and their statuses, consumer names for callers who may not read them, the CI-key allowlist,
  and the OpenAPI contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from fastapi.testclient import TestClient

from app import (
    api_check_suite_evidence,
    api_check_suite_policy_store,
    api_check_suite_routes,
    api_check_suite_store,
    comment_store,
    deploy_gate_store,
    draft_binding_store,
    git_import_routes,
    provider_check_store,
)
from app.api_check_suite import BreakingFacts, LintFacts
from app.api_check_suite_evidence import Classification
from app.auth import (
    API_KEY_SCOPE_DIFF_READ,
    API_KEY_SCOPE_LINT_READ,
    acceptable_scopes_for_request,
    validate_authentication,
)
from app.consumer_impact import ConsumerImpactReport
from app.main import app
from tests.api_check_suite_doubles import Evidence, Provider, install_evidence
from tests.fake_suite_db import FakeSuiteDb

client = TestClient(app)

TENANT = "6b7c8d90-9999-4aaa-8bbb-000000000001"
PROJECT = "6b7c8d90-9999-4aaa-8bbb-000000000002"
OTHER_PROJECT = "6b7c8d90-9999-4aaa-8bbb-000000000003"
VERSION = "6b7c8d90-9999-4aaa-8bbb-000000000010"
UNBOUND = "6b7c8d90-9999-4aaa-8bbb-000000000011"
REPOSITORY = "6b7c8d90-9999-4aaa-8bbb-000000000020"
BINDING = "6b7c8d90-9999-4aaa-8bbb-000000000030"
ALICE = "6b7c8d90-9999-4aaa-8bbb-000000000101"
BOB = "6b7c8d90-9999-4aaa-8bbb-000000000102"

COMMIT = "cccccccccccccccccccccccccccccccccccccccc"
TOKEN = "ghp_a_real_looking_repository_token_0123456789"

PROJECT_BASE = "/v1/tenants/acme/projects/pets"
SUITE = f"{PROJECT_BASE}/versions/2.0.0/check-suite"
UNBOUND_SUITE = f"{PROJECT_BASE}/versions/3.0.0/check-suite"
TENANT_POLICY = "/v1/tenants/acme/governance/check-suite-policy"
PROJECT_POLICY = f"{PROJECT_BASE}/check-suite-policy"


@pytest.fixture
def provider(monkeypatch) -> Provider:
    """The provider API every adapter reaches, and the stored credential it is reached with."""
    fake_provider = Provider()
    monkeypatch.setattr(
        "app.provider_status_adapter._default_client_factory", fake_provider.factory()
    )
    monkeypatch.setattr(git_import_routes, "resolve_stored_git_token", lambda *a, **k: TOKEN)
    return fake_provider


@pytest.fixture
def evidence(monkeypatch) -> Evidence:
    """The evidence doubles beneath the gatherer."""
    return install_evidence(monkeypatch)


@pytest.fixture
def fake(monkeypatch, evidence, provider) -> FakeSuiteDb:
    """A seeded store with one bound draft and one unbound one, beneath every module."""
    store = FakeSuiteDb()
    store.add_project(TENANT, PROJECT, "pets")
    store.add_project(TENANT, OTHER_PROJECT, "orders")
    store.add_version(PROJECT, VERSION, "2.0.0")
    store.add_version(PROJECT, UNBOUND, "3.0.0")
    store.add_repository(TENANT, REPOSITORY, clone_url="https://github.com/acme/specs", created_by=ALICE)
    store.add_member(ALICE, "Alice Anders", "alice@example.com")
    store.add_member(BOB, "Bob Brown", "bob@example.com")
    store.admins.add((TENANT, ALICE))
    now = store._tick()
    store.bindings[BINDING] = {
        "id": BINDING,
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "version_id": VERSION,
        "repository_id": REPOSITORY,
        "provider": "github",
        "repo_full_name": "acme/specs",
        "repo_url": "https://github.com/acme/specs",
        "ref": "main",
        "path": "spec",
        "commit_sha": COMMIT,
        "source_digest": "sha256:abc",
        "synchronized_at": now,
        "created_by": ALICE,
        "created_at": now,
        "updated_at": now,
        "released_at": None,
        "released_by": None,
        "release_reason": None,
    }
    for module in (
        comment_store,
        draft_binding_store,
        provider_check_store,
        api_check_suite_store,
        api_check_suite_policy_store,
        api_check_suite_evidence,
        api_check_suite_routes,
        deploy_gate_store,
    ):
        monkeypatch.setattr(module, "db", store)
    return store


@pytest.fixture
def act_as():
    """Switch the authenticated caller; defaults to Alice (a tenant admin) on a session."""

    def _set(
        user_id: Optional[str] = ALICE, tenant_id: str = TENANT, method: str = "jwt"
    ) -> None:
        auth: Dict[str, Any] = {"tenant_id": tenant_id, "auth_method": method, "user_id": user_id}
        app.dependency_overrides[validate_authentication] = lambda: auth

    _set()
    yield _set
    app.dependency_overrides.pop(validate_authentication, None)


def _code(response) -> str:
    """The stable refusal code of an error response."""
    return response.json()["detail"]["code"]


# ---------------------------------------------------------------------------------------------
# Running the suite
# ---------------------------------------------------------------------------------------------


def test_running_the_suite_records_one_verdict_and_reports_it_on_the_pull_request(
    fake, provider, act_as
):
    response = client.post(SUITE, json={})
    assert response.status_code == 201, response.text
    body = response.json()
    run = body["run"]
    assert run["state"] == "pass"
    assert run["schema_version"] == "gnc.check-suite.v1"
    assert run["commit_sha"] == COMMIT
    assert [c["component"] for c in run["components"]] == [
        "lint",
        "breaking",
        "consumers",
        "contract",
        "sdk",
    ]
    assert body["replayed"] is False
    assert body["provider"]["recorded"] is True
    assert body["check"]["check"]["name"] == "apiome/api-change"
    assert body["check"]["check"]["state"] == "pass"
    assert len(provider.calls) == 1


def test_an_empty_request_body_is_a_run_with_the_defaults(fake, provider, act_as):
    assert client.post(UNBOUND_SUITE).status_code == 201


def test_a_re_run_of_unchanged_inputs_is_a_200_replay_of_the_same_evaluation(
    fake, provider, act_as
):
    first = client.post(SUITE, json={}).json()
    again = client.post(SUITE, json={})
    assert again.status_code == 200
    assert again.json()["replayed"] is True
    assert again.json()["run"]["id"] == first["run"]["id"]
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    ("lint", "state"),
    [
        (LintFacts(grade="A", score=99), "pass"),
        (LintFacts(grade="F", score=9), "fail"),
    ],
)
def test_the_verdict_is_one_of_the_four_states(fake, provider, act_as, evidence, lint, state):
    evidence.lint = lint
    assert client.post(UNBOUND_SUITE, json={}).json()["run"]["state"] == state


def test_a_run_waiting_on_evidence_is_pending(fake, provider, act_as, evidence):
    evidence.broken = {"lint"}
    assert client.post(UNBOUND_SUITE, json={}).json()["run"]["state"] == "pending"


def test_a_policy_that_requires_nothing_skips(fake, provider, act_as):
    api_check_suite_policy_store.save_policy(
        TENANT,
        body={"components": {c: "advisory" for c in ("lint", "breaking", "consumers")}},
    )
    run = client.post(UNBOUND_SUITE, json={}).json()["run"]
    assert (run["state"], run["reason"]) == ("skipped", "no-required-components")


def test_the_drill_down_names_the_evidence_and_the_policy_behind_a_failure(
    fake, provider, act_as, evidence
):
    evidence.breaking = Classification(
        facts=BreakingFacts(
            baseline_revision_id="b1",
            baseline_label="1.0.0",
            max_severity="breaking",
            counts={"breaking": 1},
            breaking_changes=[
                {"pointer": "/paths/~1pets", "ruleId": "path-removed", "summary": "Path removed"}
            ],
        )
    )
    run = client.post(SUITE, json={}).json()["run"]
    drill = client.get(f"{PROJECT_BASE}/check-suite/runs/{run['id']}")
    assert drill.status_code == 200
    breaking = next(c for c in drill.json()["run"]["components"] if c["component"] == "breaking")
    assert breaking["state"] == "fail"
    assert breaking["reason"] == "breaking-changes-present"
    assert breaking["evidence"]["baselineRevisionId"] == "b1"
    assert breaking["evidence"]["breakingChanges"][0]["ruleId"] == "path-removed"
    assert breaking["link"].endswith(f"/{VERSION}/breaking-publish-guardrail")
    assert breaking["rule"] == {
        "requirement": "required",
        "thresholdsFrom": "deploy-gate-policy",
        "thresholds": {"warnAtSeverity": None, "failAtSeverity": "breaking"},
    }
    assert drill.json()["run"]["policy_source"] == "default"


def test_a_commit_on_an_unbound_version_is_a_conflict(fake, provider, act_as):
    response = client.post(UNBOUND_SUITE, json={"commit_sha": COMMIT})
    assert response.status_code == 409
    assert _code(response) == "check-suite-not-bound"


def test_a_commit_the_binding_never_saw_is_a_conflict(fake, provider, act_as):
    response = client.post(SUITE, json={"commit_sha": "d" * 40})
    assert response.status_code == 409
    assert _code(response) == "check-suite-commit-unknown"


def test_a_commit_that_is_not_an_object_id_is_refused(fake, provider, act_as):
    response = client.post(SUITE, json={"commit_sha": "main"})
    assert response.status_code == 422
    assert _code(response) == "check-suite-invalid-commit"


def test_a_credential_in_the_body_is_refused_by_the_schema(fake, provider, act_as):
    assert client.post(SUITE, json={"token": TOKEN}).status_code == 422


def test_an_unknown_version_is_not_found(fake, provider, act_as):
    response = client.post(f"{PROJECT_BASE}/versions/9.9.9/check-suite", json={})
    assert response.status_code == 404
    assert _code(response) == "check-suite-version-not-found"


def test_running_the_suite_needs_versions_edit(fake, provider, act_as):
    fake.grants = {("projects", "view")}
    act_as(BOB)
    assert client.post(SUITE, json={}).status_code == 403


# ---------------------------------------------------------------------------------------------
# Reading it
# ---------------------------------------------------------------------------------------------


def test_a_version_never_evaluated_is_not_found_with_its_code(fake, provider, act_as):
    response = client.get(SUITE)
    assert response.status_code == 404
    assert _code(response) == "check-suite-not-run"


def test_the_latest_evaluation_says_whether_it_still_describes_the_draft(
    fake, provider, act_as, evidence
):
    client.post(SUITE, json={})
    assert client.get(SUITE).json()["stale"] is False
    evidence.document["info"]["title"] = "edited"
    assert client.get(SUITE).json()["stale"] is True
    assert client.get(SUITE, params={"commit_sha": COMMIT}).status_code == 200


def test_a_versions_evaluations_are_listed_newest_first(fake, provider, act_as, evidence):
    first = client.post(UNBOUND_SUITE, json={}).json()["run"]["id"]
    evidence.lint = LintFacts(grade="F", score=1)
    second = client.post(UNBOUND_SUITE, json={}).json()["run"]["id"]
    page = client.get(f"{UNBOUND_SUITE}/runs").json()
    assert [run["id"] for run in page["runs"]] == [second, first]
    assert page["count"] == 2


def test_an_evaluation_is_not_readable_through_another_project(fake, provider, act_as):
    run_id = client.post(SUITE, json={}).json()["run"]["id"]
    response = client.get(f"/v1/tenants/acme/projects/orders/check-suite/runs/{run_id}")
    assert response.status_code == 404
    assert _code(response) == "check-suite-run-not-found"


def test_reading_needs_projects_view(fake, provider, act_as):
    client.post(SUITE, json={})
    fake.grants = set()
    act_as(BOB)
    assert client.get(SUITE).status_code == 403


def test_a_reader_without_the_consumer_registry_gets_the_verdict_and_not_the_names(
    fake, provider, act_as, evidence
):
    evidence.breaking = Classification(
        facts=BreakingFacts(
            baseline_revision_id="b1", max_severity="breaking", counts={"breaking": 1}
        ),
        diff=object(),
    )
    evidence.consumers = ConsumerImpactReport(
        summary="breaks 1 of 2 consumers: billing-service",
        counts={"consumers_total": 2, "consumers_breaking": 1, "consumers_affected": 1},
        breaking_consumers=["billing-service"],
    )
    client.post(SUITE, json={})
    fake.grants = {("projects", "view")}
    act_as(BOB)
    body = client.get(SUITE).json()
    assert body["run"]["state"] == "fail"
    assert "billing-service" not in json.dumps(body)


# ---------------------------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------------------------


def test_the_default_policy_is_readable_before_anything_is_saved(fake, provider, act_as):
    policy = client.get(TENANT_POLICY).json()
    assert policy["source"] == "default"
    assert policy["policy"]["components"]["lint"] == "required"
    assert policy["policy"]["requiredForPublish"] is False


def test_a_tenant_administrator_can_require_the_suite_before_publish(fake, provider, act_as):
    response = client.put(
        TENANT_POLICY, json={"requiredForPublish": True, "components": {"contract": "required"}}
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["source"] == "tenant"
    assert saved["policy"]["requiredForPublish"] is True
    assert saved["policy"]["components"]["contract"] == "required"
    (audit,) = [row for row in fake.audits if row.get("action") == "governance.check_suite_policy.update"]
    assert audit["detail"]["policy"]["requiredForPublish"] is True


def test_a_project_override_wins_and_clearing_it_falls_back(fake, provider, act_as):
    client.put(TENANT_POLICY, json={"components": {"sdk": "required"}})
    client.put(PROJECT_POLICY, json={"components": {"sdk": "off"}})
    assert client.get(PROJECT_POLICY).json()["source"] == "project"
    cleared = client.delete(PROJECT_POLICY).json()
    assert cleared["source"] == "tenant"
    assert cleared["policy"]["components"]["sdk"] == "required"
    assert client.delete(TENANT_POLICY).json()["source"] == "default"


def test_an_incoherent_policy_is_refused_with_every_problem(fake, provider, act_as):
    response = client.put(TENANT_POLICY, json={"components": {"lint": "sometimes", "nope": "off"}})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "check-suite-policy-invalid"
    assert len(response.json()["detail"]["errors"]) == 2


def test_only_a_signed_in_administrator_may_change_the_policy(fake, provider, act_as):
    act_as(BOB)
    assert client.put(TENANT_POLICY, json={}).status_code == 403
    assert client.put(PROJECT_POLICY, json={}).status_code == 403
    act_as(ALICE, method="api_key")
    assert client.put(TENANT_POLICY, json={}).status_code == 403
    assert fake.suite_policies == {}


def test_a_policy_for_an_unknown_project_is_not_found(fake, provider, act_as):
    response = client.put("/v1/tenants/acme/projects/nope/check-suite-policy", json={})
    assert response.status_code == 404


# ---------------------------------------------------------------------------------------------
# CI keys and the published contract
# ---------------------------------------------------------------------------------------------


def test_a_ci_read_key_may_read_the_latest_evaluation_but_never_run_the_suite():
    path = "/v1/tenants/acme/projects/pets/versions/2.0.0/check-suite"
    assert acceptable_scopes_for_request("GET", path) == [
        API_KEY_SCOPE_DIFF_READ,
        API_KEY_SCOPE_LINT_READ,
    ]
    assert acceptable_scopes_for_request("POST", path) == []
    assert acceptable_scopes_for_request("GET", f"{path}/runs") == []


def _openapi() -> Dict[str, Any]:
    """The committed OpenAPI contract."""
    return json.loads(
        (Path(__file__).resolve().parents[1] / "openapi.json").read_text(encoding="utf-8")
    )


def test_the_suite_routes_are_in_the_published_contract():
    paths = _openapi()["paths"]
    base = "/v1/tenants/{tenant_slug}/projects/{project_ref}"
    assert {"get", "post"} <= set(paths[f"{base}/versions/{{version_ref}}/check-suite"])
    assert "get" in paths[f"{base}/versions/{{version_ref}}/check-suite/runs"]
    assert "get" in paths[f"{base}/check-suite/runs/{{run_id}}"]
    assert {"get", "put", "delete"} <= set(paths[f"{base}/check-suite-policy"])
    assert {"get", "put", "delete"} <= set(
        paths["/v1/tenants/{tenant_slug}/governance/check-suite-policy"]
    )


def test_no_suite_schema_offers_a_place_for_a_credential():
    schemas = _openapi()["components"]["schemas"]
    for name in ("CheckSuiteRunRecord", "CheckSuiteRunDetail", "CheckSuiteRunRequest", "SuiteComponent"):
        properties = schemas[name].get("properties", {})
        assert not {key for key in properties if "token" in key or "secret" in key}
