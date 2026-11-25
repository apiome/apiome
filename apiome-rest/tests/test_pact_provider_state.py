"""The provider-state registry's rules — PFX-3.3 (#6933), :mod:`app.pact_provider_state`.

* a state's body is checked as a whole, and every refusal names its place with a JSON Pointer:
  a blank name, duplicate or malformed parameters, a setup of the wrong shape, a fixture path off
  the target, a placeholder naming no parameter, a credential header, two overrides of a target;
* the setup used on a target is its override, else the default;
* parameters: defaults fill gaps, a missing required one blocks, an undeclared one warns and is
  passed on;
* the problems an interaction's states have: unregistered, missing parameter, setup the target's
  policy forbids — and the first blocking one is what the planner skips with;
* ``${param}`` substitution keeps a whole-placeholder value's type.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

from app.contract_suite import PactProviderState
from app.pact_provider_state import (
    CODE_PARAM_MISSING,
    CODE_PARAM_UNDECLARED,
    CODE_SETUP_BLOCKED,
    CODE_STATE_INVALID,
    CODE_STATE_NOT_REGISTERED,
    MAX_FIXTURE_REQUESTS,
    MAX_PARAMETERS,
    SEVERITY_BLOCKING,
    SEVERITY_WARNING,
    ProviderStateInput,
    ProviderStateRecord,
    StateOverrideRecord,
    StateParameter,
    StateSetup,
    registry_of,
    resolve_params,
    setup_for_target,
    state_issue,
    state_problems,
    substitute,
    validate_state,
)
from app.pact_publication import PactPublicationError

_NOW = datetime(2026, 11, 25, tzinfo=timezone.utc)
_TARGET = "22222222-2222-4222-8222-222222222222"


def _body(**fields: Any) -> ProviderStateInput:
    base: Dict[str, Any] = {
        "name": "invoice 1042 exists",
        "parameters": [{"name": "id", "required": True}],
        "setup": {"kind": "state_change", "url": "/_pact/provider-states"},
    }
    base.update(fields)
    return ProviderStateInput.model_validate(base)


def _refused(body: ProviderStateInput) -> PactPublicationError:
    with pytest.raises(PactPublicationError) as refused:
        validate_state(body)
    assert refused.value.code == CODE_STATE_INVALID
    return refused.value


def _record(
    name: str = "invoice 1042 exists",
    *,
    parameters: List[Dict[str, Any]] | None = None,
    setup: Dict[str, Any] | None = None,
    overrides: List[StateOverrideRecord] | None = None,
) -> ProviderStateRecord:
    return ProviderStateRecord(
        id="33333333-3333-4333-8333-333333333333",
        provider="ledger-api",
        name=name,
        parameters=[StateParameter.model_validate(item) for item in (parameters or [])],
        setup=StateSetup.model_validate(setup or {"kind": "state_change", "url": "https://hooks.example.test/states"}),
        overrides=overrides or [],
        created_at=_NOW,
        updated_at=_NOW,
    )


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------


def test_a_well_formed_state_is_normalised() -> None:
    state = validate_state(
        _body(
            name="  invoice 1042 exists  ",
            setup={
                "kind": "fixture",
                "requests": [{"method": "post", "path": "/test-data/invoices", "body": {"id": "${id}"}}],
                "teardown_requests": [{"method": "delete", "path": "/test-data/invoices/${id}"}],
            },
        )
    )
    assert state.name == "invoice 1042 exists"
    assert [r.method for r in state.setup.requests + state.setup.teardown_requests] == ["POST", "DELETE"]


def test_a_blank_name_is_refused() -> None:
    assert _refused(_body(name="   ")).pointer == "/name"


@pytest.mark.parametrize(
    ("parameters", "pointer"),
    [
        ([{"name": "id"}, {"name": "id"}], "/parameters/1/name"),
        ([{"name": "1st"}], "/parameters/0/name"),
        ([{"name": "has space"}], "/parameters/0/name"),
        ([{"name": f"p{i}"} for i in range(MAX_PARAMETERS + 1)], "/parameters"),
    ],
)
def test_malformed_parameters_are_refused(parameters: List[Dict[str, Any]], pointer: str) -> None:
    assert _refused(_body(parameters=parameters)).pointer == pointer


@pytest.mark.parametrize(
    ("setup", "pointer"),
    [
        ({"kind": "state_change"}, "/setup/url"),
        ({"kind": "state_change", "url": "  "}, "/setup/url"),
        ({"kind": "state_change", "url": "//elsewhere/states"}, "/setup/url"),
        ({"kind": "state_change", "url": "ftp://hooks.example.test/states"}, "/setup/url"),
        ({"kind": "state_change", "url": "https://user:pw@hooks.example.test/states"}, "/setup/url"),
        (
            {"kind": "state_change", "url": "/s", "requests": [{"method": "GET", "path": "/x"}]},
            "/setup/requests",
        ),
        ({"kind": "fixture", "url": "/s"}, "/setup/url"),
        ({"kind": "fixture", "requests": [{"method": "TRACE", "path": "/x"}]}, "/setup/requests/0/method"),
        ({"kind": "fixture", "requests": [{"method": "GET", "path": "x"}]}, "/setup/requests/0/path"),
        ({"kind": "fixture", "requests": [{"method": "GET", "path": "//evil/x"}]}, "/setup/requests/0/path"),
        (
            {"kind": "fixture", "teardown_requests": [{"method": "GET", "path": "/x/${nope}"}]},
            "/setup/teardown_requests/0/path",
        ),
        (
            {"kind": "fixture", "requests": [{"method": "POST", "path": "/x", "body": {"a": ["${nope}"]}}]},
            "/setup/requests/0/body/a/0",
        ),
        (
            {"kind": "fixture", "requests": [{"method": "GET", "path": "/x", "headers": {"Authorization": "t"}}]},
            "/setup/requests/0/headers/Authorization",
        ),
        (
            {"kind": "fixture", "requests": [{"method": "GET", "path": "/x", "headers": {"bad name": "v"}}]},
            "/setup/requests/0/headers/bad name",
        ),
        (
            {"kind": "fixture", "requests": [{"method": "GET", "path": "/x", "headers": {"X-Seed": "${nope}"}}]},
            "/setup/requests/0/headers/X-Seed",
        ),
        (
            {"kind": "fixture", "requests": [{"method": "GET", "path": "/x"}] * (MAX_FIXTURE_REQUESTS + 1)},
            "/setup/requests",
        ),
    ],
)
def test_a_setup_a_run_would_trip_over_is_refused_with_its_place(setup: Dict[str, Any], pointer: str) -> None:
    assert _refused(_body(setup=setup)).pointer == pointer


def test_a_cookie_is_a_credential_whatever_its_case() -> None:
    setup = {"kind": "fixture", "requests": [{"method": "GET", "path": "/x", "headers": {"COOKIE": "s=1"}}]}
    assert "credential" in str(_refused(_body(setup=setup)))


def test_overrides_are_checked_and_one_per_target() -> None:
    bad = {"target_ref": "staging", "setup": {"kind": "state_change"}}
    assert _refused(_body(overrides=[bad])).pointer == "/overrides/0/setup/url"
    good = {"target_ref": "staging", "setup": {"kind": "fixture"}}
    assert _refused(_body(overrides=[good, {**good, "target_ref": " staging "}])).pointer == "/overrides/1/target_ref"


def test_unknown_fields_are_refused_by_the_model() -> None:
    with pytest.raises(ValueError):
        ProviderStateInput.model_validate({"name": "x", "setup": {"kind": "fixture"}, "secret": "y"})
    with pytest.raises(ValueError):
        ProviderStateInput.model_validate({"name": "x", "setup": {"kind": "script"}})


# ---------------------------------------------------------------------------
# Which setup, which parameters
# ---------------------------------------------------------------------------


def test_the_target_s_override_replaces_the_default() -> None:
    override = StateOverrideRecord(target_id=_TARGET, target_slug="staging", setup=StateSetup(kind="fixture"))
    state = _record(overrides=[override])
    assert setup_for_target(state, _TARGET) == (override.setup, True)
    assert setup_for_target(state, "another") == (state.setup, False)
    assert setup_for_target(state, None) == (state.setup, False)


def test_defaults_fill_gaps_and_missing_required_parameters_block() -> None:
    state = _record(
        parameters=[
            {"name": "id", "required": True},
            {"name": "currency", "required": True, "default": "EUR"},
            {"name": "note"},
        ]
    )
    params, problems = resolve_params(state, {"id": 1042})
    assert params == {"id": 1042, "currency": "EUR"}
    assert problems == []

    params, problems = resolve_params(state, {"extra": True})
    assert params == {"extra": True, "currency": "EUR"}
    assert [(p.code, p.severity, p.parameter) for p in problems] == [
        (CODE_PARAM_MISSING, SEVERITY_BLOCKING, "id"),
        (CODE_PARAM_UNDECLARED, SEVERITY_WARNING, "extra"),
    ]


def test_state_problems_name_every_obstacle() -> None:
    registry = registry_of(
        [
            _record(parameters=[{"name": "id", "required": True}], setup={"kind": "state_change", "url": "/states"}),
            _record("the ledger has entries", setup={"kind": "fixture"}),
        ]
    )
    states = [
        PactProviderState(name="invoice 1042 exists", params={}),
        PactProviderState(name="the ledger has entries"),
        PactProviderState(name="a customer exists"),
    ]
    problems = state_problems(states, registry, target_id=_TARGET, target_allows_mutating=False)
    assert [(p.code, p.state) for p in problems] == [
        (CODE_PARAM_MISSING, "invoice 1042 exists"),
        (CODE_SETUP_BLOCKED, "invoice 1042 exists"),
        (CODE_STATE_NOT_REGISTERED, "a customer exists"),
    ]
    # Without a target the policy is not checked.
    assert [p.code for p in state_problems(states, registry)] == [CODE_PARAM_MISSING, CODE_STATE_NOT_REGISTERED]


def test_state_issue_is_the_first_blocking_problem_and_ignores_warnings() -> None:
    registry = registry_of([_record()])
    assert state_issue([PactProviderState(name="invoice 1042 exists", params={"x": 1})], registry) is None
    code, message = state_issue([PactProviderState(name="unknown")], registry) or ("", "")
    assert code == CODE_STATE_NOT_REGISTERED and "'unknown'" in message


@pytest.mark.parametrize(
    ("setup", "mutating"),
    [
        ({"kind": "state_change", "url": "/states"}, True),
        ({"kind": "state_change", "url": "https://hooks.example.test/s"}, False),
        ({"kind": "fixture"}, False),
        ({"kind": "fixture", "requests": [{"method": "GET", "path": "/x"}]}, False),
        ({"kind": "fixture", "teardown_requests": [{"method": "DELETE", "path": "/x"}]}, True),
    ],
)
def test_which_setups_send_a_mutating_request_to_the_target(setup: Dict[str, Any], mutating: bool) -> None:
    assert StateSetup.model_validate(setup).sends_mutating() is mutating


def test_substitution_keeps_a_whole_placeholder_s_type() -> None:
    params = {"id": 1042, "paid": True, "who": "acme"}
    assert substitute("/invoices/${id}", params) == "/invoices/1042"
    assert substitute({"id": "${id}", "flags": ["${paid}", "x-${paid}"], "n": 3}, params) == {
        "id": 1042,
        "flags": [True, "x-true"],
        "n": 3,
    }
    assert substitute("${missing}-${who}", params) == "-acme"
    assert substitute(None, params) is None
