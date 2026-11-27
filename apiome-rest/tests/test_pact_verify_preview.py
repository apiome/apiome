"""What a hosted verification would do, before it runs — PFX-8.8 (#7305).

:func:`app.pact_verify_preview.preview_verification` with every store faked (the pacts are the
pact-js / pact-jvm / pact-go fixtures the verifier's own tests replay):

* the pacts listed are the ones the run would select, each with its interaction counts;
* each selector's own count, so the page can write it beside its sentence;
* already verified for this exact provider version → listed, and skipped only when asked;
* provider-state coverage for the registry, the setup URL and no setup;
* every reason the run would refuse is a refusal, never an error — mutating requests to a
  production target first;
* nothing is sent to any target.
"""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any, Dict, Optional
from unittest.mock import patch

import pytest

from app.pact_pending import NO_EVIDENCE
from app.pact_verifier import PactVerificationOptions
from app.pact_verifier_service import CODE_MUTATING_PRODUCTION, CODE_TOO_MANY_PACTS
from app.pact_verify_preview import (
    STRATEGY_NONE,
    STRATEGY_REGISTRY,
    STRATEGY_SETUP_URL,
    VerifyPreviewRequest,
    VerifyPreviewResponse,
    preview_verification,
)
from app.verification_result import VerificationResultRecord
from app.verification_target import CODE_NOT_FOUND, TargetValidationError, VerificationPolicy
from tests.pact_verifier_fakes import PACT_GO, PACT_JS, PACT_JVM
from tests.test_pact_verifier_service import _TENANT, _Broker, _registered

_MODULE = "app.pact_verify_preview"


class _Target:
    """The fields of a stored target the preview reads."""

    def __init__(self, environment: str = "staging", allow_mutating: bool = True) -> None:
        self.id = "22222222-2222-4222-8222-222222222222"
        self.slug = "ledger-staging"
        self.name = "Ledger staging"
        self.environment = environment
        self.enabled = True
        self.policy = VerificationPolicy(allow_mutating_methods=allow_mutating)


def _result(candidate: Any, *, version: str = "4f1e2d0", success: bool = True) -> VerificationResultRecord:
    return VerificationResultRecord(
        id="r-1",
        number=2,
        consumer_slug=candidate.consumer_slug,
        consumer_name=candidate.consumer_name,
        provider_slug="ledger-api",
        provider_name="Ledger API",
        provider_version=version,
        sha=candidate.sha,
        success=success,
        test_results=[],
        verified_by={},
    )


def _preview(
    broker: _Broker,
    *,
    target: Any = None,
    states: Any = (),
    latest: Optional[Dict[Any, Any]] = None,
    for_version: Optional[Dict[Any, Any]] = None,
    **body: Any,
) -> VerifyPreviewResponse:
    """Run the preview with the stores faked; fail the test if anything is sent anywhere."""
    request = VerifyPreviewRequest(**body)
    with ExitStack() as stack:
        stack.enter_context(patch(f"{_MODULE}.list_pact_candidates", side_effect=broker.list_pact_candidates))
        stack.enter_context(patch(f"{_MODULE}.get_pact_by_sha", side_effect=broker.get_pact_by_sha))
        stack.enter_context(patch(f"{_MODULE}.load_pending_evidence", return_value=NO_EVIDENCE))
        stack.enter_context(patch(f"{_MODULE}.list_states", return_value=list(states)))
        stack.enter_context(patch(f"{_MODULE}.latest_results_by_pact", return_value=dict(latest or {})))
        stack.enter_context(patch(f"{_MODULE}.results_for_provider_version", return_value=dict(for_version or {})))
        if isinstance(target, Exception):
            stack.enter_context(patch(f"{_MODULE}.get_target", side_effect=target))
        else:
            stack.enter_context(patch(f"{_MODULE}.get_target", return_value=target or _Target()))
        stack.enter_context(patch("app.contract_runner.build_guarded_client", side_effect=AssertionError("sent")))
        return preview_verification(None, _TENANT, "ledger-api", request)


def test_every_selected_pact_is_listed_with_its_interactions() -> None:
    broker = _Broker([PACT_JS, PACT_JVM, PACT_GO])
    preview = _preview(broker, target_ref="ledger-staging", provider_version="4f1e2d0")
    assert preview.selected == preview.will_run == 3 and preview.skipped == 0
    assert [pact.consumer for pact in preview.pacts] == [c.consumer_slug for c in broker.candidates]
    jvm = preview.pacts[1]
    assert (jvm.interactions, jvm.mutating_interactions) == (2, 1)
    # The run does not opt in to mutating requests, so POST /invoices would be held back.
    assert jvm.held_back >= 1
    assert preview.interactions == sum(pact.interactions for pact in preview.pacts)
    assert preview.refusals == [] and preview.target is not None and preview.target.production is False


def test_each_rule_is_counted_on_its_own() -> None:
    broker = _Broker([PACT_JS, PACT_JVM, PACT_GO], branches={PACT_JVM: ("feat-x",)})
    selectors = [{"mainBranch": True}, {"branch": "feat-x"}, {"branch": "nowhere"}]
    preview = _preview(broker, selection={"consumerVersionSelectors": selectors})
    assert [(rule.index, rule.pacts) for rule in preview.rules] == [(0, 2), (1, 1), (2, 0)]
    assert preview.rules[1].selector == {"branch": "feat-x"}
    assert preview.selected == 3


