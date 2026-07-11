"""Connect-RPC ``FileDescriptorSet`` → canonical model normalizer — MFI-12.2.

Connect-RPC speaks a Protobuf service contract (the same ``.proto`` surface gRPC uses), so this
normalizer delegates to :class:`app.proto_normalizer.ProtoNormalizer` and re-labels the emitted
:class:`~app.canonical_model.CanonicalApi` as ``connectrpc``. The canonical RPC shape is
identical; only the persisted ``format`` / provenance differ so catalog items imported as Connect
stay distinct from generic gRPC/Protobuf imports.
"""

from __future__ import annotations

from typing import Any

from .canonical_model import ApiParadigm, CanonicalApi
from .normalizer import Normalizer, normalize_ordering
from .proto_normalizer import ProtoNormalizer

__all__ = ["ConnectRpcNormalizer"]

_FORMAT_KEY = "connectrpc"


class ConnectRpcNormalizer(Normalizer, register=True):
    """Normalize a compiled protobuf descriptor set imported as Connect-RPC."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.RPC

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        api = ProtoNormalizer().normalize(source, include_raw=include_raw)
        extras = dict(api.extras)
        extras["rpc_stack"] = "connect"
        relabeled = api.model_copy(update={"format": self.format, "extras": extras})
        return normalize_ordering(relabeled)
