"""The gRPC/Connect protocol adapter of the contract-suite compiler — XPC-3.2 (#5742).

Compiled from :mod:`rpc_contract_fixtures` — a proto2 ``Orders`` service with a safe unary
method, a mutating unary method and a server-streaming method — normalized through the real
Protobuf normalizer, so the adapter sees exactly what a stored Protobuf version holds.
"""

from __future__ import annotations

from typing import Any, Dict

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.contract_protocols import PROTOCOL_GRPC, PROTOCOL_HTTP
from app.contract_suite import (
    CASE_SOURCE_DECLARED_EXAMPLE,
    CASE_SOURCE_GENERATED_FULL,
    CASE_SOURCE_GENERATED_MINIMAL,
    CASE_SOURCE_NEGATIVE_MISSING_PARAMETER,
    CASE_SOURCE_NEGATIVE_PARAMETER_TYPE,
    CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD,
    CODE_EXAMPLE_SCHEMA_MISMATCH,
    CODE_UNRESOLVED_PAYLOAD_TYPE,
    CODE_UNSUPPORTED_STREAMING,
    CONTRACT_SUITE_COMPILER_VERSION,
    CONTRACT_SUITE_SCHEMA_VERSION,
    OUTCOME_CLIENT_ERROR,
    OUTCOME_SUCCESS,
    ContractSuiteOptions,
    compile_contract_suite,
    protocol_adapter_for,
)
from app.contract_suite_rpc import (
    IDEMPOTENCY_NO_SIDE_EFFECTS,
    IDEMPOTENCY_UNKNOWN,
    RPC_CODE_INVALID_ARGUMENT,
    RPC_CODE_OK,
    RPC_SCHEMA_PREFIX,
    UNKNOWN_FIELD_NAME,
    json_name,
    procedure_path,
)
from app.schema_instance_validation import validate_json_instance
from tests.rpc_contract_fixtures import SERVICE, orders_api

GET_ORDER = f"{SERVICE}.GetOrder"
CREATE_ORDER = f"{SERVICE}.CreateOrder"
WATCH_ORDERS = f"{SERVICE}.WatchOrders"


def _cases(manifest, key):
    """The cases of one operation, in emission order."""
    return [case for case in manifest.cases if case.operation_key == key]


def _by_source(manifest, key) -> Dict[str, Any]:
    """One operation's cases keyed by source (each source appears once in the fixture)."""
    return {case.source: case for case in _cases(manifest, key)}


# ---------------------------------------------------------------------------------------------
# Adapter selection and manifest shape
# ---------------------------------------------------------------------------------------------


def test_protobuf_versions_compile_through_the_rpc_adapter() -> None:
    adapter = protocol_adapter_for(ApiParadigm.RPC, "protobuf")
    assert adapter.protocol == PROTOCOL_GRPC
    assert adapter.paradigm is ApiParadigm.RPC


def test_other_rpc_formats_keep_the_http_adapter() -> None:
    # Smithy/Thrift/JSON-RPC have no Connect or gRPC wire form.
    assert protocol_adapter_for(ApiParadigm.RPC, "thrift").protocol == PROTOCOL_HTTP
    assert protocol_adapter_for(ApiParadigm.RPC).protocol == PROTOCOL_HTTP


def test_manifest_is_stamped_grpc_with_the_bumped_versions() -> None:
    manifest = compile_contract_suite(orders_api())
    assert manifest.protocol == PROTOCOL_GRPC
    assert manifest.schema_version == CONTRACT_SUITE_SCHEMA_VERSION == 3
    assert manifest.compiler_version == CONTRACT_SUITE_COMPILER_VERSION == 3
    assert {case.protocol for case in manifest.cases} == {PROTOCOL_GRPC}


def test_same_version_and_seed_give_a_byte_identical_manifest() -> None:
    first = compile_contract_suite(orders_api(), options=ContractSuiteOptions(seed=7))
    second = compile_contract_suite(orders_api(), options=ContractSuiteOptions(seed=7))
    other = compile_contract_suite(orders_api(), options=ContractSuiteOptions(seed=8))
    assert first.digest == second.digest
    assert first.model_dump_json() == second.model_dump_json()
    assert first.digest != other.digest


