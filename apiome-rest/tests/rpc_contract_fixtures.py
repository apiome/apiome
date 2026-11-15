"""Shared Protobuf fixture for the gRPC/Connect contract adapter tests — XPC-3.2 (#5742).

One proto2 file, ``acme/orders/v1/orders.proto``, built as a descriptor (no ``buf`` needed):

* ``GetOrder`` — unary, ``idempotency_level = NO_SIDE_EFFECTS``, a ``required`` request field;
* ``CreateOrder`` — unary with no idempotency option, so it is mutating;
* ``WatchOrders`` — server-streaming, so it is ``unsupported: streaming``.

:func:`orders_api` normalizes it through the real :class:`~app.proto_normalizer.ProtoNormalizer`,
and :func:`orders_pool` loads the same file into a descriptor pool for in-process gRPC servers.
"""

from __future__ import annotations

from google.protobuf import descriptor_pb2, descriptor_pool

from app.canonical_model import CanonicalApi
from app.proto_descriptor import read_file_descriptor_set
from app.proto_normalizer import ProtoNormalizer

PACKAGE = "acme.orders.v1"
SERVICE = f"{PACKAGE}.Orders"
FILE_NAME = "acme/orders/v1/orders.proto"

_FIELD = descriptor_pb2.FieldDescriptorProto


def _field(message, name, number, kind, *, label=_FIELD.LABEL_OPTIONAL, type_name=None):
    """Append one field to a message descriptor."""
    entry = message.field.add(name=name, number=number, type=kind, label=label)
    if type_name:
        entry.type_name = type_name
    return entry


def orders_file() -> descriptor_pb2.FileDescriptorProto:
    """Return the fixture file descriptor."""
    file_proto = descriptor_pb2.FileDescriptorProto(
        name=FILE_NAME, package=PACKAGE, syntax="proto2"
    )

    status = file_proto.enum_type.add(name="Status")
    status.value.add(name="STATUS_UNSPECIFIED", number=0)
    status.value.add(name="OPEN", number=1)

    get_request = file_proto.message_type.add(name="GetOrderRequest")
    _field(get_request, "order_id", 1, _FIELD.TYPE_STRING, label=_FIELD.LABEL_REQUIRED)
    _field(get_request, "page_size", 2, _FIELD.TYPE_INT32)

    line_item = file_proto.message_type.add(name="LineItem")
    _field(line_item, "sku", 1, _FIELD.TYPE_STRING)
    _field(line_item, "quantity", 2, _FIELD.TYPE_INT32)

    order = file_proto.message_type.add(name="Order")
    _field(order, "id", 1, _FIELD.TYPE_STRING, label=_FIELD.LABEL_REQUIRED)
    _field(order, "total_cents", 2, _FIELD.TYPE_INT64)
    _field(order, "status", 3, _FIELD.TYPE_ENUM, type_name=f".{PACKAGE}.Status")
    _field(
        order,
        "items",
        4,
        _FIELD.TYPE_MESSAGE,
        label=_FIELD.LABEL_REPEATED,
        type_name=f".{PACKAGE}.LineItem",
    )

    create_request = file_proto.message_type.add(name="CreateOrderRequest")
    _field(create_request, "customer_id", 1, _FIELD.TYPE_STRING)

    service = file_proto.service.add(name="Orders")
    get = service.method.add(
        name="GetOrder",
        input_type=f".{PACKAGE}.GetOrderRequest",
        output_type=f".{PACKAGE}.Order",
    )
    get.options.idempotency_level = descriptor_pb2.MethodOptions.NO_SIDE_EFFECTS
    service.method.add(
        name="CreateOrder",
        input_type=f".{PACKAGE}.CreateOrderRequest",
        output_type=f".{PACKAGE}.Order",
    )
    service.method.add(
        name="WatchOrders",
        input_type=f".{PACKAGE}.GetOrderRequest",
        output_type=f".{PACKAGE}.Order",
        server_streaming=True,
    )
    return file_proto


def orders_descriptor_set() -> descriptor_pb2.FileDescriptorSet:
    """Return the fixture as a one-file descriptor set."""
    descriptor_set = descriptor_pb2.FileDescriptorSet()
    descriptor_set.file.append(orders_file())
    return descriptor_set


def orders_api() -> CanonicalApi:
    """Normalize the fixture into the canonical model a Protobuf version stores."""
    compiled = read_file_descriptor_set(orders_descriptor_set().SerializeToString())
    return ProtoNormalizer().normalize(compiled)


def orders_pool() -> descriptor_pool.DescriptorPool:
    """Load the fixture into a fresh descriptor pool."""
    pool = descriptor_pool.DescriptorPool()
    pool.Add(orders_file())
    return pool
