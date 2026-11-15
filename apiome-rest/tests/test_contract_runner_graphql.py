"""The contract runner executing a GraphQL suite — XPC-1.2 (#5730).

The target is a real GraphQL server in miniature: an :class:`httpx.MockTransport` that parses the
posted GraphQL-over-HTTP body and executes it with graphql-core against the same SDL the suite
was compiled from. A conforming server therefore passes every case, and each test bends it in
exactly one way to prove the judge notices.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx
from graphql import graphql_sync

from app.contract_protocols import PROTOCOL_GRAPHQL
from app.contract_runner import (
    FAILURE_GRAPHQL_ENVELOPE_INVALID,
    FAILURE_GRAPHQL_ERRORS_MISSING,
    FAILURE_GRAPHQL_ERRORS_PRESENT,
    FAILURE_MUTATING_METHOD_BLOCKED,
    FAILURE_RESPONSE_SCHEMA_MISMATCH,
    GRAPHQL_ACCEPT,
    is_mutating_case,
    run_suite,
)
from app.contract_suite import (
    CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD,
    ContractCase,
    ContractCaseExpectation,
    ContractCaseRequest,
    ContractSuiteManifest,
    compile_contract_suite,
)
from app.graphql_normalizer import GraphQlNormalizer
from app.graphql_parser import build_graphql_schema
from app.verification_evidence import (
    ASSERTION_KIND_CUSTOM,
    ASSERTION_KIND_RESPONSE_SCHEMA,
    OPERATION_OUTCOME_FAILED,
    OPERATION_OUTCOME_PASSED,
    OPERATION_OUTCOME_SKIPPED,
)
from app.verification_target import (
    NETWORK_CLASS_PRIVATE,
    ResolvedTarget,
    TargetAuthReference,
    VerificationPolicy,
)

SDL = '''
type Query {
  pet(id: ID!): Pet
  hello: String!
}
type Mutation { renamePet(id: ID!, name: String!): Pet }
type Pet { id: ID! name: String! tag: String }
'''

ENDPOINT = "http://mock.test/acme/pets/1.0.0/graphql"

PET = {"id": "1", "name": "Rex", "tag": None}

_SCHEMA = build_graphql_schema(SDL)


def _manifest() -> ContractSuiteManifest:
    """The suite of :data:`SDL` under default options."""
    return compile_contract_suite(GraphQlNormalizer().normalize(_SCHEMA))


def _target(**policy: Any) -> ResolvedTarget:
    """A resolved ``graphql`` target whose base URL is the endpoint itself."""
    return ResolvedTarget(
        target_id="22222222-2222-4222-8222-222222222222",
        slug="mock-graphql",
        name="Mock GraphQL",
        environment="mock",
        network_class=NETWORK_CLASS_PRIVATE,
        base_url=ENDPOINT,
        protocol=PROTOCOL_GRAPHQL,
        policy=VerificationPolicy(retry_attempts=0, **policy),
        auth=TargetAuthReference(),
        resolved_at=datetime(2026, 11, 14, tzinfo=timezone.utc),
    )


def _server(
    root: Optional[Dict[str, Any]] = None,
    *,
    seen: Optional[List[httpx.Request]] = None,
    rewrite: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = None,
) -> httpx.Client:
    """A client whose transport executes every posted document with graphql-core.

    Args:
        root: Root value the resolvers read.
        seen: Collects every request the transport received.
        rewrite: Bends the result document ``(request_body, result) -> result`` before it is
            sent, to simulate a non-conforming server.
    """
    values = root if root is not None else {"pet": PET, "hello": "hi", "renamePet": PET}

    def resolve(obj: Any, info: Any, **_: Any) -> Any:
        return obj.get(info.field_name) if isinstance(obj, dict) else None

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        body = json.loads(request.content)
        result = graphql_sync(
            _SCHEMA,
            body["query"],
            root_value=values,
            variable_values=body.get("variables"),
            operation_name=body.get("operationName"),
            field_resolver=resolve,
        )
        document: Dict[str, Any] = {}
        if result.errors:
            document["errors"] = [{"message": error.message} for error in result.errors]
        if result.data is not None or not result.errors:
            document["data"] = result.data
        if rewrite is not None:
            document = rewrite(body, document)
        return httpx.Response(200, json=document)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_conforming_server_passes_every_query_case() -> None:
    manifest = _manifest()
    seen: List[httpx.Request] = []
    result = run_suite(
        manifest, _target(allow_mutating_methods=True), client=_server(seen=seen)
    )
    outcomes = {op.outcome for op in result.operations}
    assert outcomes == {OPERATION_OUTCOME_PASSED}, [
        (op.operation_key, op.case_source, op.failure_message) for op in result.operations
    ]
    assert len(result.operations) == len(manifest.cases)
    # Posted to the endpoint itself — the case's "/" path is never joined onto it.
    assert {str(request.url) for request in seen} == {ENDPOINT}
    assert {request.method for request in seen} == {"POST"}
    assert all(request.headers["accept"] == GRAPHQL_ACCEPT for request in seen)
    assert all(request.headers["content-type"] == "application/json" for request in seen)


def test_mutations_obey_the_mutating_method_gate_and_queries_do_not() -> None:
    manifest = _manifest()
    result = run_suite(manifest, _target(allow_mutating_methods=False), client=_server())
    for op in result.operations:
        if op.operation_key.startswith("Mutation."):
            assert op.outcome == OPERATION_OUTCOME_SKIPPED
            assert op.failure_code == FAILURE_MUTATING_METHOD_BLOCKED
            assert "GraphQL mutation" in (op.failure_message or "")
        else:
            assert op.outcome == OPERATION_OUTCOME_PASSED


def test_is_mutating_case_reads_the_operation_type_for_graphql() -> None:
    manifest = _manifest()
    kinds = {case.operation_key: is_mutating_case(case) for case in manifest.cases}
    assert kinds["Query.pet"] is False
    assert kinds["Mutation.renamePet"] is True


def test_is_mutating_case_reads_the_method_for_http() -> None:
    def case(method: str) -> ContractCase:
        return ContractCase(
            case_id=method,
            operation_key=f"{method} /pets",
            operation_name="pets",
            source="generated_minimal",
            title=method,
            description="d",
            synthetic=True,
            request=ContractCaseRequest(method=method, path_template="/pets", path="/pets"),
            expect=ContractCaseExpectation(
                outcome="success", status_codes=["200"], status_declared=True, reason="r"
            ),
        )

    assert is_mutating_case(case("GET")) is False
    assert is_mutating_case(case("POST")) is True


def test_a_drifted_field_is_located_with_a_pointer_into_data() -> None:
    """Acceptance: schema findings are pointer-located, as the REST judge does."""

    def drift(_: Dict[str, Any], document: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(document.get("data"), dict) and isinstance(document["data"].get("pet"), dict):
            document["data"]["pet"]["name"] = 42
        return document

    result = run_suite(_manifest(), _target(), client=_server(rewrite=drift))
    failed = [
        op
        for op in result.operations
        if op.operation_key == "Query.pet" and op.outcome == OPERATION_OUTCOME_FAILED
    ]
    assert failed, "the drifted field went unnoticed"
    op = failed[0]
    assert op.failure_code == FAILURE_RESPONSE_SCHEMA_MISMATCH
    pointers = [
        assertion.subject
        for assertion in op.assertions
        if assertion.kind == ASSERTION_KIND_RESPONSE_SCHEMA and assertion.subject != "graphql:Query.pet"
    ]
    assert "/pet/name" in pointers


def test_a_success_case_answered_with_errors_fails() -> None:
    def add_error(_: Dict[str, Any], document: Dict[str, Any]) -> Dict[str, Any]:
        return {**document, "errors": [{"message": "resolver exploded"}]}

    result = run_suite(_manifest(), _target(), client=_server(rewrite=add_error))
    hello = next(op for op in result.operations if op.operation_key == "Query.hello")
    assert hello.outcome == OPERATION_OUTCOME_FAILED
    assert hello.failure_code == FAILURE_GRAPHQL_ERRORS_PRESENT
    assert "resolver exploded" in (hello.failure_message or "")
    assertion = next(a for a in hello.assertions if a.kind == ASSERTION_KIND_CUSTOM)
    assert assertion.subject == "errors"


def test_a_negative_case_answered_without_errors_fails() -> None:
    def swallow(_: Dict[str, Any], document: Dict[str, Any]) -> Dict[str, Any]:
        return {"data": {"pet": PET}}

    result = run_suite(_manifest(), _target(), client=_server(rewrite=swallow))
    unknown = next(
        op
        for op in result.operations
        if op.operation_key == "Query.pet" and op.case_source == CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD
    )
    assert unknown.outcome == OPERATION_OUTCOME_FAILED
    assert unknown.failure_code == FAILURE_GRAPHQL_ERRORS_MISSING


def test_a_negative_case_may_be_answered_with_a_4xx() -> None:
    """GraphQL over HTTP lets a server reject a request error with 400; that still passes."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"errors": [{"message": "bad request"}]})

    manifest = _manifest()
    negatives = ContractSuiteManifest(
        **{
            **manifest.model_dump(),
            "cases": [case for case in manifest.cases if case.expect.outcome == "client_error"],
        }
    )
    result = run_suite(
        negatives, _target(allow_mutating_methods=True),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert result.operations
    assert {op.outcome for op in result.operations} == {OPERATION_OUTCOME_PASSED}


def test_a_body_that_is_not_a_graphql_document_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway</html>")

    result = run_suite(
        _manifest(), _target(), client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    hello = next(op for op in result.operations if op.operation_key == "Query.hello")
    assert hello.outcome == OPERATION_OUTCOME_FAILED
    assert hello.failure_code == FAILURE_GRAPHQL_ENVELOPE_INVALID