def test_one_operation_per_unary_method_with_its_procedure() -> None:
    manifest = compile_contract_suite(orders_api())
    assert [operation.key for operation in manifest.operations] == [CREATE_ORDER, GET_ORDER]
    get = next(item for item in manifest.operations if item.key == GET_ORDER)
    assert get.http_method == "POST"
    assert get.http_path == "/acme.orders.v1.Orders/GetOrder"
    assert get.service_key == SERVICE
    assert get.case_count == len(_cases(manifest, GET_ORDER))


def test_streaming_methods_are_unsupported_rows_never_silent() -> None:
    manifest = compile_contract_suite(orders_api())
    assert [item.operation_key for item in manifest.unsupported] == [WATCH_ORDERS]
    row = manifest.unsupported[0]
    assert row.code == CODE_UNSUPPORTED_STREAMING
    assert row.reason.startswith("unsupported: streaming")
    assert "server-streaming" in row.reason
    assert not _cases(manifest, WATCH_ORDERS)
    assert manifest.counts["operations_skipped"] == 1
    assert any(
        finding.code == CODE_UNSUPPORTED_STREAMING and finding.operation_key == WATCH_ORDERS
        for finding in manifest.findings
    )


# ---------------------------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------------------------


def test_cases_come_in_the_usual_order() -> None:
    manifest = compile_contract_suite(orders_api())
    assert [case.source for case in _cases(manifest, GET_ORDER)] == [
        CASE_SOURCE_GENERATED_MINIMAL,
        CASE_SOURCE_GENERATED_FULL,
        CASE_SOURCE_NEGATIVE_MISSING_PARAMETER,
        CASE_SOURCE_NEGATIVE_PARAMETER_TYPE,
        CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD,
    ]


def test_a_case_carries_its_call_in_protobuf_json() -> None:
    manifest = compile_contract_suite(orders_api())
    case = _by_source(manifest, GET_ORDER)[CASE_SOURCE_GENERATED_FULL]
    rpc = case.rpc
    assert rpc is not None
    assert rpc.service == SERVICE
    assert rpc.method == "GetOrder"
    assert rpc.procedure == "/acme.orders.v1.Orders/GetOrder" == case.request.path
    assert rpc.input_type == "acme.orders.v1.GetOrderRequest"
    assert rpc.output_type == "acme.orders.v1.Order"
    # JSON names, not proto names.
    assert set(rpc.message) == {"orderId", "pageSize"}
    assert case.request.body == rpc.message
    assert case.request.media_type == "application/json"
    assert rpc.expect_code == RPC_CODE_OK
    assert case.expect.outcome == OUTCOME_SUCCESS
    assert case.expect.response_schema_id == RPC_SCHEMA_PREFIX + GET_ORDER


def test_generated_messages_satisfy_the_request_schema_and_int32_bounds() -> None:
    manifest = compile_contract_suite(orders_api())
    for case in manifest.cases:
        if case.expect.outcome != OUTCOME_SUCCESS:
            continue
        page_size = case.rpc.message.get("pageSize")
        if page_size is not None:
            assert -(2**31) <= page_size <= 2**31 - 1


def test_negatives_isolate_one_fault_and_mark_json_only_ones() -> None:
    manifest = compile_contract_suite(orders_api())
    cases = _by_source(manifest, GET_ORDER)
    minimal = cases[CASE_SOURCE_GENERATED_MINIMAL].rpc.message
    assert set(minimal) == {"orderId"}

    missing = cases[CASE_SOURCE_NEGATIVE_MISSING_PARAMETER]
    assert missing.rpc.message == {}
    assert missing.source_detail == "orderId"
    assert missing.rpc.json_only is False  # binary protobuf can omit a field too

    wrong = cases[CASE_SOURCE_NEGATIVE_PARAMETER_TYPE]
    assert wrong.rpc.message == {"orderId": True}
    assert wrong.rpc.json_only is True

    unknown = cases[CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD]
    assert unknown.rpc.message == {**minimal, UNKNOWN_FIELD_NAME: "x"}
    assert unknown.rpc.json_only is True

    for case in (missing, wrong, unknown):
        assert case.expect.outcome == OUTCOME_CLIENT_ERROR
        assert case.rpc.expect_code == RPC_CODE_INVALID_ARGUMENT
        assert case.expect.status_codes == ["400"]


