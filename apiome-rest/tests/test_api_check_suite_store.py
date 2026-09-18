"""Store rules for the API change check suite — GNC-3.1 (#4740).

What the pure rules cannot settle on their own: that an evaluation is recorded and then reported
through GNC-2.2, that re-running over unchanged inputs returns the same evaluation and costs the
provider nothing, that a commit the draft is not at gets an honest placeholder rather than a
borrowed verdict, that one unreadable component costs only itself, and that a reader who may not
see the consumer registry never sees a consumer's name.

The database is :class:`tests.fake_suite_db.FakeSuiteDb`; each component's evidence reader is a
double (their own reading is covered in ``test_api_check_suite_evidence.py``); the provider is an
in-memory HTTP double reached through the real status adapter.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from app import (
    api_check_suite_evidence,
    api_check_suite_policy_store,
    api_check_suite_store,
    comment_store,
    deploy_gate_store,
    draft_binding_store,
    git_import_routes,
    provider_check_store,
)
from app.api_check_suite import (
    AUDIT_SUITE_EVALUATED,
    CODE_COMMIT_UNKNOWN,
    CODE_INVALID_COMMIT,
    CODE_INVALID_DOCUMENT,
    CODE_NOT_BOUND,
    CODE_NOT_RUN,
    CODE_PROJECT_NOT_FOUND,
    CODE_RUN_NOT_FOUND,
    CODE_VERSION_NOT_FOUND,
    COMPONENT_CONSUMERS,
    COMPONENT_CONTRACT,
    COMPONENT_LINT,
    COMPONENT_SDK,
    REASON_COMPONENT_OFF,
    REASON_CONTRACT_MISSING,
    REASON_DRAFT_NOT_SYNCHRONIZED,
    REASON_EVIDENCE_UNAVAILABLE,
    REASON_NO_CAPTURED_SOURCE,
    REASON_REQUIRED_FAILED,
    REASON_REQUIRED_PASSED,
    REASON_REQUIRED_PENDING,
    REASON_SPEC_UNCHANGED,
    SUITE_CHECK_NAME,
    BreakingFacts,
    CheckSuiteError,
    CheckSuiteRunRequest,
    LintFacts,
)
from app.api_check_suite_evidence import Classification
from app.consumer_impact import ConsumerImpactReport
from app.export_source import ExportSourceError
from app.provider_checks import (
    AUDIT_CHECK_RECORDED,
    CODE_BINDING_RELEASED,
    OUTCOME_DISPATCHED,
    OUTCOME_FAILED,
    STATE_FAIL,
    STATE_PASS,
    STATE_PENDING,
    STATE_SKIPPED,
)
from tests.api_check_suite_doubles import Evidence, Provider, install_evidence
from tests.fake_suite_db import FakeSuiteDb

TENANT = "5c1e2f40-4444-4aaa-8bbb-000000000001"
PROJECT = "5c1e2f40-4444-4aaa-8bbb-000000000002"
OTHER_PROJECT = "5c1e2f40-4444-4aaa-8bbb-000000000003"
VERSION = "5c1e2f40-4444-4aaa-8bbb-000000000010"
UNBOUND = "5c1e2f40-4444-4aaa-8bbb-000000000011"
BASELINE = "5c1e2f40-4444-4aaa-8bbb-000000000012"
REPOSITORY = "5c1e2f40-4444-4aaa-8bbb-000000000020"
BINDING = "5c1e2f40-4444-4aaa-8bbb-000000000030"
ALICE = "5c1e2f40-4444-4aaa-8bbb-000000000101"

COMMIT_ONE = "1111111111111111111111111111111111111111"
COMMIT_TWO = "2222222222222222222222222222222222222222"
TOKEN = "ghp_a_real_looking_repository_token_0123456789"
SOURCE_DIGEST = "sha256:bound-selection"


@pytest.fixture
def provider(monkeypatch) -> Provider:
    """The provider, and the stored credential it is reached with."""
    monkeypatch.setattr(git_import_routes, "resolve_stored_git_token", lambda *a, **k: TOKEN)
    return Provider()


@pytest.fixture
def evidence(monkeypatch) -> Evidence:
    """The evidence doubles, swapped in beneath the gatherer."""
    return install_evidence(monkeypatch)


@pytest.fixture
def fake(monkeypatch, evidence) -> FakeSuiteDb:
    """A seeded store with one bound draft and one unbound one."""
    store = FakeSuiteDb()
    store.add_project(TENANT, PROJECT, "pets")
    store.add_project(TENANT, OTHER_PROJECT, "orders")
    store.add_version(PROJECT, VERSION, "2.0.0")
    store.add_version(PROJECT, UNBOUND, "3.0.0")
    store.add_repository(TENANT, REPOSITORY, clone_url="https://github.com/acme/specs", created_by=ALICE)
    store.add_member(ALICE, "Alice", "alice@example.com")
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
        "commit_sha": COMMIT_ONE,
        "source_digest": SOURCE_DIGEST,
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
        deploy_gate_store,
    ):
        monkeypatch.setattr(module, "db", store)
    return store


def _run(
    provider: Provider,
    version: str = "2.0.0",
    *,
    consumers_visible: bool = True,
    **body: Any,
):
    """Run the suite through the store."""
    return asyncio.run(
        api_check_suite_store.run_suite(
            tenant_id=TENANT,
            tenant_slug="acme",
            user_id=ALICE,
            project_ref="pets",
            version_ref=version,
            request=CheckSuiteRunRequest(**body),
            consumers_visible=consumers_visible,
            client_factory=provider.factory(),
        )
    )


def _code_of(call) -> str:
    """Run a store call that must refuse, and return the refusal code."""
    with pytest.raises(CheckSuiteError) as refused:
        call()
    return refused.value.code


def _actions(fake: FakeSuiteDb) -> List[str]:
    """The workflow-audit actions written so far, in order."""
    return [row["action"] for row in fake.workflow_audits]


def _set_policy(fake: FakeSuiteDb, body: Dict[str, Any]) -> None:
    """Save a tenant-wide suite policy."""
    api_check_suite_policy_store.save_policy(TENANT, body=body, actor_id=ALICE)


def _raise_candidate(fake: FakeSuiteDb, commit: str = COMMIT_TWO, **fields: Any) -> None:
    """Record that the bound branch moved to ``commit``."""
    fake.raise_binding_sync_candidate(
        tenant_id=TENANT, binding_id=BINDING, to_commit_sha=commit, origin="webhook"
    )
    if fields:
        for row in fake.candidates.values():
            if row["to_commit_sha"] == commit:
                row.update(fields)


# ---------------------------------------------------------------------------------------------
# Evaluating
# ---------------------------------------------------------------------------------------------


def test_an_unbound_draft_is_evaluated_and_recorded_without_a_provider(fake, provider):
    detail = _run(provider, "3.0.0")
    run = detail.run
    assert run.state == STATE_PASS
    assert run.reason == REASON_REQUIRED_PASSED
    assert run.evaluated is True
    assert run.binding_id is None and run.commit_sha is None
    assert [c.component for c in run.components] == [
        "lint",
        "breaking",
        "consumers",
        "contract",
        "sdk",
    ]
    assert detail.provider is None and detail.check is None
    assert detail.replayed is False
    assert provider.calls == []
    assert _actions(fake) == [AUDIT_SUITE_EVALUATED]


def test_the_evaluation_snapshots_both_policies_it_was_judged_under(fake, provider):
    _set_policy(fake, {"components": {"contract": "required"}})
    run = _run(provider, "3.0.0").run
    assert run.policy_source == "tenant"
    assert run.policy["components"]["contract"] == "required"
    assert run.policy_fingerprint.startswith("sha256:")
    assert run.thresholds_source == "default"
    assert run.thresholds["breaking"]["failAtSeverity"] == "breaking"


def test_re_running_unchanged_inputs_returns_the_same_evaluation(fake, provider):
    first = _run(provider, "3.0.0")
    second = _run(provider, "3.0.0")
    assert second.replayed is True
    assert second.run.id == first.run.id
    assert second.run.input_fingerprint == first.run.input_fingerprint
    assert len(fake.suite_runs) == 1
    assert _actions(fake).count(AUDIT_SUITE_EVALUATED) == 1


def test_new_evidence_is_a_new_evaluation(fake, provider, evidence):
    first = _run(provider, "3.0.0")
    evidence.lint = LintFacts(grade="F", score=12, report_fingerprint="sha256:worse")
    second = _run(provider, "3.0.0")
    assert second.replayed is False
    assert second.run.id != first.run.id
    assert second.run.state == STATE_FAIL
    assert second.run.reason == REASON_REQUIRED_FAILED
    assert len(fake.suite_runs) == 2


def test_an_edited_draft_is_a_new_evaluation(fake, provider, evidence):
    first = _run(provider, "3.0.0")
    evidence.document["info"]["title"] = "Pets, edited"
    second = _run(provider, "3.0.0")
    assert second.run.id != first.run.id
    assert second.run.draft_digest != first.run.draft_digest


def test_a_component_the_policy_switched_off_is_not_even_read(fake, provider, evidence):
    _set_policy(fake, {"components": {"sdk": "off", "contract": "off"}})
    run = _run(provider, "3.0.0").run
    sdk = next(c for c in run.components if c.component == COMPONENT_SDK)
    assert sdk.reason == REASON_COMPONENT_OFF
    assert evidence.calls["sdk"] == 0 and evidence.calls["contract"] == 0
    # With both model-backed components off, the canonical model is not loaded at all.
    assert evidence.calls["model"] == 0


def test_one_unreadable_component_costs_only_itself(fake, provider, evidence):
    evidence.broken = {"lint"}
    run = _run(provider, "3.0.0").run
    lint = next(c for c in run.components if c.component == COMPONENT_LINT)
    assert lint.state == STATE_PENDING
    assert lint.reason == REASON_EVIDENCE_UNAVAILABLE
    # The suite waits rather than passing on a check it could not make.
    assert run.state == STATE_PENDING
    assert run.reason == REASON_REQUIRED_PENDING
    # Every other component was still judged.
    assert all(
        c.reason != REASON_EVIDENCE_UNAVAILABLE for c in run.components if c.component != "lint"
    )


def test_a_failed_classification_costs_breaking_and_consumers_alike(fake, provider, evidence):
    evidence.broken = {"breaking"}
    run = _run(provider, "3.0.0").run
    unavailable = {c.component for c in run.components if c.reason == REASON_EVIDENCE_UNAVAILABLE}
    assert unavailable == {"breaking", "consumers"}


def test_an_unloadable_model_costs_contract_and_sdk_alike(fake, provider, evidence):
    evidence.broken = {"model"}
    run = _run(provider, "3.0.0").run
    unavailable = {c.component for c in run.components if c.reason == REASON_EVIDENCE_UNAVAILABLE}
    assert unavailable == {"contract", "sdk"}
    # Both are advisory by default, so the verdict stands on the required three.
    assert run.state == STATE_PASS


def test_a_version_with_no_captured_source_has_no_contract_or_sdk_to_check(
    fake, provider, evidence
):
    # Designed in the app rather than imported: no model, so no suite and no kit can exist. That is
    # a fact about the version, so the components are skipped — never left waiting forever.
    evidence.model_error = ExportSourceError("no captured source material", status_code=422)
    _set_policy(fake, {"components": {"sdk": "required"}})
    run = _run(provider, "3.0.0").run
    unbuildable = {c.component: c for c in run.components if c.reason == REASON_NO_CAPTURED_SOURCE}
    assert set(unbuildable) == {"contract", "sdk"}
    assert all(c.state == STATE_SKIPPED for c in unbuildable.values())
    assert unbuildable["sdk"].evidence["loader"] == "no captured source material"
    assert run.state == STATE_PASS


def test_a_model_that_is_missing_rather_than_unbuildable_is_unavailable(fake, provider, evidence):
    evidence.model_error = ExportSourceError("revision not found", status_code=404)
    run = _run(provider, "3.0.0").run
    unavailable = {c.component for c in run.components if c.reason == REASON_EVIDENCE_UNAVAILABLE}
    assert unavailable == {"contract", "sdk"}


def test_missing_contract_evidence_holds_the_suite_only_when_required(fake, provider):
    advisory = _run(provider, "3.0.0").run
    contract = next(c for c in advisory.components if c.component == COMPONENT_CONTRACT)
    assert (contract.state, contract.reason) == (STATE_SKIPPED, REASON_CONTRACT_MISSING)
    assert advisory.state == STATE_PASS

    _set_policy(fake, {"components": {"contract": "required"}})
    required = _run(provider, "3.0.0").run
    contract = next(c for c in required.components if c.component == COMPONENT_CONTRACT)
    assert contract.state == STATE_PENDING
    assert required.state == STATE_PENDING


def test_an_undrawable_draft_is_refused(fake, provider, evidence, monkeypatch):
    def broken(*_args: Any) -> Any:
        raise ValueError("no classes")

    monkeypatch.setattr(api_check_suite_store, "read_draft_document", broken)
    assert _code_of(lambda: _run(provider, "3.0.0")) == CODE_INVALID_DOCUMENT
    assert fake.suite_runs == {}


def test_unknown_projects_and_versions_are_refused(fake, provider):
    assert (
        _code_of(
            lambda: asyncio.run(
                api_check_suite_store.run_suite(
                    tenant_id=TENANT,
                    tenant_slug="acme",
                    user_id=ALICE,
                    project_ref="nope",
                    version_ref="1.0.0",
                    request=CheckSuiteRunRequest(),
                )
            )
        )
        == CODE_PROJECT_NOT_FOUND
    )
    assert _code_of(lambda: _run(provider, "9.9.9")) == CODE_VERSION_NOT_FOUND


# ---------------------------------------------------------------------------------------------
# Reporting on the pull request
# ---------------------------------------------------------------------------------------------


def test_a_bound_draft_reports_its_verdict_on_the_synchronized_commit(fake, provider):
    detail = _run(provider)
    run = detail.run
    assert run.binding_id == BINDING and run.commit_sha == COMMIT_ONE
    assert detail.provider.recorded is True
    check = detail.check.check
    assert check.name == SUITE_CHECK_NAME
    assert check.commit_sha == COMMIT_ONE
    assert check.state == run.state == STATE_PASS
    assert check.title == run.title
    # The drill-down: the published summary names the evaluation and how to read it.
    assert run.id in check.summary
    assert f"/v1/tenants/acme/projects/{PROJECT}/check-suite/runs/{run.id}" in check.summary
    assert detail.check.deliveries[0].outcome == OUTCOME_DISPATCHED
    assert len(provider.calls) == 1


def test_re_running_does_not_touch_a_provider_that_already_has_the_verdict(fake, provider):
    first = _run(provider)
    recorded = _actions(fake).count(AUDIT_CHECK_RECORDED)
    second = _run(provider)
    assert second.replayed is True
    assert second.check.check.id == first.check.check.id
    assert second.check.check.attempt == first.check.check.attempt
    assert len(provider.calls) == 1
    # Nothing moved, so nothing new is audited either.
    assert _actions(fake).count(AUDIT_CHECK_RECORDED) == recorded


def test_re_running_heals_a_publish_the_provider_refused(fake, provider):
    provider.status = 502
    first = _run(provider)
    assert first.check.deliveries[0].outcome == OUTCOME_FAILED
    provider.status = 201
    second = _run(provider)
    assert second.replayed is True
    assert second.check.deliveries[0].outcome == OUTCOME_DISPATCHED
    assert len(provider.calls) == 2


def test_a_new_verdict_moves_the_one_check_on_the_pull_request(fake, provider, evidence):
    first = _run(provider)
    evidence.lint = LintFacts(grade="F", score=3, report_fingerprint="sha256:worse")
    second = _run(provider)
    assert second.check.check.id == first.check.check.id
    assert second.check.check.state == STATE_FAIL
    assert len(fake.check_runs) == 1


def test_publish_false_records_the_check_without_sending_it(fake, provider):
    detail = _run(provider, publish=False)
    assert detail.provider.recorded is True
    assert detail.check.check.state == STATE_PASS
    assert provider.calls == []


def test_a_de_registered_repository_keeps_the_evaluation_and_says_why_nothing_was_sent(
    fake, provider
):
    fake.bindings[BINDING]["repository_id"] = None
    detail = _run(provider)
    assert detail.run.state == STATE_PASS
    assert detail.provider.recorded is False
    assert detail.provider.reason == CODE_BINDING_RELEASED
    assert detail.check is None
    assert provider.calls == []


def test_the_pull_request_number_reaches_the_check(fake, provider):
    detail = _run(provider, pr_number=17)
    assert detail.run.pr_number == 17
    assert detail.check.check.pr_number == 17


# ---------------------------------------------------------------------------------------------
# Which commit
# ---------------------------------------------------------------------------------------------


def test_naming_the_synchronized_commit_or_a_prefix_of_it_evaluates_the_draft(fake, provider):
    full = _run(provider, commit_sha=COMMIT_ONE)
    short = _run(provider, commit_sha=COMMIT_ONE[:9].upper())
    assert full.run.evaluated and short.run.evaluated
    assert short.run.commit_sha == COMMIT_ONE
    assert short.replayed is True


def test_a_commit_the_draft_has_not_caught_up_with_waits(fake, provider):
    _raise_candidate(fake)
    detail = _run(provider, commit_sha=COMMIT_TWO)
    run = detail.run
    assert run.evaluated is False
    assert (run.state, run.reason) == (STATE_PENDING, REASON_DRAFT_NOT_SYNCHRONIZED)
    assert run.components == []
    assert detail.check.check.commit_sha == COMMIT_TWO
    assert detail.check.check.state == STATE_PENDING
    assert "catch up" in detail.check.check.title


def test_a_commit_that_leaves_the_specification_alone_is_skipped(fake, provider):
    _raise_candidate(fake, to_digest=SOURCE_DIGEST)
    detail = _run(provider, commit_sha=COMMIT_TWO)
    assert (detail.run.state, detail.run.reason) == (STATE_SKIPPED, REASON_SPEC_UNCHANGED)
    assert detail.check.check.state == STATE_SKIPPED


def test_an_unread_candidate_is_read_through_the_binding_to_prove_it_unchanged(
    fake, provider, monkeypatch
):
    _raise_candidate(fake)
    reads: List[Any] = []

    def read_source(tenant_id, user_id, **kwargs):
        reads.append(kwargs)
        return SimpleNamespace(digest=SOURCE_DIGEST)

    monkeypatch.setattr(api_check_suite_store, "read_source", read_source)
    detail = _run(provider, commit_sha=COMMIT_TWO)
    assert detail.run.reason == REASON_SPEC_UNCHANGED
    assert reads == [
        {
            "repo_url": "https://github.com/acme/specs",
            "ref": COMMIT_TWO,
            "path": "spec",
            "repository_id": REPOSITORY,
        }
    ]


def test_a_commit_that_cannot_be_read_waits_rather_than_guesses(fake, provider, monkeypatch):
    _raise_candidate(fake)

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("provider down")

    monkeypatch.setattr(api_check_suite_store, "read_source", refuse)
    assert _run(provider, commit_sha=COMMIT_TWO).run.reason == REASON_DRAFT_NOT_SYNCHRONIZED


def test_a_commit_the_binding_never_saw_is_refused(fake, provider):
    assert _code_of(lambda: _run(provider, commit_sha="abcdef1234567")) == CODE_COMMIT_UNKNOWN


def test_an_unbound_draft_takes_no_commit(fake, provider):
    assert _code_of(lambda: _run(provider, "3.0.0", commit_sha=COMMIT_ONE)) == CODE_NOT_BOUND


def test_a_commit_that_is_not_an_object_id_is_refused(fake, provider):
    assert _code_of(lambda: _run(provider, commit_sha="main")) == CODE_INVALID_COMMIT


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


def _latest(**kwargs: Any):
    """The latest evaluation of the bound draft."""
    return api_check_suite_store.latest_run(TENANT, "acme", "pets", "2.0.0", **kwargs)


def test_a_version_never_evaluated_says_so(fake, provider):
    assert _code_of(lambda: _latest()) == CODE_NOT_RUN


def test_the_latest_evaluation_comes_with_its_check_and_is_fresh(fake, provider):
    run = _run(provider).run
    latest = _latest()
    assert latest.run.id == run.id
    assert latest.stale is False
    assert latest.check.check.commit_sha == COMMIT_ONE


def test_an_edit_or_a_moved_policy_makes_an_evaluation_stale(fake, provider, evidence):
    _run(provider)
    evidence.document["info"]["title"] = "edited"
    assert _latest().stale is True
    evidence.document["info"]["title"] = "Pets"
    assert _latest().stale is False
    _set_policy(fake, {"components": {"sdk": "required"}})
    assert _latest().stale is True


def test_the_latest_evaluation_at_a_commit(fake, provider):
    _run(provider)
    _raise_candidate(fake)
    _run(provider, commit_sha=COMMIT_TWO)
    assert _latest(commit_sha=COMMIT_ONE).run.evaluated is True
    assert _latest(commit_sha=COMMIT_TWO).run.evaluated is False


def test_one_evaluation_by_id_is_the_drill_down(fake, provider):
    run = _run(provider).run
    detail = api_check_suite_store.get_run(TENANT, "acme", "pets", run.id)
    assert detail.run.id == run.id
    assert detail.run.components == run.components


def test_an_evaluation_is_not_readable_through_another_project(fake, provider):
    run = _run(provider).run
    assert (
        _code_of(lambda: api_check_suite_store.get_run(TENANT, "acme", "orders", run.id))
        == CODE_RUN_NOT_FOUND
    )


def test_a_versions_evaluations_list_newest_first(fake, provider, evidence):
    first = _run(provider, "3.0.0").run
    evidence.lint = LintFacts(grade="F", score=1)
    second = _run(provider, "3.0.0").run
    page = api_check_suite_store.list_runs(TENANT, "acme", "pets", "3.0.0")
    assert [run.id for run in page.runs] == [second.id, first.id]
    assert api_check_suite_store.list_runs(TENANT, "acme", "pets", "3.0.0", limit=1, offset=1).runs[
        0
    ].id == first.id


# ---------------------------------------------------------------------------------------------
# Consumer names
# ---------------------------------------------------------------------------------------------


def _breaking_consumer(evidence: Evidence) -> None:
    """Make the draft break a named consumer."""
    evidence.breaking = Classification(
        facts=BreakingFacts(
            baseline_revision_id=BASELINE,
            baseline_label="1.0.0",
            max_severity="breaking",
            counts={"breaking": 1},
        ),
        diff=object(),
    )
    evidence.consumers = ConsumerImpactReport(
        summary="breaks 1 of 3 consumers: billing-service",
        counts={
            "consumers_total": 3,
            "consumers_breaking": 1,
            "consumers_affected": 1,
            "consumers_undeclared": 0,
        },
        breaking_consumers=["billing-service"],
    )


def test_a_reader_without_the_consumer_registry_never_sees_a_name(fake, provider, evidence):
    _breaking_consumer(evidence)
    visible = _run(provider)
    assert "billing-service" in visible.run.summary
    hidden = api_check_suite_store.latest_run(
        TENANT, "acme", "pets", "2.0.0", consumers_visible=False
    )
    consumers = next(c for c in hidden.run.components if c.component == COMPONENT_CONSUMERS)
    # Same verdict, fewer facts.
    assert hidden.run.state == visible.run.state == STATE_FAIL
    assert consumers.state == STATE_FAIL
    assert consumers.evidence["redacted"] is True
    assert "breakingConsumers" not in consumers.evidence
    assert "1 broken and 1 affected of 3 registered consumers" in consumers.detail
    assert "billing-service" not in json.dumps(hidden.model_dump(mode="json"))


def test_the_verdict_never_depends_on_who_ran_the_suite(fake, provider, evidence):
    _breaking_consumer(evidence)
    hidden = _run(provider, consumers_visible=False)
    visible = _run(provider)
    assert visible.replayed is True
    assert visible.run.id == hidden.run.id
