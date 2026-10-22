"""HAProxy configuration import source — FMT-7.5 (#5459).

The :class:`~app.import_source.ImportSource` adapter for ``haproxy.cfg``: frontends and
``listen`` sections with their path ACLs and ``use_backend`` rules become canonical
operations through :mod:`app.haproxy_parser`, and a file set supplies the map files a
computed ``use_backend`` reads. Connection, TLS, rate-counter and Lua conditions — and TCP
mode altogether — are declared on the ledger. There are no request/response schemas, so
the import lands in the catalog as non-publishable and every operation is labelled
``inferred``.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .gateway_config_normalizer import HAPROXY_FORMAT_KEY
from .haproxy_parser import (
    HAPROXY_DECLARED_CONSTRUCTS,
    HAPROXY_READ_CONSTRUCTS,
    is_haproxy,
    parse_haproxy,
    parse_haproxy_fileset,
)
from .import_source import NO_MATCH, DetectionInput, DetectionResult
from .proxy_import_source import ProxyRouteImportSource
from .proxy_route_common import directive_capabilities

__all__ = ["HaproxyImportSource"]

#: Confidence for text with HAProxy sections and proxy directives.
_CONFIDENCE = 0.9


class HaproxyImportSource(ProxyRouteImportSource, register=True):
    """Adapter for HAProxy configuration (file / url / paste / fileset)."""

    key = HAPROXY_FORMAT_KEY
    label = "HAProxy configuration"
    description = (
        "Import an HAProxy configuration — frontend, backend and listen sections — and infer "
        "canonical operations from ACL + use_backend routing: path, path_beg, path_dir and "
        "path_reg ACLs give the path, method ACLs the method, hdr(host) the hosts, and bind … "
        "ssl the scheme. Map files supplied with the configuration resolve computed backends. "
        "Source-address, TLS, rate-counter and Lua conditions and TCP-mode sections are declared "
        "on the ledger. There are no request/response schemas, so the import lands in the "
        "catalog as non-publishable and every operation is labelled inferred."
    )
    icon = "route"
    formats = ("haproxy",)
    file_extensions = (".cfg",)
    capabilities = directive_capabilities("haproxy", read=HAPROXY_READ_CONSTRUCTS, declared=HAPROXY_DECLARED_CONSTRUCTS)

    def detect(self, payload: DetectionInput) -> DetectionResult:
        if payload.text is not None and is_haproxy(payload.text):
            return DetectionResult(
                confidence=_CONFIDENCE,
                format=HAPROXY_FORMAT_KEY,
                reason="frontend / backend / listen sections with bind, acl, use_backend or server",
            )
        return NO_MATCH

    def _parse_text(self, raw: str, *, source_label: Optional[str]) -> Any:
        return parse_haproxy(raw, source_label=source_label)

    def _parse_members(self, members: Mapping[str, str], *, root: Optional[str], source_label: Optional[str]) -> Any:
        return parse_haproxy_fileset(members, root=root, source_label=source_label)