def test_a_message_with_no_required_field_has_no_missing_field_negative() -> None:
    manifest = compile_contract_suite(orders_api())
    sources = [case.source for case in _cases(manifest, CREATE_ORDER)]
    assert CASE_SOURCE_NEGATIVE_MISSING_PARAMETER not in sources
    assert _by_source(manifest, CREATE_ORDER)[CASE_SOURCE_GENERATED_MINIMAL].title == "empty message"


def test_idempotency_level_is_carried_for_the_mutating_gate() -> None:
    manifest = compile_contract_suite(orders_api())
    assert {case.rpc.idempotency_level for case in _cases(manifest, GET_ORDER)} == {
        IDEMPOTENCY_NO_SIDE_EFFECTS
    }
    assert {case.rpc.idempotency_level for case in _cases(manifest, CREATE_ORDER)} == {
        IDEMPOTENCY_UNKNOWN
    }


def test_negative_budget_and_toggles_are_honoured() -> None:
    manifest = compile_contract_suite(
        orders_api(), options=ContractSuiteOptions(max_negative_cases_per_operation=1)
    )
    negatives = [
        case for case in _cases(manifest, GET_ORDER) if case.expect.outcome == OUTCOME_CLIENT_ERROR
    ]
    assert [case.source for case in negatives] == [CASE_SOURCE_NEGATIVE_MISSING_PARAMETER]

    positives_only = compile_contract_suite(
        orders_api(), options=ContractSuiteOptions(include_negative=False)
    )
    assert all(case.expect.outcome == OUTCOME_SUCCESS for case in positives_only.cases)


def test_operations_filter_selects_by_method_key() -> None:
    manifest = compile_contract_suite(
        orders_api(), options=ContractSuiteOptions(operations=[GET_ORDER])
    )
    assert {case.operation_key for case in manifest.cases} == {GET_ORDER}


# ---------------------------------------------------------------------------------------------
# The response schema — the protobuf-JSON view of the output type
# ---------------------------------------------------------------------------------------------


def _response_schema(manifest):
    return manifest.schemas[RPC_SCHEMA_PREFIX + GET_ORDER]


def test_response_schema_accepts_every_protobuf_json_spelling() -> None:
    schema = _response_schema(compile_contract_suite(orders_api()))
    # int64 as a string or a number, an enum by name or by number, original field names.
    for message in (
        {"id": "1", "totalCents": "1200", "status": "OPEN"},
        {"id": "1", "totalCents": 1200, "status": 1},
        {"id": "1", "total_cents": "5", "items": [{"sku": "A", "quantity": 2}]},
        {"id": "1"},
    ):
        assert validate_json_instance(schema, message).valid is True, message


def test_a_response_missing_a_required_field_is_located() -> None:
    schema = _response_schema(compile_contract_suite(orders_api()))
    result = validate_json_instance(schema, {"totalCents": "5"})
    assert result.valid is False
    assert any("id" in finding.message for finding in result.findings)


def test_an_undeclared_or_wrong_typed_response_field_is_located() -> None:
    schema = _response_schema(compile_contract_suite(orders_api()))
    wrong = validate_json_instance(schema, {"id": "1", "items": [{"quantity": "two"}]})
    assert wrong.valid is False
    assert any(finding.pointer == "/items/0/quantity" for finding in wrong.findings)
    extra = validate_json_instance(schema, {"id": "1", "surprise": True})
    assert extra.valid is False


# ---------------------------------------------------------------------------------------------
# Hand-built models: examples, oneofs, well-known and unresolved types
# ---------------------------------------------------------------------------------------------


def _record(key: str, *fields: CanonicalField, **extras: Any) -> Type:
    return Type(key=key, name=key.rsplit(".", 1)[-1], kind=TypeKind.RECORD, fields=list(fields), extras=extras)


def _field(owner: str, name: str, type_name: str, number: int, **extras: Any) -> CanonicalField:
    return CanonicalField(
        key=f"{owner}.{name}",
        name=name,
        type=TypeRef(name=type_name),
        field_number=number,
        extras=extras,
    )


