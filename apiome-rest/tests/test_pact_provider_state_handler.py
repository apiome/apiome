"""Setting provider states up — PFX-3.3 (#6933), :mod:`app.pact_provider_state_handler`.

What actually goes out is the proof, so every test reads the requests a fake received:

* a state-change **path** is posted to the target, with the target's credential and the Pact
  state-change body; an absolute **URL** is posted with no credential;
* teardown is posted after, in reverse order, unless the state turns it off;
* a fixture's requests go to the target with ``${param}`` substituted (defaults included);
* a failed setup undoes what was done for the interaction and says which state and call failed;
* a mutating request is never sent to a target whose policy forbids it;
* a failed teardown is recorded, not raised;
* the planner's question (:meth:`issue`) uses the target's overrides and policy.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx

from app.contract_suite import PactProviderState
from app.pact_provider_state import (
    CODE_SETUP_BLOCKED,
    CODE_STATE_NOT_REGISTERED,
    ProviderStateRecord,
    StateOverrideRecord,
    StateParameter,
    StateSetup,
    registry_of,
)
from app.pact_provider_state_handler import RegistryStateHandler
from tests.pact_verifier_fakes import target

_NOW = datetime(2026, 11, 25, tzinfo=timezone.utc)
_AUTH = {"Authorization": "Bearer target-token"}


class _Recorder:
    """A fake server that records every request and answers with ``answer``."""

    def __init__(self, answer: Optional[Callable[[httpx.Request], httpx.Response]] = None) -> None:
        self.requests: List[httpx.Request] = []
        self.answer = answer or (lambda _r: httpx.Response(200))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.answer(request)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    @property
    def sent(self) -> List[str]:
        return [f"{r.method} {r.url}" for r in self.requests]

    def bodies(self) -> List[Any]:
        return [json.loads(r.content) if r.content else None for r in self.requests]


def _state(name: str, setup: Dict[str, Any], **extra: Any) -> ProviderStateRecord:
    return ProviderStateRecord(
        id=f"id-{name}",
        provider="ledger-api",
        name=name,
        parameters=[StateParameter.model_validate(p) for p in extra.pop("parameters", [])],
        setup=StateSetup.model_validate(setup),
        overrides=extra.pop("overrides", []),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _handler(
    states: List[ProviderStateRecord],
    *,
    on_target: Optional[_Recorder] = None,
    elsewhere: Optional[_Recorder] = None,
    allow_mutating: bool = True,
) -> RegistryStateHandler:
    return RegistryStateHandler(
        registry_of(states),
        target(allow_mutating=allow_mutating),
        _AUTH,
        target_client=(on_target or _Recorder()).client(),
        external_client=(elsewhere or _Recorder()).client(),
    )


_INVOICE = PactProviderState(name="invoice 1042 exists", params={"id": 1042})


def test_a_state_change_path_is_posted_to_the_target_with_its_credential() -> None:
    api = _Recorder()
    handler = _handler([_state("invoice 1042 exists", {"kind": "state_change", "url": "/_pact/states"})], on_target=api)

    assert handler.setup([_INVOICE]) is None
    handler.teardown([_INVOICE])

    assert api.sent == [
        "POST https://ledger.staging.example.test/_pact/states",
        "POST https://ledger.staging.example.test/_pact/states",
    ]
    assert api.bodies() == [
        {"state": "invoice 1042 exists", "params": {"id": 1042}, "action": "setup"},
        {"state": "invoice 1042 exists", "params": {"id": 1042}, "action": "teardown"},
    ]
    assert all(r.headers["Authorization"] == "Bearer target-token" for r in api.requests)
    assert handler.drain_teardown_failures() == []


def test_a_state_change_url_off_the_target_carries_no_credential_and_can_skip_teardown() -> None:
    hooks, api = _Recorder(), _Recorder()
    state = _state(
        "invoice 1042 exists", {"kind": "state_change", "url": "https://hooks.example.test/s", "teardown": False}
    )
    handler = _handler([state], on_target=api, elsewhere=hooks)

    assert handler.setup([_INVOICE]) is None
    handler.teardown([_INVOICE])

    assert hooks.sent == ["POST https://hooks.example.test/s"]
    assert "authorization" not in hooks.requests[0].headers
    assert api.requests == []


def test_a_fixture_sends_its_requests_with_parameters_substituted() -> None:
    api = _Recorder()
    state = _state(
        "invoice 1042 exists",
        {
            "kind": "fixture",
            "requests": [
                {
                    "method": "PUT",
                    "path": "/test-data/invoices/${id}",
                    "headers": {"X-Currency": "${currency}"},
                    "body": {"id": "${id}", "currency": "${currency}"},
                }
            ],
            "teardown_requests": [{"method": "DELETE", "path": "/test-data/invoices/${id}"}],
        },
        parameters=[{"name": "id", "required": True}, {"name": "currency", "default": "EUR"}],
    )
    handler = _handler([state], on_target=api)

    assert handler.setup([_INVOICE]) is None
    handler.teardown([_INVOICE])

    assert api.sent == [
        "PUT https://ledger.staging.example.test/test-data/invoices/1042",
        "DELETE https://ledger.staging.example.test/test-data/invoices/1042",
    ]
    assert api.requests[0].headers["X-Currency"] == "EUR"
    assert api.bodies()[0] == {"id": 1042, "currency": "EUR"}


def test_an_empty_fixture_sends_nothing() -> None:
    api = _Recorder()
    handler = _handler([_state("invoice 1042 exists", {"kind": "fixture"})], on_target=api)
    assert handler.setup([_INVOICE]) is None
    handler.teardown([_INVOICE])
    assert api.requests == []


def test_a_failed_setup_undoes_what_was_done_and_names_the_call() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["state"] == "second" and body["action"] == "setup":
            return httpx.Response(500, text="seed failed")
        return httpx.Response(204)

    api = _Recorder(answer)
    handler = _handler(
        [
            _state("first", {"kind": "state_change", "url": "/s"}),
            _state("second", {"kind": "state_change", "url": "/s"}),
        ],
        on_target=api,
    )

    problem = handler.setup([PactProviderState(name="first"), PactProviderState(name="second")])

    assert problem == "'second': POST /s answered 500: seed failed"
    assert [(b["state"], b["action"]) for b in api.bodies()] == [
        ("first", "setup"),
        ("second", "setup"),
        ("first", "teardown"),
    ]
    # Nothing is left to tear down afterwards.
    handler.teardown([])
    assert len(api.requests) == 3


def test_teardown_runs_in_reverse_order() -> None:
    api = _Recorder()
    handler = _handler(
        [
            _state("first", {"kind": "state_change", "url": "/s"}),
            _state("second", {"kind": "state_change", "url": "/s"}),
        ],
        on_target=api,
    )
    states = [PactProviderState(name="first"), PactProviderState(name="second")]
    assert handler.setup(states) is None
    handler.teardown(states)
    assert [(b["state"], b["action"]) for b in api.bodies()][2:] == [("second", "teardown"), ("first", "teardown")]


def test_an_unregistered_state_is_refused_without_sending_anything() -> None:
    api = _Recorder()
    handler = _handler([], on_target=api)
    assert (
        handler.setup([PactProviderState(name="nobody knows")]) == "the provider has no registered state 'nobody knows'"
    )
    assert api.requests == []


def test_a_mutating_request_is_never_sent_to_a_target_that_forbids_it() -> None:
    api = _Recorder()
    state = _state("invoice 1042 exists", {"kind": "fixture", "requests": [{"method": "POST", "path": "/seed"}]})
    handler = _handler([state], on_target=api, allow_mutating=False)

    problem = handler.setup([_INVOICE]) or ""

    assert "allow_mutating_methods=false" in problem
    assert api.requests == []


def test_a_transport_error_is_reported() -> None:
    def answer(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    handler = _handler(
        [_state("invoice 1042 exists", {"kind": "state_change", "url": "/s"})], on_target=_Recorder(answer)
    )
    assert (handler.setup([_INVOICE]) or "").startswith(
        "'invoice 1042 exists': POST /s could not be sent (ConnectError"
    )


def test_a_failed_teardown_is_recorded_not_raised() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503) if json.loads(request.content)["action"] == "teardown" else httpx.Response(200)

    handler = _handler(
        [_state("invoice 1042 exists", {"kind": "state_change", "url": "/s"})], on_target=_Recorder(answer)
    )
    assert handler.setup([_INVOICE]) is None
    handler.teardown([_INVOICE])
    assert handler.drain_teardown_failures() == ["teardown of 'invoice 1042 exists' failed: POST /s answered 503"]
    assert handler.drain_teardown_failures() == []


def test_the_target_s_override_is_used() -> None:
    default, api = _Recorder(), _Recorder()
    override = StateOverrideRecord(
        target_id=target().target_id,
        target_slug="ledger-staging",
        setup=StateSetup(kind="fixture", requests=[{"method": "GET", "path": "/warm"}]),  # type: ignore[list-item]
    )
    state = _state(
        "invoice 1042 exists", {"kind": "state_change", "url": "https://hooks.example.test/s"}, overrides=[override]
    )
    handler = _handler([state], on_target=api, elsewhere=default)
    assert handler.setup([_INVOICE]) is None
    assert api.sent == ["GET https://ledger.staging.example.test/warm"] and default.requests == []


def test_issue_answers_for_this_target() -> None:
    state = _state("invoice 1042 exists", {"kind": "state_change", "url": "/s"})
    assert _handler([state]).issue([_INVOICE]) is None
    blocked = _handler([state], allow_mutating=False).issue([_INVOICE])
    assert blocked is not None and blocked[0] == CODE_SETUP_BLOCKED
    unknown = _handler([state]).issue([PactProviderState(name="other")])
    assert unknown is not None and unknown[0] == CODE_STATE_NOT_REGISTERED


def test_close_closes_only_the_clients_it_created() -> None:
    supplied = _Recorder().client()
    handler = RegistryStateHandler(registry_of([]), target(), {}, target_client=supplied)
    handler._client(external=True)  # creates a guarded client of its own
    handler.close()
    assert not supplied.is_closed
