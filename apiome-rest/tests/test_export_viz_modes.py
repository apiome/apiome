"""Per-target visualization modes — MFX-45.4 (#4377).

Pinned here:

* modes are **registry data**: emitters declare ``viz_modes`` and ``GET /export/targets`` carries them —
  proto3 and Connect RPC draw an import graph and a service map, AsyncAPI and xRegistry a channel
  topology, SQL DDL an ERD, and every other target nothing;
* each graph is built **from the emitted files**: proto files and imports (well-known imports
  external), services → methods → request / response messages (streams labelled), AsyncAPI channels ↔
  messages ↔ operations (3.x and 2.x), xRegistry message groups → messages → event types;
* nodes that stand for a canonical construct carry its ``entity_key``;
* the export preview manifest returns the graphs as ``views`` on every page.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pytest
import yaml

from app.catalog_conversion import build_conversion_source
from app.emitter import describe_emit_targets, get_emitter, load_builtin_emitters
from app.export_preview_manifest import build_export_preview_manifest, paginate_export_preview_manifest
from app.export_viz_modes import (
    EntityRef,
    ExportVizModeKind,
    VizFile,
    VizGraph,
    attach_entity_keys,
    build_viz_graphs,
    resolve_viz_modes,
)
from app.import_source import load_builtin_import_sources

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
IMPORTS, SERVICES, TOPOLOGY, ERD = (ExportVizModeKind.PROTO_IMPORTS, ExportVizModeKind.SERVICE_MAP,
                                    ExportVizModeKind.CHANNEL_TOPOLOGY, ExportVizModeKind.ERD)


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _graph(mode: ExportVizModeKind, files: List[VizFile]) -> VizGraph:
    return build_viz_graphs([mode], files)[mode.value]


def _edges(graph: VizGraph) -> List[tuple]:
    return [(e.source, e.target, e.kind, e.label) for e in graph.edges]


def _nodes(graph: VizGraph) -> Dict[str, object]:
    return {n.id: n for n in graph.nodes}


# ===========================================================================
# The registry
# ===========================================================================


def test_modes_resolve_with_their_labels_in_declared_order_once() -> None:
    modes = resolve_viz_modes([SERVICES, IMPORTS, SERVICES])
    assert [(m.kind, m.label) for m in modes] == [(SERVICES, "Service map"), (IMPORTS, "Import graph")]
    assert [m.label for m in resolve_viz_modes([TOPOLOGY, ERD])] == ["Channel topology", "ERD"]


@pytest.mark.parametrize(("target", "expected"), [
    ("proto3", ["proto-imports", "service-map"]),
    ("connectrpc", ["proto-imports", "service-map"]),
    ("asyncapi-3", ["channel-topology"]),
    ("xregistry", ["channel-topology"]),
    ("sql-ddl", ["erd"]),
    ("openapi-3.1", []),
    ("graphql", []),
])
def test_each_family_declares_its_modes_and_others_none(target: str, expected: List[str]) -> None:
    emitter = get_emitter(target)
    assert emitter is not None
    assert [m.kind.value for m in emitter.descriptor().viz_modes] == expected


def test_the_targets_listing_carries_the_modes() -> None:
    by_format = {t.descriptor.format: t.descriptor for t in describe_emit_targets()}
    assert [m.kind.value for m in by_format["proto3"].viz_modes] == ["proto-imports", "service-map"]
    assert by_format["openapi-3.1"].viz_modes == []
    first = by_format["proto3"].model_dump(mode="json")["viz_modes"][0]
    assert first == {"kind": "proto-imports", "label": "Import graph"}


# ===========================================================================
# Protobuf
# ===========================================================================

ORDERS = """syntax = "proto3";
package shop.orders.v1;

import "shop/common/v1/money.proto";
import public "google/protobuf/timestamp.proto";

message Order {
  string id = 1;
}

message OrderRequest { string id = 1; }

service OrderService {
  // Fetch one order { with braces in a comment }
  rpc GetOrder (.shop.orders.v1.OrderRequest) returns (.shop.orders.v1.Order);
  rpc WatchOrders (OrderRequest) returns (stream Order);
  rpc Upload (stream Order) returns (google.protobuf.Empty);
  rpc Chat (stream Order) returns (stream Order) {
    option deprecated = true;
  }
}

service Health {
  rpc Check (OrderRequest) returns (Order);
}
"""
MONEY = """syntax = "proto3";
package shop.common.v1;