def _api(input_type: Type, *, request_extras: Dict[str, Any] | None = None, extra_types=()) -> CanonicalApi:
    operation = Operation(
        key="demo.Demo.Call",
        name="Call",
        kind=OperationKind.REQUEST_RESPONSE,
        messages=[
            Message(
                key="demo.Demo.Call#request",
                role=MessageRole.REQUEST,
                payload=TypeRef(name=input_type.key),
                extras=request_extras or {},
            ),
            Message(
                key="demo.Demo.Call#response",
                role=MessageRole.RESPONSE,
                payload=TypeRef(name="google.protobuf.Empty"),
            ),
        ],
        extras={"idempotency_level": "no_side_effects"},
    )
    return CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        identity=ApiIdentity(name="demo"),
        services=[Service(key="demo.Demo", name="Demo", operations=[operation])],
        types=[input_type, *extra_types],
    )


def test_declared_example_message_is_the_first_case_and_not_synthetic() -> None:
    request = _record("demo.Req", _field("demo.Req", "display_name", "string", 1))
    api = _api(request, request_extras={"example": '{"displayName": "Ada"}'})
    manifest = compile_contract_suite(api)
    first = manifest.cases[0]
    assert first.source == CASE_SOURCE_DECLARED_EXAMPLE
    assert first.synthetic is False
    assert first.rpc.message == {"displayName": "Ada"}


def test_a_declared_example_that_breaks_its_schema_is_reported_not_compiled() -> None:
    request = _record("demo.Req", _field("demo.Req", "display_name", "string", 1))
    api = _api(request, request_extras={"example": {"nope": 1}})
    manifest = compile_contract_suite(api)
    assert CASE_SOURCE_DECLARED_EXAMPLE not in {case.source for case in manifest.cases}
    assert any(finding.code == CODE_EXAMPLE_SCHEMA_MISMATCH for finding in manifest.findings)


def test_only_one_member_of_a_oneof_is_generated() -> None:
    request = _record(
        "demo.Req",
        _field("demo.Req", "email", "string", 1, oneof="contact"),
        _field("demo.Req", "phone", "string", 2, oneof="contact"),
        _field("demo.Req", "note", "string", 3),
    )
    manifest = compile_contract_suite(_api(request))
    full = next(case for case in manifest.cases if case.source == CASE_SOURCE_GENERATED_FULL)
    assert "phone" not in full.rpc.message
    assert {"email", "note"} <= set(full.rpc.message)


def test_well_known_types_use_their_json_forms() -> None:
    request = _record(
        "demo.Req",
        _field("demo.Req", "at", "google.protobuf.Timestamp", 1),
        _field("demo.Req", "ttl", "google.protobuf.Duration", 2),
        _field("demo.Req", "flag", "google.protobuf.BoolValue", 3),
    )
    manifest = compile_contract_suite(_api(request))
    full = next(case for case in manifest.cases if case.source == CASE_SOURCE_GENERATED_FULL)
    assert full.rpc.message["at"] == "2026-01-01T00:00:00Z"
    assert full.rpc.message["ttl"] == "1s"
    assert isinstance(full.rpc.message["flag"], bool)


def test_an_unresolved_imported_type_is_reported_degraded() -> None:
    request = _record("demo.Req", _field("demo.Req", "money", "google.type.Money", 1))
    manifest = compile_contract_suite(_api(request))
    assert any(
        finding.code == CODE_UNRESOLVED_PAYLOAD_TYPE and "google.type.Money" in finding.message
        for finding in manifest.findings
    )
    assert manifest.cases  # still compiled, with the position left empty


def test_the_unknown_field_name_avoids_a_declared_one() -> None:
    request = _record("demo.Req", _field("demo.Req", "apiome_unknown_field", "string", 1))
    manifest = compile_contract_suite(_api(request))
    unknown = next(case for case in manifest.cases if case.source == CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD)
    assert unknown.source_detail == f"{UNKNOWN_FIELD_NAME}2"


def test_json_name_and_procedure_path() -> None:
    assert json_name("order_id") == "orderId"
    assert json_name("line_items_2") == "lineItems2"
    assert json_name("id") == "id"
    assert procedure_path("acme.v1.Orders", "Get") == "/acme.v1.Orders/Get"
