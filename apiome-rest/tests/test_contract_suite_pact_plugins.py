"""Compiling plugin and GraphQL pacts into contract suites — PFX-3.7 (#6937).

* A gRPC call the protobuf plugin recorded becomes a ``grpc`` case on the XPC-3.2 RPC model:
  procedure, protobuf-JSON request, expected status and reply, rules renamed to JSON names.
* A pact of gRPC calls only is a ``grpc`` suite; one with HTTP interactions stays ``http``.
* A GraphQL-over-HTTP interaction keeps its HTTP request and gains the XPC-1.2 operation.
* Nothing is dropped silently: other plugins, streaming methods, unreadable descriptors or
  content, subscriptions and unreadable GraphQL are reported with a reason.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List

from app.contract_protocols import PROTOCOL_GRPC, PROTOCOL_HTTP
from app.contract_suite import (
    CODE_NO_CASES_COMPILED,
    CODE_PACT_GRAPHQL_SELECTIONS_NOT_MAPPED,
    CODE_PACT_GRAPHQL_UNREADABLE,
    CODE_PACT_MATCHING_RULE_UNSUPPORTED,
    CODE_PACT_PLUGIN_INTERACTION,
    CODE_PACT_PLUGIN_PARTIAL,
    CODE_PACT_PROVIDER_STATE,
    CODE_UNSUPPORTED_STREAMING,
    FINDING_DEGRADED,
    FINDING_INFO,
    OUTCOME_CLIENT_ERROR,
    OUTCOME_SUCCESS,
    SUITE_FINDING_CODES,
    ContractSuiteManifest,
)
from app.contract_suite_pact import compile_pact_suite
from app.pact_plugin_grpc import INT64_PATTERN
from tests.pact_plugin_fixtures import contents, graphql_interaction, grpc_interaction, grpc_pact
from tests.rpc_contract_fixtures import PACKAGE, SERVICE

GET_ORDER = f"{SERVICE}.GetOrder"


def _compile(document: Dict[str, Any]) -> ContractSuiteManifest:
    return compile_pact_suite(document, consumer="orders-web", provider="orders-grpc")


def _http_pact(interactions: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"interactions": interactions, "metadata": {"pactSpecification": {"version": "3.0.0"}}}


def _codes(manifest: ContractSuiteManifest) -> List[str]:
    return [finding.code for finding in manifest.findings]


def test_the_new_codes_are_part_of_the_published_vocabulary() -> None:
    for code in (CODE_PACT_PLUGIN_PARTIAL, CODE_PACT_GRAPHQL_UNREADABLE, CODE_PACT_GRAPHQL_SELECTIONS_NOT_MAPPED):
        assert code in SUITE_FINDING_CODES


# ---------------------------------------------------------------------------------------------
# gRPC
# ---------------------------------------------------------------------------------------------


def test_a_grpc_plugin_pact_compiles_to_a_grpc_suite_on_the_rpc_case_model() -> None:
    manifest = _compile(grpc_pact([grpc_interaction(providerStates=[{"name": "order 1042 exists"}])]))
    assert manifest.protocol == PROTOCOL_GRPC
    assert (manifest.api.protocol, manifest.api.paradigm) == (PROTOCOL_GRPC, "rpc")
    assert manifest.unsupported == []
    [case] = manifest.cases
    assert (case.protocol, case.operation_key, case.operation_name) == (PROTOCOL_GRPC, GET_ORDER, "GetOrder")
    assert case.tags == ["pact", "grpc"]
    assert case.request.method == "POST" and case.request.path == f"/{SERVICE}/GetOrder"
    assert case.request.body == {"orderId": "1042"}
    rpc = case.rpc
    assert rpc is not None
    assert (rpc.procedure, rpc.input_type, rpc.output_type) == (
        f"/{SERVICE}/GetOrder",
        f"{PACKAGE}.GetOrderRequest",
        f"{PACKAGE}.Order",
    )
    assert (rpc.expect_code, rpc.idempotency_level, rpc.message) == ("ok", "no_side_effects", {"orderId": "1042"})
    assert case.expect.outcome == OUTCOME_SUCCESS
    pact = case.pact
    assert pact is not None
    assert (pact.interaction_type, pact.pointer) == ("Synchronous/Messages", "/interactions/0")
    assert [state.name for state in pact.provider_states] == ["order 1042 exists"]
    assert pact.response.has_body and pact.response.body == {"id": "1042", "totalCents": "1200", "status": "OPEN"}
    assert pact.response.body_pointer == "/interactions/0/response/0/contents/content"
    [rule] = pact.response.matching_rules
    # Renamed to the JSON name, and — an int64 printed as a string — applied as a digits regex.
    assert (rule.category, rule.path, rule.match, rule.matcher["regex"]) == (
        "body",
        "$.totalCents",
        "regex",
        INT64_PATTERN,
    )
    assert CODE_PACT_PROVIDER_STATE in _codes(manifest)
    [operation] = manifest.operations
    assert (operation.key, operation.service_key, operation.tags) == (GET_ORDER, SERVICE, ["pact", "grpc"])


def test_the_int64_rule_rewrite_is_reported() -> None:
    manifest = _compile(grpc_pact([grpc_interaction()]))
    [finding] = [f for f in manifest.findings if f.code == CODE_PACT_PLUGIN_PARTIAL]
    assert finding.level == FINDING_INFO and "64-bit" in finding.message
    assert finding.pointer.startswith("/interactions/0/response/0/matchingRules")


def test_an_error_reply_expects_its_status_and_a_mutating_method_is_marked_so() -> None:
    interaction = grpc_interaction(
        service="Orders/CreateOrder",
        request={"contents": contents("CreateOrderRequest", {"customerId": ""})},
        response=[{"metadata": {"grpc-status": "INVALID_ARGUMENT", "grpc-message": "customer required"}}],
    )
    [case] = _compile(grpc_pact([interaction])).cases
    assert (case.rpc.expect_code, case.rpc.idempotency_level) == ("invalid_argument", "unknown")
    assert case.expect.outcome == OUTCOME_CLIENT_ERROR
    assert case.pact.response.has_body is False


def test_what_a_grpc_case_carries_weakly_is_a_degraded_finding() -> None:
    response = grpc_interaction()["response"][0]
    interaction = grpc_interaction(
        request={
            "contents": contents("GetOrderRequest", {"orderId": "1042"}),
            "metadata": {"x-tenant": "acme"},
        },
        response=[
            {
                **response,
                "metadata": {"grpc-message": "fine", "x-trace": "1"},
                "matchingRules": {
                    "body": {"$.nope": {"matchers": [{"match": "type"}]}, "$.id": {"matchers": [{"match": "weird"}]}},
                    "metadata": {"x-trace": {"matchers": [{"match": "regex", "regex": "\\d+"}]}},
                },
            }
        ],
    )
    manifest = _compile(grpc_pact([interaction]))
    degraded = [f.message for f in manifest.findings if f.level == FINDING_DEGRADED]
    assert any("x-tenant" in text for text in degraded)
    assert any("x-trace" in text and "not compared" in text for text in degraded)
    assert any("grpc-message" in text for text in degraded)
    assert any("metadata matching rule" in text for text in degraded)
    unsupported_rules = [f.message for f in manifest.findings if f.code == CODE_PACT_MATCHING_RULE_UNSUPPORTED]
    assert any("$.nope" in text and "names no field" in text for text in unsupported_rules)
    assert any("weird" in text for text in unsupported_rules)
    # Carried, never dropped.
    assert len(manifest.cases[0].pact.response.matching_rules) == 3


def test_unreadable_grpc_interactions_are_listed_with_a_reason() -> None:
    document = grpc_pact(
        [
            grpc_interaction("streaming", service="Orders/WatchOrders"),
            grpc_interaction("unknown method", service="Orders/DeleteOrder"),
            grpc_interaction("bad bytes", request={"contents": {"content": "%%%", "encoded": "base64"}}),
        ]
    )
    manifest = _compile(document)
    assert manifest.cases == [] and manifest.protocol == PROTOCOL_HTTP
    codes = {item.operation_key: item.code for item in manifest.unsupported}
    assert codes == {
        "/interactions/0": CODE_UNSUPPORTED_STREAMING,
        "/interactions/1": CODE_PACT_PLUGIN_INTERACTION,
        "/interactions/2": CODE_PACT_PLUGIN_INTERACTION,
    }
    reasons = " ".join(item.reason for item in manifest.unsupported)
    assert "grpc-streaming" in reasons and "grpc-method-not-found" in reasons and "grpc-content-unreadable" in reasons
    assert CODE_NO_CASES_COMPILED in _codes(manifest)
    assert "HTTP or gRPC" in next(f.message for f in manifest.findings if f.code == CODE_NO_CASES_COMPILED)


def test_another_plugin_or_a_protobuf_body_over_http_stays_unsupported_and_names_the_plugin() -> None:
    csv = {
        "type": "Synchronous/HTTP",
        "description": "a csv report",
        "pluginConfiguration": {"csv": {"csvHeaders": True}},
        "request": {"method": "GET", "path": "/reports/1"},
        "response": {"status": 200},
    }
    manifest = _compile(grpc_pact([csv]))
    [item] = manifest.unsupported
    assert item.code == CODE_PACT_PLUGIN_INTERACTION and "(csv)" in item.reason and "protobuf plugin" in item.reason


def test_a_mixed_pact_is_an_http_suite_carrying_both_kinds_of_case() -> None:
    http = {
        "type": "Synchronous/HTTP",
        "description": "health",
        "request": {"method": "GET", "path": "/health"},
        "response": {"status": 200},
    }
    manifest = _compile(grpc_pact([http, grpc_interaction()]))
    assert manifest.protocol == PROTOCOL_HTTP
    assert sorted(case.protocol for case in manifest.cases) == [PROTOCOL_GRPC, PROTOCOL_HTTP]


def test_the_suite_is_deterministic_per_pact_version() -> None:
    document = grpc_pact([grpc_interaction(), grpc_interaction("other", key="k-2")])
    variant = copy.deepcopy(document)
    variant["metadata"]["pactRust"] = {"version": "1.2.3"}
    variant["consumer"] = {"name": "renamed"}
    assert _compile(document).digest == _compile(variant).digest
    assert _compile(document).model_dump() == _compile(copy.deepcopy(document)).model_dump()


# ---------------------------------------------------------------------------------------------
# GraphQL
# ---------------------------------------------------------------------------------------------


def test_a_graphql_interaction_keeps_its_http_request_and_gains_the_operation() -> None:
    manifest = _compile(_http_pact([graphql_interaction()]))
    assert manifest.protocol == PROTOCOL_HTTP
    [case] = manifest.cases
    assert case.protocol == PROTOCOL_HTTP and case.request.path == "/graphql"
    assert case.graphql is not None
    assert (case.graphql.operationName, case.graphql.operation_type, case.graphql.field) == (
        "UserById",
        "query",
        "user",
    )
    assert case.graphql.variables == {"id": "7"}
    assert case.tags == ["pact", "graphql"]
    [finding] = [f for f in manifest.findings if f.code == CODE_PACT_GRAPHQL_SELECTIONS_NOT_MAPPED]
    assert finding.level == FINDING_INFO and "XPC-1.6" in finding.message and finding.pointer == "/interactions/0"


def test_the_selections_finding_is_reported_once_per_pact() -> None:
    manifest = _compile(_http_pact([graphql_interaction("a"), graphql_interaction("b")]))
    found = [f for f in manifest.findings if f.code == CODE_PACT_GRAPHQL_SELECTIONS_NOT_MAPPED]
    assert len(found) == 1 and found[0].message.startswith("2 interactions")


def test_a_graphql_subscription_is_unsupported() -> None:
    interaction = graphql_interaction(query="subscription OnEvent { onEvent { id } }", operation_name="OnEvent")
    manifest = _compile(_http_pact([interaction]))
    assert manifest.cases == []
    [item] = manifest.unsupported
    assert item.code == CODE_UNSUPPORTED_STREAMING and "subscription" in item.reason


def test_unreadable_graphql_is_replayed_as_plain_http_and_reported() -> None:
    interaction = graphql_interaction(query="query A { a } query B { b }", operation_name=None)
    manifest = _compile(_http_pact([interaction]))
    [case] = manifest.cases
    assert case.graphql is None and case.tags == ["pact"]
    [finding] = [f for f in manifest.findings if f.code == CODE_PACT_GRAPHQL_UNREADABLE]
    assert finding.level == FINDING_DEGRADED and "POST decides" in finding.message
    assert CODE_PACT_GRAPHQL_SELECTIONS_NOT_MAPPED not in _codes(manifest)


def test_a_plain_http_pact_gains_no_graphql_block_or_finding() -> None:
    interaction = {
        "description": "search",
        "request": {"method": "POST", "path": "/search", "body": {"query": "red shoes"}},
        "response": {"status": 200},
    }
    manifest = _compile(_http_pact([interaction]))
    assert manifest.cases[0].graphql is None
    assert not {CODE_PACT_GRAPHQL_UNREADABLE, CODE_PACT_GRAPHQL_SELECTIONS_NOT_MAPPED} & set(_codes(manifest))