message Money { int64 units = 1; }
"""
FILES = [VizFile("shop/orders/v1/orders.proto", ORDERS), VizFile("shop/common/v1/money.proto", MONEY),
         VizFile("README.md", "import \"nothing.proto\";")]


def test_the_import_graph_has_every_file_and_import() -> None:
    graph = _graph(IMPORTS, FILES)
    nodes = _nodes(graph)
    assert set(nodes) == {"file:shop/orders/v1/orders.proto", "file:shop/common/v1/money.proto",
                          "file:google/protobuf/timestamp.proto"}
    orders = nodes["file:shop/orders/v1/orders.proto"]
    assert orders.detail == "package shop.orders.v1" and orders.file == orders.label and not orders.external
    assert nodes["file:google/protobuf/timestamp.proto"].external
    assert nodes["file:google/protobuf/timestamp.proto"].file is None
    assert not nodes["file:shop/common/v1/money.proto"].external
    assert _edges(graph) == [
        ("file:shop/orders/v1/orders.proto", "file:shop/common/v1/money.proto", "import", None),
        ("file:shop/orders/v1/orders.proto", "file:google/protobuf/timestamp.proto", "import", None),
    ]


def test_the_service_map_reads_services_methods_and_their_messages() -> None:
    graph = _graph(SERVICES, FILES)
    nodes = _nodes(graph)
    assert [n.id for n in graph.nodes if n.kind == "service"] == ["service:OrderService", "service:Health"]
    methods = [n for n in graph.nodes if n.kind == "method"]
    assert [m.id for m in methods] == ["method:OrderService.GetOrder", "method:OrderService.WatchOrders",
                                       "method:OrderService.Upload", "method:OrderService.Chat",
                                       "method:Health.Check"]
    assert [m.detail for m in methods] == [None, "server stream", "client stream", "bidirectional stream", None]
    edges = _edges(graph)
    assert ("service:OrderService", "method:OrderService.GetOrder", "method", None) in edges
    assert ("method:OrderService.GetOrder", "message:shop.orders.v1.OrderRequest", "request", None) in edges
    assert ("method:OrderService.WatchOrders", "message:Order", "response", "stream") in edges
    assert ("method:OrderService.Upload", "message:Order", "request", "stream") in edges
    # A qualified name resolves to the message declared in the bundle; a well-known type is external.
    qualified = nodes["message:shop.orders.v1.Order"]
    assert not qualified.external and qualified.file == "shop/orders/v1/orders.proto" and qualified.line == 7
    assert nodes["message:google.protobuf.Empty"].external
    assert nodes["service:OrderService"].line == 13


def test_a_bundle_without_proto_files_draws_nothing() -> None:
    assert build_viz_graphs([IMPORTS, SERVICES], [VizFile("a.json", "{}")]) == {}


# ===========================================================================
# Events
# ===========================================================================

ASYNCAPI_3 = {
    "asyncapi": "3.0.0",
    "channels": {
        "orderPlaced": {"address": "order/placed", "messages": {"orderPlaced": {}, "orderAmended": {}}},
        "user/events": {"messages": {"signedUp": {}}},
    },
    "operations": {
        "sendOrderPlaced": {"action": "send", "channel": {"$ref": "#/channels/orderPlaced"},
                            "messages": [{"$ref": "#/channels/orderPlaced/messages/orderPlaced"}]},
        "onSignup": {"action": "receive", "channel": {"$ref": "#/channels/user~1events"},
                     "messages": [{"$ref": "#/channels/user~1events/messages/signedUp"}]},
    },
}


def test_asyncapi_3_channels_carry_messages_and_operations_use_them() -> None:
    graph = _graph(TOPOLOGY, [VizFile("asyncapi.json", json.dumps(ASYNCAPI_3))])
    nodes = _nodes(graph)
    assert nodes["channel:orderPlaced"].detail == "order/placed"
    assert nodes["operation:sendOrderPlaced"].detail == "send"
    edges = _edges(graph)
    assert ("channel:orderPlaced", "message:orderPlaced/orderPlaced", "carries", None) in edges
    assert ("channel:orderPlaced", "message:orderPlaced/orderAmended", "carries", None) in edges
    assert ("operation:sendOrderPlaced", "channel:orderPlaced", "uses", None) in edges
    assert ("operation:sendOrderPlaced", "message:orderPlaced/orderPlaced", "sends", None) in edges
    # Escaped pointers (`~1`) resolve to the same channel and message.
    assert ("operation:onSignup", "message:user/events/signedUp", "receives", None) in edges
    assert ("operation:onSignup", "channel:user/events", "uses", None) in edges
    assert ("channel:user/events", "message:user/events/signedUp", "carries", None) in edges


def test_asyncapi_2_publish_and_subscribe_are_operations_on_their_channel() -> None:
    document = {"asyncapi": "2.6.0", "channels": {"user/signedup": {
        "subscribe": {"operationId": "onUserSignedUp", "message": {"name": "UserSignedUp"}},
        "publish": {"message": {}},
    }}}
    graph = _graph(TOPOLOGY, [VizFile("asyncapi.yaml", yaml.safe_dump(document))])
    edges = _edges(graph)
    assert ("operation:onUserSignedUp", "channel:user/signedup", "uses", None) in edges
    assert ("operation:publish user/signedup", "channel:user/signedup", "uses", None) in edges
    assert _nodes(graph)["operation:onUserSignedUp"].detail == "subscribe"


def test_xregistry_groups_contain_messages_typed_by_their_event_type() -> None:
    document = {"specversion": "1.0-rc1", "messagegroups": {"default": {
        "envelope": "CloudEvents/1.0",
        "messages": {"receiveOrderPlaced": {"name": "orderPlaced",
                                            "envelopemetadata": {"type": {"value": "order/placed"}}},
                     "ping": {}},
    }}}
    graph = _graph(TOPOLOGY, [VizFile("x.xregistry.json", json.dumps(document))])
    nodes = _nodes(graph)
    assert nodes["group:default"].detail == "CloudEvents/1.0"
    message = nodes["message:default/receiveOrderPlaced"]
    assert message.label == "orderPlaced" and message.detail == "receiveOrderPlaced"
    assert nodes["message:default/ping"].detail is None
    assert ("message:default/receiveOrderPlaced", "type:order/placed", "typed", None) in _edges(graph)
    assert ("group:default", "message:default/ping", "contains", None) in _edges(graph)


def test_a_file_that_is_not_an_event_document_is_skipped() -> None:
    assert build_viz_graphs([TOPOLOGY], [VizFile("a.txt", "not: [valid"), VizFile("b.json", "[1, 2]")]) == {}


def test_erd_is_not_a_graph_mode() -> None:
    assert build_viz_graphs([ERD], FILES) == {}


# ===========================================================================
# Entity keys
# ===========================================================================


def test_nodes_point_at_their_entities_by_location_then_by_name() -> None:
    graphs = build_viz_graphs([SERVICES, IMPORTS], FILES)
    attach_entity_keys(graphs, [
        EntityRef(key="shop.OrderService", name="OrderService", kind="service",
                  file="shop/orders/v1/orders.proto", line=13),
        EntityRef(key="GET /orders/{id}", name="getOrder", kind="operation"),
        EntityRef(key="Order", name="Order", kind="type"),
        # A located entity of another kind is never taken for a node.
        EntityRef(key="orders.proto", name="orders", kind="type", file="shop/orders/v1/orders.proto", line=1),
    ])
    services = _nodes(graphs["service-map"])
    assert services["service:OrderService"].entity_key == "shop.OrderService"
    assert services["method:OrderService.GetOrder"].entity_key == "GET /orders/{id}"  # by name, case-folded
    assert services["message:Order"].entity_key == "Order"
    assert services["message:google.protobuf.Empty"].entity_key is None
    assert all(n.entity_key is None for n in graphs["proto-imports"].nodes)


def test_an_xregistry_message_points_at_its_operation_through_its_message_id() -> None:
    document = {"messagegroups": {"default": {"messages": {"receiveOrderPlaced": {"name": "orderPlaced"}}}}}
    graphs = build_viz_graphs([TOPOLOGY], [VizFile("x.json", json.dumps(document))])
    attach_entity_keys(graphs, [EntityRef(key="receiveOrderPlaced", name="receiveOrderPlaced", kind="operation"),
                                EntityRef(key="default", name="default", kind="service")])
    nodes = _nodes(graphs["channel-topology"])
    assert nodes["message:default/receiveOrderPlaced"].entity_key == "receiveOrderPlaced"
    assert nodes["group:default"].entity_key == "default"


# ===========================================================================
# The manifest
# ===========================================================================


def _petstore():
    text = (_EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml").read_text(encoding="utf-8")
    return build_conversion_source({"id": "i", "name": "petstore", "source_format": "openapi",
                                    "format_metadata": {"sourceContent": text}}).api


def test_the_manifest_returns_the_graphs_on_every_page_with_entity_keys() -> None:
    api = _petstore()
    emitter = get_emitter("proto3")
    full = build_export_preview_manifest(api, emitter, emitter().emit(api))
    first = paginate_export_preview_manifest(full, page_size=2)
    second = paginate_export_preview_manifest(full, cursor=first.next_cursor, page_size=2)
    assert set(first.views) == {"proto-imports", "service-map"} and first.views == second.views
    services = _nodes(first.views["service-map"])
    assert services["service:default"].entity_key == "default"
    assert services["method:default.getPetById"].entity_key == "GET /pets/{petId}"
    assert services["message:Pet"].entity_key == "Pet"
    dumped = first.model_dump(mode="json")["views"]["proto-imports"]
    assert dumped["mode"] == "proto-imports" and dumped["edges"][0]["kind"] == "import"


@pytest.mark.parametrize("target", ["openapi-3.1", "sql-ddl"])
def test_a_target_without_a_graph_mode_has_no_views(target: str) -> None:
    api = _petstore()
    emitter = get_emitter(target)
    full = build_export_preview_manifest(api, emitter, emitter().emit(api))
    assert paginate_export_preview_manifest(full).views == {}
