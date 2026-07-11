"""Connect-RPC emitter: canonical model → ``.proto`` — MFX-15.1.

Connect-RPC uses the same Protocol Buffers IDL as gRPC. This emitter delegates to
:class:`app.proto_emitter.ProtoEmitter` and registers under the ``connectrpc`` format key so
catalog export can target Connect explicitly while emitting a standard proto3 bundle.
"""

from __future__ import annotations

from typing import Optional, Union

from .canonical_model import ApiParadigm, CanonicalApi
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitResult,
    Emitter,
)
from .proto_emitter import ProtoEmitOptions, ProtoEmitter, ProtoFidelityRulePack

__all__ = ["ConnectRpcEmitOptions", "ConnectRpcEmitter", "ConnectRpcFidelityRulePack"]


class ConnectRpcFidelityRulePack(ProtoFidelityRulePack):
    """Connect inherits the protobuf fidelity pack — the wire contract is proto3."""

    target_label = "Connect RPC"


class ConnectRpcEmitOptions(ProtoEmitOptions):
    """Per-target options for :class:`ConnectRpcEmitter` (same surface as protobuf)."""


class ConnectRpcEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a Connect-compatible proto3 bundle."""

    key = "connectrpc"
    format = "connectrpc"
    label = "Connect RPC"
    description = "Export as a Connect-compatible Protocol Buffers (.proto) service contract."
    icon = "network"
    paradigm = ApiParadigm.RPC
    multi_file = True
    options_model = ConnectRpcEmitOptions

    OUTPUT_MEDIA_TYPE = ProtoEmitter.OUTPUT_MEDIA_TYPE

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return ProtoEmitter.capability_profile()

    @classmethod
    def fidelity_rule_pack(cls):
        return ConnectRpcFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[ConnectRpcEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, ConnectRpcEmitOptions)
            else ConnectRpcEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        result = ProtoEmitter().emit(api, opts=options)
        files = []
        for emitted in result.files:
            content = emitted.content
            if not content.lstrip().startswith("// Connect"):
                content = "// Connect-RPC service contract (Protobuf proto3)\n" + content
            files.append(emitted.model_copy(update={"content": content}))
        return result.model_copy(update={"files": files})
