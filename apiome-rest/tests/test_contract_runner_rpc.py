"""The contract runner executing a gRPC-family suite — XPC-3.2 (#5742).

Two targets, one suite. The **Connect** target is an :class:`httpx.MockTransport` that decodes
each posted protobuf-JSON message with the fixture's real descriptors (``json_format``, strict) and
answers protobuf-JSON or a Connect error object. The **gRPC** target is a real in-process
``grpcio`` server on a loopback port, with server reflection enabled, so the runner's reflection,
binary encoding, deadline and decoding all run for real. A conforming server passes every case it
is sent; each test bends it in exactly one way to prove the judge notices.
"""

from __future__ import annotations

import json
from concurrent import futures
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, Optional

import grpc
import httpx
import pytest
from google.protobuf import json_format, message_factory
from grpc_reflection.v1alpha import reflection

from app.contract_protocols import PROTOCOL_CONNECT, PROTOCOL_GRPC
from app.contract_runner import (
    FAILURE_MUTATING_METHOD_BLOCKED,
    FAILURE_RESPONSE_SCHEMA_MISMATCH,
    FAILURE_TRANSPORT_ERROR,
    is_mutating_case,
    run_suite,
)
from app.contract_runner_rpc import (
    CONNECT_PROTOCOL_VERSION,
    FAILURE_RPC_DESCRIPTOR_MISMATCH,
    FAILURE_RPC_JSON_ONLY,
    FAILURE_RPC_REFLECTION_UNAVAILABLE,
    FAILURE_RPC_RESPONSE_UNDECODABLE,
    FAILURE_RPC_STATUS_MISMATCH,
    connect_code_for_http_status,
)
from app.contract_suite import (
    CASE_SOURCE_GENERATED_MINIMAL,
    CASE_SOURCE_NEGATIVE_MISSING_PARAMETER,
    CASE_SOURCE_NEGATIVE_PARAMETER_TYPE,
    CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD,
    ContractSuiteManifest,
    compile_contract_suite,
)
from app.verification_evidence import (
    ASSERTION_KIND_RESPONSE_SCHEMA,
    OPERATION_OUTCOME_ERRORED,
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
from tests.rpc_contract_fixtures import PACKAGE, SERVICE, orders_api, orders_pool

BASE_URL = "http://mock.test/acme/orders/1.0.0"
GET_ORDER = f"{SERVICE}.GetOrder"
CREATE_ORDER = f"{SERVICE}.CreateOrder"

_POOL = orders_pool()
_GET_REQUEST = message_factory.GetMessageClass(
    _POOL.FindMessageTypeByName(f"{PACKAGE}.GetOrderRequest")
)
_CREATE_REQUEST = message_factory.GetMessageClass(
    _POOL.FindMessageTypeByName(f"{PACKAGE}.CreateOrderRequest")
)
_ORDER = message_factory.GetMessageClass(_POOL.FindMessageTypeByName(f"{PACKAGE}.Order"))


def _manifest() -> ContractSuiteManifest:
    """The fixture's suite under default options."""
    return compile_contract_suite(orders_api())


def _target(protocol: str, base_url: str = BASE_URL, **policy: Any) -> ResolvedTarget:
    """A resolved private target speaking ``protocol``."""
    return ResolvedTarget(
        target_id="44444444-4444-4444-8444-444444444444",
        slug=f"{protocol}-dev",
        name=f"{protocol} dev",
        environment="mock",
        network_class=NETWORK_CLASS_PRIVATE,
        base_url=base_url,
        protocol=protocol,
        policy=VerificationPolicy(retry_attempts=0, **policy),
        auth=TargetAuthReference(),
        resolved_at=datetime(2026, 11, 14, tzinfo=timezone.utc),
    )


def _by_source(result, key: str) -> Dict[str, Any]:
    """Operation records of one method keyed by case source."""
    return {op.case_source: op for op in result.operations if op.operation_key == key}


def _order(request) -> Any:
    """What a conforming GetOrder handler returns."""
    return _ORDER(id=request.order_id, total_cents=1200, status=1)


# ---------------------------------------------------------------------------------------------
# Connect
# ---------------------------------------------------------------------------------------------


def _connect_server(
    respond: Optional[Callable[[str, Any], Optional[httpx.Response]]] = None,
    seen: Optional[list] = None,
) -> httpx.Client:
    """A conforming Connect server for the fixture, optionally overridden per request."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        procedure = request.url.path.removeprefix("/acme/orders/1.0.0")
        classes = {
            f"/{SERVICE}/GetOrder": _GET_REQUEST,
            f"/{SERVICE}/CreateOrder": _CREATE_REQUEST,
        }
        if procedure not in classes:
            return httpx.Response(404, json={"code": "unimplemented", "message": procedure})
        message = classes[procedure]()
        try:
            json_format.Parse(request.content.decode("utf-8"), message)
        except json_format.ParseError as exc:
            return httpx.Response(400, json={"code": "invalid_argument", "message": str(exc)})
        if not message.IsInitialized():
            return httpx.Response(
                400, json={"code": "invalid_argument", "message": "order_id is required"}
            )
        if respond is not None:
            override = respond(procedure, message)
            if override is not None:
                return override
        reply = _order(message) if procedure.endswith("GetOrder") else _ORDER(id="new")
        return httpx.Response(200, json=json_format.MessageToDict(reply))

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_conforming_connect_server_passes_every_case_it_is_sent() -> None:
    result = run_suite(
        _manifest(),
        _target(PROTOCOL_CONNECT, allow_mutating_methods=True),
        client=_connect_server(),
    )
    outcomes = {(op.operation_key, op.case_source): op.outcome for op in result.operations}
    assert set(outcomes.values()) == {OPERATION_OUTCOME_PASSED}, outcomes
    assert (GET_ORDER, CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD) in outcomes


def test_connect_requests_follow_the_protocol() -> None:
    seen: list = []
    run_suite(_manifest(), _target(PROTOCOL_CONNECT), client=_connect_server(seen=seen))
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == f"/acme/orders/1.0.0/{SERVICE}/GetOrder"
    assert request.headers["content-type"] == "application/json"
    assert request.headers["connect-protocol-version"] == CONNECT_PROTOCOL_VERSION
    assert request.headers["connect-timeout-ms"] == "30000"


def test_connect_records_procedure_and_codes_on_evidence() -> None:
    result = run_suite(_manifest(), _target(PROTOCOL_CONNECT), client=_connect_server())
    minimal = _by_source(result, GET_ORDER)[CASE_SOURCE_GENERATED_MINIMAL]
    assert minimal.http_method == "POST"
    assert minimal.http_path == f"/{SERVICE}/GetOrder"
    assert minimal.expected_status == "ok"
    assert minimal.actual_status == 200
    negative = _by_source(result, GET_ORDER)[CASE_SOURCE_NEGATIVE_MISSING_PARAMETER]
    assert negative.outcome == OPERATION_OUTCOME_PASSED
    assert negative.expected_status == "invalid_argument"
    assert negative.actual_status == 400


def test_a_response_missing_a_required_field_fails_with_the_pointer() -> None:
    def drop_id(procedure: str, message: Any) -> Optional[httpx.Response]:
        return httpx.Response(200, json={"totalCents": "5"})

    result = run_suite(_manifest(), _target(PROTOCOL_CONNECT), client=_connect_server(drop_id))
    record = _by_source(result, GET_ORDER)[CASE_SOURCE_GENERATED_MINIMAL]
    assert record.outcome == OPERATION_OUTCOME_FAILED
    assert record.failure_code == FAILURE_RESPONSE_SCHEMA_MISMATCH
    schema_assertions = [
        item for item in record.assertions if item.kind == ASSERTION_KIND_RESPONSE_SCHEMA
    ]
    assert any("id" in (item.message or item.actual or "") for item in schema_assertions)


def test_a_wrong_typed_response_field_is_located_by_pointer() -> None:
    def bad_items(procedure: str, message: Any) -> Optional[httpx.Response]:
        return httpx.Response(200, json={"id": "1", "items": [{"quantity": "two"}]})

    result = run_suite(_manifest(), _target(PROTOCOL_CONNECT), client=_connect_server(bad_items))
    record = _by_source(result, GET_ORDER)[CASE_SOURCE_GENERATED_MINIMAL]
    assert record.failure_code == FAILURE_RESPONSE_SCHEMA_MISMATCH
    assert "/items/0/quantity" in {item.subject for item in record.assertions}


def test_a_lenient_server_fails_the_negative_cases() -> None:
    def accept_everything(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "1"})

    client = httpx.Client(transport=httpx.MockTransport(accept_everything))
    result = run_suite(_manifest(), _target(PROTOCOL_CONNECT), client=client)
    unknown = _by_source(result, GET_ORDER)[CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD]
    assert unknown.outcome == OPERATION_OUTCOME_FAILED
    assert unknown.failure_code == FAILURE_RPC_STATUS_MISMATCH
    assert "expected status `invalid_argument`, got `ok`" in unknown.failure_message


def test_an_error_on_a_success_case_names_the_connect_code() -> None:
    def internal(procedure: str, message: Any) -> Optional[httpx.Response]:
        return httpx.Response(500, json={"code": "internal", "message": "db down"})

    result = run_suite(_manifest(), _target(PROTOCOL_CONNECT), client=_connect_server(internal))
    record = _by_source(result, GET_ORDER)[CASE_SOURCE_GENERATED_MINIMAL]
    assert record.failure_code == FAILURE_RPC_STATUS_MISMATCH
    assert "got `internal`: db down" in record.failure_message


def test_a_codeless_error_body_is_mapped_from_its_http_status() -> None:
    def gateway(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream unavailable")

    client = httpx.Client(transport=httpx.MockTransport(gateway))
    result = run_suite(_manifest(), _target(PROTOCOL_CONNECT), client=client)
    record = _by_source(result, GET_ORDER)[CASE_SOURCE_GENERATED_MINIMAL]
    assert "got `unavailable`" in record.failure_message
    assert connect_code_for_http_status(400) == "internal"
    assert connect_code_for_http_status(404) == "unimplemented"
    assert connect_code_for_http_status(418) == "unknown"


def test_a_non_message_success_body_is_undecodable() -> None:
    def text(procedure: str, message: Any) -> Optional[httpx.Response]:
        return httpx.Response(200, text="hello")

    result = run_suite(_manifest(), _target(PROTOCOL_CONNECT), client=_connect_server(text))
    record = _by_source(result, GET_ORDER)[CASE_SOURCE_GENERATED_MINIMAL]
    assert record.failure_code == FAILURE_RPC_RESPONSE_UNDECODABLE


def test_a_connect_transport_failure_is_errored_after_retries() -> None:
    calls = {"n": 0}

    def down(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(down))
    manifest = compile_contract_suite(orders_api())
    manifest = manifest.model_copy(update={"cases": manifest.cases[-1:]})
    target = _target(PROTOCOL_CONNECT, allow_mutating_methods=True)
    target = target.model_copy(
        update={"policy": target.policy.model_copy(update={"retry_attempts": 2})}
    )
    result = run_suite(manifest, target, client=client)
    record = result.operations[0]
    assert record.outcome == OPERATION_OUTCOME_ERRORED
    assert record.failure_code == FAILURE_TRANSPORT_ERROR
    assert record.attempts == 3
    assert calls["n"] == 3


# ---------------------------------------------------------------------------------------------
# Mutating gate
# ---------------------------------------------------------------------------------------------


def test_methods_without_no_side_effects_obey_the_mutating_gate() -> None:
    manifest = _manifest()
    get = next(case for case in manifest.cases if case.operation_key == GET_ORDER)
    create = next(case for case in manifest.cases if case.operation_key == CREATE_ORDER)
    assert is_mutating_case(get) is False
    assert is_mutating_case(create) is True

    result = run_suite(manifest, _target(PROTOCOL_CONNECT), client=_connect_server())
    for record in result.operations:
        if record.operation_key == CREATE_ORDER:
            assert record.outcome == OPERATION_OUTCOME_SKIPPED
            assert record.failure_code == FAILURE_MUTATING_METHOD_BLOCKED
            assert "NO_SIDE_EFFECTS" in record.failure_message


# ---------------------------------------------------------------------------------------------
# Native gRPC (in-process server with reflection)
# ---------------------------------------------------------------------------------------------


def _grpc_server(
    get_order: Optional[Callable[[Any, Any], bytes]] = None,
    *,
    reflect: bool = True,
) -> Iterator[int]:
    """Start a loopback gRPC server for the fixture and yield its port."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))

    def default_get(request: Any, context: Any) -> bytes:
        if not request.HasField("order_id"):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "order_id is required")
        return _order(request).SerializeToString()

    def create(request: Any, context: Any) -> bytes:
        return _ORDER(id="new").SerializeToString()

    handlers = {
        "GetOrder": grpc.unary_unary_rpc_method_handler(
            get_order or default_get,
            request_deserializer=_GET_REQUEST.FromString,
            response_serializer=lambda payload: payload,
        ),
        "CreateOrder": grpc.unary_unary_rpc_method_handler(
            create,
            request_deserializer=_CREATE_REQUEST.FromString,
            response_serializer=lambda payload: payload,
        ),
    }
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(SERVICE, handlers),))
    if reflect:
        reflection.enable_server_reflection((SERVICE, reflection.SERVICE_NAME), server, pool=_POOL)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    try:
        yield port
    finally:
        server.stop(0)


