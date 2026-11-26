"""Unit tests for :mod:`app.pact_plugin_grpc` — PFX-3.7 (#6937).

A protobuf-plugin interaction is read onto the XPC-3.2 unary-call model through the descriptors
the pact files: the service and method resolve (short or qualified name), the request and reply
decode to protobuf-JSON, the expected status comes from ``grpc-status``, and every way it cannot
be read is a problem with a stable code — never a silent skip.
"""

from __future__ import annotations

import base64
from typing import Any, Dict

import pytest
from google.protobuf import descriptor_pb2, descriptor_pool

from app.pact_matching_rules import parse_path
from app.pact_plugin_grpc import (
    CODE_GRPC_CONTENT_UNREADABLE,
    CODE_GRPC_DESCRIPTORS_MISSING,
    CODE_GRPC_METHOD_NOT_FOUND,
    CODE_GRPC_STREAMING,
    INT64_PATTERN,
    DescriptorCatalog,
    grpc_status_code,
    int64_matcher,
    is_grpc_plugin_interaction,
    plugin_names,
    read_grpc_interaction,
    rename_rule_path,
)
from tests.pact_plugin_fixtures import DESCRIPTOR_KEY, contents, grpc_interaction, grpc_pact
from tests.rpc_contract_fixtures import PACKAGE, SERVICE, orders_descriptor_set, orders_pool


def _read(interaction: Dict[str, Any], document: Dict[str, Any] = None):
    """Read one interaction against the fixture pact's descriptors."""
    pact = document if document is not None else grpc_pact([interaction])
    return read_grpc_interaction(interaction, "/interactions/0", DescriptorCatalog(pact))


# ---------------------------------------------------------------------------------------------
# Recognition
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "interaction, expected",
    [
        ({"type": "Synchronous/Messages", "transport": "grpc"}, True),
        ({"type": "Synchronous/HTTP", "transport": "GRPC"}, True),
        ({"type": "Synchronous/Messages", "pluginConfiguration": {"protobuf": {}}}, True),
        ({"type": "Synchronous/Messages"}, False),
        ({"type": "Synchronous/HTTP", "pluginConfiguration": {"protobuf": {}}}, False),
        ({"type": "Asynchronous/Messages", "pluginConfiguration": {"protobuf": {}}}, False),
        ({"type": "Synchronous/HTTP"}, False),
    ],
)
def test_a_grpc_call_is_recognised_by_its_transport_or_plugin(interaction: Dict[str, Any], expected: bool) -> None:
    assert is_grpc_plugin_interaction(interaction) is expected


def test_plugin_names_are_sorted_and_tolerate_junk() -> None:
    assert plugin_names({"pluginConfiguration": {"protobuf": {}, "csv": {}}}) == ["csv", "protobuf"]
    assert plugin_names({"pluginConfiguration": "protobuf"}) == []
    assert plugin_names({}) == []


@pytest.mark.parametrize(
    "value, expected",
    [
        ("NOT_FOUND", "not_found"),
        ("not_found", "not_found"),
        (5, "not_found"),
        ("5", "not_found"),
        (["INVALID_ARGUMENT"], "invalid_argument"),
        ("OK", "ok"),
        ("TEAPOT", None),
        (99, None),
        (True, None),
        ("", None),
        (None, None),
    ],
)
def test_a_recorded_grpc_status_normalises_to_the_runners_code(value: Any, expected: Any) -> None:
    assert grpc_status_code(value) == expected


# ---------------------------------------------------------------------------------------------
# A readable call
# ---------------------------------------------------------------------------------------------


def test_a_unary_call_reads_onto_procedure_types_and_protobuf_json() -> None:
    call, problem = _read(grpc_interaction())
    assert problem is None and call is not None
    assert (call.service, call.method, call.procedure) == (SERVICE, "GetOrder", f"/{SERVICE}/GetOrder")
    assert (call.input_type, call.output_type) == (f"{PACKAGE}.GetOrderRequest", f"{PACKAGE}.Order")
    assert call.idempotency_level == "no_side_effects"
    assert call.message == {"orderId": "1042"}
    assert call.expect_code == "ok" and call.has_body
    # protobuf-JSON: JSON names, int64 as a decimal string, enums by name.
    assert call.body == {"id": "1042", "totalCents": "1200", "status": "OPEN"}
    assert call.response_pointer == "/interactions/0/response/0"
    assert call.notes == []


def test_a_qualified_service_name_resolves_too_and_a_method_without_options_is_unknown() -> None:
    interaction = grpc_interaction(
        service=f"{SERVICE}/CreateOrder",
        request={"contents": contents("CreateOrderRequest", {"customerId": "c-1"})},
        response=[{"contents": contents("Order", {"id": "9"})}],
    )
    call, problem = _read(interaction)
    assert problem is None and call is not None
    assert call.idempotency_level == "unknown"
    assert call.message == {"customerId": "c-1"}


