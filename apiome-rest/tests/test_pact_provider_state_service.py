"""Registering states and checking pacts against them — PFX-3.3 (#6933).

:mod:`app.pact_provider_state_service` with the stores faked:

* a state is checked before it is stored, and its overrides' targets are resolved **in the
  caller's tenant** — an unknown target is a ``provider-state-invalid`` at the override, and two
  references to one target are refused;
* the check selects the same pacts a run would, lists every state their interactions name
  (unregistered first) with the setup the chosen target would use, flags each problem once —
  per state for "not registered" and "setup blocked", per interaction for parameters — and is
  ``ready`` only when nothing blocks;
* it reports registered states no pact uses, refuses more pacts than a run takes, and sends
  nothing anywhere.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List
from unittest.mock import MagicMock, patch

import pytest

from app.consumer_contract_store import ConsumerActor
from app.pact_pending import NO_EVIDENCE
from app.pact_provider_state import (
    CODE_PARAM_MISSING,
    CODE_PARAM_UNDECLARED,
    CODE_SETUP_BLOCKED,
    CODE_STATE_INVALID,
    CODE_STATE_NOT_REGISTERED,
    ProviderStateInput,
    ProviderStateRecord,
    StateOverrideRecord,
    StateParameter,
    StateSetup,
)
from app.pact_provider_state_service import (
    StateCheckRequest,
    check_provider_states,
    register_provider_state,
    replace_provider_state,
)
from app.pact_publication import PactPublicationError
from app.pact_verifier_service import CODE_TOO_MANY_PACTS, PactVerifierError
from app.pacticipant import PacticipantRecord
from app.verification_target import CODE_NOT_FOUND, TargetValidationError, VerificationPolicy
from tests.pact_verifier_fakes import PACT_GO, PACT_JS, PACT_JVM
from tests.test_pact_verifier_service import _Broker

_SERVICE = "app.pact_provider_state_service"
_VERIFIER = "app.pact_verifier_service"
_TENANT = "11111111-1111-4111-8111-111111111111"
_TARGET_ID = "22222222-2222-4222-8222-222222222222"
_NOW = datetime(2026, 11, 25, tzinfo=timezone.utc)
_ACTOR = ConsumerActor(user_id=None, label="ci@example.test", kind="api_key")
_PROVIDER = PacticipantRecord(
    id="p-ledger", tenant_id=_TENANT, slug="ledger-api", name="Ledger API", main_branch="main"
)


def _target(*, allow_mutating: bool) -> MagicMock:
    record = MagicMock()
    record.id, record.slug = _TARGET_ID, "ledger-staging"
    record.policy = VerificationPolicy(allow_mutating_methods=allow_mutating)
    return record


def _registered(name: str, setup: Dict[str, Any], **extra: Any) -> ProviderStateRecord:
    return ProviderStateRecord(
        id=f"id-{name}",
        provider="ledger-api",
        name=name,
        parameters=[StateParameter.model_validate(p) for p in extra.get("parameters", [])],
        setup=StateSetup.model_validate(setup),
        overrides=extra.get("overrides", []),
        created_at=_NOW,
        updated_at=_NOW,
    )


# ---------------------------------------------------------------------------
# Registering
# ---------------------------------------------------------------------------


@pytest.fixture
def stores() -> Iterator[Dict[str, MagicMock]]:
    with ExitStack() as stack:
        mocks = {
            name: stack.enter_context(patch(f"{_SERVICE}.{name}"))
            for name in ("get_pacticipant", "create_state", "replace_state", "get_target")
        }
        mocks["get_pacticipant"].return_value = _PROVIDER
        yield mocks


_BODY = {
    "name": " invoice 1042 exists ",
    "parameters": [{"name": "id", "required": True}],
    "setup": {"kind": "state_change", "url": "/_pact/states"},
    "overrides": [{"target_ref": "ledger-staging", "setup": {"kind": "fixture"}}],
}


def test_registering_checks_the_body_and_resolves_overrides_in_the_tenant(stores: Dict[str, MagicMock]) -> None:
    stores["get_target"].return_value = _target(allow_mutating=True)
    register_provider_state(None, _TENANT, "ledger-api", ProviderStateInput.model_validate(_BODY), actor=_ACTOR)

    stores["get_pacticipant"].assert_called_once_with(None, _TENANT, "ledger-api")
    stores["get_target"].assert_called_once_with(_TENANT, "ledger-staging")
    (_db, tenant, provider, state, overrides), kwargs = stores["create_state"].call_args
    assert (tenant, provider, state.name) == (_TENANT, _PROVIDER, "invoice 1042 exists")
    assert [(o.target_id, o.target_slug, o.setup.kind) for o in overrides] == [
        (_TARGET_ID, "ledger-staging", "fixture")
    ]
    assert kwargs == {"actor": _ACTOR}


def test_an_override_naming_an_unknown_target_is_refused_at_its_place(stores: Dict[str, MagicMock]) -> None:
    stores["get_target"].side_effect = TargetValidationError(CODE_NOT_FOUND, "no verification target 'x'")
    with pytest.raises(PactPublicationError) as refused:
        register_provider_state(None, _TENANT, "ledger-api", ProviderStateInput.model_validate(_BODY), actor=_ACTOR)
    assert (refused.value.code, refused.value.pointer) == (CODE_STATE_INVALID, "/overrides/0/target_ref")
    stores["create_state"].assert_not_called()


def test_a_slug_and_an_id_of_one_target_are_two_overrides_of_it(stores: Dict[str, MagicMock]) -> None:
    stores["get_target"].return_value = _target(allow_mutating=True)
    body = dict(_BODY, overrides=[_BODY["overrides"][0], {"target_ref": _TARGET_ID, "setup": {"kind": "fixture"}}])
    with pytest.raises(PactPublicationError) as refused:
        replace_provider_state(None, _TENANT, "ledger-api", "id", ProviderStateInput.model_validate(body), actor=_ACTOR)
    assert refused.value.pointer == "/overrides/1/target_ref"
    stores["replace_state"].assert_not_called()


def test_a_malformed_body_is_refused_before_any_target_is_resolved(stores: Dict[str, MagicMock]) -> None:
    body = dict(_BODY, setup={"kind": "state_change"})
    with pytest.raises(PactPublicationError):
        register_provider_state(None, _TENANT, "ledger-api", ProviderStateInput.model_validate(body), actor=_ACTOR)
    stores["get_target"].assert_not_called()


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------


def _check(names: List[str], states: List[ProviderStateRecord], *, target: Any = None, **request: Any) -> Any:
    broker = _Broker(names)
    with ExitStack() as stack:
        stack.enter_context(patch(f"{_VERIFIER}.list_pact_candidates", side_effect=broker.list_pact_candidates))
        stack.enter_context(patch(f"{_VERIFIER}.load_pending_evidence", return_value=NO_EVIDENCE))
        stack.enter_context(patch(f"{_SERVICE}.get_pact_by_sha", side_effect=broker.get_pact_by_sha))
        stack.enter_context(patch(f"{_SERVICE}.list_states", return_value=states))
        get_target = stack.enter_context(patch(f"{_SERVICE}.get_target", return_value=target))
        send = stack.enter_context(patch("app.pact_provider_state_handler.build_guarded_client"))
        response = check_provider_states(None, _TENANT, "ledger-api", StateCheckRequest(**request))
        send.assert_not_called()
        return response, get_target


def test_with_nothing_registered_every_state_is_flagged_once() -> None:
    response, _ = _check([PACT_JS, PACT_JVM, PACT_GO], [])
    assert response.provider == "ledger-api" and response.pacts == 3
    assert response.ready is False
    names = [entry.name for entry in response.states]
    assert "invoice 1042 exists" in names and "the ledger has entries" in names
    for entry in response.states:
        assert entry.registered is False and entry.state_id is None
        assert [(p.code, p.consumer) for p in entry.problems] == [(CODE_STATE_NOT_REGISTERED, None)]
    assert response.blocking == len(response.states) and response.warnings == 0


def test_a_fully_registered_provider_is_ready_and_unused_states_are_listed() -> None:
    first, _ = _check([PACT_JS, PACT_JVM, PACT_GO], [])
    states = [_registered(entry.name, {"kind": "fixture"}) for entry in first.states]
    states.append(_registered("a retired state", {"kind": "fixture"}))
    response, _ = _check([PACT_JS, PACT_JVM, PACT_GO], states)
    assert response.ready is True and response.blocking == 0
    assert all(entry.registered and entry.setup_kind == "fixture" for entry in response.states)
    assert response.unused == ["a retired state"]
    invoice = next(entry for entry in response.states if entry.name == "invoice 1042 exists")
    assert invoice.interactions >= 1
    assert invoice.uses[0].consumer == "billing-service" and invoice.uses[0].params == {"id": 1042}


def test_parameter_problems_name_the_interaction_and_unregistered_states_come_first() -> None:
    states = [
        _registered(
            "invoice 1042 exists",
            {"kind": "fixture"},
            parameters=[{"name": "customer", "required": True}],
        )
    ]
    response, _ = _check([PACT_JS, PACT_GO], states)
    assert [entry.registered for entry in response.states] == sorted(entry.registered for entry in response.states)
    invoice = next(entry for entry in response.states if entry.name == "invoice 1042 exists")
    assert [(p.code, p.parameter, p.consumer, p.interaction) for p in invoice.problems] == [
        (CODE_PARAM_MISSING, "customer", "billing-service", "a request for invoice 1042"),
        (CODE_PARAM_UNDECLARED, "id", "billing-service", "a request for invoice 1042"),
    ]
    assert response.ready is False and response.warnings == 1


def test_the_target_s_override_and_policy_are_checked() -> None:
    override = StateOverrideRecord(
        target_id=_TARGET_ID, target_slug="ledger-staging", setup=StateSetup(kind="state_change", url="/_pact/states")
    )
    states = [
        _registered("invoice 1042 exists", {"kind": "fixture"}, parameters=[{"name": "id"}], overrides=[override])
    ]
    response, get_target = _check([PACT_JS], states, target=_target(allow_mutating=False), target_ref="ledger-staging")
    get_target.assert_called_once_with(_TENANT, "ledger-staging")
    (entry,) = response.states
    assert (entry.setup_kind, entry.overridden) == ("state_change", True)
    assert [p.code for p in entry.problems] == [CODE_SETUP_BLOCKED]
    assert response.target == "ledger-staging" and response.ready is False


def test_more_pacts_than_a_run_takes_are_refused() -> None:
    with patch(f"{_SERVICE}.MAX_PACTS_PER_RUN", 0), pytest.raises(PactVerifierError) as refused:
        _check([PACT_JS], [])
    assert refused.value.code == CODE_TOO_MANY_PACTS