@pytest.fixture
def grpc_port() -> Iterator[int]:
    yield from _grpc_server()


def test_native_grpc_passes_over_reflection(grpc_port: int) -> None:
    result = run_suite(
        _manifest(),
        _target(PROTOCOL_GRPC, f"http://127.0.0.1:{grpc_port}", allow_mutating_methods=True),
    )
    records = {(op.operation_key, op.case_source): op for op in result.operations}
    minimal = records[(GET_ORDER, CASE_SOURCE_GENERATED_MINIMAL)]
    assert minimal.outcome == OPERATION_OUTCOME_PASSED
    assert minimal.actual_status is None  # no HTTP status over native gRPC
    missing = records[(GET_ORDER, CASE_SOURCE_NEGATIVE_MISSING_PARAMETER)]
    assert missing.outcome == OPERATION_OUTCOME_PASSED  # INVALID_ARGUMENT, as expected
    passed = {op.outcome for op in result.operations if op.failure_code != FAILURE_RPC_JSON_ONLY}
    assert passed == {OPERATION_OUTCOME_PASSED}


def test_json_only_negatives_are_skipped_over_native_grpc(grpc_port: int) -> None:
    result = run_suite(_manifest(), _target(PROTOCOL_GRPC, f"http://127.0.0.1:{grpc_port}"))
    get = _by_source(result, GET_ORDER)
    for source in (CASE_SOURCE_NEGATIVE_PARAMETER_TYPE, CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD):
        assert get[source].outcome == OPERATION_OUTCOME_SKIPPED
        assert get[source].failure_code == FAILURE_RPC_JSON_ONLY