def test_an_empty_request_is_the_empty_message() -> None:
    interaction = grpc_interaction(
        service="Orders/CreateOrder",
        request={"contents": {"content": "", "encoded": "base64"}},
        response=[{"contents": contents("Order", {"id": "9"})}],
    )
    call, _ = _read(interaction)
    assert call is not None and call.message == {}


def test_an_error_response_expects_its_grpc_status_and_compares_no_message() -> None:
    interaction = grpc_interaction(
        response=[{"metadata": {"grpc-status": "NOT_FOUND", "grpc-message": "no order 1042"}}]
    )
    call, _ = _read(interaction)
    assert call is not None
    assert (call.expect_code, call.expect_message, call.has_body, call.body) == (
        "not_found",
        "no order 1042",
        False,
        None,
    )


def test_what_is_carried_weakly_is_noted_never_dropped() -> None:
    response = grpc_interaction()["response"][0]
    interaction = grpc_interaction(
        request={
            "contents": contents("GetOrderRequest", {"orderId": "1042"}),
            "metadata": {"contentType": "application/protobuf", "x-tenant": "acme"},
        },
        response=[
            {**response, "metadata": {"grpc-status": "TEAPOT", "x-trace": "1"}},
            response,
        ],
    )
    call, _ = _read(interaction)
    assert call is not None
    notes = [text for _, text in call.notes]
    assert any("x-tenant" in text and "not sent" in text for text in notes)
    assert any("2 responses" in text for text in notes)
    assert any("TEAPOT" in text for text in notes)
    assert any("x-trace" in text and "not compared" in text for text in notes)
    assert call.expect_code == "ok"


# ---------------------------------------------------------------------------------------------
# What cannot be read
# ---------------------------------------------------------------------------------------------


def test_no_descriptor_key_or_no_descriptors_under_it_is_reported() -> None:
    keyless = grpc_interaction(pluginConfiguration={"protobuf": {"service": "Orders/GetOrder"}})
    assert _read(keyless)[1].code == CODE_GRPC_DESCRIPTORS_MISSING
    other_key = grpc_pact([grpc_interaction()], key="another-key")
    _, problem = _read(grpc_interaction(), other_key)
    assert problem.code == CODE_GRPC_DESCRIPTORS_MISSING and DESCRIPTOR_KEY in problem.reason
    bare = {"interactions": [grpc_interaction()], "metadata": {"pactSpecification": {"version": "4.0"}}}
    assert _read(grpc_interaction(), bare)[1].code == CODE_GRPC_DESCRIPTORS_MISSING


@pytest.mark.parametrize("encoded", ["%%%not base64%%%", base64.b64encode(b"\xff\xfe garbage").decode()])
def test_descriptors_that_do_not_decode_are_reported(encoded: str) -> None:
    _, problem = _read(grpc_interaction(), grpc_pact([grpc_interaction()], descriptors=encoded))
    assert problem.code == CODE_GRPC_DESCRIPTORS_MISSING


def test_descriptors_that_do_not_load_are_reported() -> None:
    broken = descriptor_pb2.FileDescriptorSet()
    file_proto = broken.file.add(name="broken.proto", package="x")
    message = file_proto.message_type.add(name="M")
    message.field.add(name="f", number=1, type=11, label=1, type_name=".x.Missing")
    encoded = base64.b64encode(broken.SerializeToString()).decode()
    _, problem = _read(grpc_interaction(), grpc_pact([grpc_interaction()], descriptors=encoded))
    assert problem.code == CODE_GRPC_DESCRIPTORS_MISSING and "do not load" in problem.reason


@pytest.mark.parametrize(
    "service, fragment",
    [
        ("", "names no service"),
        ("Orders", "not of the form"),
        ("Billing/GetOrder", "declare no service"),
        ("Orders/DeleteOrder", "declares no method"),
    ],
)
def test_a_service_or_method_the_descriptors_do_not_declare_is_reported(service: str, fragment: str) -> None:
    _, problem = _read(grpc_interaction(service=service))
    assert problem.code == CODE_GRPC_METHOD_NOT_FOUND and fragment in problem.reason


def test_an_ambiguous_short_service_name_is_reported() -> None:
    twin = descriptor_pb2.FileDescriptorProto(name="other/orders.proto", package="other.v1", syntax="proto3")
    twin.message_type.add(name="Empty")
    twin.service.add(name="Orders").method.add(
        name="GetOrder", input_type=".other.v1.Empty", output_type=".other.v1.Empty"
    )
    both = orders_descriptor_set()
    both.file.append(twin)
    encoded = base64.b64encode(both.SerializeToString()).decode()
    _, problem = _read(grpc_interaction(), grpc_pact([grpc_interaction()], descriptors=encoded))
    assert problem.code == CODE_GRPC_METHOD_NOT_FOUND and "several" in problem.reason


