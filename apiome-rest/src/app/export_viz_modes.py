"""Per-target visualization modes of an export — MFX-45.4 (#4377).

The Review step can show an emitted artifact as a picture as well as text. Which pictures make sense is
**registry data**, declared per emitter like its test-drive tools (MFX-44.1): an emitter lists its
:attr:`app.emitter.Emitter.viz_modes`, :func:`resolve_viz_modes` turns them into the ``viz_modes`` of its
descriptor (``GET /export/targets``), and the UI draws one view per declared mode — no format switch in
the UI.

Four modes:

* ``erd`` — the tables of a database export (MFX-45.3; data: the manifest's ``relational``);
* ``proto-imports`` — a protobuf bundle's files as nodes and its ``import`` statements as edges;
* ``service-map`` — an RPC export's services → methods → request / response message types;
* ``channel-topology`` — an event export's channels ↔ messages ↔ operations (AsyncAPI), or its message
  groups → messages → event types (xRegistry).

The last three are graphs built here **from the emitted files** (:func:`build_viz_graphs`), so they
show what the artifact holds, and returned by the export preview manifest as ``views``. Each node that
stands for a canonical construct carries its ``entity_key`` (:func:`attach_entity_keys`), so selecting
it is the Review step's own entity selection.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import yaml
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ExportVizMode",
    "ExportVizModeKind",
    "VizEdge",
    "VizFile",
    "VizGraph",
    "VizNode",
    "EntityRef",
    "attach_entity_keys",
    "build_viz_graphs",
    "resolve_viz_modes",
]


class ExportVizModeKind(str, Enum):
    """A way to draw an emitted artifact."""

    ERD = "erd"  # tables, columns and foreign keys (MFX-45.3)
    PROTO_IMPORTS = "proto-imports"  # proto files and their imports
    SERVICE_MAP = "service-map"  # services → methods → message types
    CHANNEL_TOPOLOGY = "channel-topology"  # channels ↔ messages ↔ operations


#: The label of each mode's view switch button.
_MODE_LABELS: Dict[ExportVizModeKind, str] = {
    ExportVizModeKind.ERD: "ERD",
    ExportVizModeKind.PROTO_IMPORTS: "Import graph",
    ExportVizModeKind.SERVICE_MAP: "Service map",
    ExportVizModeKind.CHANNEL_TOPOLOGY: "Channel topology",
}


class ExportVizMode(BaseModel):
    """One visualization mode of a target, as ``GET /export/targets`` reports it."""

    model_config = ConfigDict(frozen=True)

    kind: ExportVizModeKind = Field(description="The mode, e.g. ``proto-imports`` or ``channel-topology``.")
    label: str = Field(description="The view switch label, e.g. ``Import graph``.")


def resolve_viz_modes(declared: Sequence[ExportVizModeKind]) -> List[ExportVizMode]:
    """The descriptor entries of an emitter's declared modes, in declared order, without duplicates.

    Args:
        declared: The emitter's :attr:`~app.emitter.Emitter.viz_modes`.

    Returns:
        One :class:`ExportVizMode` per distinct mode.
    """
    seen: List[ExportVizModeKind] = []
    for kind in declared:
        if kind not in seen:
            seen.append(kind)
    return [ExportVizMode(kind=kind, label=_MODE_LABELS[kind]) for kind in seen]


# ===========================================================================
# The graph
# ===========================================================================


class VizNode(BaseModel):
    """One node of a mode's graph."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Stable node id within the graph, e.g. ``file:api.proto``.")
    label: str = Field(description="What the node is called in the artifact.")
    kind: str = Field(
        description="`file`, `service`, `method`, `message`, `channel`, `operation`, `message-group` or `event-type`."
    )
    detail: Optional[str] = Field(
        default=None, description="A short fact shown under the label: a package, an address, an action."
    )
    external: bool = Field(
        default=False, description="True for something the artifact references but does not hold (a well-known import)."
    )
    file: Optional[str] = Field(default=None, description="The emitted file the node is declared in.")
    line: Optional[int] = Field(default=None, description="The 1-based line it is declared on, when known.")
    entity_key: Optional[str] = Field(
        default=None, description="The canonical construct the node stands for, when there is one."
    )