def test_native_grpc_response_missing_a_required_field_fails_with_the_pointer() -> None:
    def no_id(request: Any, context: Any) -> bytes:
        return _ORDER(total_cents=5).SerializePartialToString()

    for port in _grpc_server(no_id):
        result = run_suite(_manifest(), _target(PROTOCOL_GRPC, f"http://127.0.0.1:{port}"))
    record = _by_source(result, GET_ORDER)[CASE_SOURCE_GENERATED_MINIMAL]
    assert record.outcome == OPERATION_OUTCOME_FAILED
    assert record.failure_code == FAILURE_RESPONSE_SCHEMA_MISMATCH
    assert "id" in (record.failure_message or "")


def test_native_grpc_without_reflection_is_errored_with_a_reason() -> None:
    for port in _grpc_server(reflect=False):
        result = run_suite(_manifest(), _target(PROTOCOL_GRPC, f"http://127.0.0.1:{port}"))
    record = _by_source(result, GET_ORDER)[CASE_SOURCE_GENERATED_MINIMAL]
    assert record.outcome == OPERATION_OUTCOME_ERRORED
    assert record.failure_code == FAILURE_RPC_REFLECTION_UNAVAILABLE
    assert "connect" in record.failure_message


def test_native_grpc_refuses_a_server_missing_the_contract_types(grpc_port: int) -> None:
    manifest = _manifest()
    case = next(item for item in manifest.cases if item.operation_key == GET_ORDER)
    renamed = case.model_copy(
        update={"rpc": case.rpc.model_copy(update={"input_type": f"{PACKAGE}.Missing"})}
    )
    manifest = manifest.model_copy(update={"cases": [renamed]})
    result = run_suite(manifest, _target(PROTOCOL_GRPC, f"http://127.0.0.1:{grpc_port}"))
    assert result.operations[0].failure_code == FAILURE_RPC_DESCRIPTOR_MISMATCH


def test_a_public_grpc_target_is_vetted_by_the_ssrf_guard() -> None:
    target = _target(PROTOCOL_GRPC, "http://127.0.0.1:1").model_copy(
        update={"network_class": "public"}
    )
    result = run_suite(_manifest(), target)
    record = _by_source(result, GET_ORDER)[CASE_SOURCE_GENERATED_MINIMAL]
    assert record.outcome == OPERATION_OUTCOME_ERRORED
    assert "SSRF" in record.failure_message


def test_evidence_records_are_json_serializable() -> None:
    result = run_suite(_manifest(), _target(PROTOCOL_CONNECT), client=_connect_server())
    for record in result.operations:
        json.dumps(record.model_dump(mode="json"))
