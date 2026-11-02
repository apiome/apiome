"""Connect-RPC import source — MFI-12.6 / MFI-19.5.

The :class:`~app.import_source.ImportSource` adapter for Connect-RPC catalog imports. Connect
reuses Protocol Buffers ``.proto`` contracts (the same compiled descriptor set gRPC uses), so
**parse** / **discover** / **parse_fileset** delegate to :class:`app.grpc_import_source.GrpcImportSource`
while **normalize** runs through :class:`app.connectrpc_normalizer.ConnectRpcNormalizer` so the
stored catalog item is labeled ``connectrpc`` rather than ``protobuf`` and every method carries
its Connect HTTP/JSON binding.

**Detection** (MFI-19.5) recognises a Connect module three ways, strongest first: Connect prose in
the ``.proto`` itself; a Buf config next to it (``buf.gen.yaml`` naming a Connect plugin,
``buf.yaml`` depending on ``buf.build/connectrpc``) when the file arrives in an archive or a
repository; and a Connect-oriented path. A plain ``.proto`` with none of these stays gRPC.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional, Sequence, Tuple

from . import connectrpc_normalizer  # noqa: F401 — self-registers the normalizer
from .canonical_model import ApiParadigm, CanonicalApi
from .fileset import IntakeFileset
from .grpc_import_source import GrpcImportSource
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
    LintReport,
)
from .proto_descriptor import CompiledDescriptorSet

__all__ = ["ConnectRpcImportSource", "buf_config_connect_evidence"]

# Connect-RPC prose in comments, docs, or paths — strong enough to prefer this adapter over gRPC.
_CONNECT_MARKER_RE = re.compile(
    r"(?i)connect[\s\-]*rpc|connectrpc|buf\.build/connect",
)

# Buf configuration files a module ships next to its ``.proto`` files (v1 and v2 layouts).
_BUF_CONFIG_NAMES: Tuple[str, ...] = (
    "buf.gen.yaml",
    "buf.gen.yml",
    "buf.yaml",
    "buf.yml",
    "buf.work.yaml",
    "buf.work.yml",
)

# What a Buf config says when the module targets Connect: a Connect plugin (``buf.build/connectrpc/go``,
# ``protoc-gen-connect-go``, ``connect-es`` …) or a ``buf.build/connectrpc`` dependency.
_BUF_CONNECT_RE = re.compile(
    r"(?i)buf\.build/connectrpc|connectrpc/|protoc-gen-connect|connect-(?:go|es|web|kotlin|swift|query|node)",
)

# Cheap protobuf markers shared with the gRPC adapter (detection must never shell out to ``buf``).
_PROTO_MARKERS: Tuple[str, ...] = (
    'syntax = "proto3"',
    'syntax = "proto2"',
    "edition = ",
    "message ",
    "service ",
    "enum ",
    "package ",
)


def _looks_like_proto(text: str) -> bool:
    if 'syntax = "proto3"' in text or 'syntax = "proto2"' in text:
        return True
    if "edition = " in text and ("message " in text or "service " in text):
        return True
    return any(marker in text for marker in _PROTO_MARKERS)


def buf_config_connect_evidence(members: Optional[Mapping[str, str]]) -> Optional[str]:
    """Name the Buf config in *members* that targets Connect, if any (MFI-19.5).

    A Connect module is an ordinary Protobuf module whose ``buf.gen.yaml`` lists a Connect code
    generator (``buf.build/connectrpc/go``, ``protoc-gen-connect-go``, ``connect-es`` …) or whose
    ``buf.yaml`` depends on ``buf.build/connectrpc``. The ``.proto`` files themselves rarely say
    "Connect", so the config is the signal that distinguishes a Connect service from plain gRPC.

    Args:
        members: The fileset members (path → text), or ``None`` for a single-document import.

    Returns:
        The member path of the first Buf config (sorted by path) that names Connect, or ``None``.
    """
    if not members:
        return None
    for path in sorted(members):
        name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if name in _BUF_CONFIG_NAMES and _BUF_CONNECT_RE.search(members[path] or ""):
            return path
    return None


def _connect_path_hint(filename: str) -> bool:
    lowered = filename.replace("\\", "/").lower()
    return (
        "connectrpc" in lowered
        or "/connect/" in lowered
        or lowered.startswith("connect/")
        or "/connect-" in lowered
    )


class ConnectRpcImportSource(ImportSource, register=True):
    """Adapter for Connect-RPC (Protobuf ``.proto`` upload or live gRPC reflection)."""

    key = "connectrpc"
    label = "Connect RPC"
    description = (
        "Import a Connect-RPC service from a .proto file or a live gRPC-compatible reflection endpoint."
    )
    icon = "network"
    paradigm = ApiParadigm.RPC
    input_kinds = (
        InputKind.FILE,
        InputKind.URL,
        InputKind.PASTE,
        InputKind.DISCOVERY,
        InputKind.FILESET,
    )
    supports_live_discovery = True
    formats = ("connectrpc",)
    file_extensions = (".proto",)
    required_tools = ("buf",)

    def __init__(self) -> None:
        self._grpc = GrpcImportSource()

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a ``.proto`` as Connect when its text, a sibling Buf config, or its path says so.

        Args:
            payload: The document under detection; ``siblings`` (archive / git intake) lets the
                Buf config next to the candidate count as evidence.

        Returns:
            A ``connectrpc`` match at 0.98 for Connect prose or a Connect-targeting Buf config
            (above the gRPC adapter's 0.97 for a bare ``syntax`` marker), a weaker match for a
            Connect-oriented path, else :data:`NO_MATCH`. Never raises.
        """
        text = payload.text
        filename = (payload.filename or "").replace("\\", "/")

        if text is not None and _looks_like_proto(text):
            if _CONNECT_MARKER_RE.search(text):
                return DetectionResult(
                    confidence=0.98,
                    format="connectrpc",
                    reason="Connect-RPC protobuf contract",
                )
            buf_config = buf_config_connect_evidence(payload.siblings)
            if buf_config is not None:
                return DetectionResult(
                    confidence=0.98,
                    format="connectrpc",
                    reason=f"Buf config `{buf_config}` targets Connect",
                )
            if filename and _connect_path_hint(filename):
                return DetectionResult(
                    confidence=0.93,
                    format="connectrpc",
                    reason="`.proto` under a Connect path",
                )

        if filename:
            lowered = filename.lower()
            if lowered.endswith(".proto") and _connect_path_hint(filename):
                return DetectionResult(
                    confidence=0.75,
                    format="connectrpc",
                    reason="Connect-oriented `.proto` filename/path",
                )

        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> CompiledDescriptorSet:
        return self._grpc.parse(raw, source_label=source_label)

    def accepts_bytes(self, raw: bytes, *, filename: Optional[str] = None) -> bool:
        """Delegate binary descriptor-set routing to the gRPC adapter (IXH-7.5)."""
        return self._grpc.accepts_bytes(raw, filename=filename)

    def parse_bytes(
        self, raw: bytes, *, source_label: Optional[str] = None
    ) -> CompiledDescriptorSet:
        """Decode a binary ``FileDescriptorSet`` / buf image via the gRPC adapter (IXH-7.5)."""
        return self._grpc.parse_bytes(raw, source_label=source_label)

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> CompiledDescriptorSet:
        return self._grpc.parse_fileset(fileset, source_label=source_label)

    def discover(
        self,
        target: str,
        *,
        auth_type: Optional[str] = None,
        auth_payload: Optional[Mapping[str, Any]] = None,
        metadata: Optional[Sequence[Tuple[str, str]]] = None,
        secure: bool = False,
        timeout: Optional[float] = None,
        transport_factory: Optional[Any] = None,
    ) -> CompiledDescriptorSet:
        return self._grpc.discover(
            target,
            auth_type=auth_type,
            auth_payload=auth_payload,
            metadata=metadata,
            secure=secure,
            timeout=timeout,
            transport_factory=transport_factory,
        )

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        try:
            return self._normalize_via_registry("connectrpc", native_ast, include_raw=include_raw)
        except ValueError as exc:
            raise ImportSourceError(str(exc)) from exc

    def lint(self, model: CanonicalApi) -> LintReport:
        from .proto_lint import lint_protobuf_result

        return LintReport.from_lint_result(lint_protobuf_result(model))
