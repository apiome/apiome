"""The API change check suite rules — GNC-3.1 (#4740).

:mod:`app.api_check_suite` is the verdict as a pure function: five components' facts in, one of
``pending | pass | fail | skipped`` out. These tests pin the decisions that are easy to relax by
accident — the deploy-gate status mapping, what "required" means for missing evidence, the
aggregation precedence, the policy grammar, and the determinism of the fingerprint and the text a
reviewer reads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

from app.api_check_suite import (
    COMPONENT_BREAKING,
    COMPONENT_CONSUMERS,
    COMPONENT_CONTRACT,
    COMPONENT_LINT,
    COMPONENT_SDK,
    COMPONENTS,
    DEFAULT_POLICY,
    DEFAULT_REQUIREMENTS,
    MAX_LISTED_EVIDENCE,
    POLICY_SCHEMA_VERSION,
    REASON_COMPONENT_OFF,
    REASON_CONSUMERS_NO_BASELINE,
    REASON_CONTRACT_FAILED,
    REASON_CONTRACT_INCOMPLETE,
    REASON_CONTRACT_MISSING,
    REASON_CONTRACT_NOT_APPLICABLE,
    REASON_CONTRACT_PASSED,
    REASON_CONTRACT_STALE,
    REASON_DRAFT_NOT_SYNCHRONIZED,
    REASON_EVIDENCE_UNAVAILABLE,
    REASON_LINT_ERRORS,
    REASON_NO_CAPTURED_SOURCE,
    REASON_NO_REQUIRED,
    REASON_NOTHING_APPLIED,
    REASON_REQUIRED_FAILED,
    REASON_REQUIRED_PASSED,
    REASON_REQUIRED_PENDING,
    REASON_SDK_FAILED,
    REASON_SDK_GENERATED,
    REASON_SDK_NOT_APPLICABLE,
    REASON_SPEC_UNCHANGED,
    REQUIREMENT_ADVISORY,
    REQUIREMENT_OFF,
    REQUIREMENT_REQUIRED,
    SUITE_CHECK_NAME,
    BreakingFacts,
    CheckSuitePolicy,
    CheckSuitePolicyError,
    CheckSuiteRunRecord,
    ContractFacts,
    LintFacts,
    SdkFacts,
    SuiteComponent,
    aggregate,
    canonical_policy_body,
    component_counts,
    component_from_signal,
    disabled_component,
    input_fingerprint,
    judge_breaking,
    judge_consumers,
    judge_contract,
    judge_lint,
    judge_sdk,
    policy_fingerprint,
    policy_from_body,
    render_summary,
    render_title,
    requirements_fingerprint,
    unavailable_component,
    unbuildable_component,
)
from app.consumer_impact import ConsumerImpactReport
from app.deploy_gate import (
    DEFAULT_THRESHOLDS,
    REASON_BREAKING_INITIAL_PUBLICATION,
    REASON_BREAKING_NONE,
    REASON_BREAKING_PRESENT,
    REASON_CONSUMERS_BREAKING,
    REASON_CONSUMERS_NONE_REGISTERED,
    REASON_LINT_BELOW_FAIL,
    REASON_LINT_BELOW_WARN,
    REASON_LINT_NOT_CAPTURED,
    REASON_LINT_OK,
    STATUS_FAIL,
    STATUS_NOT_CONFIGURED,
    STATUS_PASS,
    STATUS_UNKNOWN,
    STATUS_WARN,
    BreakingThresholds,
    GateSignal,
)
from app.provider_checks import (
    DEFAULT_CHECK_NAME,
    MAX_SUMMARY_LENGTH,
    MAX_TITLE_LENGTH,
    STATE_FAIL,
    STATE_PASS,
    STATE_PENDING,
    STATE_SKIPPED,
)

LINK = "/v1/evidence"


def _component(component: str, state: str, requirement: str = REQUIREMENT_REQUIRED) -> SuiteComponent:
    """A minimal judged component."""
    return SuiteComponent(
        component=component,
        label=component,
        requirement=requirement,
        counted=requirement == REQUIREMENT_REQUIRED,
        state=state,
        reason="r",
        detail=f"{component} is {state}",
    )


def _signal(status: str, reason: str = "some-reason") -> GateSignal:
    """A CTG-4.5 gate signal in one status."""
    return GateSignal(
        signal="lint", status=status, reason=reason, detail="d", link=LINK, data={"k": 1}
    )


# ---------------------------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------------------------


def test_the_suite_reports_under_the_check_name_the_webhook_seeds():
    # The verdict must replace the pending check that appeared when the PR opened, not sit beside it.
    assert SUITE_CHECK_NAME == DEFAULT_CHECK_NAME == "apiome/api-change"


def test_the_default_policy_requires_what_the_draft_itself_proves():
    assert DEFAULT_POLICY.required_components() == [
        COMPONENT_LINT,
        COMPONENT_BREAKING,
        COMPONENT_CONSUMERS,
    ]
    assert DEFAULT_POLICY.requirement(COMPONENT_CONTRACT) == REQUIREMENT_ADVISORY
    assert DEFAULT_POLICY.requirement(COMPONENT_SDK) == REQUIREMENT_ADVISORY
    # Publishing is never gated until a tenant opts in.
    assert DEFAULT_POLICY.required_for_publish is False


def test_no_body_is_the_documented_default():
    assert policy_from_body(None) == DEFAULT_POLICY
    assert policy_from_body({}) == DEFAULT_POLICY


def test_a_body_naming_one_component_configures_exactly_that_one():
    policy = policy_from_body({"components": {"contract": "required"}})
    assert policy.requirement(COMPONENT_CONTRACT) == REQUIREMENT_REQUIRED
    for component in (COMPONENT_LINT, COMPONENT_BREAKING, COMPONENT_CONSUMERS, COMPONENT_SDK):
        assert policy.requirement(component) == DEFAULT_REQUIREMENTS[component]


@pytest.mark.parametrize("key", ["requiredForPublish", "required_for_publish"])
def test_required_for_publish_accepts_either_spelling(key):
    assert policy_from_body({key: True}).required_for_publish is True


def test_a_stored_canonical_body_parses_back_to_the_same_policy():
    policy = policy_from_body({"components": {"sdk": "off"}, "requiredForPublish": True})
    assert policy_from_body(canonical_policy_body(policy)) == policy


def test_every_problem_is_reported_at_once():
    with pytest.raises(CheckSuitePolicyError) as refused:
        policy_from_body(
            {
                "components": {"lnt": "required", "sdk": "mandatory"},
                "requiredForPublish": "yes",
                "gate": 1,
            }
        )
    errors = refused.value.errors
    assert len(errors) == 4
    assert any("components.lnt" in e for e in errors)
    assert any("components.sdk" in e and "mandatory" in e for e in errors)
    assert any("requiredForPublish" in e for e in errors)
    assert any("gate" in e for e in errors)


@pytest.mark.parametrize("body", [["lint"], "required", 3])
def test_a_body_that_is_not_an_object_is_refused(body):
    with pytest.raises(CheckSuitePolicyError):
        policy_from_body(body)  # type: ignore[arg-type]


def test_components_must_be_an_object():
    with pytest.raises(CheckSuitePolicyError) as refused:
        policy_from_body({"components": ["lint"]})
    assert "components must be an object" in refused.value.errors[0]


def test_a_publish_gate_that_can_never_block_is_refused():
    body = {
        "components": {component: "advisory" for component in COMPONENTS},
        "requiredForPublish": True,
    }
    with pytest.raises(CheckSuitePolicyError) as refused:
        policy_from_body(body)
    assert "at least one required component" in refused.value.errors[0]
    # The same components without the publish requirement are a coherent, advisory-only policy.
    assert policy_from_body({**body, "requiredForPublish": False}).required_components() == []


def test_the_canonical_body_names_every_component_and_the_schema():
    body = canonical_policy_body(policy_from_body({"components": {"sdk": "off"}}))
    assert body["schemaVersion"] == POLICY_SCHEMA_VERSION
    assert list(body["components"]) == list(COMPONENTS)
    assert body["components"]["sdk"] == REQUIREMENT_OFF
    assert body["requiredForPublish"] is False


def test_the_fingerprint_depends_on_meaning_not_spelling():
    partial = policy_from_body({"components": {"contract": "required"}})
    full = policy_from_body(canonical_policy_body(partial))
    assert policy_fingerprint(partial) == policy_fingerprint(full)
    assert policy_fingerprint(partial).startswith("sha256:")
    assert policy_fingerprint(partial) != policy_fingerprint(DEFAULT_POLICY)
    assert policy_fingerprint(
        policy_from_body({"requiredForPublish": True})
    ) != policy_fingerprint(DEFAULT_POLICY)


def test_the_requirements_fingerprint_ignores_what_cannot_change_a_verdict():
    armed = policy_from_body({"requiredForPublish": True})
    assert requirements_fingerprint(armed) == requirements_fingerprint(DEFAULT_POLICY)
    assert policy_fingerprint(armed) != policy_fingerprint(DEFAULT_POLICY)
    moved = policy_from_body({"components": {"sdk": "required"}})
    assert requirements_fingerprint(moved) != requirements_fingerprint(DEFAULT_POLICY)


# ---------------------------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------------------------


def test_a_switched_off_component_is_listed_skipped_and_uncounted():
    component = disabled_component(COMPONENT_SDK)
    assert component.state == STATE_SKIPPED
    assert component.reason == REASON_COMPONENT_OFF
    assert component.requirement == REQUIREMENT_OFF
    assert component.counted is False


@pytest.mark.parametrize(
    ("component", "subject"),
    [(COMPONENT_CONTRACT, "No contract suite"), (COMPONENT_SDK, "No client kit")],
)
def test_a_version_nothing_can_be_built_from_is_skipped_not_waited_on(component, subject):
    result = unbuildable_component(component, REQUIREMENT_REQUIRED, reason="no source", link=LINK)
    assert result.state == STATE_SKIPPED
    assert result.reason == REASON_NO_CAPTURED_SOURCE
    assert result.detail.startswith(subject)
    assert result.evidence == {"loader": "no source"}
    assert result.counted is True


def test_unreadable_evidence_is_pending_never_pass_or_fail():
    component = unavailable_component(COMPONENT_LINT, REQUIREMENT_REQUIRED, detail="gone")
    assert component.state == STATE_PENDING
    assert component.reason == REASON_EVIDENCE_UNAVAILABLE
    assert component.counted is True


@pytest.mark.parametrize(
    ("status", "state", "warned"),
    [
        (STATUS_PASS, STATE_PASS, False),
        (STATUS_WARN, STATE_PASS, True),
        (STATUS_FAIL, STATE_FAIL, False),
        (STATUS_NOT_CONFIGURED, STATE_SKIPPED, False),
        (STATUS_UNKNOWN, STATE_PENDING, False),
    ],
)
def test_gate_statuses_map_onto_the_four_check_states(status, state, warned):
    component = component_from_signal(COMPONENT_LINT, _signal(status), REQUIREMENT_REQUIRED)
    assert component.state == state
    assert component.warned is warned
    # The gate's own reason survives, so the PR and the deploy gate name a verdict the same way.
    assert component.reason == "some-reason"
    assert component.link == LINK


def test_a_translated_component_carries_the_gate_data_and_its_rule():
    component = component_from_signal(
        COMPONENT_LINT,
        _signal(STATUS_PASS),
        REQUIREMENT_ADVISORY,
        rule={"thresholds": {"x": 1}},
        evidence={"extra": 2},
    )
    assert component.evidence == {"k": 1, "extra": 2}
    assert component.rule == {"requirement": REQUIREMENT_ADVISORY, "thresholds": {"x": 1}}
    assert component.counted is False


def _lint(**overrides: Any) -> LintFacts:
    """Lint facts for a clean A-grade report, with overrides."""
    facts: Dict[str, Any] = {
        "grade": "A",
        "score": 95,
        "severity_counts": {"error": 0, "warning": 2},
        "error_findings": [],
        "guide": {"id": "g1", "name": "Acme guide"},
        "report_fingerprint": "sha256:report",
    }
    facts.update(overrides)
    return LintFacts(**facts)


def test_error_violations_fail_lint_whatever_the_grade():
    findings = [
        {"rule": f"rule-{i}", "path": f"/paths/{i}", "message": "bad"} for i in range(15)
    ]
    component = judge_lint(
        _lint(severity_counts={"error": 15}, error_findings=findings),
        thresholds=DEFAULT_THRESHOLDS.lint,
        requirement=REQUIREMENT_REQUIRED,
        link=LINK,
    )
    assert component.state == STATE_FAIL
    assert component.reason == REASON_LINT_ERRORS
    assert "15 error-severity violations under Acme guide" in component.detail
    assert component.evidence["errorCount"] == 15
    assert len(component.evidence["errorFindings"]) == MAX_LISTED_EVIDENCE
    assert component.rule["errorSeverityFails"] is True
    assert component.rule["thresholds"] == {"warnBelowGrade": "B", "failBelowGrade": "D"}


@pytest.mark.parametrize(
    ("grade", "state", "reason", "warned"),
    [
        ("A", STATE_PASS, REASON_LINT_OK, False),
        ("C", STATE_PASS, REASON_LINT_BELOW_WARN, True),
        ("F", STATE_FAIL, REASON_LINT_BELOW_FAIL, False),
        (None, STATE_SKIPPED, REASON_LINT_NOT_CAPTURED, False),
    ],
)
def test_without_errors_the_grade_is_judged_by_the_deploy_gate(grade, state, reason, warned):
    component = judge_lint(
        _lint(grade=grade),
        thresholds=DEFAULT_THRESHOLDS.lint,
        requirement=REQUIREMENT_REQUIRED,
        link=LINK,
    )
    assert (component.state, component.reason, component.warned) == (state, reason, warned)
    assert component.evidence["reportFingerprint"] == "sha256:report"
    assert component.evidence["guide"]["name"] == "Acme guide"


def _breaking_changes(count: int) -> List[Dict[str, str]]:
    """``count`` breaking changelog entries."""
    return [
        {"pointer": f"/paths/~1p{i}", "ruleId": "path-removed", "pathGroup": f"/p{i}", "summary": "gone"}
        for i in range(count)
    ]


def test_a_first_publication_has_no_contract_to_break():
    component = judge_breaking(
        BreakingFacts(baseline_revision_id=None),
        thresholds=DEFAULT_THRESHOLDS.breaking,
        requirement=REQUIREMENT_REQUIRED,
        link=LINK,
    )
    assert component.state == STATE_PASS
    assert component.reason == REASON_BREAKING_INITIAL_PUBLICATION


def test_no_changes_against_the_baseline_pass():
    component = judge_breaking(
        BreakingFacts(baseline_revision_id="b1", baseline_label="1.0.0"),
        thresholds=DEFAULT_THRESHOLDS.breaking,
        requirement=REQUIREMENT_REQUIRED,
        link=LINK,
    )
    assert (component.state, component.reason) == (STATE_PASS, REASON_BREAKING_NONE)


def test_a_breaking_change_fails_under_the_default_thresholds_and_is_listed():
    component = judge_breaking(
        BreakingFacts(
            baseline_revision_id="b1",
            baseline_label="1.0.0",
            max_severity="breaking",
            counts={"breaking": 12, "total": 12},
            breaking_changes=_breaking_changes(12),
        ),
        thresholds=DEFAULT_THRESHOLDS.breaking,
        requirement=REQUIREMENT_REQUIRED,
        link=LINK,
    )
    assert component.state == STATE_FAIL
    assert component.reason == REASON_BREAKING_PRESENT
    assert "against 1.0.0" in component.detail
    assert component.evidence["baselineRevisionId"] == "b1"
    assert len(component.evidence["breakingChanges"]) == MAX_LISTED_EVIDENCE
    assert component.evidence["breakingChangesTruncated"] is True


def test_moving_the_bar_moves_the_breaking_verdict_the_same_way_it_moves_the_gate():
    facts = BreakingFacts(
        baseline_revision_id="b1", max_severity="breaking", counts={"breaking": 1}
    )
    relaxed = judge_breaking(
        facts,
        thresholds=BreakingThresholds(fail_at_severity=None, warn_at_severity="breaking"),
        requirement=REQUIREMENT_REQUIRED,
        link=LINK,
    )
    assert relaxed.state == STATE_PASS
    assert relaxed.warned is True


def _report(total: int, breaking: List[str], affected: int = 0) -> ConsumerImpactReport:
    """A CTG-4.2 report with the given tallies."""
    return ConsumerImpactReport(
        summary=f"breaks {len(breaking)} of {total} consumers: {', '.join(breaking)}",
        counts={
            "consumers_total": total,
            "consumers_breaking": len(breaking),
            "consumers_affected": affected or len(breaking),
            "consumers_undeclared": 0,
        },
        breaking_consumers=breaking,
    )


def test_without_a_baseline_nobody_can_be_a_consumer():
    component = judge_consumers(
        None, thresholds=DEFAULT_THRESHOLDS.consumers, requirement=REQUIREMENT_REQUIRED, link=LINK
    )
    assert (component.state, component.reason) == (STATE_SKIPPED, REASON_CONSUMERS_NO_BASELINE)


def test_no_registered_consumer_is_skipped_not_passed():
    component = judge_consumers(
        _report(0, []),
        thresholds=DEFAULT_THRESHOLDS.consumers,
        requirement=REQUIREMENT_REQUIRED,
        link=LINK,
    )
    assert (component.state, component.reason) == (STATE_SKIPPED, REASON_CONSUMERS_NONE_REGISTERED)


def test_a_broken_consumer_fails_and_is_named():
    names = [f"svc-{i}" for i in range(12)]
    component = judge_consumers(
        _report(20, names),
        thresholds=DEFAULT_THRESHOLDS.consumers,
        requirement=REQUIREMENT_REQUIRED,
        link=LINK,
    )
    assert component.state == STATE_FAIL
    assert component.reason == REASON_CONSUMERS_BREAKING
    assert component.evidence["breakingConsumers"] == names[:MAX_LISTED_EVIDENCE]
    assert component.evidence["breakingConsumersTruncated"] is True


def _run(**overrides: Any) -> Dict[str, Any]:
    """A contract run summary."""
    run = {
        "id": "run-1",
        "outcome": "passed",
        "suiteDigest": "sha256:suite",
        "reference": "project/pets/2.0.0",
        "targetSlug": "staging",
        "finishedAt": "2026-09-17T00:00:00+00:00",
        "cases": {"total": 4, "passed": 4, "failed": 0, "errored": 0, "skipped": 0},
    }
    run.update(overrides)
    return run


def test_a_version_without_operations_has_no_contract():
    component = judge_contract(
        ContractFacts(applicable=False), requirement=REQUIREMENT_REQUIRED, link=LINK
    )
    assert (component.state, component.reason) == (STATE_SKIPPED, REASON_CONTRACT_NOT_APPLICABLE)


@pytest.mark.parametrize(
    ("requirement", "state"),
    [(REQUIREMENT_REQUIRED, STATE_PENDING), (REQUIREMENT_ADVISORY, STATE_SKIPPED)],
)
def test_missing_contract_evidence_holds_a_required_suite_and_skips_an_advisory_one(
    requirement, state
):
    component = judge_contract(ContractFacts(applicable=True), requirement=requirement, link=LINK)
    assert (component.state, component.reason) == (state, REASON_CONTRACT_MISSING)


@pytest.mark.parametrize("current", ["sha256:other", None])
def test_a_run_of_a_suite_this_draft_no_longer_compiles_to_is_stale(current):
    component = judge_contract(
        ContractFacts(applicable=True, run=_run(), current_digest=current),
        requirement=REQUIREMENT_REQUIRED,
        link=LINK,
    )
    assert (component.state, component.reason) == (STATE_PENDING, REASON_CONTRACT_STALE)
    assert component.evidence["runId"] == "run-1"
    assert component.evidence["currentSuiteDigest"] == current


def test_a_current_passing_run_passes_and_cites_the_run():
    component = judge_contract(
        ContractFacts(applicable=True, run=_run(), current_digest="sha256:suite"),
        requirement=REQUIREMENT_REQUIRED,
        link=LINK,
    )
    assert (component.state, component.reason) == (STATE_PASS, REASON_CONTRACT_PASSED)
    assert "against staging: 4 of 4 cases passed" in component.detail
    assert component.evidence["suiteDigest"] == "sha256:suite"


@pytest.mark.parametrize("outcome", ["failed", "errored"])
def test_a_current_failing_run_fails(outcome):
    component = judge_contract(
        ContractFacts(applicable=True, run=_run(outcome=outcome), current_digest="sha256:suite"),
        requirement=REQUIREMENT_ADVISORY,
        link=LINK,
    )
    assert (component.state, component.reason) == (STATE_FAIL, REASON_CONTRACT_FAILED)
    assert component.counted is False


def test_a_cancelled_run_is_no_verdict():
    component = judge_contract(
        ContractFacts(applicable=True, run=_run(outcome="cancelled"), current_digest="sha256:suite"),
        requirement=REQUIREMENT_REQUIRED,
        link=LINK,
    )
    assert (component.state, component.reason) == (STATE_PENDING, REASON_CONTRACT_INCOMPLETE)


def _sdk(**overrides: Any) -> SdkFacts:
    """SDK facts for a kit that generated completely."""
    facts: Dict[str, Any] = {
        "operation_count": 3,
        "total_operation_count": 3,
        "kit_digest": "sha256:kit",
        "go_package": "pets",
        "file_count": 20,
    }
    facts.update(overrides)
    return SdkFacts(**facts)


def test_an_api_without_callable_operations_has_no_sdk():
    component = judge_sdk(
        _sdk(operation_count=0, total_operation_count=2),
        requirement=REQUIREMENT_REQUIRED,
        link=LINK,
    )
    assert (component.state, component.reason) == (STATE_SKIPPED, REASON_SDK_NOT_APPLICABLE)


def test_a_generator_failure_fails_the_sdk_and_names_every_one():
    component = judge_sdk(
        _sdk(go_client_error="ValueError: bad", server_stub_error="KeyError: x"),
        requirement=REQUIREMENT_REQUIRED,
        link=LINK,
    )
    assert (component.state, component.reason) == (STATE_FAIL, REASON_SDK_FAILED)
    assert "Go client: ValueError: bad" in component.detail
    assert "server stubs: KeyError: x" in component.detail


def test_a_generated_kit_passes_and_cites_its_digest():
    component = judge_sdk(_sdk(), requirement=REQUIREMENT_REQUIRED, link=LINK)
    assert (component.state, component.reason, component.warned) == (
        STATE_PASS,
        REASON_SDK_GENERATED,
        False,
    )
    assert component.evidence["kitDigest"] == "sha256:kit"


def test_operations_without_a_binding_are_a_caveat_not_a_failure():
    component = judge_sdk(
        _sdk(total_operation_count=5, skipped_operations=2), requirement=REQUIREMENT_REQUIRED, link=LINK
    )
    assert component.state == STATE_PASS
    assert component.warned is True
    assert "2 operations without an HTTP binding" in component.detail


# ---------------------------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------------------------


def test_one_required_failure_fails_the_suite():
    state, reason = aggregate(
        [
            _component("lint", STATE_PASS),
            _component("breaking", STATE_PENDING),
            _component("consumers", STATE_FAIL),
        ]
    )
    assert (state, reason) == (STATE_FAIL, REASON_REQUIRED_FAILED)


def test_an_unfinished_required_component_holds_the_suite():
    state, reason = aggregate([_component("lint", STATE_PASS), _component("breaking", STATE_PENDING)])
    assert (state, reason) == (STATE_PENDING, REASON_REQUIRED_PENDING)


def test_advisory_components_never_decide():
    state, reason = aggregate(
        [
            _component("lint", STATE_PASS),
            _component("contract", STATE_FAIL, REQUIREMENT_ADVISORY),
            _component("sdk", STATE_PENDING, REQUIREMENT_ADVISORY),
        ]
    )
    assert (state, reason) == (STATE_PASS, REASON_REQUIRED_PASSED)


def test_a_skipped_required_component_does_not_spoil_a_pass():
    state, _reason = aggregate([_component("lint", STATE_PASS), _component("consumers", STATE_SKIPPED)])
    assert state == STATE_PASS


def test_a_set_of_skips_is_a_skip_never_a_hollow_pass():
    state, reason = aggregate(
        [_component("lint", STATE_SKIPPED), _component("sdk", STATE_PASS, REQUIREMENT_ADVISORY)]
    )
    assert (state, reason) == (STATE_SKIPPED, REASON_NOTHING_APPLIED)


def test_a_policy_requiring_nothing_is_skipped():
    state, reason = aggregate([_component("lint", STATE_PASS, REQUIREMENT_ADVISORY)])
    assert (state, reason) == (STATE_SKIPPED, REASON_NO_REQUIRED)


def test_counts_tally_only_the_required_components():
    components = [
        _component("lint", STATE_PASS),
        _component("breaking", STATE_FAIL),
        _component("contract", STATE_FAIL, REQUIREMENT_ADVISORY),
    ]
    assert component_counts(components) == {
        "required": 2,
        STATE_PASS: 1,
        STATE_FAIL: 1,
        STATE_PENDING: 0,
        STATE_SKIPPED: 0,
    }
    # Stored dicts count the same as models.
    assert component_counts([c.model_dump() for c in components]) == component_counts(components)


def _fingerprint(**overrides: Any) -> str:
    """The fingerprint of a baseline evaluation, with overrides."""
    args: Dict[str, Any] = {
        "version_id": "v1",
        "draft_digest": "sha256:d",
        "binding_id": "b1",
        "commit_sha": "abc1234",
        "check_name": SUITE_CHECK_NAME,
        "evaluated": True,
        "state": STATE_PASS,
        "reason": REASON_REQUIRED_PASSED,
        "policy_fingerprint_value": "sha256:p",
        "thresholds_fingerprint": "sha256:t",
        "components": [_component("lint", STATE_PASS)],
    }
    args.update(overrides)
    return input_fingerprint(**args)


def test_the_same_inputs_fingerprint_the_same():
    assert _fingerprint() == _fingerprint()
    assert _fingerprint().startswith("sha256:")


@pytest.mark.parametrize(
    "override",
    [
        {"draft_digest": "sha256:edited"},
        {"commit_sha": "def5678"},
        {"policy_fingerprint_value": "sha256:moved"},
        {"thresholds_fingerprint": "sha256:moved"},
        {"binding_id": None},
        {"evaluated": False},
        {"components": [_component("lint", STATE_FAIL)]},
    ],
)
def test_any_input_that_could_change_the_verdict_changes_the_fingerprint(override):
    assert _fingerprint(**override) != _fingerprint()


def test_new_evidence_behind_an_unchanged_verdict_is_a_new_evaluation():
    before = _component("contract", STATE_PASS).model_copy(update={"evidence": {"runId": "r1"}})
    after = before.model_copy(update={"evidence": {"runId": "r2"}})
    assert _fingerprint(components=[before]) != _fingerprint(components=[after])


# ---------------------------------------------------------------------------------------------
# What a reviewer reads
# ---------------------------------------------------------------------------------------------


def test_titles_name_what_decided_the_verdict():
    failing = [_component("Breaking changes", STATE_FAIL), _component("lint", STATE_PASS)]
    assert render_title(STATE_FAIL, REASON_REQUIRED_FAILED, failing) == (
        "API change check failed: breaking changes"
    )
    waiting = [_component("Contract tests", STATE_PENDING)]
    assert render_title(STATE_PENDING, REASON_REQUIRED_PENDING, waiting) == (
        "API change check waiting on: contract tests"
    )
    passing = [_component("lint", STATE_PASS), _component("consumers", STATE_SKIPPED)]
    assert render_title(STATE_PASS, REASON_REQUIRED_PASSED, passing) == (
        "API change check passed (1 of 2 required checks applied)"
    )
    assert "requires no check" in render_title(STATE_SKIPPED, REASON_NO_REQUIRED, [])
    assert "no required check applied" in render_title(STATE_SKIPPED, REASON_NOTHING_APPLIED, [])
    assert "catch up" in render_title(STATE_PENDING, REASON_DRAFT_NOT_SYNCHRONIZED, [])
    assert "does not touch the specification" in render_title(
        STATE_SKIPPED, REASON_SPEC_UNCHANGED, []
    )


def test_a_title_never_exceeds_what_a_provider_accepts():
    long = [_component("x" * 200, STATE_FAIL), _component("y" * 200, STATE_FAIL)]
    assert len(render_title(STATE_FAIL, REASON_REQUIRED_FAILED, long)) <= MAX_TITLE_LENGTH


def _summary(components: List[SuiteComponent], **overrides: Any) -> str:
    """Render a summary with sensible defaults."""
    args: Dict[str, Any] = {
        "run_id": "run-42",
        "state": STATE_FAIL,
        "reason": REASON_REQUIRED_FAILED,
        "components": components,
        "version_label": "2.0.0",
        "commit_sha": "0123456789abcdef0123",
        "draft_digest": "sha256:draft",
        "policy_source": "tenant",
        "policy_fingerprint_value": "sha256:pol",
        "thresholds_source": "default",
        "thresholds_fingerprint": "sha256:thr",
        "drill_down": "/v1/tenants/acme/projects/p/check-suite/runs/run-42",
    }
    args.update(overrides)
    return render_summary(**args)


def test_the_summary_is_the_verdict_and_everything_behind_it():
    breaking = judge_breaking(
        BreakingFacts(
            baseline_revision_id="b1",
            baseline_label="1.0.0",
            max_severity="breaking",
            counts={"breaking": 1},
            breaking_changes=[
                {"pointer": "/paths/~1pets|x", "ruleId": "path-removed", "summary": "Path removed"}
            ],
        ),
        thresholds=DEFAULT_THRESHOLDS.breaking,
        requirement=REQUIREMENT_REQUIRED,
        link=LINK,
    )
    lint = judge_lint(_lint(), thresholds=DEFAULT_THRESHOLDS.lint, requirement=REQUIREMENT_REQUIRED, link=LINK)
    summary = _summary([lint, breaking, disabled_component(COMPONENT_SDK)])
    assert summary.startswith("**API change check: fail** — version 2.0.0")
    assert "- **Breaking changes** fail:" in summary
    assert "| Check | Policy | Result | Why |" in summary
    assert "| Breaking changes | required | **fail** |" in summary
    assert "| SDK generation | off | skipped |" in summary
    # A pipe inside evidence cannot break the table or the list.
    assert "`/paths/~1pets\\|x`" in summary
    assert "Lint report `sha256:report`" in summary
    assert "at `0123456789ab`" in summary
    assert "suite policy (tenant, `sha256:pol`)" in summary
    assert "GET /v1/tenants/acme/projects/p/check-suite/runs/run-42" in summary


def test_the_summary_is_deterministic():
    components = [_component("lint", STATE_PASS)]
    assert _summary(components) == _summary(components)


def test_a_placeholder_explains_itself_instead_of_listing_components():
    waiting = _summary([], state=STATE_PENDING, reason=REASON_DRAFT_NOT_SYNCHRONIZED)
    assert "Synchronize the draft" in waiting
    assert "| Check |" not in waiting
    unchanged = _summary([], state=STATE_SKIPPED, reason=REASON_SPEC_UNCHANGED)
    assert "does not touch the API" in unchanged


def test_an_enormous_summary_is_truncated_with_a_pointer_to_the_drill_down():
    noisy = _component("lint", STATE_FAIL).model_copy(update={"detail": "x" * (MAX_SUMMARY_LENGTH * 2)})
    summary = _summary([noisy])
    assert len(summary) <= MAX_SUMMARY_LENGTH
    assert summary.endswith("read the full evaluation through the drill-down)")


def test_a_run_record_forbids_fields_it_does_not_declare():
    # No column that later grew a secret can arrive in a response by accident.
    with pytest.raises(Exception):
        CheckSuiteRunRecord(
            id="r",
            tenant_id="t",
            project_id="p",
            version_id="v",
            check_name=SUITE_CHECK_NAME,
            evaluated=True,
            state=STATE_PASS,
            reason=REASON_REQUIRED_PASSED,
            draft_digest="d",
            policy_source="default",
            policy_fingerprint="p",
            thresholds_source="default",
            thresholds_fingerprint="t",
            input_fingerprint="i",
            created_at=datetime.now(timezone.utc),
            token="ghp_secret",
        )


def test_a_policy_model_round_trips_through_camel_case():
    policy = CheckSuitePolicy(required_for_publish=True)
    dumped = policy.model_dump(by_alias=True)
    assert dumped["requiredForPublish"] is True
    assert CheckSuitePolicy.model_validate(dumped) == policy