class VizEdge(BaseModel):
    """One edge of a mode's graph."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Stable edge id within the graph.")
    source: str = Field(description="The source node id.")
    target: str = Field(description="The target node id.")
    kind: str = Field(
        description="`import`, `method`, `request`, `response`, `carries` (channel → message), `uses` "
        "(operation → channel), `sends` / `receives` (operation → message), `contains` (group → message) or "
        "`typed` (message → event type)."
    )
    label: Optional[str] = Field(default=None, description="A short edge label, e.g. `stream`.")


class VizGraph(BaseModel):
    """The graph one mode draws."""

    model_config = ConfigDict(extra="forbid")

    mode: ExportVizModeKind = Field(description="The mode this graph is for.")
    nodes: List[VizNode] = Field(default_factory=list, description="The nodes, in a stable order.")
    edges: List[VizEdge] = Field(default_factory=list, description="The edges, in a stable order.")


@dataclass(frozen=True)
class VizFile:
    """One emitted file, as the builders read it: its path and its download-serialized text."""

    path: str
    text: str


class _GraphBuilder:
    """Collects nodes and edges once each, in insertion order."""

    def __init__(self, mode: ExportVizModeKind) -> None:
        self.mode = mode
        self.nodes: Dict[str, VizNode] = {}
        self.edges: Dict[str, VizEdge] = {}

    def node(self, node_id: str, label: str, kind: str, **extra: Any) -> str:
        if node_id not in self.nodes:
            self.nodes[node_id] = VizNode(id=node_id, label=label, kind=kind, **extra)
        return node_id

    def edge(self, source: str, target: str, kind: str, label: Optional[str] = None) -> None:
        edge_id = f"{kind}:{source}->{target}"
        if edge_id not in self.edges:
            self.edges[edge_id] = VizEdge(id=edge_id, source=source, target=target, kind=kind, label=label)

    def graph(self) -> VizGraph:
        return VizGraph(mode=self.mode, nodes=list(self.nodes.values()), edges=list(self.edges.values()))


# ===========================================================================
# Protobuf: imports and the service map
# ===========================================================================

_PROTO_IMPORT = re.compile(r'^\s*import\s+(?:public\s+|weak\s+)?"([^"]+)"\s*;')
_PROTO_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;")
_PROTO_SERVICE = re.compile(r"^\s*service\s+(\w+)\s*\{")
_PROTO_MESSAGE = re.compile(r"^\s*(?:message|enum)\s+(\w+)\s*\{")
_PROTO_RPC = re.compile(
    r"^\s*rpc\s+(\w+)\s*\(\s*(stream\s+)?\.?([\w.]+)\s*\)\s*returns\s*\(\s*(stream\s+)?\.?([\w.]+)\s*\)"
)
_LINE_COMMENT = re.compile(r"//.*$")


def _proto_files(files: Sequence[VizFile]) -> List[VizFile]:
    return [f for f in files if f.path.endswith(".proto")]


def _proto_imports_graph(files: Sequence[VizFile]) -> VizGraph:
    """Every ``.proto`` file a node (with its package), every ``import`` an edge; an import the bundle
    does not hold (a well-known type such as ``google/protobuf/empty.proto``) is an external node."""
    builder = _GraphBuilder(ExportVizModeKind.PROTO_IMPORTS)
    protos = _proto_files(files)
    held = {f.path for f in protos}
    for file in protos:
        package = next((m.group(1) for m in map(_PROTO_PACKAGE.match, file.text.splitlines()) if m), None)
        builder.node(f"file:{file.path}", file.path, "file", detail=f"package {package}" if package else None,
                     file=file.path, line=1)
    for file in protos:
        for line_number, line in enumerate(file.text.splitlines(), start=1):
            match = _PROTO_IMPORT.match(line)
            if not match:
                continue
            imported = match.group(1)
            target = builder.node(f"file:{imported}", imported, "file", external=imported not in held,
                                  file=imported if imported in held else None)
            builder.edge(f"file:{file.path}", target, "import")
    return builder.graph()


def _message_id(name: str) -> str:
    return f"message:{name.lstrip('.')}"


def _proto_service_graph(files: Sequence[VizFile]) -> VizGraph:
    """Services → methods → request / response message types, read from the ``.proto`` files.

    A message declared in the bundle carries its file and line; one the bundle only references (a
    well-known type such as ``google.protobuf.Empty``) is external.
    """
    builder = _GraphBuilder(ExportVizModeKind.SERVICE_MAP)
    declared: Dict[str, Tuple[str, int]] = {}
    for file in _proto_files(files):
        for line_number, line in enumerate(file.text.splitlines(), start=1):
            match = _PROTO_MESSAGE.match(line)
            if match:
                declared.setdefault(match.group(1), (file.path, line_number))

    def message(name: str) -> str:
        short = name.lstrip(".")
        simple = short.rsplit(".", 1)[-1]
        where = declared.get(short) or declared.get(simple)
        return builder.node(_message_id(short), short, "message", external=where is None,
                            file=where[0] if where else None, line=where[1] if where else None)

    for file in _proto_files(files):
        service: Optional[str] = None
        depth = 0
        for line_number, raw in enumerate(file.text.splitlines(), start=1):
            line = _LINE_COMMENT.sub("", raw)
            start = _PROTO_SERVICE.match(line)
            if start and service is None:
                service = builder.node(f"service:{start.group(1)}", start.group(1), "service",
                                       file=file.path, line=line_number)
                depth = 0
            if service is not None:
                rpc = _PROTO_RPC.match(line)
                if rpc:
                    name, req_stream, request, resp_stream, response = rpc.groups()
                    method = builder.node(f"method:{service[len('service:'):]}.{name}", name, "method",
                                          detail=_stream_detail(req_stream, resp_stream),
                                          file=file.path, line=line_number)
                    builder.edge(service, method, "method")
                    builder.edge(method, message(request), "request", label="stream" if req_stream else None)
                    builder.edge(method, message(response), "response", label="stream" if resp_stream else None)
                depth += line.count("{") - line.count("}")
                if depth <= 0 and "}" in line:
                    service = None
    return builder.graph()


def _stream_detail(request_stream: Optional[str], response_stream: Optional[str]) -> Optional[str]:
    if request_stream and response_stream:
        return "bidirectional stream"
    if request_stream:
        return "client stream"
    if response_stream:
        return "server stream"
    return None


# ===========================================================================
# Events: AsyncAPI and xRegistry
# ===========================================================================


def _load_document(file: VizFile) -> Optional[Mapping[str, Any]]:
    """The file as a JSON or YAML mapping, or ``None`` when it is neither."""
    for loader in (json.loads, yaml.safe_load):
        try:
            document = loader(file.text)
        except Exception:  # noqa: BLE001 - a file that is not this syntax simply is not read
            continue
        if isinstance(document, Mapping):
            return document
    return None


def _ref_tail(ref: Any) -> Optional[str]:
    """The last segment of a ``$ref`` (``#/channels/orderPlaced`` → ``orderPlaced``)."""
    if isinstance(ref, Mapping):
        ref = ref.get("$ref")
    if not isinstance(ref, str) or not ref:
        return None
    return ref.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")


def _asyncapi_topology(builder: _GraphBuilder, file: VizFile, document: Mapping[str, Any]) -> None:
    """AsyncAPI: channels (with their address) carry messages; operations use a channel and send or
    receive messages."""
    channels = document.get("channels") or {}
    for channel_id, channel in channels.items() if isinstance(channels, Mapping) else ():
        channel = channel if isinstance(channel, Mapping) else {}
        address = channel.get("address")
        node = builder.node(f"channel:{channel_id}", str(channel_id), "channel",
                            detail=str(address) if address else None, file=file.path)
        messages = channel.get("messages") or {}
        for message_id in messages if isinstance(messages, Mapping) else ():
            message = builder.node(f"message:{channel_id}/{message_id}", str(message_id), "message", file=file.path)
            builder.edge(node, message, "carries")
        # AsyncAPI 2.x: publish / subscribe operations live on the channel.
        for action in ("publish", "subscribe"):
            operation = channel.get(action)
            if isinstance(operation, Mapping):
                op_name = str(operation.get("operationId") or f"{action} {channel_id}")
                op = builder.node(f"operation:{op_name}", op_name, "operation", detail=action, file=file.path)
                builder.edge(op, node, "uses")
    operations = document.get("operations") or {}
    for op_id, operation in operations.items() if isinstance(operations, Mapping) else ():
        operation = operation if isinstance(operation, Mapping) else {}
        action = str(operation.get("action") or "") or None
        op = builder.node(f"operation:{op_id}", str(op_id), "operation", detail=action, file=file.path)
        channel_id = _ref_tail(operation.get("channel"))
        if channel_id:
            builder.edge(op, builder.node(f"channel:{channel_id}", channel_id, "channel", file=file.path), "uses")
        for ref in operation.get("messages") or []:
            target = ref.get("$ref") if isinstance(ref, Mapping) else None
            message_id = _ref_tail(ref)
            if not message_id:
                continue
            owner = None
            if isinstance(target, str) and target.startswith("#/channels/") and "/messages/" in target:
                owner = target[len("#/channels/"):].split("/messages/", 1)[0].replace("~1", "/")
            node_id = f"message:{owner}/{message_id}" if owner else f"message:{message_id}"
            message = builder.node(node_id, message_id, "message", file=file.path)
            builder.edge(op, message, "sends" if action == "send" else "receives")


def _xregistry_topology(builder: _GraphBuilder, file: VizFile, document: Mapping[str, Any]) -> None:
    """xRegistry: message groups contain messages; each message is typed by its CloudEvents ``type``."""
    groups = document.get("messagegroups") or {}
    for group_id, group in groups.items() if isinstance(groups, Mapping) else ():
        group = group if isinstance(group, Mapping) else {}
        envelope = group.get("envelope")
        node = builder.node(f"group:{group_id}", str(group_id), "message-group",
                            detail=str(envelope) if envelope else None, file=file.path)
        messages = group.get("messages") or {}
        for message_id, message in messages.items() if isinstance(messages, Mapping) else ():
            message = message if isinstance(message, Mapping) else {}
            label = str(message.get("name") or message_id)
            msg = builder.node(f"message:{group_id}/{message_id}", label, "message",
                               detail=str(message_id) if label != message_id else None, file=file.path)
            builder.edge(node, msg, "contains")
            event_type = ((message.get("envelopemetadata") or {}).get("type") or {}).get("value") \
                if isinstance(message.get("envelopemetadata"), Mapping) else None
            if isinstance(event_type, str) and event_type:
                builder.edge(msg, builder.node(f"type:{event_type}", event_type, "event-type"), "typed")


def _channel_topology_graph(files: Sequence[VizFile]) -> VizGraph:
    builder = _GraphBuilder(ExportVizModeKind.CHANNEL_TOPOLOGY)
    for file in files:
        document = _load_document(file)
        if document is None:
            continue
        if "asyncapi" in document:
            _asyncapi_topology(builder, file, document)
        elif "messagegroups" in document:
            _xregistry_topology(builder, file, document)
    return builder.graph()


_BUILDERS = {
    ExportVizModeKind.PROTO_IMPORTS: _proto_imports_graph,
    ExportVizModeKind.SERVICE_MAP: _proto_service_graph,
    ExportVizModeKind.CHANNEL_TOPOLOGY: _channel_topology_graph,
}


def build_viz_graphs(modes: Iterable[ExportVizModeKind], files: Sequence[VizFile]) -> Dict[str, VizGraph]:
    """The graph of every declared mode that draws a graph (``erd`` draws the manifest's ``relational``).

    Args:
        modes: The target's declared modes.
        files: The emitted files, download-serialized.

    Returns:
        Mode value → its graph; a mode whose graph comes out empty is left out (nothing to draw).
    """
    graphs: Dict[str, VizGraph] = {}
    for mode in modes:
        builder = _BUILDERS.get(ExportVizModeKind(mode))
        if builder is None:
            continue
        graph = builder(files)
        if graph.nodes:
            graphs[ExportVizModeKind(mode).value] = graph
    return graphs


# ===========================================================================
# Selection: nodes ↔ canonical entities
# ===========================================================================

#: Which manifest entity kinds a node kind may stand for.
_ENTITY_KINDS: Dict[str, Tuple[str, ...]] = {
    "service": ("service",),
    "method": ("operation",),
    # An xRegistry message is an operation's event (its message id is the operation's key).
    "message": ("type", "operation"),
    "channel": ("channel",),
    "operation": ("operation",),
    # An xRegistry message group is the service it was written from.
    "message-group": ("service",),
}


def _token(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold())


@dataclass(frozen=True)
class EntityRef:
    """What :func:`attach_entity_keys` needs of a manifest entity."""

    key: str
    name: str
    kind: str
    file: Optional[str] = None
    line: Optional[int] = None


def attach_entity_keys(graphs: Mapping[str, VizGraph], entities: Sequence[EntityRef]) -> None:
    """Point each node at the canonical construct it stands for, in place.

    A node declared on the same file and line as a located entity of a matching kind is that entity
    (the manifest locates proto services, rpcs and messages on their declaration lines). Otherwise a
    node matches the entity of a matching kind whose key or name is the node's label, or else its detail
    (alphanumerics, case-insensitive) — the way an AsyncAPI channel or operation keeps its canonical name,
    and an xRegistry message keeps its operation's key as its message id. A node that
    matches nothing (a file, an external message, an event type) has no entity.
    """
    by_location = {(e.file, e.line): e for e in entities if e.file is not None and e.line is not None}
    by_name: Dict[Tuple[str, str], EntityRef] = {}
    for entity in entities:
        for token in (_token(entity.key), _token(entity.name)):
            if token:
                by_name.setdefault((entity.kind, token), entity)
    for graph in graphs.values():
        for node in graph.nodes:
            kinds = _ENTITY_KINDS.get(node.kind, ())
            if not kinds:
                continue
            located = by_location.get((node.file, node.line)) if node.line is not None else None
            if located is not None and located.kind in kinds:
                node.entity_key = located.key
                continue
            names = [_token(node.label)] + ([_token(node.detail)] if node.detail else [])
            match = next(
                (by_name[(kind, name)] for name in names for kind in kinds if (kind, name) in by_name), None
            )
            if match is not None:
                node.entity_key = match.key