def test_a_streaming_method_is_reported() -> None:
    _, problem = _read(grpc_interaction(service="Orders/WatchOrders"))
    assert problem.code == CODE_GRPC_STREAMING


def test_request_content_that_does_not_decode_is_reported() -> None:
    bad = grpc_interaction(request={"contents": {"content": "%%%", "encoded": "base64"}})
    assert _read(bad)[1].code == CODE_GRPC_CONTENT_UNREADABLE
    garbage = grpc_interaction(
        request={"contents": {"content": base64.b64encode(b"\xff\xff\xff").decode(), "encoded": "base64"}}
    )
    assert _read(garbage)[1].code == CODE_GRPC_CONTENT_UNREADABLE
    wrong = grpc_interaction(request={"contents": contents("Order", {"id": "1"})})
    _, problem = _read(wrong)
    assert problem.code == CODE_GRPC_CONTENT_UNREADABLE and "takes" in problem.reason
    not_text = grpc_interaction(request={"contents": {"content": 42}})
    assert _read(not_text)[1].code == CODE_GRPC_CONTENT_UNREADABLE


def test_an_expected_reply_that_does_not_decode_is_reported() -> None:
    bad = grpc_interaction(response=[{"contents": {"content": "%%%", "encoded": "base64"}}])
    _, problem = _read(bad)
    assert problem.code == CODE_GRPC_CONTENT_UNREADABLE and "expected response" in problem.reason


# ---------------------------------------------------------------------------------------------
# Rule paths
# ---------------------------------------------------------------------------------------------


def _order() -> Any:
    return orders_pool().FindMessageTypeByName(f"{PACKAGE}.Order")


@pytest.mark.parametrize(
    "path, expected, int64",
    [
        ("$", "$", False),
        ("$.total_cents", "$.totalCents", True),
        ("$.totalCents", "$.totalCents", True),
        ("$.id", "$.id", False),
        ("$.items", "$.items", False),
        ("$.items[*].sku", "$.items[*].sku", False),
        ("$.items[0].quantity", "$.items[0].quantity", False),
        ("$.missing", None, False),
        ("$[0]", None, False),
    ],
)
def test_a_rule_path_is_renamed_to_protobuf_json_names(path: str, expected: Any, int64: bool) -> None:
    assert rename_rule_path(parse_path(path), _order()) == (expected, int64)


def test_a_map_field_takes_a_key_and_continues_in_its_value_type() -> None:
    file_proto = descriptor_pb2.FileDescriptorProto(name="m.proto", package="m", syntax="proto3")
    value = file_proto.message_type.add(name="Value")
    value.field.add(name="unit_price", number=1, type=3, label=1, json_name="unitPrice")
    holder = file_proto.message_type.add(name="Holder")
    entry = holder.nested_type.add(name="PricesEntry")
    entry.options.map_entry = True
    entry.field.add(name="key", number=1, type=9, label=1, json_name="key")
    entry.field.add(name="value", number=2, type=11, label=1, type_name=".m.Value", json_name="value")
    holder.field.add(
        name="sku_prices", number=1, type=11, label=3, type_name=".m.Holder.PricesEntry", json_name="skuPrices"
    )
    counts = holder.nested_type.add(name="CountsEntry")
    counts.options.map_entry = True
    counts.field.add(name="key", number=1, type=9, label=1, json_name="key")
    counts.field.add(name="value", number=2, type=3, label=1, json_name="value")
    holder.field.add(name="counts", number=2, type=11, label=3, type_name=".m.Holder.CountsEntry", json_name="counts")
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    descriptor = pool.FindMessageTypeByName("m.Holder")
    assert rename_rule_path(parse_path("$.sku_prices.*.unit_price"), descriptor) == ("$.skuPrices[*].unitPrice", True)
    assert rename_rule_path(parse_path("$.sku_prices['A-1'].unit_price"), descriptor) == (
        "$.skuPrices.A-1.unitPrice",
        True,
    )
    assert rename_rule_path(parse_path("$.counts.*"), descriptor) == ("$.counts[*]", True)
    assert rename_rule_path(parse_path("$.counts"), descriptor) == ("$.counts", False)
    assert rename_rule_path(parse_path("$.sku_prices['a b']"), descriptor) == ("$.skuPrices['a b']", False)


def test_a_numeric_rule_on_an_int64_field_is_applied_as_a_digits_regex() -> None:
    assert int64_matcher("integer", {"match": "integer"}) == {"match": "regex", "regex": INT64_PATTERN}
    assert int64_matcher("number", {"match": "number", "x": 1}) == {"match": "regex", "regex": INT64_PATTERN, "x": 1}
    assert int64_matcher("type", {"match": "type"}) is None
