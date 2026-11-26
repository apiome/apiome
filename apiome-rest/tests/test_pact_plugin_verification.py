"""Verifying plugin and GraphQL pacts — PFX-3.7 (#6937).

* **Planner** — a gRPC call is sent only to a ``grpc`` / ``connect`` target and an HTTP request
  only to an ``http`` one; the other kind is held back with ``pact-interaction-protocol-mismatch``.
  A gRPC call is mutating unless its method declares ``NO_SIDE_EFFECTS``; a GraphQL ``query`` is
  not mutating although it is a ``POST``, a ``mutation`` is.
* **Runner** — a pact gRPC reply is judged against the recorded status and message under the
  pact's matching rules (over Connect and through any RPC transport); a GraphQL reply carrying
  ``errors`` the consumer never recorded fails.
* **Service** — a gRPC pact verified on a Connect target publishes; on an HTTP target it is
  ``incomplete`` and publishes nothing; the tenant is the caller's throughout.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx
import pytest
from google.protobuf import json_format, message_factory

from app.contract_protocols import PROTOCOL_CONNECT, PROTOCOL_GRPC, PROTOCOL_HTTP
from app.contract_runner import (
    FAILURE_GRAPHQL_ERRORS_PRESENT,
    FAILURE_MUTATING_METHOD_BLOCKED,
    FAILURE_PACT_BODY_MISMATCH,
    is_mutating_case,
    run_suite,
)
from app.contract_runner_rpc import FAILURE_RPC_STATUS_MISMATCH, RpcReply, execute_rpc_case
from app.contract_suite import ContractSuiteManifest
from app.contract_suite_pact import compile_pact_suite
from app.pact_publication import pact_content_sha
from app.pact_selectors import PactCandidate
from app.pact_verifier import (
    OUTCOME_INCOMPLETE,
    OUTCOME_PASSED,
    SKIP_MUTATING_BLOCKED,
    SKIP_PROTOCOL_MISMATCH,
    VERIFIABLE_TARGET_PROTOCOLS,
    PactVerificationOptions,
    interaction_results,
    pact_outcome,
    plan_pact_run,
)
from app.verification_evidence import OPERATION_OUTCOME_FAILED, OPERATION_OUTCOME_PASSED
from app.verification_target import (
    NETWORK_CLASS_PRIVATE,
    ResolvedTarget,
    TargetAuthReference,
    VerificationPolicy,
)
from tests.pact_plugin_fixtures import contents, graphql_interaction, grpc_interaction, grpc_pact
from tests.pact_verifier_fakes import target
from tests.rpc_contract_fixtures import PACKAGE, SERVICE, orders_pool
from tests.test_pact_verifier_service import _TENANT, _Broker, _verify

GET_ORDER = f"{SERVICE}.GetOrder"
_BASE_URL = "http://orders.internal.test"
_POOL = orders_pool()
_GET_REQUEST = message_factory.GetMessageClass(_POOL.FindMessageTypeByName(f"{PACKAGE}.GetOrderRequest"))


def _compile(document: Dict[str, Any]) -> ContractSuiteManifest:
    return compile_pact_suite(document, consumer="orders-web", provider="orders-grpc")


def _http_pact(interactions: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"interactions": interactions, "metadata": {"pactSpecification": {"version": "3.0.0"}}}


def _target(protocol: str, *, allow_mutating: bool = False) -> ResolvedTarget:
    """A resolved private target speaking ``protocol``."""
    return ResolvedTarget(
        target_id="44444444-4444-4444-8444-444444444444",
        slug=f"orders-{protocol}",
        name=f"orders {protocol}",
        environment="staging",
        network_class=NETWORK_CLASS_PRIVATE,
        base_url=_BASE_URL,
        protocol=protocol,
        policy=VerificationPolicy(retry_attempts=0, allow_mutating_methods=allow_mutating),
        auth=TargetAuthReference(),
        resolved_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
    )


class ConnectOrders:
    """A Connect server for ``Orders``: ``GetOrder`` answers ``order``, everything else 404."""

    def __init__(self, order: Optional[Dict[str, Any]] = None, *, status: int = 200, error: Any = None) -> None:
        self.order = order if order is not None else {"id": "1042", "totalCents": "1200", "status": "OPEN"}
        self.status = status
        self.error = error
        self.requests: List[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path != f"/{SERVICE}/GetOrder":
            return httpx.Response(404, json={"code": "unimplemented"})
        assert request.headers["connect-protocol-version"] == "1"
        message = _GET_REQUEST()
        json_format.Parse(request.content.decode("utf-8"), message)
        if self.status != 200:
            return httpx.Response(self.status, json=self.error or {"code": "not_found", "message": "gone"})
        return httpx.Response(200, json={**self.order, "id": message.order_id})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


# ---------------------------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------------------------


def _mixed() -> ContractSuiteManifest:
    http = {
        "type": "Synchronous/HTTP",
        "description": "health",
        "request": {"method": "GET", "path": "/health"},
        "response": {"status": 200},
    }
    return _compile(grpc_pact([http, grpc_interaction()]))


def test_pacts_verify_on_http_grpc_and_connect_targets() -> None:
    assert VERIFIABLE_TARGET_PROTOCOLS == (PROTOCOL_HTTP, PROTOCOL_GRPC, PROTOCOL_CONNECT)


@pytest.mark.parametrize("protocol", [PROTOCOL_GRPC, PROTOCOL_CONNECT])
def test_a_grpc_target_sends_the_grpc_calls_and_holds_back_the_http_requests(protocol: str) -> None:
    manifest = _mixed()
    plan = plan_pact_run(manifest, PactVerificationOptions(), target_allows_mutating=False, target_protocol=protocol)
    by_key = {case.operation_key: case.case_id for case in manifest.cases}
    assert plan.skips == {by_key["GET /health"]: SKIP_PROTOCOL_MISMATCH}
    message = plan.decisions[by_key["GET /health"]].skip_message
    assert "http target" in message and protocol in message


def test_an_http_target_holds_back_the_grpc_calls_with_the_reason() -> None:
    manifest = _mixed()
    plan = plan_pact_run(manifest, PactVerificationOptions(), target_allows_mutating=False)
    grpc_id = next(case.case_id for case in manifest.cases if case.protocol == PROTOCOL_GRPC)
    assert plan.skips == {grpc_id: SKIP_PROTOCOL_MISMATCH}
    assert "grpc or connect target" in plan.decisions[grpc_id].skip_message


def test_a_grpc_call_without_no_side_effects_is_mutating_and_named_so() -> None:
    interaction = grpc_interaction(
        "create",
        service="Orders/CreateOrder",
        request={"contents": contents("CreateOrderRequest", {"customerId": "c"})},
        response=[{"contents": contents("Order", {"id": "9"})}],
    )
    manifest = _compile(grpc_pact([interaction, grpc_interaction()]))
    by_key = {case.operation_key: case for case in manifest.cases}
    assert is_mutating_case(by_key[f"{SERVICE}.CreateOrder"]) and not is_mutating_case(by_key[GET_ORDER])
    plan = plan_pact_run(
        manifest, PactVerificationOptions(), target_allows_mutating=True, target_protocol=PROTOCOL_GRPC
    )
    create = by_key[f"{SERVICE}.CreateOrder"].case_id
    assert plan.skips == {create: SKIP_MUTATING_BLOCKED}
    assert "NO_SIDE_EFFECTS" in plan.decisions[create].skip_message
    opted = plan_pact_run(
        manifest,
        PactVerificationOptions(allow_mutating=True),
        target_allows_mutating=True,
        target_protocol=PROTOCOL_GRPC,
    )
    assert opted.skips == {}


def test_a_graphql_query_is_not_mutating_but_a_mutation_is() -> None:
    mutation = graphql_interaction(
        "create a user",
        query="mutation CreateUser($name: String!) { createUser(name: $name) { id } }",
        variables={"name": "Ada"},
        operation_name="CreateUser",
        response_body={"data": {"createUser": {"id": "8"}}},
    )
    manifest = _compile(_http_pact([graphql_interaction(), mutation]))
    plan = plan_pact_run(manifest, PactVerificationOptions(), target_allows_mutating=True)
    by_title = {case.title: case.case_id for case in manifest.cases}
    assert plan.skips == {by_title["create a user"]: SKIP_MUTATING_BLOCKED}
    assert "GraphQL mutation 'CreateUser'" in plan.decisions[by_title["create a user"]].skip_message


# ---------------------------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------------------------


def _run(manifest: ContractSuiteManifest, server: Any, protocol: str = PROTOCOL_CONNECT):
    client = server.client()
    try:
        return run_suite(manifest, _target(protocol), client=client)
    finally:
        client.close()


def test_a_conforming_connect_reply_passes_under_the_pacts_rules() -> None:
    manifest = _compile(grpc_pact([grpc_interaction()]))
    server = ConnectOrders({"id": "x", "totalCents": "98765", "status": "OPEN", "items": []})
    [operation] = _run(manifest, server).operations
    assert operation.outcome == OPERATION_OUTCOME_PASSED, operation.failure_message
    assert json.loads(server.requests[0].content) == {"orderId": "1042"}
    [result] = interaction_results(manifest, [operation])
    assert pact_outcome([result]) == OUTCOME_PASSED


def test_a_drifted_reply_fails_with_the_field_and_rule_named() -> None:
    manifest = _compile(grpc_pact([grpc_interaction()]))
    [operation] = _run(manifest, ConnectOrders({"id": "1042", "totalCents": "12.5", "status": "CLOSED"})).operations
    assert operation.outcome == OPERATION_OUTCOME_FAILED
    assert operation.failure_code == FAILURE_PACT_BODY_MISMATCH
    [result] = interaction_results(manifest, [operation])
    fields = {(mismatch.field, mismatch.rule) for mismatch in result.mismatches}
    assert ("/totalCents", "regex") in fields and ("/status", "equality") in fields


def test_a_missing_field_fails_the_reply() -> None:
    manifest = _compile(grpc_pact([grpc_interaction()]))
    [operation] = _run(manifest, ConnectOrders({"id": "1042", "totalCents": "1"})).operations
    assert operation.outcome == OPERATION_OUTCOME_FAILED
    [result] = interaction_results(manifest, [operation])
    assert any(mismatch.field == "/status" for mismatch in result.mismatches)


def test_an_unexpected_status_fails_before_the_message_is_compared() -> None:
    manifest = _compile(grpc_pact([grpc_interaction()]))
    [operation] = _run(manifest, ConnectOrders(status=404)).operations
    assert (operation.outcome, operation.failure_code) == (OPERATION_OUTCOME_FAILED, FAILURE_RPC_STATUS_MISMATCH)


def test_a_recorded_error_status_passes_when_the_provider_answers_it() -> None:
    interaction = grpc_interaction(response=[{"metadata": {"grpc-status": "NOT_FOUND"}}])
    manifest = _compile(grpc_pact([interaction]))
    [operation] = _run(manifest, ConnectOrders(status=404, error={"code": "not_found"})).operations
    assert operation.outcome == OPERATION_OUTCOME_PASSED


class _FakeTransport:
    """An RPC transport that answers every call with one reply (the native-gRPC seam)."""

    protocol = PROTOCOL_GRPC

    def __init__(self, reply: RpcReply) -> None:
        self.reply = reply

    def call(self, case: Any) -> RpcReply:
        return self.reply

    def close(self) -> None:
        return None


@pytest.mark.parametrize(
    "body, outcome",
    [
        ({"id": "1042", "totalCents": "1200", "status": "OPEN"}, OPERATION_OUTCOME_PASSED),
        ({"id": "1042", "totalCents": "-7", "status": "OPEN", "extra": 1}, OPERATION_OUTCOME_PASSED),
        # A server printing the int64 as a number still satisfies the digits regex.
        ({"id": "1042", "totalCents": 1200, "status": "OPEN"}, OPERATION_OUTCOME_PASSED),
        ({"id": "1042", "totalCents": "12a", "status": "OPEN"}, OPERATION_OUTCOME_FAILED),
        ({"id": "1042", "status": "OPEN"}, OPERATION_OUTCOME_FAILED),
    ],
)
def test_any_rpc_transport_is_judged_by_the_pact(body: Dict[str, Any], outcome: str) -> None:
    [case] = _compile(grpc_pact([grpc_interaction()])).cases
    result = execute_rpc_case(
        case, target=_target(PROTOCOL_GRPC), transport=_FakeTransport(RpcReply(code="ok", body=body)), schemas={}
    )
    assert result.outcome == outcome


def _graphql_server(body: Dict[str, Any]) -> Any:
    class _Server:
        def __init__(self) -> None:
            self.requests: List[httpx.Request] = []

        def __call__(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(200, json=body)

        def client(self) -> httpx.Client:
            return httpx.Client(transport=httpx.MockTransport(self))

    return _Server()


def test_a_graphql_reply_with_unrecorded_errors_fails_even_when_data_matches() -> None:
    manifest = _compile(_http_pact([graphql_interaction()]))
    server = _graphql_server({"data": {"user": {"id": "7", "name": "Ada"}}, "errors": [{"message": "partial"}]})
    [operation] = _run(manifest, server, PROTOCOL_HTTP).operations
    assert (operation.outcome, operation.failure_code) == (OPERATION_OUTCOME_FAILED, FAILURE_GRAPHQL_ERRORS_PRESENT)
    assert "partial" in operation.failure_message
    assert server.requests[0].url.path == "/graphql"


def test_a_graphql_reply_that_matches_passes() -> None:
    manifest = _compile(_http_pact([graphql_interaction()]))
    [operation] = _run(
        manifest, _graphql_server({"data": {"user": {"id": "7", "name": "Ada"}}}), PROTOCOL_HTTP
    ).operations
    assert operation.outcome == OPERATION_OUTCOME_PASSED


def test_recorded_graphql_errors_are_judged_by_the_pact_instead() -> None:
    expected = {"data": None, "errors": [{"message": "not found"}]}
    manifest = _compile(_http_pact([graphql_interaction(response_body=expected)]))
    [operation] = _run(manifest, _graphql_server(expected), PROTOCOL_HTTP).operations
    assert operation.outcome == OPERATION_OUTCOME_PASSED


def test_a_graphql_mutation_is_held_back_by_the_target_policy_with_its_name() -> None:
    mutation = graphql_interaction(query="mutation M { m { id } }", operation_name="M", response_body={"data": {}})
    manifest = _compile(_http_pact([mutation]))
    [operation] = _run(manifest, _graphql_server({"data": {}}), PROTOCOL_HTTP).operations
    assert operation.failure_code == FAILURE_MUTATING_METHOD_BLOCKED
    assert "GraphQL mutation" in operation.failure_message


# ---------------------------------------------------------------------------------------------
# Service, end to end
# ---------------------------------------------------------------------------------------------


def _broker(document: Dict[str, Any]) -> _Broker:
    broker = _Broker([])
    sha = pact_content_sha(document)
    broker.documents[sha] = copy.deepcopy(document)
    broker.candidates.append(
        PactCandidate(
            consumer_id="c-1",
            consumer_slug="orders-web",
            consumer_name="orders-web",
            consumer_main_branch="main",
            version_id="v-1",
            version_number="1.0.0",
            version_seq=1,
            sha=sha,
            branches=("main",),
        )
    )
    return broker


def _resolve(protocol: str) -> Callable[..., ResolvedTarget]:
    def resolve(tenant_id: str, _ref: str, *, protocol: str = "", **_kwargs: Any) -> ResolvedTarget:
        assert tenant_id == _TENANT and protocol == "pact"
        return target(allow_mutating=True).model_copy(update={"protocol": wanted})

    wanted = protocol
    return resolve


def test_a_grpc_pact_on_a_connect_target_verifies_and_publishes() -> None:
    broker = _broker(grpc_pact([grpc_interaction()]))
    server = ConnectOrders()
    response = _verify(broker, server, resolve=_resolve(PROTOCOL_CONNECT))
    assert response.outcome == OUTCOME_PASSED and response.success
    assert response.target.protocol == PROTOCOL_CONNECT
    [pact] = response.pacts
    assert pact.published and [i.outcome for i in pact.interactions] == ["passed"]
    [published] = broker.published
    assert published["tenant"] == _TENANT and published["request"].success is True
    assert server.requests[0].url.path == f"/{SERVICE}/GetOrder"


def test_a_grpc_pact_on_an_http_target_is_incomplete_and_publishes_nothing() -> None:
    broker = _broker(grpc_pact([grpc_interaction()]))
    server = ConnectOrders()
    response = _verify(broker, server, resolve=_resolve(PROTOCOL_HTTP))
    assert response.outcome == OUTCOME_INCOMPLETE and not response.success
    [pact] = response.pacts
    [interaction] = pact.interactions
    assert (interaction.outcome, interaction.code) == ("skipped", SKIP_PROTOCOL_MISMATCH)
    assert not pact.published and broker.published == [] and server.requests == []


def test_a_drifted_grpc_provider_publishes_a_failure_naming_the_field() -> None:
    broker = _broker(grpc_pact([grpc_interaction()]))
    response = _verify(
        broker,
        ConnectOrders({"id": "1042", "totalCents": "1200", "status": "CLOSED"}),
        resolve=_resolve(PROTOCOL_CONNECT),
    )
    assert response.outcome == "failed"
    [published] = broker.published
    [entry] = published["request"].test_results
    assert entry["success"] is False
    assert any(m["identifier"] == "/status" for m in entry["mismatches"])