def test_already_verified_is_shown_and_skipped_only_when_asked() -> None:
    broker = _Broker([PACT_JS, PACT_GO])
    first = broker.candidates[0]
    found = {(first.consumer_id, first.sha): _result(first)}
    shown = _preview(broker, provider_version="4f1e2d0", for_version=found, latest=found)
    assert [pact.already_verified for pact in shown.pacts] == [True, False]
    assert shown.will_run == 2 and shown.pacts[0].last_result is not None
    assert shown.pacts[0].last_result.provider_version == "4f1e2d0"

    skipped = _preview(broker, provider_version="4f1e2d0", for_version=found, skip_already_verified=True)
    assert (skipped.will_run, skipped.skipped) == (1, 1)
    assert [pact.will_run for pact in skipped.pacts] == [False, True]
    assert skipped.interactions == skipped.pacts[1].interactions


def test_without_a_provider_version_nothing_is_already_verified() -> None:
    broker = _Broker([PACT_JS])
    with patch(f"{_MODULE}.results_for_provider_version") as lookup:
        preview = _preview(broker, skip_already_verified=True)
    lookup.assert_not_called()
    assert preview.pacts[0].already_verified is False


def test_registry_coverage_names_the_missing_states() -> None:
    broker = _Broker([PACT_JS])
    preview = _preview(broker, states=[_registered("some other state")])
    assert preview.states.strategy == STRATEGY_REGISTRY
    assert (preview.states.used, preview.states.handled, preview.states.missing) == (1, 0, ["invoice 1042 exists"])
    assert preview.states.registered == 1
    assert preview.pacts[0].held_back == 1

    covered = _preview(broker, states=[_registered()])
    assert (covered.states.handled, covered.states.missing) == (1, [])
    assert covered.pacts[0].held_back == 0


def test_the_setup_url_covers_every_state_unless_the_target_forbids_the_post() -> None:
    broker = _Broker([PACT_JS])
    url = PactVerificationOptions(provider_states_setup_url="/_pact/states")
    covered = _preview(broker, target_ref="t", verification=url)
    assert (covered.states.strategy, covered.states.handled, covered.states.missing) == (STRATEGY_SETUP_URL, 1, [])

    blocked = _preview(broker, target_ref="t", verification=url, target=_Target(allow_mutating=False))
    assert blocked.states.missing == ["invoice 1042 exists"] and blocked.pacts[0].held_back == 1


def test_no_setup_replays_as_is_and_reports_every_state_unhandled() -> None:
    broker = _Broker([PACT_JS])
    preview = _preview(broker, verification=PactVerificationOptions(replay_without_state_setup=True))
    assert preview.states.strategy == STRATEGY_NONE
    assert preview.states.missing == ["invoice 1042 exists"]
    assert preview.pacts[0].held_back == 0


def test_mutating_on_a_production_target_is_a_refusal() -> None:
    broker = _Broker([PACT_JVM])
    preview = _preview(
        broker,
        target_ref="prod",
        target=_Target(environment="production"),
        verification=PactVerificationOptions(allow_mutating=True),
    )
    assert preview.target is not None and preview.target.production is True
    assert [refusal.code for refusal in preview.refusals] == [CODE_MUTATING_PRODUCTION]
    assert "never sent to a production target" in preview.refusals[0].message


def test_a_production_target_read_only_is_fine() -> None:
    preview = _preview(_Broker([PACT_JVM]), target_ref="prod", target=_Target(environment="production"))
    assert preview.refusals == []


def test_an_unknown_target_is_a_refusal_and_the_pacts_are_still_listed() -> None:
    broker = _Broker([PACT_JS])
    preview = _preview(broker, target_ref="nope", target=TargetValidationError(CODE_NOT_FOUND, "no target 'nope'"))
    assert [refusal.code for refusal in preview.refusals] == [CODE_NOT_FOUND]
    assert preview.target is None and preview.selected == 1


def test_more_pacts_than_a_run_takes_is_a_refusal() -> None:
    with patch(f"{_MODULE}.MAX_PACTS_PER_RUN", 1):
        preview = _preview(_Broker([PACT_JS, PACT_GO]))
    assert [refusal.code for refusal in preview.refusals] == [CODE_TOO_MANY_PACTS]


@pytest.mark.parametrize("field, value", [("provider_version", "1.0\x07"), ("provider_branch", "main\x00")])
def test_a_malformed_version_or_branch_is_a_refusal(field: str, value: str) -> None:
    preview = _preview(_Broker([PACT_JS]), **{field: value})
    assert preview.refusals and preview.refusals[0].message


def test_a_long_selection_is_described_up_to_the_cap() -> None:
    broker = _Broker([PACT_JS, PACT_JVM, PACT_GO])
    with patch(f"{_MODULE}.MAX_PREVIEW_PACTS", 2):
        preview = _preview(broker)
    assert (len(preview.pacts), preview.selected, preview.truncated) == (2, 3, True)


def test_the_body_refuses_unknown_fields() -> None:
    with pytest.raises(ValueError):
        VerifyPreviewRequest(publish=True)  # type: ignore[call-arg]
